"""Visibly bannered browser fixture for the M3TI thread-locality surface."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    InjectPrepareRequest,
    InjectPrepareResponse,
    MemoryFeatures,
    MemoryKind,
    ScoredMemoryCard,
)
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import FixtureSpine, _model

UPDATED = datetime(2026, 8, 21, 12, tzinfo=UTC)
SAME_THREAD_MEMORY_ID = UUID("91000000-0000-4000-8000-000000000001")
LEGACY_MEMORY_ID = UUID("91000000-0000-4000-8000-000000000002")


class ThreadIndexSpine(FixtureSpine):
    def __init__(self) -> None:
        super().__init__()
        self.prepared_thread_id: UUID | None = None

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepared_thread_id = request.thread_id
        shared = {
            "sem": 0.6,
            "kw": 0.0,
            "time": 1.0,
            "proj": 1.0,
            "freq": 0.0,
            "hist": 0.0,
            "loc": None,
        }
        return InjectPrepareResponse(
            injection_id=UUID("92000000-0000-4000-8000-000000000001"),
            snapshot_ts=UPDATED,
            scorer_version="m3ti-thread-v1",
            injected=[
                ScoredMemoryCard(
                    memory_id=SAME_THREAD_MEMORY_ID,
                    label="Born in this thread",
                    body="The equal-relevance memory carries this conversation's birthplace.",
                    kind=MemoryKind.PROJECT_NOTE,
                    pin=False,
                    score=0.6412,
                    features=MemoryFeatures(**shared, thread=1.0),
                    rank=1,
                ),
                ScoredMemoryCard(
                    memory_id=LEGACY_MEMORY_ID,
                    label="Threadless legacy twin",
                    body="The equal-relevance legacy memory has no conversation birthplace.",
                    kind=MemoryKind.PROJECT_NOTE,
                    pin=False,
                    score=0.61,
                    features=MemoryFeatures(**shared, thread=None),
                    rank=2,
                ),
            ],
            near_misses=[],
            final_block=None,
        )


def create_scenario_app() -> FastAPI:
    spine = ThreadIndexSpine()
    settings = HarnessSettings(
        principal_id="m3ti-verification",
        machine_id="m3ti-verification-machine",
        agent_id="m3ti-verification-agent",
        chat_model="local:m3ti-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="M3TI deterministic verification")
    install_fixture_isolation(app, "M3TI REGRESSION")

    @app.get("/__scenario__/trace")
    async def trace() -> dict[str, str | None]:
        return {
            "prepared_thread_id": (
                None if spine.prepared_thread_id is None else str(spine.prepared_thread_id)
            )
        }

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
