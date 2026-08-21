"""Deterministic rendered fixture for the M2G per-message re-scoring SOP."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    FeedbackRequest,
    FeedbackResponse,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    ListMemoriesParams,
    MemoryFeatures,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    ScoredMemoryCard,
    SpendEventsRequest,
    SpendEventsResponse,
    VitalsLifecycleRate,
    VitalsPalaceCount,
    VitalsSnapshot,
    VitalsSpend,
    VitalsSpendLane,
)
from verification.fixture_isolation import install_fixture_isolation

TRACE_PATH = Path(__file__).with_name("trace.jsonl")
FIRST_PROMPT = "Map the release boundary and hold the queue open."
SECOND_PROMPT = "Now include the ambient scoring rule too."
MACHINE_ID = "m2g-verification-machine"
AGENT_ID = "m2g-verification-agent"
UPDATED = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
CONFIRMED_ID = UUID("10000000-0000-4000-8000-000000000001")
AMBIENT_ID = UUID("10000000-0000-4000-8000-000000000002")


def _unit(memory_id: UUID, label: str, body: str) -> MemoryUnit:
    return MemoryUnit(
        memory_id=memory_id,
        principal_id="m2g-verification",
        label=label,
        body=body,
        kind=MemoryKind.PROJECT_NOTE,
        keywords=["M2G", "verification"],
        project_key=None,
        thread_origin=None,
        origin_thread_id=None,
        origin_path="verification/m2g",
        pin=False,
        status=MemoryStatus.ACTIVE,
        revision=1,
        stats={},
        bias=0.0,
        embedding_model="fixture",
        created_at=UPDATED,
        updated_at=UPDATED,
    )


CONFIRMED = _unit(
    CONFIRMED_ID,
    "M2G confirmed context",
    "The first accepted memory remains locked into later turns.",
)
AMBIENT = _unit(
    AMBIENT_ID,
    "M2G ambient entry",
    "Each ordinary message is rescored without reopening the decision gate.",
)


def _card(memory: MemoryUnit, rank: int) -> ScoredMemoryCard:
    return ScoredMemoryCard(
        memory_id=memory.memory_id,
        label=memory.label,
        body=memory.body,
        kind=memory.kind,
        pin=memory.pin,
        score=0.95 - rank / 100,
        features=MemoryFeatures(sem=0.9, kw=0.8, time=0.7, proj=0.6, freq=0.5, hist=0.4),
        rank=rank,
    )


def _final_block(*cards: ScoredMemoryCard) -> str:
    prefix = (
        "<memory_system>\n"
        "The following long-term memories were retrieved for this conversation.\n"
        "Treat them as your own accumulated knowledge; they may be imperfect.\n"
    )
    fragments = [
        (
            f'<memory label="{card.label}" kind="{card.kind.value}" '
            f'updated="{UPDATED.isoformat().replace("+00:00", "Z")}">\n'
            f"{card.body}\n</memory>"
        )
        for card in cards
    ]
    return prefix + "\n".join(fragments) + "\n</memory_system>"


class FixtureSpine:
    def __init__(self) -> None:
        self.trace: list[dict[str, Any]] = []
        self.prepare_count = 0

    def record(self, kind: str, **values: object) -> None:
        item = {"at": datetime.now(UTC).isoformat(), "kind": kind, **values}
        self.trace.append(item)
        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, separators=(",", ":")) + "\n")

    async def aclose(self) -> None:
        return None

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepare_count += 1
        confirmed = _card(CONFIRMED, 1)
        ambient = _card(AMBIENT, 2)
        autonomous = request.mode == "autonomous"
        cards = [confirmed]
        if autonomous and AMBIENT_ID not in request.excluded_memory_ids:
            cards.append(ambient)
        self.record(
            "spine.prepare",
            call=self.prepare_count,
            mode=request.mode,
            thread_id=str(request.thread_id),
            current=[str(value) for value in request.current_memory_ids],
            confirmed=[str(value) for value in request.confirmed_memory_ids],
            excluded=[str(value) for value in request.excluded_memory_ids],
            selected=[str(card.memory_id) for card in cards],
        )
        return InjectPrepareResponse(
            injection_id=uuid4(),
            snapshot_ts=datetime.now(UTC),
            scorer_version="m2g-fixture-v1",
            injected=cards,
            near_misses=[] if autonomous else [ambient],
            final_block=_final_block(*cards) if autonomous else None,
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self.record(
            "spine.commit",
            injection_id=str(request.injection_id),
            removed=[str(value.memory_id) for value in request.removed],
        )
        return InjectCommitResponse(final_block=_final_block(_card(CONFIRMED, 1)), wrong_removed=[])

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        self.record(
            "spine.feedback",
            injection_id=str(request.injection_id),
            memory_id=str(request.memory_id),
            signal=request.signal.value,
        )
        return FeedbackResponse(ok=True)

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        del params
        return PagedMemoryListResponse(items=[CONFIRMED, AMBIENT], total=2, limit=200, offset=0)

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        self.record("spine.spend", accepted=len(request.events))
        return SpendEventsResponse(accepted=len(request.events))

    async def vitals_snapshot(self) -> VitalsSnapshot:
        return _vitals()


def _vitals() -> VitalsSnapshot:
    return VitalsSnapshot(
        as_of=datetime.now(UTC),
        window_minutes=60,
        spend=VitalsSpend(
            source_view="v_spend_rate",
            latest_minute=None,
            lanes=[VitalsSpendLane(dimension="total", key=None, label="Total", points=[])],
        ),
        lifecycle_rates=[
            VitalsLifecycleRate(metric="created", status="measured", per_hour=0, source="fixture"),
            *[
                VitalsLifecycleRate(
                    metric=metric,
                    status="not_recorded",
                    per_hour=None,
                    source=None,
                )
                for metric in (
                    "reinforced",
                    "superseded",
                    "merged",
                    "quarantined",
                    "tombstoned",
                    "add_backs",
                )
            ],
        ],
        palace_counts=[
            VitalsPalaceCount(metric="active_units", status="measured", count=2, source="fixture"),
            VitalsPalaceCount(metric="pinned_units", status="measured", count=0, source="fixture"),
            *[
                VitalsPalaceCount(metric=metric, status="not_recorded", count=None, source=None)
                for metric in ("candidates_pending", "edges", "staged_units")
            ],
            VitalsPalaceCount(metric="queue_depth", status="placeholder", count=None, source=None),
        ],
    )


def _model(spine: FixtureSpine) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo):
        del info
        prompt = _latest_prompt(messages)
        spine.record("model.call", prompt=prompt)
        yield "M2G deterministic model response."

    return FunctionModel(stream_function=respond, model_name="local:m2g-verification")


def _latest_prompt(messages: Sequence[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    raise ValueError("fixture model received no user prompt")


def create_scenario_app() -> FastAPI:
    TRACE_PATH.write_text("", encoding="utf-8")
    spine = FixtureSpine()
    settings = HarnessSettings(
        principal_id="m2g-verification",
        machine_id=MACHINE_ID,
        agent_id=AGENT_ID,
        chat_model="local:m2g-verification",
        model_context_tokens=4096,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model(spine)),
        spine=spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2G deterministic verification")
    install_fixture_isolation(app, "M2G REGRESSION")

    @app.get("/__scenario__/expectation")
    async def expectation() -> Mapping[str, object]:
        return {"first_prompt": FIRST_PROMPT, "second_prompt": SECOND_PROMPT}

    @app.get("/__scenario__/trace")
    async def trace() -> Mapping[str, object]:
        return {"events": spine.trace}

    app.mount("/", harness_app)
    return app


__all__ = ["FIRST_PROMPT", "SECOND_PROMPT", "TRACE_PATH", "create_scenario_app"]
