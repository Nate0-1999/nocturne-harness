"""Isolated M2O proof for fixture identity and pending receipt drift."""

from __future__ import annotations

from fastapi import FastAPI

from harness.daemon import create_app
from harness.spine_client import VitalsAccounting, VitalsSnapshot
from verification.fixture_isolation import install_fixture_isolation
from verification.m2m.scenario_app import AS_OF, DRIFT_SNAPSHOT

FIXTURE = "M2O REGRESSION"
PENDING_SNAPSHOT = DRIFT_SNAPSHOT.model_copy(
    update={
        "accounting": VitalsAccounting(
            status="pending",
            pending_lines=2,
            oldest_queued_at=AS_OF,
        )
    }
)


def create_scenario_app() -> FastAPI:
    """Mount the production Rack behind the shared A-038 reachability wall."""

    scenario = FastAPI(title="M2O RULE-7 FIXTURE")
    install_fixture_isolation(scenario, FIXTURE)

    async def read_vitals() -> VitalsSnapshot:
        return PENDING_SNAPSHOT

    scenario.mount("/", create_app(vitals_snapshot_reader=read_vitals))
    return scenario


__all__ = ["create_scenario_app"]
