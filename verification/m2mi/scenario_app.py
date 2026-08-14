"""Deterministic M2MI fixture using the repository's real AGENTS.md offer."""

from pathlib import Path

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from verification.fixture_isolation import install_fixture_isolation
from verification.m2i.scenario_app import SeedFixtureSpine, _model


def create_scenario_app() -> FastAPI:
    spine = SeedFixtureSpine()
    settings = HarnessSettings(
        principal_id="m2mi-verification",
        machine_id="m2mi-verification-machine",
        agent_id="m2mi-verification-agent",
        chat_model="local:m2mi-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=spine,  # type: ignore[arg-type]
        seed_discovery_root=Path(__file__).resolve().parents[2],
    )
    app = FastAPI(title="M2MI deterministic verification")
    install_fixture_isolation(app, "M2MI REGRESSION")

    @app.get("/__scenario__/trace")
    async def trace() -> dict[str, object]:
        pending = await spine.approval_queue("x", birthplace="seed")
        return {"decisions": spine.decisions, "pending": len(pending.cards)}

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
