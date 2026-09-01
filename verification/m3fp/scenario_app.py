"""Deterministic packaged-asset core-loop heartbeat for CI and handoffs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.onboarding import nocturne_home
from harness.packaged import _runtime_web_assets
from harness.spine_client import (
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    MemoryAllocation,
    SpendEventsRequest,
    SpendEventsResponse,
)
from harness.transcript import TranscriptJournal
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2st3.scenario_app import HonestDisplaySpine

FIXTURE = "M3FP REGRESSION"
PROMPT = "Open the memory gate, then answer the heartbeat check."
ANSWER = (
    "M2H final post: the relay stays explicit, candidates remain reviewable, "
    "and contradictions never passively resolve."
)


class HeartbeatSpine(HonestDisplaySpine):
    """Count the exact Palace boundaries required by the standing heartbeat."""

    def __init__(self) -> None:
        super().__init__()
        self.prepare_calls = 0
        self.commit_calls = 0
        self.receipt_lines = 0

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepare_calls += 1
        return InjectPrepareResponse(
            injection_id=uuid4(),
            snapshot_ts=datetime.now(UTC),
            scorer_version="m3fp-heartbeat-v1",
            injected=[],
            near_misses=[],
            final_block=None,
            memory_allocation=MemoryAllocation(
                memory_context_share=0.10,
                share_tokens=100,
                regular_tokens=0,
                pinned_tokens=0,
                total_tokens=0,
                pinned_overflow_tokens=0,
            ),
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self.commit_calls += 1
        return await super().commit_injection(request)

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        self.receipt_lines += len(request.events)
        return await super().record_spend_events(request)


def create_scenario_app() -> FastAPI:
    """Serve the real packaged asset resolution with deterministic local dependencies."""

    settings = HarnessSettings(
        principal_id="m3fp-heartbeat",
        machine_id="m3fp-heartbeat",
        agent_id="m3fp-heartbeat",
        chat_model="local:m3fp-heartbeat",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    spine = HeartbeatSpine()
    journal = TranscriptJournal(nocturne_home() / "transcripts")
    web_dist, refusal = _runtime_web_assets()
    harness_app = create_dev_app(
        web_dist,
        missing_web_message=refusal or "The packaged Rack is unavailable.",
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=journal,
    )
    app = FastAPI(title="M3FP packaged core-loop heartbeat")
    install_fixture_isolation(app, FIXTURE)

    @app.get("/__scenario__/heartbeat")
    async def heartbeat() -> dict[str, Any]:
        conversations = []
        for entry in journal.catalog():
            conversations.append(
                {
                    "thread_id": entry.thread_id,
                    "messages": journal.read_messages(entry.thread_id),
                }
            )
        return {
            "packaged_assets": web_dist.name in {"_web", "dist"},
            "prepare_calls": spine.prepare_calls,
            "commit_calls": spine.commit_calls,
            "receipt_lines": spine.receipt_lines,
            "conversations": conversations,
        }

    app.mount("/", harness_app)
    return app


__all__ = ["ANSWER", "FIXTURE", "PROMPT", "create_scenario_app"]
