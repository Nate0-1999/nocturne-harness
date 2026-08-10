"""Deterministic, visibly isolated M2Z4 learning-cockpit regression fixture.

This exercises Harness's real rack query/action callbacks. The scenario-only
background transition is presentation evidence, not proof of Spine's worker.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI

from harness.daemon import create_app
from harness.spine_client import (
    RackScorerActivateRequest,
    RackScorerAuditionRequest,
    RackScorerSimulationRequest,
    RetrainResponse,
    ScorerAuditionResponse,
    ScorerConfigurationView,
    ScorerConsoleSnapshot,
    ScorerSimulationResponse,
    SpineClientError,
    VitalsSnapshot,
)
from verification.fixture_isolation import install_fixture_isolation

NOW = datetime(2026, 8, 9, 18, 0, tzinfo=UTC)
INJECTION_ID = "00000000-0000-0000-0000-000000000404"
FIRST_MEMORY_ID = "00000000-0000-0000-0000-000000000405"
SECOND_MEMORY_ID = "00000000-0000-0000-0000-000000000406"
ACTIVE_VERSION = "m2z4-incumbent"
PROPOSAL_VERSION = "m2z4-proposal"
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


def _at(minutes: int) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


def _fresh_state() -> dict[str, Any]:
    return {
        "phase": "collecting",
        "console_reads": 0,
        "manual_retrains": [],
        "scenario_background_triggers": 0,
        "simulations": [],
        "auditions": [],
        "activation_attempts": [],
        "active_version": ACTIVE_VERSION,
    }


def _configuration(
    version: str,
    *,
    status: str,
    values: dict[str, object],
    created_at: str,
) -> dict[str, object]:
    return {
        "version": version,
        "created_at": created_at,
        "status": status,
        "values": deepcopy(values),
        "replay": None,
    }


def _proposal_values() -> dict[str, object]:
    values = deepcopy(VALUES)
    values["tau"] = 0.49
    return values


def _live_agreement(*, proposed: bool) -> list[dict[str, object]]:
    rows = (
        ("03", -50, 1, 0, "1", "0", "100"),
        ("04", -40, 2, 0, "2", "0", "100"),
        ("05", -30, 2, 1, "2", "1", "66.6667"),
        ("06", -20, 3, 1, "3", "1", "75"),
        ("07", -10, 4, 1, "4", "1", "80"),
        ("08", 0, 5, 1, "5", "1", "83.3333"),
        ("09", 2, 5, 2, "5", "2", "71.4286"),
        ("10", 4, 6, 2, "6", "2", "75"),
        ("11", 6, 7, 2, "7", "2", "77.7778"),
        ("12", 8, 8, 2, "8", "2", "80"),
        ("13", 10, 9, 2, "9", "2", "81.8182"),
        ("14", 12, 10, 2, "10", "2", "83.3333"),
    )
    limit = len(rows) if proposed else 6
    return [
        {
            "event_uid": f"01KZ4L000000000000000000{suffix}",
            "ts": _at(minute),
            "scorer_version": ACTIVE_VERSION,
            "right": right,
            "wrong": wrong,
            "weighted_right": weighted_right,
            "weighted_wrong": weighted_wrong,
            "weighted_agreement_percent": agreement,
        }
        for suffix, minute, right, wrong, weighted_right, weighted_wrong, agreement in rows[:limit]
    ]


def _background_run() -> dict[str, object]:
    return {
        "run_uid": "m2z4-background-1",
        "trigger": "background",
        "result": "proposed",
        "incumbent_version": ACTIVE_VERSION,
        "proposal_version": PROPOSAL_VERSION,
        "eligible_dispositions": 25,
        "training_dispositions": 20,
        "holdout_dispositions": 5,
        "training_pairs": 12,
        "source_boundary": "01KZ4L00000000000000000014",
        "incumbent": {
            "disagreements": 2,
            "weighted_disagreements": "2",
            "injected_tokens": 800,
        },
        "challenger": {
            "disagreements": 1,
            "weighted_disagreements": "1",
            "injected_tokens": 800,
        },
        "reason": "challenger won replay and remains inactive pending owner activation",
        "ts": _at(15),
    }


def _learning(state: dict[str, Any]) -> dict[str, object]:
    proposed = state["phase"] == "proposed"
    annotations: list[dict[str, object]] = [
        {
            "kind": "activation",
            "event_uid": "01KZ4L00000000000000000001",
            "ts": _at(-110),
            "version": ACTIVE_VERSION,
            "result": None,
        },
        {
            "kind": "force_values",
            "event_uid": "01KZ4L00000000000000000002",
            "ts": _at(-105),
            "version": ACTIVE_VERSION,
            "result": None,
        },
    ]
    for run in state["manual_retrains"]:
        annotations.append(
            {
                "kind": "retrain",
                "event_uid": run["run_uid"],
                "ts": run["ts"],
                "version": run["proposal_version"] or run["incumbent_version"],
                "result": run["result"],
            }
        )
    runs = deepcopy(state["manual_retrains"])
    if proposed:
        background = _background_run()
        runs.append(background)
        annotations.append(
            {
                "kind": "retrain",
                "event_uid": background["run_uid"],
                "ts": background["ts"],
                "version": PROPOSAL_VERSION,
                "result": "proposed",
            }
        )
    return {
        "eligible_dispositions": 25 if proposed else 18,
        "hygiene_excluded_dispositions": 6,
        "minimum_dispositions": 25,
        "remaining_to_floor": 0 if proposed else 7,
        "floor_met": proposed,
        "retrain_signal_stride": 25,
        "evaluated_through": 25 if proposed else None,
        "signals_since_last_run": 0 if proposed else 18,
        "signals_until_next_run": 25 if proposed else 7,
        "active_scorer_version": ACTIVE_VERSION,
        "right": 10 if proposed else 5,
        "wrong": 2 if proposed else 1,
        "weighted_right": "10" if proposed else "5",
        "weighted_wrong": "2" if proposed else "1",
        "weighted_agreement_percent": "83.3333",
        "live_agreement": _live_agreement(proposed=proposed),
        "retrain_runs": runs,
        "annotations": annotations,
    }


def _candidate(
    memory_id: str,
    label: str,
    *,
    score: str,
    rank: int,
    shown_as: str,
) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "label": label,
        "kind": "preference" if rank == 2 else "fact",
        "points": [
            {
                "event_uid": f"01KZ4L000000000000000000{14 + rank:02d}",
                "injection_id": INJECTION_ID,
                "ts": _at(12),
                "scorer_version": ACTIVE_VERSION,
                "score": score,
                "rank": rank,
                "shown_as": shown_as,
                "outcome": "kept" if rank == 1 else None,
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
        ],
    }


def _console_payload(state: dict[str, Any]) -> dict[str, object]:
    proposed = state["phase"] == "proposed"
    configurations = [
        _configuration(
            ACTIVE_VERSION,
            status="active",
            values=VALUES,
            created_at=_at(-120),
        )
    ]
    proposals: list[dict[str, object]] = []
    accuracy: list[dict[str, object]] = [
        {
            "version": "v0",
            "created_at": _at(-240),
            "status": "measured",
            "accuracy_percent": "80",
            "holdout_dispositions": 25,
            "disagreements": 5,
            "weighted_dispositions": "25",
            "weighted_wrong": "5",
        },
        {
            "version": ACTIVE_VERSION,
            "created_at": _at(-120),
            "status": "measured",
            "accuracy_percent": "84",
            "holdout_dispositions": 25,
            "disagreements": 4,
            "weighted_dispositions": "25",
            "weighted_wrong": "4",
        },
    ]
    if proposed:
        proposal = _configuration(
            PROPOSAL_VERSION,
            status="proposed",
            values=_proposal_values(),
            created_at=_at(15),
        )
        proposal["replay"] = {
            "holdout_dispositions": 5,
            "weighted_dispositions": "5",
            "weighted_wrong": "0.4",
        }
        configurations.append(proposal)
        proposals.append(proposal)
        accuracy.append(
            {
                "version": PROPOSAL_VERSION,
                "created_at": _at(15),
                "status": "measured",
                "accuracy_percent": "92",
                "holdout_dispositions": 5,
                "disagreements": 1,
                "weighted_dispositions": "5",
                "weighted_wrong": "0.4",
            }
        )
    return {
        "as_of": _at(20),
        "scope": "GLOBAL",
        "thread_id": None,
        "descriptors": [],
        "active_version": ACTIVE_VERSION,
        "configurations": configurations,
        "activations": [
            {
                "event_uid": "01KZ4L00000000000000000001",
                "version": ACTIVE_VERSION,
                "previous_version": "v0",
                "actor_class": "human",
                "machine_id": "m2z4-fixture",
                "reason": "learner_proposal",
                "changes": {},
                "ts": _at(-110),
            }
        ],
        "proposed_versions": proposals,
        "accuracy": accuracy,
        "learning": _learning(state),
        "candidates": [
            _candidate(
                FIRST_MEMORY_ID,
                "Owner architecture",
                score="0.601",
                rank=1,
                shown_as="injected",
            ),
            _candidate(
                SECOND_MEMORY_ID,
                "No silent inference",
                score="0.521",
                rank=2,
                shown_as="near_miss",
            ),
        ],
    }


def _audition_instant() -> dict[str, object]:
    return {
        "status": "ready",
        "injection_id": INJECTION_ID,
        "candidates": [
            {
                "memory_id": FIRST_MEMORY_ID,
                "label": "Owner architecture",
                "incumbent_score": "0.601",
                "preview_score": "0.625",
                "score_delta": "0.024",
                "incumbent_rank": 1,
                "preview_rank": 1,
                "incumbent_selected": True,
                "preview_selected": True,
                "disposition": "also_shown",
            },
            {
                "memory_id": SECOND_MEMORY_ID,
                "label": "No silent inference",
                "incumbent_score": "0.521",
                "preview_score": "0.551",
                "score_delta": "0.030",
                "incumbent_rank": 2,
                "preview_rank": 2,
                "incumbent_selected": False,
                "preview_selected": True,
                "disposition": "would_add",
            },
        ],
    }


def _vitals_snapshot() -> VitalsSnapshot:
    return VitalsSnapshot.model_validate(
        {
            "as_of": NOW.isoformat(),
            "window_minutes": 60,
            "spend": {
                "source_view": "v_spend_rate",
                "latest_minute": None,
                "lanes": [{"dimension": "total", "key": None, "label": "All spend", "points": []}],
            },
            "reconciliation": {
                "status": "not_recorded",
                "checked_at": None,
                "broker_usage_usd": None,
                "ledger_cost_usd": None,
                "broker_since_baseline_usd": None,
                "ledger_since_baseline_usd": None,
                "drift_usd": None,
                "tolerance_usd": None,
                "unpriced_lines": 0,
                "source": None,
                "error_code": None,
            },
            "accounting": {
                "status": "clear",
                "pending_lines": 0,
                "oldest_queued_at": None,
                "source": "harness.receipt_queue",
            },
            "resources": {
                "status": "partial",
                "daemon_rss_bytes": None,
                "daemon_uptime_seconds": None,
                "disk_free_bytes": None,
                "disk_total_bytes": None,
                "database_bytes": 0,
                "journal_bytes": None,
                "backup_bytes": None,
                "warning": None,
            },
            "lifecycle_rates": [
                {
                    "metric": "created",
                    "status": "measured",
                    "per_hour": 0,
                    "source": "m2z4.fixture",
                },
                *[
                    {
                        "metric": metric,
                        "status": "not_recorded",
                        "per_hour": None,
                        "source": None,
                    }
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
            "palace_counts": [
                *[
                    {
                        "metric": metric,
                        "status": "measured",
                        "count": count,
                        "source": "m2z4.fixture",
                    }
                    for metric, count in (
                        ("active_units", 12),
                        ("pinned_units", 2),
                        ("candidates_pending", 1),
                        ("edges", 4),
                    )
                ],
                {
                    "metric": "staged_units",
                    "status": "not_recorded",
                    "count": None,
                    "source": None,
                },
                {
                    "metric": "queue_depth",
                    "status": "measured",
                    "count": 0,
                    "source": "m2z4.fixture",
                },
            ],
        }
    )


def create_scenario_app() -> FastAPI:
    state = _fresh_state()

    async def vitals() -> VitalsSnapshot:
        return _vitals_snapshot()

    async def thread_vitals(_thread_id: UUID) -> VitalsSnapshot:
        return _vitals_snapshot()

    async def console(_thread_id: str | None) -> ScorerConsoleSnapshot:
        state["console_reads"] += 1
        return ScorerConsoleSnapshot.model_validate(_console_payload(state))

    async def retrain() -> RetrainResponse:
        proposed = state["phase"] == "proposed"
        index = len(state["manual_retrains"]) + 1
        response: dict[str, object] = {
            "status": "not_better" if proposed else "insufficient_data",
            "incumbent_version": ACTIVE_VERSION,
            "proposal_version": None,
            "eligible_dispositions": 25 if proposed else 18,
            "training_dispositions": 20 if proposed else 0,
            "holdout_dispositions": 5 if proposed else 0,
            "training_pairs": 12 if proposed else 0,
            "incumbent": (
                {
                    "disagreements": 2,
                    "weighted_disagreements": "2",
                    "injected_tokens": 800,
                }
                if proposed
                else None
            ),
            "challenger": (
                {
                    "disagreements": 2,
                    "weighted_disagreements": "2",
                    "injected_tokens": 800,
                }
                if proposed
                else None
            ),
            "reason": (
                "challenger did not clear the replay win rule"
                if proposed
                else "minimum disposition floor not reached: 18/25"
            ),
        }
        state["manual_retrains"].append(
            {
                "run_uid": f"m2z4-manual-{index}",
                "trigger": "manual",
                "result": response["status"],
                "incumbent_version": response["incumbent_version"],
                "proposal_version": response["proposal_version"],
                "eligible_dispositions": response["eligible_dispositions"],
                "training_dispositions": response["training_dispositions"],
                "holdout_dispositions": response["holdout_dispositions"],
                "training_pairs": response["training_pairs"],
                "source_boundary": ("01KZ4L00000000000000000014" if proposed else None),
                "incumbent": response["incumbent"],
                "challenger": response["challenger"],
                "reason": response["reason"],
                "ts": _at(4 + index),
            }
        )
        return RetrainResponse.model_validate(response)

    async def simulate(body: RackScorerSimulationRequest) -> ScorerSimulationResponse:
        state["simulations"].append(body.model_dump(mode="json"))
        return ScorerSimulationResponse.model_validate(
            {
                "simulation_digest": "4" * 64,
                "base_version": body.base_version,
                "values": body.values.model_dump(mode="json"),
                "source_boundary": "01KZ4L00000000000000000014",
                "holdout_dispositions": 5,
                "accuracy_percent": "84",
                "incumbent_accuracy_percent": "84",
                "delta_percent": "0",
                "instant": (
                    _audition_instant()
                    if body.injection_id is not None
                    else {"status": "not_requested", "injection_id": None, "candidates": []}
                ),
                "slice": {"parameter_id": body.slice_parameter_id, "points": []},
            }
        )

    async def audition(body: RackScorerAuditionRequest) -> ScorerAuditionResponse:
        if state["phase"] != "proposed" or body.proposal_version != PROPOSAL_VERSION:
            raise SpineClientError("the M2Z4 proposal is not available yet")
        state["auditions"].append(body.model_dump(mode="json"))
        return ScorerAuditionResponse.model_validate(
            {
                "incumbent_version": ACTIVE_VERSION,
                "proposal_version": PROPOSAL_VERSION,
                "instant": _audition_instant(),
            }
        )

    async def refuse_activation(
        version: str, body: RackScorerActivateRequest
    ) -> ScorerConfigurationView:
        state["activation_attempts"].append({"version": version, **body.model_dump(mode="json")})
        raise SpineClientError("the M2Z4 regression fixture never activates a proposal")

    def scenario_routes(app: FastAPI) -> None:
        install_fixture_isolation(app, "M2Z4 REGRESSION")

        @app.post("/__scenario__/reset")
        async def reset() -> dict[str, object]:
            state.clear()
            state.update(_fresh_state())
            return {"phase": state["phase"], "active_version": state["active_version"]}

        @app.post("/__scenario__/background-proposal")
        async def reveal_background_proposal() -> dict[str, object]:
            transitioned = state["phase"] != "proposed"
            state["phase"] = "proposed"
            state["scenario_background_triggers"] += 1
            return {
                "transitioned": transitioned,
                "phase": state["phase"],
                "proposal_version": PROPOSAL_VERSION,
                "evidence_scope": (
                    "deterministic UI polling evidence only; actual worker behavior is "
                    "proved by Spine/Postgres tests"
                ),
            }

        @app.get("/__scenario__/trace")
        async def trace() -> dict[str, object]:
            return {
                "fixture": "M2Z4 REGRESSION",
                "evidence_scope": (
                    "Harness rack/UI regression only; not actual background-worker proof"
                ),
                "actual_background_proof": (
                    "spine/tests/test_learner_api.py::test_real_worker_startup_and_"
                    "work_wake_persists_background_inactive_winner; companion "
                    "Postgres proof: test_background_retrain_crosses_authentic_floor_"
                    "and_never_activates"
                ),
                "state": deepcopy(state),
                "snapshot": _console_payload(state),
            }

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    return create_app(
        web_dist,
        vitals_snapshot_reader=vitals,
        thread_vitals_snapshot_reader=thread_vitals,
        scorer_console_reader=console,
        scorer_simulator=simulate,
        scorer_auditioner=audition,
        scorer_retrainer=retrain,
        scorer_proposal_activator=refuse_activation,
        before_static_mount=scenario_routes,
    )


__all__ = ["create_scenario_app"]
