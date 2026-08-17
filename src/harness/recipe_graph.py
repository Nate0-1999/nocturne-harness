"""Read-only live projection of the conductor's recipe DAG."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecipeNodeKind(StrEnum):
    """Visual distinctions carried by real graph roles."""

    PACKET = "packet"
    SEARCH = "search"
    JUDGE = "judge"


class RecipeNodeState(StrEnum):
    """Small human-facing state vocabulary for every recipe node."""

    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    REVIEW = "review"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecipeGraphNode(BaseModel):
    """One packet, search node, or judge gate in the rendered recipe."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str
    label: str
    kind: RecipeNodeKind
    state: RecipeNodeState
    bead_id: str | None = None
    motivation: str | None = None

    @model_validator(mode="after")
    def _validate_text(self) -> RecipeGraphNode:
        if not self.node_id.strip() or not self.label.strip():
            raise ValueError("recipe nodes require nonblank identities and labels")
        if self.bead_id is not None and not self.bead_id.strip():
            raise ValueError("a present bead identity must be nonblank")
        return self


class RecipeGraphEdge(BaseModel):
    """One dependency or search-to-judge gate edge."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source: str
    target: str
    kind: Literal["blocks", "judged_by"]


class RecipeGraphSnapshot(BaseModel):
    """One internally consistent current recipe projection."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    revision: int = Field(ge=0)
    as_of: datetime
    packet_id: str | None
    bead_id: str | None
    nodes: tuple[RecipeGraphNode, ...]
    edges: tuple[RecipeGraphEdge, ...]
    ready_node_ids: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_graph(self) -> RecipeGraphSnapshot:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("recipe graph node identities must be unique")
        known = set(node_ids)
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError("recipe graph edges must join known nodes")
        ready = {node.node_id for node in self.nodes if node.state is RecipeNodeState.READY}
        if set(self.ready_node_ids) != ready or len(self.ready_node_ids) != len(ready):
            raise ValueError("ready frontier must equal the nodes visibly marked ready")
        return self


class _MutableNode:
    def __init__(
        self,
        *,
        node_id: str,
        label: str,
        kind: RecipeNodeKind,
        state: RecipeNodeState,
        bead_id: str | None = None,
        motivation: str | None = None,
    ) -> None:
        self.node_id = node_id
        self.label = label
        self.kind = kind
        self.state = state
        self.bead_id = bead_id
        self.motivation = motivation

    def freeze(self) -> RecipeGraphNode:
        return RecipeGraphNode(
            node_id=self.node_id,
            label=self.label,
            kind=self.kind,
            state=self.state,
            bead_id=self.bead_id,
            motivation=self.motivation,
        )


