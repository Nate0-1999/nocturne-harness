from __future__ import annotations

import hashlib
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from harness.conductor import (
    AuthoritativeClaim,
    ChildCharge,
    ChildStatus,
    Conductor,
    JudgeCharter,
    JudgeSeat,
    SearchAttemptBrief,
    SearchAttemptStatus,
    SearchJudgmentStatus,
    SearchNodeDeclaration,
)
from harness.judge_panel import (
    FeedbackPacketDraft,
    FeedbackPacketReceipt,
    JudgeLaunch,
    JudgePanel,
    JudgePanelError,
)
from harness.supervisor import WorkerSupervisor


def _wait_for(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _charters() -> tuple[JudgeCharter, ...]:
    return (
        JudgeCharter(
            seat=JudgeSeat.MOTIVATION,
            rubric=("The attempt solves the complete deliberated why without scope drift.",),
            evidence_requirements=("Tie the claimed outcome to the charge and artifacts.",),
        ),
        JudgeCharter(
            seat=JudgeSeat.IMPLEMENTATION,
            rubric=("The implementation is minimal, coherent, and contract-safe.",),
            evidence_requirements=("Inspect the implementation and adversarial proof.",),
            model_policy="pinned:openrouter:judge/implementation",
        ),
        JudgeCharter(
            seat=JudgeSeat.PERFORMANCE,
            rubric=("The fixed performance bar is met without hiding search cost.",),
            evidence_requirements=("Read the frozen measurements and their sources.",),
            metrics=("suite remains green", "total spend remains below the wall"),
        ),
    )


def _claim() -> AuthoritativeClaim:
    return AuthoritativeClaim(
        packet_id="SYMPHONY",
        bead_id="ng-symphony",
        charge_digest="a" * 64,
        claim_token="claim-symphony",
        accepted_commit="accepted-parent",
        motivation_chain=(
            "P3: independent verdicts retain the whole why and release only unanimity.",
        ),
        scope=("component/hard-step",),
        status="in_progress",
    )


def _distillate(attempt_id: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "status": "completed",
            "claims": [f"{attempt_id} completed its declared approach"],
            "evidence_refs": [f"verification/{attempt_id}.json"],
            "uncertainties": [],
            "metrics_refs": [f"metrics/{attempt_id}.json"],
            "artifacts": [],
            "patch": None,
            "product": {"kind": "commit", "commit": f"commit-{attempt_id}"},
        }
    )


def _settled_search(
    tmp_path: Path,
    supervisor: WorkerSupervisor,
    events: list[dict[str, object]],
) -> Conductor:
    parent = tmp_path / "parent"
    parent.mkdir()
    locations = tuple(tmp_path / f"attempt-{attempt_id}" for attempt_id in ("a", "b", "c"))
    for location in locations:
        location.mkdir()
    attempts = tuple(
        SearchAttemptBrief(
            attempt_id=attempt_id,
            approach=f"approach {attempt_id}",
            charge=f"Complete approach {attempt_id} with direct evidence.",
            location=location,
            estimated_completion_cost_usd=Decimal("0.10"),
            estimated_completion_seconds=10.0,
        )
        for attempt_id, location in zip(("a", "b", "c"), locations, strict=True)
    )
    conductor = Conductor(
        supervisor=supervisor,
        event_sink=events.append,
        search_spend_reader=lambda _packet, _child: Decimal(0),
    )
    conductor.claim(_claim())
    conductor.expand(
        (
            ChildCharge(
                child_id="hard-step",
                title="A hard deliberated step",
                charge="Produce one contract-safe implementation of the complete P3 outcome.",
                surfaces=("component/hard-step",),
                evidence_requirements=("Return typed direct evidence and frozen metrics.",),
                location=parent,
                search=SearchNodeDeclaration(
                    attempts=attempts,
                    judge_charters=_charters(),
                ),
            ),
        )
    )
    smoke_payload = json.dumps(
        {
            "schema_version": 1,
            "status": "pass",
            "score": 0.8,
            "checks": ["compiles", "coherent"],
            "evidence_refs": ["smoke.json"],
        }
    )
    conductor.explode_search(
        "hard-step",
        {
            attempt_id: (
                sys.executable,
                "-c",
                f"from pathlib import Path; Path('smoke.json').write_text({smoke_payload!r})",
            )
            for attempt_id in ("a", "b", "c")
        },
    )
    for attempt_id, location in zip(("a", "b", "c"), locations, strict=True):
        _wait_for(location / "smoke.json")
        while conductor.observe_search_attempt("hard-step", attempt_id) is (
            SearchAttemptStatus.SMOKE_RUNNING
        ):
            time.sleep(0.01)
        conductor.accept_smoke_gate("hard-step", attempt_id, location / "smoke.json")
    assert len(conductor.narrow_search_beam("hard-step")) == 3
    for attempt_id in ("a", "b", "c"):
        payload = _distillate(attempt_id)
        conductor.dispatch_search_completion(
            "hard-step",
            attempt_id,
            (
                sys.executable,
                "-c",
                f"from pathlib import Path; Path('distillate.json').write_text({payload!r})",
            ),
        )
    for attempt_id, location in zip(("a", "b", "c"), locations, strict=True):
        _wait_for(location / "distillate.json")
        while conductor.observe_search_attempt("hard-step", attempt_id) is (
            SearchAttemptStatus.COMPLETION_RUNNING
        ):
            time.sleep(0.01)
        conductor.accept_search_distillate("hard-step", attempt_id, location / "distillate.json")
    assert conductor.child_status("hard-step") is ChildStatus.AWAITING_DISTILLATE
    return conductor


