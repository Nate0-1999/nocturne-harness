"""Deterministic, visibly bannered M2H consent-surface fixture."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.memory_panel import EMPTY_MEMORY_BLOCK
from harness.spine_client import (
    ExtractionRequest,
    ExtractionResponse,
    FeedbackRequest,
    FeedbackResponse,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    QueueCard,
    QueueDecisionRequest,
    QueueDecisionResponse,
    QueueResponse,
    SearchRequest,
    SearchResponse,
    SimilarityMemoryCard,
    SpendEventsRequest,
    SpendEventsResponse,
    VitalsLifecycleRate,
    VitalsPalaceCount,
    VitalsSnapshot,
    VitalsSpend,
    VitalsSpendLane,
)
from verification.fixture_isolation import install_fixture_isolation

UPDATED = datetime(2026, 8, 3, 18, 30, tzinfo=UTC)
NEIGHBOR_ID = UUID("20000000-0000-4000-8000-000000000001")


def _uid(index: int) -> str:
    return f"01J{index:023d}"


def _memory(
    memory_id: UUID,
    label: str,
    body: str,
    *,
    status: MemoryStatus,
    thread_origin: str | None = None,
    keywords: list[str] | None = None,
) -> MemoryUnit:
    return MemoryUnit(
        memory_id=memory_id,
        principal_id="m2h-verification",
        label=label,
        body=body,
        kind=MemoryKind.PROJECT_NOTE,
        keywords=keywords or ["garden", "relay"],
        project_key="N8_Harness",
        thread_origin=thread_origin,
        origin_path="verification/m2h",
        pin=False,
        status=status,
        revision=1,
        stats={},
        bias=0.0,
        embedding_model="fixture",
        created_at=UPDATED,
        updated_at=UPDATED,
    )


NEIGHBOR = _memory(
    NEIGHBOR_ID,
    "Existing Garden relay rule",
    "Claim exactly one packet and preserve independent judgment.",
    status=MemoryStatus.ACTIVE,
)


class FixtureSpine:
    def __init__(self) -> None:
        self.cards: dict[str, QueueCard] = {}
        self.decisions: list[dict[str, str]] = []

    async def aclose(self) -> None:
        return None

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        return InjectPrepareResponse(
            injection_id=uuid4(),
            snapshot_ts=UPDATED,
            scorer_version="m2h-fixture-v1",
            injected=[],
            near_misses=[],
            final_block=EMPTY_MEMORY_BLOCK if request.mode == "autonomous" else None,
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        del request
        return InjectCommitResponse(final_block=EMPTY_MEMORY_BLOCK, wrong_removed=[])

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        del request
        return FeedbackResponse(ok=True)

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        del params
        return PagedMemoryListResponse(items=[NEIGHBOR], total=1, limit=200, offset=0)

    async def search(self, request: SearchRequest) -> SearchResponse:
        del request
        return SearchResponse(
            results=[
                SimilarityMemoryCard(
                    memory_id=NEIGHBOR.memory_id,
                    label=NEIGHBOR.label,
                    body=NEIGHBOR.body,
                    kind=NEIGHBOR.kind,
                    pin=False,
                    score=0.82,
                    features=None,
                    rank=None,
                )
            ]
        )

    async def create_extraction(self, request: ExtractionRequest) -> ExtractionResponse:
        cards: list[QueueCard] = []
        for index, candidate in enumerate(request.candidates, start=1):
            item_uid = _uid(index)
            memory = _memory(
                UUID(f"30000000-0000-4000-8000-{index:012d}"),
                candidate.label,
                candidate.body,
                status=MemoryStatus.CANDIDATE,
                thread_origin=str(request.thread_id),
                keywords=candidate.keywords,
            )
            card = QueueCard(
                item_uid=item_uid,
                candidate=memory,
                birthplace="thread",
                birthplace_thread_id=request.thread_id,
                batch_uid=None,
                source_name=None,
                source_sha256=None,
                verdict=candidate.verdict,
                neighbors=[] if candidate.verdict == "new" else [await self.search_one()],
                target_ids=candidate.target_ids,
                state="pending",
                created_at=UPDATED,
            )
            self.cards[item_uid] = card
            cards.append(card)
        return ExtractionResponse(cards=cards, duplicate_count=0)

    async def search_one(self) -> SimilarityMemoryCard:
        return (
            await self.search(SearchRequest(principal_id="m2h-verification", query="x"))
        ).results[0]

    async def approval_queue(
        self,
        principal_id: str,
        *,
        thread_id: UUID | None = None,
        birthplace: str | None = None,
    ) -> QueueResponse:
        del principal_id
        cards = [
            card
            for card in self.cards.values()
            if card.state == "pending"
            and (thread_id is None or card.birthplace_thread_id == thread_id)
            and (birthplace is None or card.birthplace == birthplace)
        ]
        return QueueResponse(cards=cards)

    async def decide_queue_item(
        self, item_uid: str, request: QueueDecisionRequest
    ) -> QueueDecisionResponse:
        card = self.cards[item_uid]
        if card.verdict == "contradict" and request.approval_mode == "passive":
            raise ValueError("contradictions require explicit approval")
        state = "approved" if request.decision == "approve" else "rejected"
        card = card.model_copy(update={"state": state})
        self.cards[item_uid] = card
        self.decisions.append(
            {
                "item_uid": item_uid,
                "decision": request.decision,
                "approval_mode": request.approval_mode,
                "actor_class": request.actor_class,
            }
        )
        return QueueDecisionResponse(
            card=card,
            decision=request.decision,
            approval_mode=request.approval_mode,
            actor_class=request.actor_class,
            decision_uid=_uid(100 + len(self.decisions)),
        )

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        return SpendEventsResponse(accepted=len(request.events))

    async def vitals_snapshot(self) -> VitalsSnapshot:
        return VitalsSnapshot(
            as_of=UPDATED,
            window_minutes=60,
            spend=VitalsSpend(
                source_view="v_spend_rate",
                latest_minute=None,
                lanes=[VitalsSpendLane(dimension="total", key=None, label="Total", points=[])],
            ),
            lifecycle_rates=[
                VitalsLifecycleRate(
                    metric="created", status="measured", per_hour=5, source="fixture"
                ),
                *[
                    VitalsLifecycleRate(
                        metric=metric, status="not_recorded", per_hour=None, source=None
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
                VitalsPalaceCount(
                    metric="active_units", status="measured", count=1, source="fixture"
                ),
                VitalsPalaceCount(
                    metric="pinned_units", status="measured", count=0, source="fixture"
                ),
                VitalsPalaceCount(
                    metric="candidates_pending", status="measured", count=5, source="fixture"
                ),
                VitalsPalaceCount(metric="edges", status="measured", count=0, source="fixture"),
                VitalsPalaceCount(
                    metric="staged_units", status="not_recorded", count=None, source=None
                ),
                VitalsPalaceCount(
                    metric="queue_depth", status="measured", count=5, source="fixture"
                ),
            ],
        )


def _latest_prompt(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    return ""


def _model() -> FunctionModel:
    async def respond(messages: list[Any], info: AgentInfo) -> ModelResponse:
        del info
        return ModelResponse(parts=[TextPart(_response_text(messages))])

    async def stream(messages: list[Any], info: AgentInfo):
        del info
        yield _response_text(messages)

    return FunctionModel(
        function=respond,
        stream_function=stream,
        model_name="local:m2h-verification",
    )


def _response_text(messages: list[Any]) -> str:
    prompt = _latest_prompt(messages)
    if prompt.startswith("["):
        return _extraction_json()
    if prompt.startswith("Candidate:"):
        verdict = "new"
        targets = "[]"
        for label, candidate_verdict in (
            ("Merge relay", "merge"),
            ("Supersede relay", "supersede"),
            ("Contradiction", "contradict"),
        ):
            if label in prompt:
                verdict = candidate_verdict
                targets = f'["{NEIGHBOR_ID}"]'
                break
        return f'{{"verdict":"{verdict}","target_ids":{targets}}}'
    return (
        "M2H final post: the relay stays explicit, candidates remain reviewable, "
        "and contradictions never passively resolve."
    )


def _extraction_json() -> str:
    return json.dumps(
        {
            "working_summary": "M2H deterministic extraction fixture.",
            "open_loops": ["Verify consent behavior at desktop and mobile widths."],
            "candidates": [
                {
                    "label": "New relay note",
                    "body": "Archive creates a review queue.",
                    "kind": "project_note",
                    "keywords": ["archive", "queue"],
                },
                {
                    "label": "Merge relay note",
                    "body": "One packet per relay remains the governing rule.",
                    "kind": "project_note",
                    "keywords": ["relay", "packet"],
                },
                {
                    "label": "Supersede relay note",
                    "body": "The current board supersedes historical handoffs.",
                    "kind": "project_note",
                    "keywords": ["board", "handoff"],
                },
                {
                    "label": "Contradiction warning",
                    "body": "Contradictions require an explicit owner tap.",
                    "kind": "project_note",
                    "keywords": ["contradiction", "consent"],
                },
                {
                    "label": "Visibility boundary",
                    "body": "Only fully visible rows can resolve passively.",
                    "kind": "procedure",
                    "keywords": ["visibility", "passive"],
                },
            ],
        },
        separators=(",", ":"),
    )


def create_scenario_app() -> FastAPI:
    spine = FixtureSpine()
    settings = HarnessSettings(
        principal_id="m2h-verification",
        machine_id="m2h-verification-machine",
        agent_id="m2h-verification-agent",
        chat_model="local:m2h-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2H deterministic verification")
    install_fixture_isolation(app, "M2H REGRESSION")

    @app.get("/__scenario__/trace")
    async def trace() -> dict[str, object]:
        pending = await spine.approval_queue("x")
        return {"decisions": spine.decisions, "pending": len(pending.cards)}

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
