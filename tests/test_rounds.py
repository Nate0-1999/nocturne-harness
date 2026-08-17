from __future__ import annotations

from pathlib import Path

import pytest

from harness.conductor import (
    DistillateStatus,
    ProductBaton,
    SearchAttemptRecord,
    SearchAttemptStatus,
    SearchBudget,
    SearchJudgmentStatus,
    TypedDistillate,
)
from harness.judge_panel import (
    FeedbackPacketReceipt,
    JudgeFeedback,
    JudgeVerdict,
    PanelDecision,
)
from harness.rounds import (
    AcceptedWork,
    GraftReceipt,
    RoundAttemptPlan,
    RoundError,
    RoundStatus,
    SymphonyRounds,
)

_DIGEST = "a" * 64


def _attempt(attempt_id: str, location: Path, commit: str) -> SearchAttemptRecord:
    location.mkdir(exist_ok=True)
    return SearchAttemptRecord(
        attempt_id=attempt_id,
        approach=f"approach {attempt_id}",
        artifact_root=location,
        accepted_commit="commit-base" if attempt_id.startswith("round1") else "commit-graft",
        status=SearchAttemptStatus.COMPLETED,
        smoke=None,
        distillate=TypedDistillate(
            schema_version=1,
            status=DistillateStatus.COMPLETED,
            claims=(f"{attempt_id} produced a candidate",),
            evidence_refs=(f"{attempt_id}/evidence",),
            uncertainties=(),
            metrics_refs=(),
            artifacts=(),
            patch=None,
            product=ProductBaton(kind="commit", commit=commit),
        ),
    )


def _verdict(seat: str, *, selected: str | None) -> JudgeVerdict:
    passing = selected is not None
    return JudgeVerdict(
        schema_version=1,
        seat=seat,
        judge_session_id=f"session-{seat}",
        charter_sha256=_DIGEST,
        evidence_sha256=_DIGEST,
        outcome="pass" if passing else "fail",
        selected_attempt_id=selected,
        rationale=f"{seat} direct assessment",
        evidence_refs=(f"{seat}/evidence",),
        feedback=()
        if passing
        else (
            JudgeFeedback(
                problem=f"{seat} found the missing delta",
                desired_observation="The delta passes directly.",
                evidence_refs=(f"{seat}/failure",),
            ),
        ),
    )


def _decision(
    *,
    child_id: str,
    lineage: tuple[SearchAttemptRecord, ...],
    selected: tuple[str | None, str | None, str | None],
    feedback: tuple[FeedbackPacketReceipt, ...],
) -> PanelDecision:
    unanimous = len(set(selected)) == 1 and selected[0] is not None
    return PanelDecision(
        packet_id="SYM-DEMO",
        search_child_id=child_id,
        status=(
            SearchJudgmentStatus.UNANIMOUS_PASS
            if unanimous
            else SearchJudgmentStatus.FAILED_JUDGMENT
        ),
        winner_attempt_id=selected[0] if unanimous else None,
        evidence_sha256=_DIGEST,
        verdicts=tuple(
            _verdict(seat, selected=attempt_id)
            for seat, attempt_id in zip(
                ("motivation", "implementation", "performance"),
                selected,
                strict=True,
            )
        ),
        attempt_lineage=lineage,
        feedback_packets=feedback,
    )


def _round_attempt(
    attempt_id: str,
    location: Path,
    *,
    checkpoint: str = "commit-graft",
    feedback: str = "FB-DELTA",
) -> RoundAttemptPlan:
    location.mkdir(exist_ok=True)
    return RoundAttemptPlan(
        attempt_id=attempt_id,
        feedback_packet_ids=(feedback,),
        parent_attempt_ids=("round1-a",),
        accepted_commit=checkpoint,
        location=location,
    )


