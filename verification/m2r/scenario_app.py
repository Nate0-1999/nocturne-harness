"""Isolated rendered proof for Context Bars."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from harness.context_window import ContextCategories, ContextObservation, ContextWindowSnapshot
from harness.daemon import create_app
from harness.spine_client import VitalsSnapshot
from verification.fixture_isolation import install_fixture_isolation
from verification.m2m.scenario_app import DRIFT_SNAPSHOT

FIXTURE = "M2R REGRESSION"
THREAD_ID = "00000000-0000-4000-8000-000000000039"
OBSERVATION = ContextObservation(
    thread_id=THREAD_ID,
    model="openrouter:anthropic/claude-sonnet-4",
    observed_at=datetime(2026, 8, 4, 18, 30, tzinfo=UTC),
    used_tokens=102_400,
    context_tokens=128_000,
    threshold_tokens=102_400,
    categories=ContextCategories(system=4_300, history=81_200, memory=11_700, tools=5_200),
)


def create_scenario_app() -> FastAPI:
    scenario = FastAPI(title="CONTEXT BARS REGRESSION")
    install_fixture_isolation(scenario, FIXTURE)

    async def read_vitals() -> VitalsSnapshot:
        return DRIFT_SNAPSHOT

    def read_context(thread_id: str | None) -> ContextWindowSnapshot:
        return ContextWindowSnapshot(
            scope="CURRENT" if thread_id is not None else "GLOBAL",
            selected_thread_id=thread_id,
            observations=[OBSERVATION],
            aggregate=OBSERVATION,
        )

    scenario.mount(
        "/",
        create_app(vitals_snapshot_reader=read_vitals, context_window_reader=read_context),
    )
    return scenario


__all__ = ["create_scenario_app"]