def _judge_command(outcome: str, selected: str | None) -> tuple[str, ...]:
    code = f"""
import json, time
from pathlib import Path
session_path = Path('JUDGE_SESSION.json')
while not session_path.exists():
    time.sleep(0.01)
session = json.loads(session_path.read_text())
brief = json.loads(Path('JUDGE_BRIEF.json').read_text())
outcome = {outcome!r}
feedback = [] if outcome == 'pass' else [{{
    'problem': 'The implementation evidence omits the declared failure boundary.',
    'desired_observation': 'The failure boundary is reproduced and passes directly.',
    'evidence_refs': ['verification/failure-boundary.json'],
}}]
metrics = []
if session['seat'] == 'performance':
    metrics = [{{
        'metric': metric,
        'observed': 'measured and inside the fixed bound',
        'passed': True,
        'evidence_ref': 'metrics/frozen.json',
    }} for metric in brief['charter']['metrics']]
verdict = {{
    'schema_version': 1,
    'seat': session['seat'],
    'judge_session_id': session['judge_session_id'],
    'charter_sha256': session['charter_sha256'],
    'evidence_sha256': session['evidence_sha256'],
    'outcome': outcome,
    'selected_attempt_id': {selected!r} if outcome == 'pass' else None,
    'rationale': 'The frozen charter and direct artifacts support this independent verdict.',
    'evidence_refs': ['verification/direct.json'],
    'feedback': feedback,
    'metrics': metrics,
}}
Path('judge-verdict.json').write_text(json.dumps(verdict))
"""
    return (sys.executable, "-c", code)


def _launches(
    tmp_path: Path,
    outcomes: dict[JudgeSeat, tuple[str, str | None]],
) -> dict[JudgeSeat, JudgeLaunch]:
    launches: dict[JudgeSeat, JudgeLaunch] = {}
    for seat in JudgeSeat:
        location = tmp_path / f"judge-{seat.value}"
        location.mkdir()
        outcome, selected = outcomes[seat]
        launches[seat] = JudgeLaunch(
            command=_judge_command(outcome, selected),
            location=location,
        )
    return launches


def _accept_all(panel: JudgePanel, launches: dict[JudgeSeat, JudgeLaunch]) -> None:
    for seat in JudgeSeat:
        verdict = launches[seat].location / "judge-verdict.json"
        _wait_for(verdict)
        panel.accept_verdict(seat, verdict)


