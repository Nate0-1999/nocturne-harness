"""Deterministic, visibly bannered M2M Vitals reconciliation fixture."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from harness.daemon import create_app
from harness.spine_client import (
    VitalsLifecycleRate,
    VitalsPalaceCount,
    VitalsReconciliation,
    VitalsSnapshot,
    VitalsSpend,
    VitalsSpendLane,
)

FIXTURE = "M2M REGRESSION"
AS_OF = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)
DRIFT = VitalsReconciliation(
    status="drift",
    checked_at=AS_OF,
    broker_usage_usd="10.300000000000",
    ledger_cost_usd="1.350000000000",
    broker_since_baseline_usd="0.300000000000",
    ledger_since_baseline_usd="0.350000000000",
    drift_usd="0.050000000000",
    tolerance_usd="0.000001000000",
    unpriced_lines=1,
    source="openrouter:/api/v1/key",
    error_code=None,
)
DRIFT_SNAPSHOT = VitalsSnapshot(
    as_of=AS_OF,
    window_minutes=60,
    spend=VitalsSpend(
        source_view="v_spend_rate",
        latest_minute=None,
        lanes=[
            VitalsSpendLane(
                dimension="total",
                key=None,
                label="All spend",
                points=[],
            )
        ],
    ),
    reconciliation=DRIFT,
    lifecycle_rates=[
        VitalsLifecycleRate(
            metric="created", status="measured", per_hour=2, source="fixture"
        ),
        *[
            VitalsLifecycleRate(
                metric=metric, status="not_recorded", per_hour=None, source=None
            )
            for metric in (
                "reinforced", "superseded", "merged", "quarantined", "tombstoned", "add_backs"
            )
        ],
    ],
    palace_counts=[
        VitalsPalaceCount(metric="active_units", status="measured", count=12, source="fixture"),
        VitalsPalaceCount(metric="pinned_units", status="measured", count=2, source="fixture"),
        VitalsPalaceCount(
            metric="candidates_pending", status="measured", count=3, source="fixture"
        ),
        VitalsPalaceCount(metric="edges", status="measured", count=8, source="fixture"),
        VitalsPalaceCount(metric="staged_units", status="not_recorded", count=None, source=None),
        VitalsPalaceCount(metric="queue_depth", status="measured", count=1, source="fixture"),
    ],
)


def create_scenario_app() -> FastAPI:
    scenario = FastAPI(title="M2M RULE-7 FIXTURE")

    @scenario.middleware("http")
    async def force_fixture_marker(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/" and request.query_params.get("fixture") != FIXTURE:
            return RedirectResponse(
                request.url.include_query_params(fixture=FIXTURE),
                status_code=307,
            )
        return await call_next(request)

    async def read_vitals() -> VitalsSnapshot:
        return DRIFT_SNAPSHOT

    @scenario.get("/__scenario__/identity")
    async def identity() -> dict[str, str]:
        return {"fixture": FIXTURE}

    @scenario.get("/__scenario__/snapshot")
    async def snapshot() -> dict[str, object]:
        return DRIFT_SNAPSHOT.model_dump(mode="json")

    scenario.mount("/", create_app(vitals_snapshot_reader=read_vitals))
    return scenario


__all__ = ["create_scenario_app"]
