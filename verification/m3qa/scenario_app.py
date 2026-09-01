"""Real Rack scenario for M3QA's 0.1.6-shaped curator-activity absence."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import CuratorActivity, SpineClient
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2st3.scenario_app import HonestDisplaySpine

FIXTURE = "M3QA REGRESSION"


class LegacyCuratorSpine(HonestDisplaySpine):
    """Keep live Palace State data while routing curation through the real adapter."""

    def __init__(self) -> None:
        super().__init__()

        async def legacy_palace(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/curation"
            assert request.url.params.get("principal_id") == "m3qa-verification"
            return httpx.Response(
                404,
                json={"detail": "Not Found"},
                headers={"content-type": "application/json"},
            )

        self._legacy_client = SpineClient(
            "https://palace-0-1-6.invalid",
            "verification-token",
            transport=httpx.MockTransport(legacy_palace),
        )

    async def curator_activity(self, principal_id: str) -> CuratorActivity | None:
        return await self._legacy_client.curator_activity(principal_id)

    async def aclose(self) -> None:
        await self._legacy_client.aclose()
        await super().aclose()


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="m3qa-verification",
        machine_id="m3qa-verification",
        agent_id="m3qa-verification",
        chat_model="local:m3qa-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=LegacyCuratorSpine(),  # type: ignore[arg-type]
    )
    app = FastAPI(title="M3QA legacy-Palace tolerance verification")
    install_fixture_isolation(app, FIXTURE)

    @app.get("/__scenario__/palace")
    async def palace_shape() -> dict[str, str]:
        return {
            "version": "0.1.6",
            "schema_version": "0017",
            "api_contract_version": "0.1.6",
            "curator_activity": "absent",
        }

    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
