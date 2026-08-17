"""Delta-only Symphony rounds over immutable judge-panel decisions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.conductor import SearchAttemptRecord, SearchAttemptStatus, SearchBudget
from harness.judge_panel import FeedbackPacketReceipt, JudgeOutcome, PanelDecision


class RoundError(RuntimeError):
    """The round frontier cannot advance without losing provenance or replaying work."""


class RoundStatus(StrEnum):
    WAITING_JUDGMENT = "waiting_judgment"
    DELTA_READY = "delta_ready"
    CONVERGED = "converged"
    EXHAUSTED = "exhausted"


class AcceptedWork(BaseModel):
    """One already-passed child that remains accepted without another execution."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    child_id: str
    attempt_id: str
    accepted_commit: str
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_work(self) -> AcceptedWork:
        if (
            any(
                not value.strip()
                for value in (self.child_id, self.attempt_id, self.accepted_commit)
            )
            or not self.evidence_refs
        ):
            raise ValueError("accepted work requires identities, a checkpoint, and evidence")
        if any(not value.strip() for value in self.evidence_refs):
            raise ValueError("accepted-work evidence must be nonblank")
        return self


class RoundAttemptPlan(BaseModel):
    """One fresh attempt over judge-minted feedback and an accepted checkpoint."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt_id: str
    feedback_packet_ids: tuple[str, ...]
    parent_attempt_ids: tuple[str, ...]
    accepted_commit: str
    location: Path

    @model_validator(mode="after")
    def _validate_attempt(self) -> RoundAttemptPlan:
        if not self.attempt_id.strip() or not self.accepted_commit.strip():
            raise ValueError("round attempts require an identity and accepted commit")
        if not self.feedback_packet_ids or any(
            not packet_id.strip() for packet_id in self.feedback_packet_ids
        ):
            raise ValueError("round attempts may execute only a nonempty feedback delta")
        if len(set(self.feedback_packet_ids)) != len(self.feedback_packet_ids) or len(
            set(self.parent_attempt_ids)
        ) != len(self.parent_attempt_ids):
            raise ValueError("round feedback and parent identities must be unique")
        location = self.location.expanduser().resolve(strict=True)
        if not location.is_dir():
            raise ValueError("round attempt location must be an existing worktree directory")
        object.__setattr__(self, "location", location)
        return self


class GraftReceipt(BaseModel):
    """The explicit verified crossover that becomes the next G14 checkpoint."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    base_commit: str
    accepted_commit: str
    source_attempt_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_graft(self) -> GraftReceipt:
        if (
            not self.base_commit.strip()
            or not self.accepted_commit.strip()
            or not self.source_attempt_ids
            or not self.evidence_refs
        ):
            raise ValueError("a graft requires checkpoints, surviving sources, and evidence")
        if len(set(self.source_attempt_ids)) != len(self.source_attempt_ids) or any(
            not value.strip() for value in (*self.source_attempt_ids, *self.evidence_refs)
        ):
            raise ValueError("graft sources must be unique and its evidence nonblank")
        return self


class GraftLineageEdge(BaseModel):
    """One append-only source-attempt to next-attempt crossover edge."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_round: int = Field(ge=1)
    source_attempt_id: str
    target_round: int = Field(ge=2)
    target_attempt_id: str
    checkpoint_commit: str
    edge_type: Literal["graft"] = "graft"


class RoundPlan(BaseModel):
    """The complete executable frontier for one post-judgment round."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    round_number: int = Field(ge=2)
    search_child_id: str
    prior_decision_sha256: str
    checkpoint_commit: str
    delta_frontier: tuple[FeedbackPacketReceipt, ...]
    attempts: tuple[RoundAttemptPlan, ...]
    passed_work: tuple[AcceptedWork, ...]
    graft_edges: tuple[GraftLineageEdge, ...]


