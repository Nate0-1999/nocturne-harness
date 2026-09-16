"""M3SR / ADR-024: pause ordinary runs at measured request boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.models.wrapper import WrapperModel

from harness.run_protocol import RunEmitter
from harness.spend import SpendGateway, _native_cost, _provider_details
from harness.spine_client import SpendEventsRequest, SpendEventsResponse, SpendTableSnapshot


class SpendLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    run_usd: Decimal | None = Field(default=None, gt=0)
    day_usd: Decimal | None = Field(default=None, gt=0)


@dataclass
class _RunSpend:
    walls: SpendWalls
    emitter: RunEmitter
    run_id: str
    costs: list[Decimal | None] = field(default_factory=list)


_current: ContextVar[_RunSpend | None] = ContextVar("spend_wall_run", default=None)


class SpendWalls:
    """Serialize ledger acknowledgement with pending spend to avoid double counting."""

    def __init__(
        self, path: Path, gateway: SpendGateway,
        reader: Callable[[], Awaitable[SpendTableSnapshot]],
    ) -> None:
        self.path, self.gateway, self.reader = path, gateway, reader
        self.limits = (
            SpendLimits.model_validate_json(path.read_text()) if path.exists() else SpendLimits()
        )
        self._condition = asyncio.Condition()
        self._pending: dict[tuple[str, str], tuple[datetime, Decimal | None]] = {}

    async def configure(self, limits: SpendLimits) -> None:
        async with self._condition:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(limits.model_dump_json() + "\n")
            temporary.replace(self.path)
            self.limits = limits
            self._condition.notify_all()

    @contextmanager
    def bind(self, run_id: str, emitter: RunEmitter):
        token = _current.set(_RunSpend(self, emitter, run_id))
        try:
            yield
        finally:
            _current.reset(token)

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        async with self._condition:
            result = await self.gateway.record_spend_events(request)
            if result.accepted == len(request.events):
                for event in request.events:
                    if event.run_id is not None:
                        self._pending.pop((event.run_id, event.ref), None)
            self._condition.notify_all()
            return result

    async def observe(self, run: _RunSpend, response: Any) -> None:
        cost, _ = _native_cost(_provider_details(response))
        async with self._condition:
            run.costs.append(cost)
            ref = response.provider_response_id or f"unattributed:{id(response)}"
            self._pending[(run.run_id, ref)] = (response.timestamp, cost)

    async def check(self, run: _RunSpend) -> None:
        announced = False
        async with self._condition:
            while True:
                reason = await self._reason(run)
                if reason is None:
                    if announced:
                        await self._card(run, "resumed", "Spend authority changed; resuming.")
                    return
                if not announced:
                    await self._card(run, "owner_action", reason)
                    announced = True
                # A UTC day reset releases a daily wall without owner attention.
                now = datetime.now(UTC)
                tomorrow = datetime.fromtimestamp(
                    (int(now.timestamp()) // 86400 + 1) * 86400, UTC
                )
                try:
                    await asyncio.wait_for(self._condition.wait(), (tomorrow - now).total_seconds())
                except TimeoutError:
                    pass

    async def check_current(self) -> None:
        run = _current.get()
        if run is not None and run.costs:
            await self.check(run)

    async def _reason(self, run: _RunSpend) -> str | None:
        limits = self.limits
        if limits.run_usd is not None:
            if any(cost is None for cost in run.costs):
                return "A request has no reported price; the run wall cannot be verified."
            cost = sum((cost for cost in run.costs if cost is not None), Decimal(0))
            if cost >= limits.run_usd:
                return f"Run spend ${cost} reached its ${limits.run_usd} wall."
        if limits.day_usd is not None:
            try:
                snapshot = await self.reader()
                if "days" not in snapshot.model_fields_set:
                    return "The Palace does not yet provide daily spend for this wall."
            except Exception:
                return "Daily spend is unavailable; the day wall cannot be verified."
            today = datetime.now(UTC).date()
            day = next((row for row in snapshot.days if row.day.date() == today), None)
            pending = [
                cost for ts, cost in self._pending.values() if ts.astimezone(UTC).date() == today
            ]
            if (day is not None and day.unpriced_lines) or any(cost is None for cost in pending):
                return (
                    "Today's receipts include an unreported price; "
                    "the day wall cannot be verified."
                )
            cost = Decimal(day.total_usd or "0") if day is not None else Decimal(0)
            cost += sum((cost for cost in pending if cost is not None), Decimal(0))
            if cost >= limits.day_usd:
                return f"Today's UTC spend ${cost} reached its ${limits.day_usd} wall."
        return None

    @staticmethod
    async def _card(run: _RunSpend, decision: str, reason: str) -> None:
        await run.emitter.event({
            "event_kind": "boundary_card", "wall": "spend", "decision": decision,
            "judge": "Spend ledger", "policy": "Per-run and UTC-day spend walls",
            "run_id": run.run_id, "created_at": datetime.now(UTC).isoformat(),
            "reason": reason,
            "action": (
                "Paused. Raise the relevant wall in App settings to resume, or cancel the run."
            ),
        })


class SpendWallModel(WrapperModel):
    async def request(self, *args: Any, **kwargs: Any):
        run = _current.get()
        if run is not None:
            await run.walls.check(run)
        response = await super().request(*args, **kwargs)
        if run is not None:
            await run.walls.observe(run, response)
        return response

    @asynccontextmanager
    async def request_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        run = _current.get()
        if run is not None:
            await run.walls.check(run)
        async with super().request_stream(*args, **kwargs) as response:
            try:
                yield response
            finally:
                if run is not None:
                    await run.walls.observe(run, response.get())
