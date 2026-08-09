"""Deterministic, visibly bannered M2I seed-ingestion fixture."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    BatchDecisionResponse,
    MemoryStatus,
    QueueCard,
    QueueDecisionRequest,
    SeedRequest,
    SeedResponse,
)
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import UPDATED, FixtureSpine, _memory, _uid


class SeedFixtureSpine(FixtureSpine):
    async def create_seed(self, request: SeedRequest) -> SeedResponse:
        cards: list[QueueCard] = []
        for index, candidate in enumerate(request.candidates, start=20):
            item_uid = _uid(index)
            card = QueueCard(
                item_uid=item_uid,
                candidate=_memory(
                    UUID(f"40000000-0000-4000-8000-{index:012d}"),
                    candidate.label,
                    candidate.body,
                    status=MemoryStatus.CANDIDATE,
                    keywords=candidate.keywords,
                ),
                birthplace="seed",
                birthplace_thread_id=None,
                batch_uid=request.batch_uid,
                source_name=request.source_name,
                source_sha256=request.source_sha256,
                verdict=candidate.verdict,
                neighbors=[],
                target_ids=candidate.target_ids,
                state="pending",
                created_at=UPDATED,
            )
            self.cards[item_uid] = card
            cards.append(card)
        return SeedResponse(
            batch_uid=request.batch_uid,
            cards=cards,
            duplicate_count=0,
        )

    async def decide_queue_batch(
        self, batch_uid: UUID, request: QueueDecisionRequest
    ) -> BatchDecisionResponse:
        decided: list[QueueCard] = []
        for item_uid, card in list(self.cards.items()):
            if card.batch_uid != batch_uid:
                continue
            state = "approved" if request.decision == "approve" else "rejected"
            updated = card.model_copy(update={"state": state})
            self.cards[item_uid] = updated
            self.decisions.append(
                {
                    "batch_uid": str(batch_uid),
                    "item_uid": item_uid,
                    "decision": request.decision,
                    "approval_mode": request.approval_mode,
                    "actor_class": request.actor_class,
                    "machine_id": request.machine_id,
                }
            )
            decided.append(updated)
        return BatchDecisionResponse(
            batch_uid=batch_uid,
            decision=request.decision,
            cards=decided,
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
        model_name="local:m2i-verification",
    )


def _response_text(messages: list[Any]) -> str:
    prompt = _latest_prompt(messages)
    if prompt.startswith("Source:"):
        return json.dumps(
            {
                "candidates": [
                    {
                        "label": "Semantic splitting",
                        "body": "Seed split points follow meaning rather than fixed token windows.",
                        "kind": "procedure",
                        "keywords": ["seed", "semantic", "splitting"],
                    },
                    {
                        "label": "Batch consent",
                        "body": (
                            "A seed document enters the Palace only through an explicit "
                            "batch action."
                        ),
                        "kind": "procedure",
                        "keywords": ["batch", "consent", "palace"],
                    },
                ]
            },
            separators=(",", ":"),
        )
    if prompt.startswith("Candidate:"):
        return '{"verdict":"new","target_ids":[]}'
    return "M2I deterministic fixture."


def create_scenario_app() -> FastAPI:
    spine = SeedFixtureSpine()
    settings = HarnessSettings(
        principal_id="m2i-verification",
        machine_id="m2i-verification-machine",
        agent_id="m2i-verification-agent",
        chat_model="local:m2i-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2I deterministic verification")
    install_fixture_isolation(app, "M2I REGRESSION")

    @app.get("/__scenario__/trace")
    async def trace() -> dict[str, object]:
        pending = await spine.approval_queue("x", birthplace="seed")
        return {"decisions": spine.decisions, "pending": len(pending.cards)}

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