class RoundOutcome(BaseModel):
    """One watchable round boundary, including complete retained lineage."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: RoundStatus
    round_number: int = Field(ge=1)
    checkpoint_commit: str
    winner_attempt_id: str | None
    delta_frontier: tuple[FeedbackPacketReceipt, ...]
    passed_work: tuple[AcceptedWork, ...]
    attempt_lineage: tuple[SearchAttemptRecord, ...]
    graft_lineage: tuple[GraftLineageEdge, ...]


EventSink = Callable[[Mapping[str, Any]], None]


class SymphonyRounds:
    """Advance only failed deltas while accepted work and checkpoints stand."""

    def __init__(
        self,
        *,
        packet_id: str,
        initial_search_child_id: str,
        initial_checkpoint: str,
        budget: SearchBudget,
        event_sink: EventSink,
        passed_work: Sequence[AcceptedWork] = (),
    ) -> None:
        if not packet_id.strip() or not initial_search_child_id.strip():
            raise ValueError("round coordination requires packet and search identities")
        if not initial_checkpoint.strip():
            raise ValueError("round coordination requires the last accepted commit")
        accepted = tuple(passed_work)
        child_ids = [work.child_id for work in accepted]
        if len(set(child_ids)) != len(child_ids):
            raise ValueError("passed children must be unique")
        self._packet_id = packet_id
        self._search_child_id = initial_search_child_id
        self._checkpoint = initial_checkpoint
        self._budget = budget
        self._event_sink = event_sink
        self._passed_work = accepted
        self._round_number = 1
        self._status = RoundStatus.WAITING_JUDGMENT
        self._frontier: tuple[FeedbackPacketReceipt, ...] = ()
        self._surviving_attempt_ids: tuple[str, ...] = ()
        self._decisions: list[PanelDecision] = []
        self._plans: list[RoundPlan] = []
        self._attempt_lineage: list[SearchAttemptRecord] = []
        self._graft_lineage: list[GraftLineageEdge] = []
        self._planned_attempts: dict[str, RoundAttemptPlan] | None = None
        self._used_search_child_ids = {initial_search_child_id}

    @property
    def status(self) -> RoundStatus:
        return self._status

    @property
    def plans(self) -> tuple[RoundPlan, ...]:
        return tuple(self._plans)

    def accept_panel_decision(self, decision: PanelDecision) -> RoundOutcome:
        """Consume one immutable panel decision and stop early or expose its delta."""

        if self._status is not RoundStatus.WAITING_JUDGMENT:
            raise RoundError("the current round is not waiting for a panel decision")
        if decision.packet_id != self._packet_id or decision.search_child_id != (
            self._search_child_id
        ):
            raise RoundError("the panel decision does not belong to the current round")
        self._validate_decision_lineage(decision)
        if decision.status.value == "failed_judgment" and {
            item.packet_id for item in decision.feedback_packets
        } & {work.child_id for work in self._passed_work}:
            raise RoundError("a feedback delta cannot masquerade as already-passed work")
        self._decisions.append(decision)
        self._attempt_lineage.extend(decision.attempt_lineage)
        self._emit(
            "round_judged",
            round_number=self._round_number,
            decision_sha256=decision.digest,
            status=decision.status.value,
            attempt_lineage=[record.model_dump(mode="json") for record in decision.attempt_lineage],
        )

        if decision.status.value == "unanimous_pass":
            self._status = RoundStatus.CONVERGED
            self._frontier = ()
            self._surviving_attempt_ids = ()
            self._emit(
                "rounds_converged",
                round_number=self._round_number,
                winner_attempt_id=decision.winner_attempt_id,
                early_exit=self._round_number < self._budget.max_rounds,
            )
            return self._outcome(winner_attempt_id=decision.winner_attempt_id)

        self._frontier = decision.feedback_packets
        self._surviving_attempt_ids = tuple(
            dict.fromkeys(
                verdict.selected_attempt_id
                for verdict in decision.verdicts
                if verdict.outcome == JudgeOutcome.PASS and verdict.selected_attempt_id is not None
            )
        )
        if self._round_number >= self._budget.max_rounds:
            self._status = RoundStatus.EXHAUSTED
            self._emit(
                "rounds_exhausted",
                round_number=self._round_number,
                feedback_packet_ids=[item.packet_id for item in self._frontier],
            )
        else:
            self._status = RoundStatus.DELTA_READY
            self._emit(
                "round_delta_ready",
                round_number=self._round_number,
                feedback_packet_ids=[item.packet_id for item in self._frontier],
                passed_child_ids=[work.child_id for work in self._passed_work],
                surviving_attempt_ids=list(self._surviving_attempt_ids),
            )
        return self._outcome(winner_attempt_id=None)

    def prepare_next_round(
        self,
        *,
        search_child_id: str,
        attempts: Sequence[RoundAttemptPlan],
        graft: GraftReceipt | None,
    ) -> RoundPlan:
        """Bind a feedback-only frontier to fresh worktrees at accepted truth."""

        if self._status is not RoundStatus.DELTA_READY:
            raise RoundError("only a failed judgment with remaining budget opens another round")
        if not search_child_id.strip() or search_child_id in self._used_search_child_ids:
            raise RoundError("each round requires a fresh search-child identity")
        proposed = tuple(attempts)
        if len(proposed) != self._budget.attempts:
            raise RoundError("the next round must declare exactly its budgeted attempts")
        attempt_ids = [attempt.attempt_id for attempt in proposed]
        prior_attempt_ids = {record.attempt_id for record in self._attempt_lineage}
        if len(set(attempt_ids)) != len(attempt_ids) or set(attempt_ids) & prior_attempt_ids:
            raise RoundError("round attempt identities must be fresh across the whole lineage")
        locations = [attempt.location for attempt in proposed]
        prior_locations = {record.artifact_root.resolve() for record in self._attempt_lineage}
        if len(set(locations)) != len(locations) or set(locations) & prior_locations:
            raise RoundError(
                "G14 requires fresh worktrees; prior attempt residue stays quarantined"
            )

        next_checkpoint = self._checkpoint
        survivors = set(self._surviving_attempt_ids)
        if survivors:
            if graft is None:
                raise RoundError("surviving attempts require an explicit verified graft")
            if graft.base_commit != self._checkpoint or set(graft.source_attempt_ids) != survivors:
                raise RoundError("the graft must consume exactly the surviving accepted lineage")
            next_checkpoint = graft.accepted_commit
        elif graft is not None:
            raise RoundError("no prior attempt survived; arbitrary residue cannot become a graft")

        feedback_ids = {item.packet_id for item in self._frontier}
        scheduled_feedback: set[str] = set()
        scheduled_parents: set[str] = set()
        for attempt in proposed:
            if attempt.accepted_commit != next_checkpoint:
                raise RoundError("every successor must restart from the accepted round checkpoint")
            attempt_feedback = set(attempt.feedback_packet_ids)
            attempt_parents = set(attempt.parent_attempt_ids)
            if not attempt_feedback <= feedback_ids:
                raise RoundError("only judge-minted feedback packets may enter the next round")
            if not attempt_parents <= survivors or (survivors and not attempt_parents):
                raise RoundError("graft parents must be surviving attempts from the prior panel")
            if not survivors and attempt_parents:
                raise RoundError("a round with no survivor restarts without inherited residue")
            scheduled_feedback.update(attempt_feedback)
            scheduled_parents.update(attempt_parents)
        if scheduled_feedback != feedback_ids:
            raise RoundError("the next round must cover the complete feedback delta")
        if scheduled_parents != survivors:
            raise RoundError("every surviving attempt must remain in graft lineage")

        next_round = self._round_number + 1
        edges = tuple(
            GraftLineageEdge(
                source_round=self._round_number,
                source_attempt_id=source,
                target_round=next_round,
                target_attempt_id=attempt.attempt_id,
                checkpoint_commit=next_checkpoint,
            )
            for attempt in proposed
            for source in attempt.parent_attempt_ids
        )
        prior_decision = self._decisions[-1]
        plan = RoundPlan(
            round_number=next_round,
            search_child_id=search_child_id,
            prior_decision_sha256=prior_decision.digest,
            checkpoint_commit=next_checkpoint,
            delta_frontier=self._frontier,
            attempts=proposed,
            passed_work=self._passed_work,
            graft_edges=edges,
        )
        self._plans.append(plan)
        self._graft_lineage.extend(edges)
        self._round_number = next_round
        self._search_child_id = search_child_id
        self._checkpoint = next_checkpoint
        self._planned_attempts = {attempt.attempt_id: attempt for attempt in proposed}
        self._used_search_child_ids.add(search_child_id)
        self._frontier = ()
        self._surviving_attempt_ids = ()
        self._status = RoundStatus.WAITING_JUDGMENT
        self._emit(
            "round_prepared",
            plan=plan.model_dump(mode="json"),
            reexecuted_passed_child_ids=[],
        )
        return plan

    def _validate_decision_lineage(self, decision: PanelDecision) -> None:
        lineage_ids = [record.attempt_id for record in decision.attempt_lineage]
        if not lineage_ids or len(set(lineage_ids)) != len(lineage_ids):
            raise RoundError("each panel decision requires complete unique attempt lineage")
        if self._planned_attempts is not None:
            if set(lineage_ids) != set(self._planned_attempts):
                raise RoundError("the panel lineage does not match the prepared round attempts")
            if any(
                record.artifact_root.resolve() != self._planned_attempts[record.attempt_id].location
                or record.accepted_commit
                != self._planned_attempts[record.attempt_id].accepted_commit
                for record in decision.attempt_lineage
            ):
                raise RoundError(
                    "panel lineage must retain each planned G14 checkpoint and worktree"
                )
        completed = {
            record.attempt_id
            for record in decision.attempt_lineage
            if record.status is SearchAttemptStatus.COMPLETED
        }
        pass_selections = {
            verdict.selected_attempt_id
            for verdict in decision.verdicts
            if verdict.outcome == JudgeOutcome.PASS
        }
        if None in pass_selections or not pass_selections <= completed:
            raise RoundError("a passing judge may select only a completed attempt")
        unanimous = (
            bool(decision.verdicts)
            and all(verdict.outcome == JudgeOutcome.PASS for verdict in decision.verdicts)
            and len(pass_selections) == 1
        )
        if decision.status.value == "unanimous_pass":
            if (
                not unanimous
                or decision.winner_attempt_id not in pass_selections
                or decision.feedback_packets
            ):
                raise RoundError("unanimous passage must expose one winner and no feedback")
        elif unanimous or decision.winner_attempt_id is not None or not decision.feedback_packets:
            raise RoundError("failed judgment requires a real feedback frontier and no winner")

    def _outcome(self, *, winner_attempt_id: str | None) -> RoundOutcome:
        return RoundOutcome(
            status=self._status,
            round_number=self._round_number,
            checkpoint_commit=self._checkpoint,
            winner_attempt_id=winner_attempt_id,
            delta_frontier=self._frontier,
            passed_work=self._passed_work,
            attempt_lineage=tuple(self._attempt_lineage),
            graft_lineage=tuple(self._graft_lineage),
        )

    def _emit(self, event: str, **payload: Any) -> None:
        self._event_sink(
            {
                "schema_version": 1,
                "event": event,
                "packet_id": self._packet_id,
                **payload,
            }
        )