def test_three_fresh_chartered_judges_unanimously_release_exactly_one_attempt(
    tmp_path: Path,
) -> None:
    """SPEC B.6, ADR-012, ADR-017, and D.2 114 require fresh 3-of-3 judgment."""

    events: list[dict[str, object]] = []
    minted: list[FeedbackPacketDraft] = []
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = _settled_search(tmp_path, supervisor, events)

        def mint_feedback(draft: FeedbackPacketDraft) -> FeedbackPacketReceipt:
            minted.append(draft)
            return FeedbackPacketReceipt(
                packet_id=draft.packet_id,
                bead_id=f"ng-{draft.packet_id.lower()}",
                charge_digest=hashlib.sha256(draft.charge.encode()).hexdigest(),
                minter_role="judge",
            )

        panel = JudgePanel(
            conductor=conductor,
            search_child_id="hard-step",
            supervisor=supervisor,
            event_sink=events.append,
            feedback_minter=mint_feedback,
        )
        launches = _launches(
            tmp_path,
            {seat: ("pass", "a") for seat in JudgeSeat},
        )
        sessions = panel.dispatch(launches)
        motivation_verdict = launches[JudgeSeat.MOTIVATION].location / "judge-verdict.json"
        _wait_for(motivation_verdict)
        original_verdict = motivation_verdict.read_text()
        tampered = json.loads(original_verdict)
        tampered["judge_session_id"] = "borrowed-builder-session"
        motivation_verdict.write_text(json.dumps(tampered))
        with pytest.raises(JudgePanelError, match="sealed fresh session"):
            panel.accept_verdict(JudgeSeat.MOTIVATION, motivation_verdict)
        motivation_verdict.write_text(original_verdict)
        brief = sessions[0].brief_path.read_text()
        assert '"motivation_chain"' in brief
        assert '"attempt_lineage"' in brief
        assert '"command"' not in brief
        _accept_all(panel, launches)
        decision = panel.resolve()

    assert len({session.judge_session_id for session in sessions}) == 3
    assert [session.model_policy for session in sessions] == [
        "max",
        "pinned:openrouter:judge/implementation",
        "max",
    ]
    assert all(session.brief_path.stat().st_mode & 0o777 == 0o600 for session in sessions)
    assert decision.status is SearchJudgmentStatus.UNANIMOUS_PASS
    assert decision.winner_attempt_id == "a"
    assert len(decision.attempt_lineage) == 3
    assert minted == []
    assert conductor.child_status("hard-step") is ChildStatus.COMPLETED
    assert sum(event["event"] == "judge_session_dispatched" for event in events) == 3


def test_two_of_three_never_passes_and_dissent_mints_scoped_feedback_with_lineage(
    tmp_path: Path,
) -> None:
    """SPEC D.2 102/114 and P3 require dissent to become feedback plus FAILED_JUDGMENT."""

    events: list[dict[str, object]] = []
    minted: list[FeedbackPacketDraft] = []
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = _settled_search(tmp_path, supervisor, events)

        def mint_feedback(draft: FeedbackPacketDraft) -> FeedbackPacketReceipt:
            minted.append(draft)
            return FeedbackPacketReceipt(
                packet_id=draft.packet_id,
                bead_id=f"ng-{draft.packet_id.lower()}",
                charge_digest=hashlib.sha256(draft.charge.encode()).hexdigest(),
                minter_role="judge",
            )

        panel = JudgePanel(
            conductor=conductor,
            search_child_id="hard-step",
            supervisor=supervisor,
            event_sink=events.append,
            feedback_minter=mint_feedback,
        )
        launches = _launches(
            tmp_path,
            {
                JudgeSeat.MOTIVATION: ("pass", "a"),
                JudgeSeat.IMPLEMENTATION: ("fail", None),
                JudgeSeat.PERFORMANCE: ("pass", "a"),
            },
        )
        panel.dispatch(launches)
        _accept_all(panel, launches)
        decision = panel.resolve()

    assert decision.status is SearchJudgmentStatus.FAILED_JUDGMENT
    assert decision.winner_attempt_id is None
    assert len(decision.attempt_lineage) == 3
    assert len(decision.feedback_packets) == 1
    assert len(minted) == 1
    assert minted[0].packet_id.startswith("FB")
    assert "MOTIVATION: P3" in minted[0].charge
    assert "RECIPE: deps —; surfaces component/hard-step" in minted[0].charge
    assert "AUTHORITY: none beyond CONTRACTS" in minted[0].charge
    assert conductor.child_status("hard-step") is ChildStatus.FAILED_JUDGMENT
    resolved = next(event for event in events if event["event"] == "judge_panel_resolved")
    assert len(resolved["decision"]["attempt_lineage"]) == 3