def test_two_rounds_converge_without_reexecuting_passed_work(tmp_path: Path) -> None:
    """SPEC D.2 114, ADR-017, and P3 require SYM9 delta rounds with G14 lineage."""

    feedback = FeedbackPacketReceipt(
        packet_id="FB-DELTA",
        bead_id="bead-feedback-delta",
        charge_digest="b" * 64,
        minter_role="judge",
    )
    events: list[dict[str, object]] = []
    rounds = SymphonyRounds(
        packet_id="SYM-DEMO",
        initial_search_child_id="round-1",
        initial_checkpoint="commit-base",
        budget=SearchBudget(),
        event_sink=events.append,
        passed_work=(
            AcceptedWork(
                child_id="already-green",
                attempt_id="accepted-child-attempt",
                accepted_commit="commit-base",
                evidence_refs=("tests/already-green",),
            ),
        ),
    )
    round_one_lineage = (
        _attempt("round1-a", tmp_path / "round1-a", "commit-a"),
        _attempt("round1-b", tmp_path / "round1-b", "commit-b"),
        _attempt("round1-c", tmp_path / "round1-c", "commit-c"),
    )
    failed = _decision(
        child_id="round-1",
        lineage=round_one_lineage,
        selected=("round1-a", None, "round1-a"),
        feedback=(feedback,),
    )

    delta = rounds.accept_panel_decision(failed)

    assert delta.status is RoundStatus.DELTA_READY
    assert tuple(item.packet_id for item in delta.delta_frontier) == ("FB-DELTA",)
    assert tuple(work.child_id for work in delta.passed_work) == ("already-green",)

    attempts = tuple(
        _round_attempt(f"round2-{name}", tmp_path / f"round2-{name}") for name in ("a", "b", "c")
    )
    plan = rounds.prepare_next_round(
        search_child_id="round-2",
        attempts=attempts,
        graft=GraftReceipt(
            base_commit="commit-base",
            accepted_commit="commit-graft",
            source_attempt_ids=("round1-a",),
            evidence_refs=("graft/test-green",),
        ),
    )

    assert plan.round_number == 2
    assert plan.checkpoint_commit == "commit-graft"
    assert {item.packet_id for item in plan.delta_frontier} == {"FB-DELTA"}
    assert {edge.source_attempt_id for edge in plan.graft_edges} == {"round1-a"}
    assert {edge.target_attempt_id for edge in plan.graft_edges} == {
        "round2-a",
        "round2-b",
        "round2-c",
    }
    assert tuple(work.child_id for work in plan.passed_work) == ("already-green",)
    assert events[-1]["reexecuted_passed_child_ids"] == []

    round_two_lineage = tuple(
        _attempt(f"round2-{name}", tmp_path / f"round2-{name}", f"commit-2-{name}")
        for name in ("a", "b", "c")
    )
    passed = _decision(
        child_id="round-2",
        lineage=round_two_lineage,
        selected=("round2-b", "round2-b", "round2-b"),
        feedback=(),
    )

    converged = rounds.accept_panel_decision(passed)

    assert converged.status is RoundStatus.CONVERGED
    assert converged.round_number == 2
    assert converged.winner_attempt_id == "round2-b"
    assert converged.checkpoint_commit == "commit-graft"
    assert [record.attempt_id for record in converged.attempt_lineage] == [
        "round1-a",
        "round1-b",
        "round1-c",
        "round2-a",
        "round2-b",
        "round2-c",
    ]
    assert len(converged.graft_lineage) == 3
    assert events[-1]["event"] == "rounds_converged"
    assert events[-1]["early_exit"] is True


def test_next_round_refuses_passed_work_residue_and_checkpoint_drift(tmp_path: Path) -> None:
    """SPEC D.2 114 and P3 require feedback-only successors from accepted truth."""

    feedback = FeedbackPacketReceipt(
        packet_id="FB-DELTA",
        bead_id="bead-feedback-delta",
        charge_digest="b" * 64,
        minter_role="judge",
    )
    prior = _attempt("round1-a", tmp_path / "prior", "commit-a")
    other = _attempt("round1-b", tmp_path / "other", "commit-b")
    third = _attempt("round1-c", tmp_path / "third", "commit-c")
    rounds = SymphonyRounds(
        packet_id="SYM-DEMO",
        initial_search_child_id="round-1",
        initial_checkpoint="commit-base",
        budget=SearchBudget(),
        event_sink=lambda _event: None,
    )
    rounds.accept_panel_decision(
        _decision(
            child_id="round-1",
            lineage=(prior, other, third),
            selected=("round1-a", None, "round1-a"),
            feedback=(feedback,),
        )
    )
    invalid = tuple(
        _round_attempt(
            f"round2-{index}",
            prior.artifact_root if index == 0 else tmp_path / f"fresh-{index}",
            checkpoint="dirty-attempt-commit",
            feedback="already-green" if index == 1 else "FB-DELTA",
        )
        for index in range(3)
    )

    with pytest.raises(RoundError, match="fresh worktrees"):
        rounds.prepare_next_round(
            search_child_id="round-2",
            attempts=invalid,
            graft=GraftReceipt(
                base_commit="commit-base",
                accepted_commit="commit-graft",
                source_attempt_ids=("round1-a",),
                evidence_refs=("graft/evidence",),
            ),
        )

    clean_locations = [tmp_path / f"clean-{index}" for index in range(3)]
    for location in clean_locations:
        location.mkdir()
    drifted = tuple(
        RoundAttemptPlan(
            attempt_id=f"round2-clean-{index}",
            feedback_packet_ids=("FB-DELTA",),
            parent_attempt_ids=("round1-a",),
            accepted_commit="dirty-attempt-commit",
            location=location,
        )
        for index, location in enumerate(clean_locations)
    )
    with pytest.raises(RoundError, match="accepted round checkpoint"):
        rounds.prepare_next_round(
            search_child_id="round-2",
            attempts=drifted,
            graft=GraftReceipt(
                base_commit="commit-base",
                accepted_commit="commit-graft",
                source_attempt_ids=("round1-a",),
                evidence_refs=("graft/evidence",),
            ),
        )

    wrong_delta = tuple(
        RoundAttemptPlan(
            attempt_id=f"round2-delta-{index}",
            feedback_packet_ids=("already-green",),
            parent_attempt_ids=("round1-a",),
            accepted_commit="commit-graft",
            location=location,
        )
        for index, location in enumerate(clean_locations)
    )
    with pytest.raises(RoundError, match="only judge-minted feedback"):
        rounds.prepare_next_round(
            search_child_id="round-2",
            attempts=wrong_delta,
            graft=GraftReceipt(
                base_commit="commit-base",
                accepted_commit="commit-graft",
                source_attempt_ids=("round1-a",),
                evidence_refs=("graft/evidence",),
            ),
        )
