"""SYM12 recipe graph projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from harness.daemon import create_app
from harness.recipe_graph import (
    RecipeGraphProjection,
    RecipeNodeKind,
    RecipeNodeState,
    snapshot_from_symphony_stack,
)


def _event(event: str, **payload: object) -> dict[str, object]:
    return {"schema_version": 1, "event": event, **payload}


def _expansion() -> dict[str, object]:
    return _event(
        "packet_expanded",
        packet_id="ROOT",
        children=[
            {
                "child_id": "PREP",
                "title": "Prepare the ground",
                "charge": "Make the graph honest.",
                "depends_on": [],
                "search": None,
            },
            {
                "child_id": "HARD",
                "title": "Find the hard answer",
                "charge": "Search only where deliberation marked expense.",
                "depends_on": ["PREP"],
                "search": {
                    "judge_charters": [
                        {"seat": "motivation"},
                        {"seat": "implementation"},
                        {"seat": "performance"},
                    ]
                },
            },
        ],
    )


def test_projection_renders_dependencies_frontier_search_and_judge_gates() -> None:
    """P2.3/SYM12: the live graph marks deps, ready work, search, and judge gates."""

    projection = RecipeGraphProjection()
    projection.record(_event("claim_accepted", packet_id="ROOT", bead_id="ng-root"))
    projection.record(_expansion())

    first = projection.snapshot()
    nodes = {node.node_id: node for node in first.nodes}
    assert first.packet_id == "ROOT"
    assert first.bead_id == "ng-root"
    assert first.ready_node_ids == ("PREP",)
    assert nodes["PREP"].state is RecipeNodeState.READY
    assert nodes["HARD"].kind is RecipeNodeKind.SEARCH
    assert nodes["HARD"].state is RecipeNodeState.BLOCKED
    assert [edge.model_dump() for edge in first.edges] == [
        {"source": "PREP", "target": "HARD", "kind": "blocks"},
        {"source": "HARD", "target": "HARD:judge:motivation", "kind": "judged_by"},
        {
            "source": "HARD",
            "target": "HARD:judge:implementation",
            "kind": "judged_by",
        },
        {"source": "HARD", "target": "HARD:judge:performance", "kind": "judged_by"},
    ]

    projection.record(_event("worker_admitted", child_id="PREP"))
    projection.record(_event("distillate_accepted", child_id="PREP", status="completed"))
    assert projection.snapshot().ready_node_ids == ("HARD",)

    projection.record(_event("search_exploded", child_id="HARD"))
    projection.record(_event("search_ready_for_judging", child_id="HARD"))
    review_nodes = {node.node_id: node for node in projection.snapshot().nodes}
    assert review_nodes["HARD"].state is RecipeNodeState.REVIEW
    assert all(
        review_nodes[f"HARD:judge:{seat}"].state is RecipeNodeState.READY
        for seat in ("motivation", "implementation", "performance")
    )

    projection.record(_event("judge_session_dispatched", seat="motivation"))
    projection.record(_event("judge_verdict_accepted", seat="motivation", outcome="pass"))
    projection.record(_event("search_judgment_recorded", child_id="HARD", status="unanimous_pass"))
    final = {node.node_id: node for node in projection.snapshot().nodes}
    assert final["HARD:judge:motivation"].state is RecipeNodeState.PASSED
    assert final["HARD"].state is RecipeNodeState.PASSED


def test_projection_refuses_unversioned_or_repeated_authority() -> None:
    """P2.3/SYM12: the visualizer never invents graph authority."""

    projection = RecipeGraphProjection()
    with pytest.raises(ValueError, match="schema-1"):
        projection.record({"event": "claim_accepted"})

    projection.record(_event("claim_accepted", packet_id="ROOT", bead_id="ng-root"))
    with pytest.raises(ValueError, match="only one authoritative claim"):
        projection.record(_event("claim_accepted", packet_id="OTHER", bead_id="ng-other"))


def test_signed_symphony_stack_projects_current_work_without_inventing_parallelism() -> None:
    """F054/P2.3/B.6 r7: signed order drives real Recipe dimming and judge gates."""

    snapshot = snapshot_from_symphony_stack(
        {
            "symphony_id": "01M0JZZ3VAHCH0E13A5DQYWQQJ",
            "state": "running",
            "launch": {
                "motivation": "The owner needs to see the live plan.",
                "recipe": [
                    {
                        "step_id": "scout",
                        "title": "Scout the released endpoint",
                        "done_when": "The live source is known",
                        "search": True,
                    },
                    {
                        "step_id": "wire",
                        "title": "Wire the composition root",
                        "done_when": "Recipe reads the signed stack",
                        "search": False,
                    },
                    {
                        "step_id": "prove",
                        "title": "Prove the rendered view",
                        "done_when": "Current work is obvious",
                        "search": False,
                    },
                ],
                "judge_charters": [
                    {"seat": "motivation"},
                    {"seat": "implementation"},
                    {"seat": "performance"},
                ],
            },
        },
        revision=4,
        as_of=datetime(2026, 8, 21, 20, 25, tzinfo=UTC),
    )

    nodes = {node.node_id: node for node in snapshot.nodes}
    assert snapshot.packet_id == "01M0JZZ3VAHCH0E13A5DQYWQQJ"
    assert nodes["scout"].kind is RecipeNodeKind.SEARCH
    assert nodes["scout"].state is RecipeNodeState.RUNNING
    assert nodes["wire"].state is RecipeNodeState.BLOCKED
    assert nodes["prove"].state is RecipeNodeState.BLOCKED
    assert [edge.model_dump() for edge in snapshot.edges] == [
        {"source": "scout", "target": "scout:judge:motivation", "kind": "judged_by"},
        {
            "source": "scout",
            "target": "scout:judge:implementation",
            "kind": "judged_by",
        },
        {"source": "scout", "target": "scout:judge:performance", "kind": "judged_by"},
        {"source": "scout", "target": "wire", "kind": "blocks"},
        {"source": "wire", "target": "prove", "kind": "blocks"},
    ]


def test_failed_judgment_exposes_the_minted_delta_and_next_round_lineage() -> None:
    """P3/SYM9/SYM12: failed work stays visible while only its minted delta advances."""

    projection = RecipeGraphProjection()
    projection.record(_event("claim_accepted", packet_id="ROOT", bead_id="ng-root"))
    projection.record(_expansion())
    projection.record(_event("search_exploded", child_id="HARD"))
    projection.record(
        _event(
            "judge_panel_resolved",
            decision={
                "search_child_id": "HARD",
                "verdicts": [
                    {"seat": "motivation", "outcome": "pass"},
                    {"seat": "implementation", "outcome": "fail"},
                    {"seat": "performance", "outcome": "pass"},
                ],
            },
        )
    )
    projection.record(
        _event(
            "search_judgment_recorded",
            child_id="HARD",
            status="failed_judgment",
        )
    )
    projection.record(
        _event(
            "round_delta_ready",
            feedback_packet_ids=["FB-DELTA"],
        )
    )

    delta = {node.node_id: node for node in projection.snapshot().nodes}
    assert delta["HARD"].state is RecipeNodeState.FAILED
    assert delta["HARD:judge:implementation"].state is RecipeNodeState.FAILED
    assert delta["FB-DELTA"].state is RecipeNodeState.READY

    projection.record(
        _event(
            "round_prepared",
            plan={
                "round_number": 2,
                "search_child_id": "HARD-R2",
                "delta_frontier": [
                    {"packet_id": "FB-DELTA", "bead_id": "ng-fb-delta"},
                ],
            },
        )
    )
    prepared = projection.snapshot()
    nodes = {node.node_id: node for node in prepared.nodes}
    assert nodes["HARD-R2"].state is RecipeNodeState.BLOCKED
    assert all(
        f"HARD-R2:judge:{seat}" in nodes for seat in ("motivation", "implementation", "performance")
    )
    assert any(edge.source == "FB-DELTA" and edge.target == "HARD-R2" for edge in prepared.edges)


def test_public_rack_query_serves_the_current_projection_without_history_guessing() -> None:
    """ADR-023 and SYM12: the public query serves live truth and refuses fake history."""

    projection = RecipeGraphProjection()
    projection.record(_event("claim_accepted", packet_id="ROOT", bead_id="ng-root"))
    projection.record(_expansion())
    client = TestClient(create_app(recipe_graph_reader=projection.snapshot))

    live = client.get("/v1/rack/query?resource=recipe_graph&as_of=now")
    assert live.status_code == 200
    payload = live.json()
    assert payload["status"] == "live"
    assert payload["data"]["packet_id"] == "ROOT"
    assert payload["data"]["ready_node_ids"] == ["PREP"]

    historical = client.get("/v1/rack/query?resource=recipe_graph&as_of=2026-08-17T00:00:00Z")
    assert historical.json() == {
        "status": "historical_unavailable",
        "as_of": "2026-08-17T00:00:00Z",
        "data": None,
    }
