"""Deterministic, visibly bannered M2K memory-instrument fixture."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from harness.daemon import create_app
from harness.spine_client import (
    ActivateScorerConfigRequest,
    CreateScorerConfigRequest,
    MemoryGraphSnapshot,
    ScorerConfigurationView,
    ScorerConsoleSnapshot,
)

NOW = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)
FIRST = "00000000-0000-0000-0000-000000000101"
SECOND = "00000000-0000-0000-0000-000000000102"
VALUES = {
    "tau": 0.55,
    "top_k": 8,
    "budget_tokens": 3000,
    "half_life_time_days": 14.0,
    "half_life_hist_days": 7.0,
    "weights": {"sem": 0.42, "kw": 0.16, "time": 0.11, "proj": 0.16, "freq": 0.08, "hist": 0.07},
}


def graph_payload() -> dict[str, object]:
    def memory(
        memory_id: str, label: str, kind: str, status: str, pin: bool, injections: int
    ) -> dict[str, object]:
        return {
            "memory_id": memory_id,
            "principal_id": "owner",
            "label": label,
            "body": f"{label} body with durable owner context.",
            "kind": kind,
            "keywords": ["m2k", "owner"],
            "project_key": None,
            "thread_origin": None,
            "origin_path": None,
            "pin": pin,
            "status": status,
            "revision": 2,
            "stats": {"injections": injections},
            "bias": 0.0,
            "embedding_model": "fixture-1536",
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }

    return {
        "as_of": NOW.isoformat(),
        "graph_edge_sim": 0.75,
        "nodes": [
            {
                "memory": memory(FIRST, "Owner architecture", "fact", "active", True, 11),
                "in_current_context": True,
                "revisions": [{"rev_uid": "01KZ4S00000000000000000001"}],
            },
            {
                "memory": memory(
                    SECOND, "No silent inference", "preference", "quarantined", False, 3
                ),
                "in_current_context": False,
                "revisions": [{"rev_uid": "01KZ4S00000000000000000002"}],
            },
        ],
        "edges": [
            {
                "kind": "similarity",
                "from_memory_id": FIRST,
                "to_memory_id": SECOND,
                "similarity": "0.8125000",
            }
        ],
        "omitted_memory_ids": [],
    }


def console_payload(active: str = "v0") -> dict[str, object]:
    point = {
        "event_uid": "01KZ4S00000000000000000003",
        "ts": NOW.isoformat(),
        "scorer_version": active,
        "score": "0.6010000",
        "rank": 1,
        "shown_as": "injected",
        "outcome": "kept",
        "features": {"sem": 0.9, "kw": 0.5, "time": 0.8, "proj": 0.4, "freq": 0.2, "hist": 0.6},
        "contributions": {
            "sem": "0.3780000",
            "kw": "0.0800000",
            "time": "0.0880000",
            "proj": "0.0640000",
            "freq": "0.0160000",
            "hist": "0.0420000",
            "bias": "-0.0670000",
        },
    }
    return {
        "as_of": NOW.isoformat(),
        "scope": "GLOBAL",
        "thread_id": None,
        "descriptors": [],
        "active_version": active,
        "configurations": [
            {
                "version": active,
                "created_at": NOW.isoformat(),
                "status": "active",
                "values": VALUES,
                "replay": None,
            }
        ],
        "activations": [],
        "proposed_versions": [],
        "accuracy": [
            {
                "version": active,
                "created_at": NOW.isoformat(),
                "status": "measured",
                "accuracy_percent": "88.0000",
                "holdout_dispositions": 25,
                "disagreements": 3,
            }
        ],
        "candidates": [
            {"memory_id": FIRST, "label": "Owner architecture", "kind": "fact", "points": [point]},
            {
                "memory_id": SECOND,
                "label": "No silent inference",
                "kind": "preference",
                "points": [],
            },
        ],
    }


def create_scenario_app() -> FastAPI:
    state = {"active": "v0", "writes": []}

    async def graph(_thread_id: str | None) -> MemoryGraphSnapshot:
        return MemoryGraphSnapshot.model_validate(graph_payload())

    async def console(_thread_id: str | None) -> ScorerConsoleSnapshot:
        return ScorerConsoleSnapshot.model_validate(console_payload(state["active"]))

    async def enact(body: CreateScorerConfigRequest) -> ScorerConfigurationView:
        state["active"] = f"m2k-{body.event_uid}"
        state["writes"].append(body.model_dump(mode="json"))
        return ScorerConfigurationView.model_validate(
            {
                "version": state["active"],
                "created_at": NOW.isoformat(),
                "status": "active",
                "values": body.values.model_dump(mode="json"),
                "replay": None,
            }
        )

    async def activate(version: str, body: ActivateScorerConfigRequest) -> ScorerConfigurationView:
        del body
        state["active"] = version
        return ScorerConfigurationView.model_validate(
            {
                "version": version,
                "created_at": NOW.isoformat(),
                "status": "active",
                "values": VALUES,
                "replay": None,
            }
        )

    def scenario_routes(app: FastAPI) -> None:
        @app.get("/__scenario__/identity")
        async def identity() -> dict[str, object]:
            return {"fixture": "M2K REGRESSION", "deterministic": True}

        @app.get("/__scenario__/trace")
        async def trace() -> dict[str, object]:
            return deepcopy(state)

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    app = create_app(
        web_dist,
        memory_graph_reader=graph,
        scorer_console_reader=console,
        scorer_config_writer=enact,
        scorer_proposal_activator=activate,
        before_static_mount=scenario_routes,
    )

    return app


__all__ = ["create_scenario_app"]
