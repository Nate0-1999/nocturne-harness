"""Deterministic, data-bearing fixture for M2ST3 honest display."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    CuratorActivity,
    MemoryGraphSnapshot,
    MemoryStatus,
    QueueCard,
    ScorerConsoleSnapshot,
    SpendTableSnapshot,
    SpineTransportError,
    VitalsSnapshot,
)
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import NEIGHBOR_ID, UPDATED, _memory, _model, _uid
from verification.m2k.scenario_app import graph_payload
from verification.m2ux1.scenario_app import LayoutSpine
from verification.m2z4.scenario_app import _console_payload, _vitals_snapshot

FIXTURE = "M2ST3 REGRESSION"


class HonestDisplaySpine(LayoutSpine):
    """Supply deliberately over-precise values and crowded graph labels."""

    def __init__(self) -> None:
        super().__init__()
        self.palace_available = True
        item_uid = _uid(301)
        self.cards[item_uid] = QueueCard(
            item_uid=item_uid,
            candidate=_memory(
                UUID("30000000-0000-4000-8000-000000000301"),
                "Owner architecture",
                "The owner architecture stays local and provenance-preserving.",
                status=MemoryStatus.ACTIVE,
                keywords=["owner", "architecture"],
            ),
            birthplace="curator",
            birthplace_thread_id=None,
            batch_uid=None,
            source_name=None,
            source_sha256=None,
            candidate_revision=3,
            curator_run_uid="01K3CURATORRUN000000000301",
            curator_finding_uid="01K3CURATORFIND00000000301",
            proposal_payload={
                "action": "keyword_repair",
                "rationale": (
                    "Two stable terms make this memory findable without changing its claim."
                ),
                "keywords": ["owner", "architecture"],
            },
            verdict="keyword_repair",
            neighbors=[],
            target_ids=[NEIGHBOR_ID],
            state="pending",
            created_at=UPDATED,
        )

    def _require_palace(self) -> None:
        if not self.palace_available:
            raise SpineTransportError

    async def vitals_snapshot(self) -> VitalsSnapshot:
        self._require_palace()
        return _honest_vitals()

    async def thread_vitals_snapshot(self, _thread_id: UUID) -> VitalsSnapshot:
        self._require_palace()
        return _honest_vitals()

    async def spend_table(
        self, thread_ids: list[UUID] | None = None
    ) -> SpendTableSnapshot:
        self._require_palace()
        snapshot = _honest_spend_table()
        if thread_ids is None:
            return snapshot
        threads = [row for row in snapshot.threads if row.thread_id in thread_ids]
        return snapshot.model_copy(
            update={"threads": threads, "purposes": snapshot.purposes if threads else []}
        )

    async def memory_graph(self, _request: object) -> MemoryGraphSnapshot:
        self._require_palace()
        return MemoryGraphSnapshot.model_validate(_crowded_graph())

    async def scorer_console(self, _request: object) -> ScorerConsoleSnapshot:
        self._require_palace()
        payload = _console_payload(self._learning_state)
        payload["learning"]["weighted_agreement_percent"] = "11.1111111111111111"
        payload["learning"]["weighted_right"] = "12.345678901234"
        payload["accuracy"][0]["accuracy_percent"] = "11.1111111111111111"
        point = payload["candidates"][0]["points"][0]
        point["score"] = "0.0990035717639611430"
        point["contributions"] = {
            "sem": "0.0990035746257907776",
            "kw": "0",
            "time": "0",
            "proj": "0",
            "freq": "0",
            "hist": "0",
            "bias": "-0.0000000028618296346",
        }
        return ScorerConsoleSnapshot.model_validate(payload)

    async def curator_activity(self, principal_id: str) -> CuratorActivity:
        self._require_palace()
        return CuratorActivity.model_validate(
            {
                "principal_id": principal_id,
                "admitted_writes": 41,
                "last_run_writes": 25,
                "pressure_events": 4,
                "last_run_pressure": 3,
                "trigger_every": 25,
                "pressure_trigger_every": 3,
                "writes_until_run": 9,
                "pressure_until_run": 2,
                "latest_run": {
                    "status": "completed",
                    "completed_at": "2026-08-31T18:00:00Z",
                },
                "pending_cards": sum(
                    card.birthplace == "curator" and card.state == "pending"
                    for card in self.cards.values()
                ),
            }
        )


def _honest_vitals() -> VitalsSnapshot:
    payload = _vitals_snapshot().model_dump(mode="json")
    minute = payload["as_of"]
    point = {
        "minute": minute,
        "cost_usd": "0.084555772000",
        "receipt_lines": 2,
        "unpriced_lines": 0,
    }
    payload["spend"] = {
        "source_view": "v_spend_rate",
        "latest_minute": minute,
        "lanes": [
            {"dimension": "total", "key": None, "label": "All spend", "points": [point]},
            {
                "dimension": "purpose",
                "key": "memory_curation",
                "label": "Memory curation",
                "points": [point],
            },
            {
                "dimension": "model",
                "key": "openrouter:anthropic/claude-sonnet-4",
                "label": "Claude Sonnet 4",
                "points": [point],
            },
        ],
    }
    payload["reconciliation"] = {
        "status": "drift",
        "checked_at": minute,
        "broker_usage_usd": "1.000000000000",
        "ledger_cost_usd": "0.915444228000",
        "broker_since_baseline_usd": "1.000000000000",
        "ledger_since_baseline_usd": "0.915444228000",
        "drift_usd": "-0.084555772000",
        "tolerance_usd": "0.010000000000",
        "unpriced_lines": 0,
        "source": "openrouter:/api/v1/key",
        "error_code": None,
    }
    return VitalsSnapshot.model_validate(payload)


def _honest_spend_table() -> SpendTableSnapshot:
    metrics = {
        "input_tokens": "1200.5",
        "kv_cache_tokens": "400",
        "reasoning_tokens": "72",
        "output_tokens": "180",
        "total_usd": "0.084555772000",
        "total_receipt_lines": 4,
        "total_unpriced_lines": 0,
        "spend_per_hour_usd": "0.012500000000",
        "hourly_receipt_lines": 2,
        "hourly_unpriced_lines": 0,
    }
    return SpendTableSnapshot.model_validate(
        {
            "as_of": "2026-08-31T17:00:00Z",
            "window_minutes": 60,
            "threads": [
                {
                    "thread_id": "307e6141-bc47-44d8-be1d-365dbc18f9d6",
                    "models": [{"model": "openrouter:minimax/minimax-m3", **metrics}],
                    **metrics,
                }
            ],
            "purposes": [
                {"purpose": "curation", "label": "Memory curation", **metrics},
                {
                    "purpose": "building",
                    "label": "Owner app",
                    **{
                        **metrics,
                        "total_usd": None,
                        "total_receipt_lines": 1,
                        "total_unpriced_lines": 1,
                        "spend_per_hour_usd": None,
                        "hourly_receipt_lines": 1,
                        "hourly_unpriced_lines": 1,
                    },
                },
            ],
        }
    )


def _crowded_graph() -> dict[str, object]:
    payload = deepcopy(graph_payload())
    prototype = payload["nodes"][0]
    labels = [
        "Owner architecture and durable intent",
        "No silent inference across boundaries",
        "Current project memory selection",
        "Exact accounting source authority",
        "Human attention remains scarce",
        "Procedural visuals encode truth",
        "Module settings belong in chrome",
        "Context follows the active thread",
        "Receipts preserve exact decimals",
        "The stage remains fully watchable",
    ]
    nodes = []
    for index, label in enumerate(labels, start=1):
        node = deepcopy(prototype)
        node["memory"]["memory_id"] = f"00000000-0000-4000-8000-{index:012d}"
        node["memory"]["label"] = label
        node["memory"]["body"] = f"{label}. Full text remains in the inspector."
        node["memory"]["pin"] = index in {1, 7}
        node["memory"]["stats"]["injections"] = 12 - index
        node["in_current_context"] = index in {1, 3}
        nodes.append(node)
    payload["nodes"] = nodes
    payload["edges"] = [
        {
            "kind": "similarity",
            "from_memory_id": nodes[index]["memory"]["memory_id"],
            "to_memory_id": nodes[index + 1]["memory"]["memory_id"],
            "similarity": "0.8125000",
        }
        for index in range(len(nodes) - 1)
    ]
    return payload


def create_scenario_app() -> FastAPI:
    settings = HarnessSettings(
        principal_id="m2st3-verification",
        machine_id="m2st3-verification",
        agent_id="m2st3-verification",
        chat_model="local:m2st3-verification",
        model_context_tokens=4096,
        extraction_idle_hours=None,
    )
    harness_app = create_dev_app(
        settings=settings,
        agent=HarnessAgent(settings, model=_model()),
        spine=HonestDisplaySpine(),  # type: ignore[arg-type]
    )
    app = FastAPI(title="M2ST3 deterministic honest-display verification")
    install_fixture_isolation(app, FIXTURE)
    app.mount("/", harness_app)
    return app


__all__ = ["create_scenario_app"]
