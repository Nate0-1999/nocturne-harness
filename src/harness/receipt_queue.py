"""Owner-local replay spool for B.6 rule-11 spend receipts. [A-038]"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from harness.spend import SpendGateway
from harness.spine_client import SpendEvent, SpendEventsRequest


@dataclass(frozen=True, slots=True)
class AccountingQueueSnapshot:
    """Immediate Harness-owned accounting drift for the Rack. [A-038]"""

    status: str
    pending_lines: int
    oldest_queued_at: datetime | None
    source: str = "harness.receipt_queue"


@dataclass(slots=True)
class _MemoryBatch:
    request: SpendEventsRequest
    queued_at: datetime


class SpendReceiptQueue:
    """Persist immutable estimated batches and replay through A-027 idempotency."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.root = root
        self._clock = clock
        self._memory: list[_MemoryBatch] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, request: SpendEventsRequest) -> bool:
        """Queue one failed batch; return whether its copy is durable."""

        async with self._lock:
            queued_at = self._aware_now()
            estimated = _estimated_request(request, queued_at=queued_at)
            try:
                self._write(estimated)
            except OSError:
                self._memory.append(_MemoryBatch(estimated, queued_at))
                return False
            return True

    async def flush(self, gateway: SpendGateway) -> bool:
        """Replay oldest-first and retain the first failure plus everything after it."""

        async with self._lock:
            try:
                paths = self._paths()
            except OSError:
                return False
            for path in paths:
                try:
                    request = SpendEventsRequest.model_validate_json(path.read_text("utf-8"))
                    result = await gateway.record_spend_events(request)
                    if result.accepted != len(request.events):
                        return False
                    path.unlink()
                except (OSError, ValueError, TypeError):
                    return False
                except Exception:
                    return False

            retained: list[_MemoryBatch] = []
            for index, batch in enumerate(self._memory):
                try:
                    result = await gateway.record_spend_events(batch.request)
                    if result.accepted != len(batch.request.events):
                        retained.extend(self._memory[index:])
                        break
                except Exception:
                    retained.extend(self._memory[index:])
                    break
            self._memory = retained
            return not self._memory

    def snapshot(self) -> AccountingQueueSnapshot:
        """Read a safe local count without mutating or parsing receipt content."""

        disk_lines = 0
        oldest: datetime | None = None
        degraded = bool(self._memory)
        try:
            for path in self._paths():
                try:
                    request = SpendEventsRequest.model_validate_json(path.read_text("utf-8"))
                except (OSError, ValueError, TypeError):
                    degraded = True
                    continue
                disk_lines += len(request.events)
                queued_at = _queued_at(request.events[0])
                oldest = queued_at if oldest is None else min(oldest, queued_at)
        except OSError:
            degraded = True

        memory_lines = sum(len(batch.request.events) for batch in self._memory)
        for batch in self._memory:
            oldest = batch.queued_at if oldest is None else min(oldest, batch.queued_at)
        pending = disk_lines + memory_lines
        status = "degraded" if degraded else "pending" if pending else "clear"
        return AccountingQueueSnapshot(status, pending, oldest)

    def _paths(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.glob("*.json"), key=lambda path: path.name)

    def _write(self, request: SpendEventsRequest) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        path = self.root / f"{request.events[0].event_uid}.json"
        encoded = request.model_dump_json()
        if path.exists():
            if path.read_text("utf-8") != encoded:
                raise OSError("receipt event id collision")
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt.", dir=self.root)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("receipt queue clock must return an aware datetime")
        return now


def _estimated_request(
    request: SpendEventsRequest,
    *,
    queued_at: datetime,
) -> SpendEventsRequest:
    events = []
    for event in request.events:
        meta = dict(event.meta)
        meta["receipt_queue"] = {
            "original_basis": event.basis,
            "queued_at": queued_at.isoformat(),
            "reason": "ledger_unavailable",
        }
        events.append(event.model_copy(update={"basis": "estimated", "meta": meta}))
    return SpendEventsRequest(events=events)


def _queued_at(event: SpendEvent) -> datetime:
    marker = event.meta.get("receipt_queue")
    if isinstance(marker, dict) and isinstance(marker.get("queued_at"), str):
        value = datetime.fromisoformat(marker["queued_at"])
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value
    return event.ts


__all__ = ["AccountingQueueSnapshot", "SpendReceiptQueue"]
