"""Current-shape, local-only Rack fixture for the M2UX1 rendered sweep."""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import MemoryGraphSnapshot, ScorerConsoleSnapshot, VitalsSnapshot
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import FixtureSpine, _model
from verification.m2k.scenario_app import graph_payload
from verification.m2z4.scenario_app import _console_payload, _fresh_state, _vitals_snapshot


class LayoutSpine(FixtureSpine):
    """Keep M2H's local write seams while supplying every current Rack read shape."""

    def __init__(self) -> None:
        super().__init__()
        self._learning_state = _fresh_state()

    async def vitals_snapshot(self) -> VitalsSnapshot:
        return _vitals_snapshot()

    async def thread_vitals_snapshot(self, _thread_id: UUID) -> VitalsSnapshot:
        return _vitals_snapshot()

    async def memory_graph(self, _request: object) -> MemoryGraphSnapshot:
        return MemoryGraphSnapshot.model_validate(graph_payload())

    async def scorer_console(self, _request: object) -> ScorerConsoleSnapshot:
        return ScorerConsoleSnapshot.model_validate(_console_payload(self._learning_state))


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="m2ux1-verification",
        machine_id="m2ux1-verification",
        agent_id="m2ux1-verification",
        chat_model="local:m2ux1-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=LayoutSpine(),  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2UX1 deterministic layout verification")
    install_fixture_isolation(app, "M2UX1 REGRESSION")
    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
