"""Deterministic, data-bearing fixture for M2ST3 honest display."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from fastapi import FastAPI

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import MemoryGraphSnapshot, ScorerConsoleSnapshot, VitalsSnapshot
from verification.fixture_isolation import install_fixture_isolation
from verification.m2h.scenario_app import _model
from verification.m2k.scenario_app import graph_payload
from verification.m2ux1.scenario_app import LayoutSpine
from verification.m2z4.scenario_app import _console_payload, _vitals_snapshot

FIXTURE = "M2ST3 REGRESSION"


class HonestDisplaySpine(LayoutSpine):
    """Supply deliberately over-precise values and crowded graph labels."""

    async def vitals_snapshot(self) -> VitalsSnapshot:
        return _honest_vitals()

    async def thread_vitals_snapshot(self, _thread_id: UUID) -> VitalsSnapshot:
        return _honest_vitals()

    async def memory_graph(self, _request: object) -> MemoryGraphSnapshot:
        return MemoryGraphSnapshot.model_validate(_crowded_graph())

    async def scorer_console(self, _request: object) -> ScorerConsoleSnapshot:
        payload = _console_payload(self._learning_state)
        payload["learning"]["weighted_agreement_percent"] = "11.1111111111111111"
        payload["learning"]["weighted_right"] = "12.345678901234"
        payload["accuracy"][0]["accuracy_percent"] = "11.1111111111111111"
        return ScorerConsoleSnapshot.model_validate(payload)


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
