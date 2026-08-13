"""Data-bearing, local-only fixture for the standing M2ST4 UI canon."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2st3.scenario_app import HonestDisplaySpine

FIXTURE = "M2ST4 REGRESSION"


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="m2st4-verification",
        machine_id="m2st4-verification",
        agent_id="m2st4-verification",
        chat_model="local:m2st4-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    spine = HonestDisplaySpine()
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2ST4 standing UI canon")
    install_fixture_isolation(app, FIXTURE)

    @app.post("/__scenario__/palace/{state}")
    async def set_palace_state(state: str) -> dict[str, bool]:
        """F045 exercises one health truth for the header and degraded modules."""

        if state not in {"available", "unavailable"}:
            raise ValueError("unknown fixture Palace state")
        spine.palace_available = state == "available"
        return {"palace_available": spine.palace_available}

    @app.post("/v1/threads/{thread_id}/archive")
    async def archive_fixture_thread(thread_id: UUID) -> dict[str, object]:
        """Expose the ordinary Thread End empty result without mutating owner history."""

        return {
            "thread_id": str(thread_id),
            "final_post": "The standing canon keeps the archive return path visible.",
            "working_summary": "",
            "open_loops": [],
            "cards": [],
            "duplicate_count": 0,
            "already_extracted": True,
        }

    app.mount("/", harness_app)
    return app


__all__ = ["FIXTURE", "create_scenario_app"]
