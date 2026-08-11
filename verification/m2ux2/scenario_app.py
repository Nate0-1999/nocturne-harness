"""Current-shape, local-only Rack fixture for the M2UX2 navigation crawl."""

from __future__ import annotations

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2ux1.scenario_app import LayoutSpine


def create_scenario_app() -> FastAPI:
    spine = LayoutSpine()
    settings = HarnessSettings(
        principal_id="m2h-verification",
        machine_id="m2ux2-verification",
        agent_id="m2ux2-verification",
        chat_model="local:m2ux2-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2UX2 deterministic navigation verification")
    install_fixture_isolation(app, "M2UX2 REGRESSION")

    @app.get("/__scenario__/trace")
    async def trace() -> dict[str, object]:
        return {
            "pending_thread_candidates": sum(
                card.state == "pending" and card.birthplace == "thread"
                for card in spine.cards.values()
            ),
            "candidate_labels": [
                card.candidate.label
                for card in spine.cards.values()
                if card.birthplace == "thread"
            ],
        }

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
