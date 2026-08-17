"""Isolated rendered proof for the live Recipe instrument."""

from __future__ import annotations

from fastapi import FastAPI

from harness.daemon import create_app
from harness.recipe_graph import RecipeGraphProjection
from verification.fixture_isolation import install_fixture_isolation

FIXTURE = "SYM12 REGRESSION"


def _event(event: str, **payload: object) -> dict[str, object]:
    return {"schema_version": 1, "event": event, **payload}


def _projection() -> RecipeGraphProjection:
    projection = RecipeGraphProjection()
    projection.record(
        _event(
            "claim_accepted",
            packet_id="OWNER-RECIPE",
            bead_id="ng-owner-recipe",
        )
    )
    projection.record(
        _event(
            "packet_expanded",
            packet_id="OWNER-RECIPE",
            children=[
                {
                    "child_id": "GROUND",
                    "title": "Verify the ground",
                    "charge": "Know what is already true before changing the plan.",
                    "depends_on": [],
                    "search": None,
                },
                {
                    "child_id": "FRAME",
                    "title": "Build the visible frame",
                    "charge": "Make the working path legible while hard research stays bounded.",
                    "depends_on": [],
                    "search": None,
                },
                {
                    "child_id": "HARD",
                    "title": "Find the hard answer",
                    "charge": "Spend only where deliberation marked uncertainty.",
                    "depends_on": ["GROUND"],
                    "search": {
                        "judge_charters": [
                            {"seat": "motivation"},
                            {"seat": "implementation"},
                            {"seat": "performance"},
                        ]
                    },
                },
                {
                    "child_id": "SHIP",
                    "title": "Prove the whole recipe",
                    "charge": "Join accepted implementation and independently judged search.",
                    "depends_on": ["FRAME", "HARD"],
                    "search": None,
                },
            ],
        )
    )
    projection.record(_event("worker_admitted", child_id="GROUND"))
    projection.record(_event("distillate_accepted", child_id="GROUND", status="completed"))
    projection.record(_event("worker_admitted", child_id="FRAME"))
    return projection


def create_scenario_app() -> FastAPI:
    scenario = FastAPI(title=FIXTURE)
    install_fixture_isolation(scenario, FIXTURE)
    projection = _projection()
    scenario.mount("/", create_app(recipe_graph_reader=projection.snapshot))
    return scenario


__all__ = ["create_scenario_app"]
