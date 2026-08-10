"""Deterministic, visibly bannered M2P scorer-consequence fixture."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from harness.daemon import create_app
from harness.spine_client import (
    RackScorerActivateRequest,
    RackScorerAuditionRequest,
    RackScorerForceRequest,
    RackScorerSimulationRequest,
    ScorerAuditionResponse,
    ScorerConfigurationView,
    ScorerConsoleSnapshot,
    ScorerSimulationResponse,
)
from verification.fixture_isolation import install_fixture_isolation

NOW = datetime(2026, 8, 4, 18, 0, tzinfo=UTC)
INJECTION = "00000000-0000-0000-0000-000000000201"
FIRST = "00000000-0000-0000-0000-000000000202"
SECOND = "00000000-0000-0000-0000-000000000203"
VALUES = {
    "tau": 0.55,
    "top_k": 8,
    "budget_tokens": 3000,
    "half_life_time_days": 14.0,
    "half_life_hist_days": 7.0,
    "weights": {
        "sem": 0.42,
        "kw": 0.16,
        "time": 0.11,
        "proj": 0.16,
        "freq": 0.08,
        "hist": 0.07,
    },
}


def _point(score: str, rank: int, shown_as: str) -> dict[str, object]:
    return {
        "event_uid": f"01KZ5P0000000000000000000{rank}",
        "injection_id": INJECTION,
        "ts": NOW.isoformat(),
        "scorer_version": "v0",
        "score": score,
        "rank": rank,
        "shown_as": shown_as,
        "outcome": None,
        "features": {
            "sem": 0.9,
            "kw": 0.5,
            "time": 0.8,
            "proj": 0.4,
            "freq": 0.2,
            "hist": 0.6,
        },
        "contributions": {
            "sem": "0.378",
            "kw": "0.080",
            "time": "0.088",
            "proj": "0.064",
            "freq": "0.016",
            "hist": "0.042",
            "bias": "-0.067",
        },
    }


def _console(active: str, active_values: dict[str, object]) -> dict[str, object]:
    proposal_values = deepcopy(VALUES)
    proposal_values["tau"] = 0.49
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
                "values": active_values,
                "replay": None,
            }
        ],
        "activations": [],
        "proposed_versions": [
            {
                "version": "learner-m2p",
                "created_at": NOW.isoformat(),
                "status": "proposed",
                "values": proposal_values,
                "replay": {"holdout_dispositions": 25},
            }
        ],
        "accuracy": [
            {
                "version": "v0",
                "created_at": NOW.isoformat(),
                "status": "measured",
                "accuracy_percent": "88",
                "holdout_dispositions": 25,
                "disagreements": 3,
                "weighted_dispositions": "25",
                "weighted_wrong": "3",
            },
            {
                "version": "learner-m2p",
                "created_at": NOW.isoformat(),
                "status": "measured",
                "accuracy_percent": "92",
                "holdout_dispositions": 25,
                "disagreements": 2,
                "weighted_dispositions": "25",
                "weighted_wrong": "2",
            },
        ],
        "learning": {
            "eligible_dispositions": 31,
            "hygiene_excluded_dispositions": 3,
            "minimum_dispositions": 25,
            "remaining_to_floor": 0,
            "floor_met": True,
            "retrain_signal_stride": 25,
            "evaluated_through": 31,
            "signals_since_last_run": 0,
            "signals_until_next_run": 25,
            "active_scorer_version": active,
            "right": 7,
            "wrong": 2,
            "weighted_right": "6.25",
            "weighted_wrong": "2",
            "weighted_agreement_percent": "75.7576",
            "live_agreement": [
                {
                    "event_uid": "01KZ5P00000000000000000003",
                    "ts": NOW.isoformat(),
                    "scorer_version": active,
                    "right": 6,
                    "wrong": 2,
                    "weighted_right": "5.25",
                    "weighted_wrong": "2",
                    "weighted_agreement_percent": "72.4138",
                },
                {
                    "event_uid": "01KZ5P00000000000000000004",
                    "ts": NOW.isoformat(),
                    "scorer_version": active,
                    "right": 7,
                    "wrong": 2,
                    "weighted_right": "6.25",
                    "weighted_wrong": "2",
                    "weighted_agreement_percent": "75.7576",
                },
            ],
            "retrain_runs": [
                {
                    "run_uid": "01KZ5P00000000000000000005",
                    "trigger": "background",
                    "result": "proposed",
                    "incumbent_version": active,
                    "proposal_version": "learner-m2p",
                    "eligible_dispositions": 31,
                    "training_dispositions": 25,
                    "holdout_dispositions": 6,
                    "training_pairs": 14,
                    "source_boundary": "01KZ5P00000000000000000004",
                    "incumbent": {
                        "disagreements": 3,
                        "weighted_disagreements": "3",
                        "injected_tokens": 900,
                    },
                    "challenger": {
                        "disagreements": 2,
                        "weighted_disagreements": "2",
                        "injected_tokens": 900,
                    },
                    "reason": "challenger won replay and remains inactive pending owner activation",
                    "ts": NOW.isoformat(),
                }
            ],
            "annotations": [
                {
                    "kind": "retrain",
                    "event_uid": "01KZ5P00000000000000000005",
                    "ts": NOW.isoformat(),
                    "version": "learner-m2p",
                    "result": "proposed",
                }
            ],
        },
        "candidates": [
            {
                "memory_id": FIRST,
                "label": "Owner architecture",
                "kind": "fact",
                "points": [_point("0.601", 1, "injected")],
            },
            {
                "memory_id": SECOND,
                "label": "No silent inference",
                "kind": "preference",
                "points": [_point("0.521", 2, "near_miss")],
            },
        ],
    }


def _instant(tau: float, *, audition: bool = False) -> dict[str, object]:
    first_selected = tau <= 0.64
    second_selected = tau <= 0.53 or audition
    return {
        "status": "ready",
        "injection_id": INJECTION,
        "candidates": [
            {
                "memory_id": FIRST,
                "label": "Owner architecture",
                "incumbent_score": "0.601",
                "preview_score": f"{0.601 + (0.55 - tau) * 0.4:.3f}",
                "score_delta": f"{(0.55 - tau) * 0.4:.3f}",
                "incumbent_rank": 1,
                "preview_rank": 1,
                "incumbent_selected": True,
                "preview_selected": first_selected,
                "disposition": "also_shown" if first_selected else "would_drop",
            },
            {
                "memory_id": SECOND,
                "label": "No silent inference",
                "incumbent_score": "0.521",
                "preview_score": f"{0.521 + (0.55 - tau) * 0.5:.3f}",
                "score_delta": f"{(0.55 - tau) * 0.5:.3f}",
                "incumbent_rank": 2,
                "preview_rank": 2,
                "incumbent_selected": False,
                "preview_selected": second_selected,
                "disposition": "would_add" if second_selected else "still_out",
            },
        ],
    }


def create_scenario_app() -> FastAPI:
    state: dict[str, object] = {
        "active": "v0",
        "active_values": deepcopy(VALUES),
        "simulations": [],
        "forces": [],
        "auditions": [],
    }

    async def console(_thread_id: str | None) -> ScorerConsoleSnapshot:
        return ScorerConsoleSnapshot.model_validate(
            _console(str(state["active"]), deepcopy(state["active_values"]))
        )

    async def simulate(body: RackScorerSimulationRequest) -> ScorerSimulationResponse:
        state["simulations"].append(body.model_dump(mode="json"))
        points = [
            {"value": index / 8, "accuracy_percent": f"{84 + index * 1.25:.2f}"}
            for index in range(9)
        ]
        return ScorerSimulationResponse.model_validate(
            {
                "simulation_digest": "a" * 64,
                "base_version": body.base_version,
                "values": body.values.model_dump(mode="json"),
                "source_boundary": "01KZ5P00000000000000000002",
                "holdout_dispositions": 25,
                "accuracy_percent": "92",
                "incumbent_accuracy_percent": "88",
                "delta_percent": "4",
                "instant": (
                    _instant(body.values.tau)
                    if body.injection_id is not None
                    else {"status": "not_requested", "injection_id": None, "candidates": []}
                ),
                "slice": {"parameter_id": body.slice_parameter_id, "points": points},
            }
        )

    async def force(body: RackScorerForceRequest) -> ScorerConfigurationView:
        state["forces"].append(body.model_dump(mode="json"))
        state["active"] = f"m2k-{body.event_uid}"
        state["active_values"] = body.values.model_dump(mode="json")
        return ScorerConfigurationView.model_validate(
            {
                "version": state["active"],
                "created_at": NOW.isoformat(),
                "status": "active",
                "values": state["active_values"],
                "replay": None,
            }
        )

    async def audition(body: RackScorerAuditionRequest) -> ScorerAuditionResponse:
        state["auditions"].append(body.model_dump(mode="json"))
        return ScorerAuditionResponse.model_validate(
            {
                "incumbent_version": state["active"],
                "proposal_version": body.proposal_version,
                "instant": _instant(0.49, audition=True),
            }
        )

    async def activate(version: str, body: RackScorerActivateRequest) -> ScorerConfigurationView:
        del body
        state["active"] = version
        return ScorerConfigurationView.model_validate(
            {
                "version": version,
                "created_at": NOW.isoformat(),
                "status": "active",
                "values": state["active_values"],
                "replay": None,
            }
        )

    def scenario_routes(app: FastAPI) -> None:
        install_fixture_isolation(app, "M2P REGRESSION")

        @app.get("/__scenario__/trace")
        async def trace() -> dict[str, object]:
            return deepcopy(state)

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    return create_app(
        web_dist,
        scorer_console_reader=console,
        scorer_simulator=simulate,
        scorer_config_writer=force,
        scorer_auditioner=audition,
        scorer_proposal_activator=activate,
        before_static_mount=scenario_routes,
    )


__all__ = ["create_scenario_app"]
