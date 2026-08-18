"""Fixture-safe rendered proof for the SYM13 plan completion grid."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from harness.daemon import create_app
from harness.recipe_graph import RecipeGraphProjection
from harness.spine_client import MemoryGraphSnapshot, VitalsSnapshot
from verification.fixture_isolation import install_fixture_isolation
from verification.m2c.scenario_app import EMPTY_SNAPSHOT

FIXTURE = "SYM13 REGRESSION"


def _event(event: str, **payload: object) -> dict[str, object]:
    return {"schema_version": 1, "event": event, **payload}


def _child(
    child_id: str,
    title: str,
    charge: str,
    depends_on: list[str],
    *,
    search: bool = False,
) -> dict[str, object]:
    return {
        "child_id": child_id,
        "title": title,
        "charge": charge,
        "depends_on": depends_on,
        "search": (
            {
                "judge_charters": [
                    {"seat": "motivation"},
                    {"seat": "implementation"},
                    {"seat": "performance"},
                ]
            }
            if search
            else None
        ),
    }


def _projection() -> RecipeGraphProjection:
    projection = RecipeGraphProjection()
    projection.record(_event("claim_accepted", packet_id="SYMPHONY", bead_id="ng-symphony"))
    projection.record(
        _event(
            "packet_expanded",
            packet_id="SYMPHONY",
            children=[
                _child("SYM1", "Adapt the Garden", "Turn recipes into live Bead graphs.", []),
                _child("SYM2", "Shadow the Board", "Prove generated board parity.", ["SYM1"]),
                _child(
                    "SYM3", "Draft the handoff", "Carry graph history into the baton.", ["SYM2"]
                ),
                _child(
                    "SYM4", "Supervise workers", "Certify death and recover without replay.", []
                ),
                _child(
                    "SYM5",
                    "Conduct the run",
                    "Send charges down and distillates up.",
                    ["SYM1", "SYM4"],
                ),
                _child(
                    "SYM6", "Bridge the Palace", "Keep losing timelines out of memory.", ["SYM5"]
                ),
                _child(
                    "SYM7",
                    "Search the hard step",
                    "Spend only where deliberation marked uncertainty.",
                    ["SYM5"],
                    search=True,
                ),
                _child(
                    "SYM8",
                    "Convene the judges",
                    "Require independent unanimous judgment.",
                    ["SYM7"],
                ),
                _child(
                    "SYM9",
                    "Run delta rounds",
                    "Advance feedback without rerunning passed work.",
                    ["SYM8"],
                ),
                _child(
                    "SYM10",
                    "Deliberate in chat",
                    "Fix the recipe and authority with the owner.",
                    ["SYM9"],
                ),
                _child(
                    "SYM11",
                    "Steer the conductor",
                    "Keep intervention and lineage on the Deck.",
                    ["SYM10"],
                ),
                _child(
                    "SYM12",
                    "Render the live graph",
                    "Show graph truth and the ready frontier.",
                    ["SYM9"],
                ),
                _child(
                    "SYM13",
                    "Serve the recipe grid",
                    "Make completion legible from left to right.",
                    ["SYM12"],
                ),
            ],
        )
    )

    for child_id in ("SYM1", "SYM4", "SYM2", "SYM3", "SYM5", "SYM6"):
        projection.record(_event("worker_admitted", child_id=child_id))
        projection.record(_event("distillate_accepted", child_id=child_id, status="completed"))
    projection.record(_event("search_exploded", child_id="SYM7"))
    projection.record(_event("search_ready_for_judging", child_id="SYM7"))
    for seat in ("motivation", "implementation", "performance"):
        projection.record(_event("judge_session_dispatched", child_id="SYM7", seat=seat))
        projection.record(
            _event(
                "judge_verdict_accepted",
                child_id="SYM7",
                seat=seat,
                outcome="pass",
            )
        )
    projection.record(_event("search_judgment_recorded", child_id="SYM7", status="unanimous_pass"))
    for child_id in ("SYM8", "SYM9", "SYM10", "SYM11", "SYM12"):
        projection.record(_event("worker_admitted", child_id=child_id))
        projection.record(_event("distillate_accepted", child_id=child_id, status="completed"))
    projection.record(_event("worker_admitted", child_id="SYM13"))
    return projection


def create_scenario_app() -> FastAPI:
    scenario = FastAPI(title=FIXTURE)
    install_fixture_isolation(scenario, FIXTURE)
    projection = _projection()

    async def read_vitals() -> VitalsSnapshot:
        return EMPTY_SNAPSHOT

    async def read_memory_graph(_thread_id: str | None) -> MemoryGraphSnapshot:
        return MemoryGraphSnapshot(
            as_of=datetime(2026, 8, 18, tzinfo=UTC),
            graph_edge_sim=0.72,
            nodes=[],
            edges=[],
            omitted_memory_ids=[],
        )

    def configure_fixture_routes(app: FastAPI) -> None:
        @app.get("/v1/transcripts/catalog")
        async def transcript_catalog() -> dict[str, list[object]]:
            return {"threads": []}

    scenario.mount(
        "/",
        create_app(
            vitals_snapshot_reader=read_vitals,
            memory_graph_reader=read_memory_graph,
            recipe_graph_reader=projection.snapshot,
            before_static_mount=configure_fixture_routes,
        ),
    )
    return scenario


__all__ = ["FIXTURE", "create_scenario_app"]
