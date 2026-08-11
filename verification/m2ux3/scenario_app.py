"""Current-shape, local-only Rack fixture for M2UX3 module handling."""

from __future__ import annotations

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2ux1.scenario_app import LayoutSpine


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="m2ux3-verification",
        machine_id="m2ux3-verification",
        agent_id="m2ux3-verification",
        chat_model="local:m2ux3-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=LayoutSpine(),  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2UX3 deterministic module-template verification")
    install_fixture_isolation(app, "M2UX3 REGRESSION")
    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
