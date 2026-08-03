"""Isolated, visibly bannered rule-7 fixture for the M2C rack resident."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from harness.daemon import create_app
from harness.spine_client import (
    SpineTransportError,
    VitalsLifecycleRate,
    VitalsPalaceCount,
    VitalsSnapshot,
    VitalsSpend,
    VitalsSpendLane,
    VitalsSpendPoint,
)

AS_OF = datetime(2026, 8, 2, 17, 35, tzinfo=UTC)
MINUTE_ESCAPE = datetime(2026, 8, 2, 17, 32, tzinfo=UTC)
MINUTE_A = datetime(2026, 8, 2, 17, 33, tzinfo=UTC)
MINUTE_B = datetime(2026, 8, 2, 17, 34, tzinfo=UTC)
MINUTE_C = datetime(2026, 8, 2, 17, 35, tzinfo=UTC)


def _point(
    minute: datetime,
    cost_usd: str | None,
    receipt_lines: int,
    unpriced_lines: int = 0,
) -> VitalsSpendPoint:
    return VitalsSpendPoint(
        minute=minute,
        cost_usd=cost_usd,
        receipt_lines=receipt_lines,
        unpriced_lines=unpriced_lines,
    )


SNAPSHOT = VitalsSnapshot(
    as_of=AS_OF,
    window_minutes=60,
    spend=VitalsSpend(
        source_view="v_spend_rate",
        latest_minute=MINUTE_C,
        lanes=[
            VitalsSpendLane(
                dimension="total",
                key=None,
                label="All spend",
                points=[
                    _point(MINUTE_ESCAPE, "0.005000000000", 2),
                    _point(MINUTE_A, "0.035000000000", 3),
                    _point(MINUTE_B, "0.004000000000", 2, 1),
                    _point(MINUTE_C, None, 1, 1),
                ],
            ),
            VitalsSpendLane(
                dimension="purpose",
                key="building",
                label="Building",
                points=[
                    _point(MINUTE_ESCAPE, "0.005000000000", 2),
                    _point(MINUTE_A, "0.015000000000", 2),
                    _point(MINUTE_B, "0.004000000000", 2, 1),
                ],
            ),
            VitalsSpendLane(
                dimension="purpose",
                key="curation",
                label="Curation",
                points=[_point(MINUTE_A, "0.020000000000", 1)],
            ),
            VitalsSpendLane(
                dimension="purpose",
                key="judge",
                label="Judging",
                points=[_point(MINUTE_C, None, 1, 1)],
            ),
            VitalsSpendLane(
                dimension="model",
                key="anthropic/claude-sonnet-4.6",
                label="anthropic/claude-sonnet-4.6",
                points=[_point(MINUTE_A, "0.015000000000", 2)],
            ),
            VitalsSpendLane(
                dimension="model",
                key="openai/gpt-5.2",
                label="openai/gpt-5.2",
                points=[
                    _point(MINUTE_A, "0.020000000000", 1),
                    _point(MINUTE_C, None, 1, 1),
                ],
            ),
            VitalsSpendLane(
                dimension="model",
                key="unreported",
                label="Model not reported",
                points=[_point(MINUTE_B, "0.004000000000", 2, 1)],
            ),
            VitalsSpendLane(
                dimension="model",
                key="~unreported",
                label="unreported",
                points=[_point(MINUTE_ESCAPE, "0.002000000000", 1)],
            ),
            VitalsSpendLane(
                dimension="model",
                key="~~unreported",
                label="~unreported",
                points=[_point(MINUTE_ESCAPE, "0.003000000000", 1)],
            ),
        ],
    ),
    lifecycle_rates=[
        VitalsLifecycleRate(
            metric="created",
            status="measured",
            per_hour=3,
            source="memory_unit.created_at",
        ),
        *[
            VitalsLifecycleRate(metric=metric, status="not_recorded", per_hour=None, source=None)
            for metric in (
                "reinforced",
                "superseded",
                "merged",
                "quarantined",
                "tombstoned",
                "add_backs",
            )
        ],
    ],
    palace_counts=[
        VitalsPalaceCount(
            metric="active_units",
            status="measured",
            count=12,
            source="memory_unit.status",
        ),
        VitalsPalaceCount(
            metric="pinned_units",
            status="measured",
            count=2,
            source="memory_unit.status + memory_unit.pin",
        ),
        VitalsPalaceCount(
            metric="candidates_pending",
            status="not_recorded",
            count=None,
            source=None,
        ),
        VitalsPalaceCount(metric="edges", status="not_recorded", count=None, source=None),
        VitalsPalaceCount(
            metric="staged_units",
            status="not_recorded",
            count=None,
            source=None,
        ),
        VitalsPalaceCount(
            metric="queue_depth",
            status="placeholder",
            count=None,
            source=None,
        ),
    ],
)

EMPTY_SNAPSHOT = VitalsSnapshot(
    as_of=AS_OF,
    window_minutes=60,
    spend=VitalsSpend(
        source_view="v_spend_rate",
        latest_minute=None,
        lanes=[VitalsSpendLane(dimension="total", key=None, label="All spend", points=[])],
    ),
    lifecycle_rates=SNAPSHOT.lifecycle_rates,
    palace_counts=SNAPSHOT.palace_counts,
)


def create_scenario_app() -> FastAPI:
    """Create one outer control shell around the real built Harness daemon."""

    scenario = FastAPI(title="M2C RULE-7 FIXTURE")
    state = {"mode": "live"}

    @scenario.middleware("http")
    async def force_fixture_marker(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        additions: dict[str, str] = {}
        if request.url.path == "/" and request.query_params.get("fixture") != "M2C REGRESSION":
            additions["fixture"] = "M2C REGRESSION"
        if (
            request.url.path == "/"
            and request.query_params.get("rack_module") is not None
            and request.query_params.get("rack_host") is None
        ):
            additions["rack_host"] = f"http://127.0.0.1:{request.url.port or 80}"
        if additions:
            return RedirectResponse(
                request.url.include_query_params(**additions),
                status_code=307,
            )
        return await call_next(request)

    async def read_vitals() -> VitalsSnapshot:
        if state["mode"] == "failed":
            raise SpineTransportError()
        return EMPTY_SNAPSHOT if state["mode"] == "empty" else SNAPSHOT

    @scenario.post("/__scenario__/vitals/{mode}")
    async def set_vitals_mode(mode: str) -> dict[str, str]:
        if mode not in {"live", "empty", "failed"}:
            raise ValueError("mode must be live, empty, or failed")
        state["mode"] = mode
        return {"mode": state["mode"]}

    @scenario.get("/__scenario__/trace")
    async def trace() -> dict[str, object]:
        return {
            "fixture": "M2C REGRESSION",
            "source_view": "v_spend_rate",
            "snapshot": SNAPSHOT.model_dump(mode="json"),
        }

    @scenario.get("/__scenario__/identity")
    async def identity() -> dict[str, str]:
        return {"fixture": "M2C REGRESSION"}

    scenario.mount("/", create_app(vitals_snapshot_reader=read_vitals))
    return scenario


__all__ = ["create_scenario_app"]