class RecipeGraphProjection:
    """Project the existing graph-history event stream without owning its writes."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._revision = 0
        self._packet_id: str | None = None
        self._bead_id: str | None = None
        self._nodes: dict[str, _MutableNode] = {}
        self._order: list[str] = []
        self._dependencies: dict[str, tuple[str, ...]] = {}
        self._edges: list[RecipeGraphEdge] = []
        self._current_search_id: str | None = None

    def record(self, raw: Mapping[str, Any]) -> None:
        """Consume one validated-shape SYM5-SYM9 history event."""

        if raw.get("schema_version") != 1 or not isinstance(raw.get("event"), str):
            raise ValueError("recipe projection requires a schema-1 graph event")
        event = str(raw["event"])
        with self._lock:
            if event == "claim_accepted":
                self._accept_claim(raw)
            elif event == "packet_expanded":
                self._accept_expansion(raw)
            elif event == "judge_panel_resolved":
                self._resolve_panel(raw)
            elif event == "round_delta_ready":
                self._accept_delta_frontier(raw)
            elif event == "round_prepared":
                self._prepare_round(raw)
            else:
                self._apply_transition(event, raw)
            self._recompute_frontier()
            self._revision += 1

    def snapshot(self) -> RecipeGraphSnapshot:
        """Return one immutable current view for the public rack query surface."""

        with self._lock:
            nodes = tuple(self._nodes[node_id].freeze() for node_id in self._order)
            ready = tuple(node.node_id for node in nodes if node.state is RecipeNodeState.READY)
            return RecipeGraphSnapshot(
                revision=self._revision,
                as_of=datetime.now(UTC),
                packet_id=self._packet_id,
                bead_id=self._bead_id,
                nodes=nodes,
                edges=tuple(self._edges),
                ready_node_ids=ready,
            )

    def _accept_claim(self, raw: Mapping[str, Any]) -> None:
        packet_id = _required_text(raw, "packet_id")
        bead_id = _required_text(raw, "bead_id")
        if self._packet_id is not None:
            raise ValueError("a recipe projection may follow only one authoritative claim")
        self._packet_id = packet_id
        self._bead_id = bead_id

    def _accept_expansion(self, raw: Mapping[str, Any]) -> None:
        if self._packet_id is None or raw.get("packet_id") != self._packet_id:
            raise ValueError("recipe expansion must follow its authoritative claim")
        children = raw.get("children")
        if not isinstance(children, list) or not children or self._nodes:
            raise ValueError("recipe expansion must be one nonempty immutable child list")
        child_ids: set[str] = set()
        for value in children:
            if not isinstance(value, Mapping):
                raise ValueError("recipe child must be an object")
            child_id = _required_text(value, "child_id")
            if child_id in child_ids:
                raise ValueError("recipe child identities must be unique")
            child_ids.add(child_id)
            search = value.get("search")
            kind = RecipeNodeKind.SEARCH if isinstance(search, Mapping) else RecipeNodeKind.PACKET
            self._add_node(
                _MutableNode(
                    node_id=child_id,
                    label=_required_text(value, "title"),
                    kind=kind,
                    state=RecipeNodeState.BLOCKED,
                    motivation=_required_text(value, "charge"),
                )
            )
            depends_on = value.get("depends_on", [])
            if not isinstance(depends_on, list) or any(
                not isinstance(dependency, str) or not dependency.strip()
                for dependency in depends_on
            ):
                raise ValueError("recipe dependencies must be nonblank string lists")
            self._dependencies[child_id] = tuple(depends_on)
            for dependency in depends_on:
                self._edges.append(
                    RecipeGraphEdge(source=dependency, target=child_id, kind="blocks")
                )
            if isinstance(search, Mapping):
                self._add_judge_gates(child_id, search)
        unknown = {
            dependency
            for dependencies in self._dependencies.values()
            for dependency in dependencies
            if dependency not in child_ids
        }
        if unknown:
            raise ValueError(f"recipe dependencies name unknown nodes: {sorted(unknown)}")

    def _add_judge_gates(self, child_id: str, search: Mapping[str, Any]) -> None:
        charters = search.get("judge_charters")
        if not isinstance(charters, list) or not charters:
            raise ValueError("search nodes require their deliberation-fixed judge gates")
        for charter in charters:
            if not isinstance(charter, Mapping):
                raise ValueError("judge charter must be an object")
            seat = _required_text(charter, "seat")
            node_id = f"{child_id}:judge:{seat}"
            self._add_node(
                _MutableNode(
                    node_id=node_id,
                    label=f"{seat.removeprefix('user:').replace('_', ' ').title()} judge",
                    kind=RecipeNodeKind.JUDGE,
                    state=RecipeNodeState.BLOCKED,
                )
            )
            self._edges.append(RecipeGraphEdge(source=child_id, target=node_id, kind="judged_by"))

    def _add_node(self, node: _MutableNode) -> None:
        if node.node_id in self._nodes:
            raise ValueError(f"recipe graph repeats node {node.node_id}")
        self._nodes[node.node_id] = node
        self._order.append(node.node_id)

    def _apply_transition(self, event: str, raw: Mapping[str, Any]) -> None:
        child_id = raw.get("child_id") or raw.get("search_child_id")
        if event in {"worker_admitted", "worker_readmitted", "search_exploded"}:
            self._set_state(child_id, RecipeNodeState.RUNNING)
            if event == "search_exploded" and isinstance(child_id, str):
                self._current_search_id = child_id
        elif event in {"worker_stopped", "search_ready_for_judging"}:
            self._set_state(child_id, RecipeNodeState.REVIEW)
            if event == "search_ready_for_judging":
                self._set_judges(child_id, RecipeNodeState.READY)
        elif event in {"attempt_failed", "child_flagged"}:
            self._set_state(child_id, RecipeNodeState.FAILED)
        elif event == "distillate_accepted":
            status = raw.get("status")
            next_state = {
                "completed": RecipeNodeState.PASSED,
                "cancelled": RecipeNodeState.CANCELLED,
                "failed": RecipeNodeState.FAILED,
                "blocked": RecipeNodeState.FAILED,
            }.get(status)
            if next_state is not None:
                self._set_state(child_id, next_state)
        elif event == "judge_session_dispatched":
            seat = raw.get("seat")
            if isinstance(seat, str):
                self._set_judge_seat(
                    child_id or self._current_search_id,
                    seat,
                    RecipeNodeState.RUNNING,
                )
        elif event == "judge_verdict_accepted":
            seat = raw.get("seat")
            outcome = raw.get("outcome")
            if isinstance(seat, str):
                self._set_judge_seat(
                    child_id or self._current_search_id,
                    seat,
                    RecipeNodeState.PASSED if outcome == "pass" else RecipeNodeState.FAILED,
                )
        elif event == "search_judgment_recorded":
            if isinstance(child_id, str):
                self._current_search_id = child_id
            self._set_state(
                child_id,
                RecipeNodeState.PASSED
                if raw.get("status") == "unanimous_pass"
                else RecipeNodeState.FAILED,
            )
        elif event == "round_judged":
            self._set_state(self._current_search_id, RecipeNodeState.REVIEW)
        elif event == "rounds_converged":
            self._set_state(self._current_search_id, RecipeNodeState.PASSED)
        elif event == "rounds_exhausted":
            self._set_state(self._current_search_id, RecipeNodeState.FAILED)

    def _resolve_panel(self, raw: Mapping[str, Any]) -> None:
        decision = raw.get("decision")
        if not isinstance(decision, Mapping):
            raise ValueError("judge-panel projection requires its decision")
        search_child_id = _required_text(decision, "search_child_id")
        self._current_search_id = search_child_id
        verdicts = decision.get("verdicts")
        if not isinstance(verdicts, list):
            raise ValueError("judge-panel decision requires verdicts")
        for verdict in verdicts:
            if not isinstance(verdict, Mapping):
                raise ValueError("judge verdict projection must be an object")
            seat = _required_text(verdict, "seat")
            outcome = verdict.get("outcome")
            self._set_judge_seat(
                search_child_id,
                seat,
                RecipeNodeState.PASSED if outcome == "pass" else RecipeNodeState.FAILED,
            )

    def _accept_delta_frontier(self, raw: Mapping[str, Any]) -> None:
        packet_ids = raw.get("feedback_packet_ids")
        if not isinstance(packet_ids, list) or any(
            not isinstance(packet_id, str) or not packet_id.strip() for packet_id in packet_ids
        ):
            raise ValueError("round delta requires judge-minted packet identities")
        for packet_id in packet_ids:
            if packet_id in self._nodes:
                continue
            self._add_node(
                _MutableNode(
                    node_id=packet_id,
                    label=packet_id.replace("-", " ").title(),
                    kind=RecipeNodeKind.PACKET,
                    state=RecipeNodeState.READY,
                    motivation="Judge-minted feedback for the next delta-only round.",
                )
            )
            self._dependencies[packet_id] = ()
            if self._current_search_id in self._nodes:
                self._edges.append(
                    RecipeGraphEdge(
                        source=self._current_search_id,
                        target=packet_id,
                        kind="blocks",
                    )
                )

    def _prepare_round(self, raw: Mapping[str, Any]) -> None:
        plan = raw.get("plan")
        if not isinstance(plan, Mapping):
            raise ValueError("round preparation requires its immutable plan")
        search_child_id = _required_text(plan, "search_child_id")
        if search_child_id in self._nodes:
            raise ValueError("a round search identity must be fresh")
        frontier = plan.get("delta_frontier")
        if not isinstance(frontier, list) or not frontier:
            raise ValueError("a prepared round requires a nonempty delta frontier")
        dependencies: list[str] = []
        for receipt in frontier:
            if not isinstance(receipt, Mapping):
                raise ValueError("round frontier receipts must be objects")
            packet_id = _required_text(receipt, "packet_id")
            dependencies.append(packet_id)
            if packet_id not in self._nodes:
                self._add_node(
                    _MutableNode(
                        node_id=packet_id,
                        label=packet_id.replace("-", " ").title(),
                        kind=RecipeNodeKind.PACKET,
                        state=RecipeNodeState.READY,
                        bead_id=_required_text(receipt, "bead_id"),
                        motivation="Judge-minted feedback for the next delta-only round.",
                    )
                )
                self._dependencies[packet_id] = ()
        round_number = plan.get("round_number")
        label = f"Round {round_number} search" if isinstance(round_number, int) else "Next search"
        self._add_node(
            _MutableNode(
                node_id=search_child_id,
                label=label,
                kind=RecipeNodeKind.SEARCH,
                state=RecipeNodeState.BLOCKED,
                motivation="Run only the failed judgment delta; accepted work stands.",
            )
        )
        self._dependencies[search_child_id] = tuple(dependencies)
        for dependency in dependencies:
            self._edges.append(
                RecipeGraphEdge(source=dependency, target=search_child_id, kind="blocks")
            )
        seats = self._judge_seats(self._current_search_id)
        for seat in seats:
            node_id = f"{search_child_id}:judge:{seat}"
            self._add_node(
                _MutableNode(
                    node_id=node_id,
                    label=f"{seat.removeprefix('user:').replace('_', ' ').title()} judge",
                    kind=RecipeNodeKind.JUDGE,
                    state=RecipeNodeState.BLOCKED,
                )
            )
            self._edges.append(
                RecipeGraphEdge(source=search_child_id, target=node_id, kind="judged_by")
            )
        self._current_search_id = search_child_id

    def _judge_seats(self, search_child_id: str | None) -> tuple[str, ...]:
        if search_child_id is None:
            return ()
        prefix = f"{search_child_id}:judge:"
        return tuple(
            node_id.removeprefix(prefix) for node_id in self._order if node_id.startswith(prefix)
        )

    def _set_state(self, node_id: object, state: RecipeNodeState) -> None:
        if not isinstance(node_id, str) or node_id not in self._nodes:
            return
        self._nodes[node_id].state = state

    def _set_judges(self, child_id: object, state: RecipeNodeState) -> None:
        if not isinstance(child_id, str):
            return
        prefix = f"{child_id}:judge:"
        for node_id, node in self._nodes.items():
            if node_id.startswith(prefix):
                node.state = state

    def _set_judge_seat(self, child_id: object, seat: str, state: RecipeNodeState) -> None:
        exact = f"{child_id}:judge:{seat}" if isinstance(child_id, str) else None
        matches = [
            node_id
            for node_id in self._nodes
            if node_id == exact or (exact is None and node_id.endswith(f":judge:{seat}"))
        ]
        if len(matches) == 1:
            self._nodes[matches[0]].state = state

    def _recompute_frontier(self) -> None:
        for node_id, dependencies in self._dependencies.items():
            node = self._nodes[node_id]
            if node.state not in {RecipeNodeState.BLOCKED, RecipeNodeState.READY}:
                continue
            node.state = (
                RecipeNodeState.READY
                if all(
                    self._nodes[dependency].state is RecipeNodeState.PASSED
                    for dependency in dependencies
                )
                else RecipeNodeState.BLOCKED
            )


def _required_text(value: Mapping[str, Any], key: str) -> str:
    found = value.get(key)
    if not isinstance(found, str) or not found.strip():
        raise ValueError(f"recipe event requires nonblank {key}")
    return found


__all__ = [
    "RecipeGraphEdge",
    "RecipeGraphNode",
    "RecipeGraphProjection",
    "RecipeGraphSnapshot",
    "RecipeNodeKind",
    "RecipeNodeState",
]
