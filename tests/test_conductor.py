from __future__ import annotations

import json
import os
import signal
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from harness.conductor import (
    AuthoritativeClaim,
    CancellationState,
    ChildCharge,
    ChildStatus,
    Conductor,
    ConductorError,
    IrreversibleBoundary,
    ScopeExpansionError,
    SearchAttemptBrief,
    SearchAttemptStatus,
    SearchBrake,
    SearchBudget,
    SearchBudgetExceeded,
    SearchNodeDeclaration,
)
from harness.supervisor import WorkerSupervisor


def _wait_for(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _wait_stopped(conductor: Conductor, child_id: str, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if conductor.observe(child_id) is not ChildStatus.RUNNING:
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {child_id} to stop")


def _result(
    *,
    status: str,
    claim: str,
    evidence: str,
    artifact: str | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "status": status,
            "claims": [claim] if claim else [],
            "evidence_refs": [evidence],
            "uncertainties": [],
            "metrics_refs": [],
            "artifacts": [artifact] if artifact else [],
            "patch": None,
            "product": {"kind": "not_applicable", "commit": None},
        }
    )


def _claim(scope: tuple[str, ...]) -> AuthoritativeClaim:
    return AuthoritativeClaim(
        packet_id="SYM5-DEMO",
        bead_id="nocturne-sym5-demo",
        charge_digest="digest-sym5-demo",
        claim_token="authoritative-claim-001",
        accepted_commit="commit-parent",
        motivation_chain=("P3: charges down, distillates up",),
        scope=scope,
        status="in_progress",
    )


def _child(child_id: str, surface: str, location: Path, *, blast: str = "leaf") -> ChildCharge:
    return ChildCharge(
        child_id=child_id,
        title=f"Child {child_id}",
        charge=f"Prove {child_id} within its declared surface.",
        surfaces=(surface,),
        evidence_requirements=("Return one typed distillate with direct evidence.",),
        location=location,
        blast_radius=blast,
    )


def test_expansion_refuses_scope_growth_and_worker_brief_carries_the_fence(
    tmp_path: Path,
) -> None:
    """SPEC D.2 114 and P3 require G4 scope subdivision plus the G5 mini-boot."""

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    events: list[dict[str, object]] = []
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(supervisor=supervisor, event_sink=events.append)
        conductor.claim(_claim(("component/allowed",)))
        with pytest.raises(ScopeExpansionError, match="adds surfaces"):
            conductor.expand((_child("outside", "component/outside", outside),))

        child = _child("allowed", "component/allowed", allowed, blast="compounding")
        conductor.expand((child,))
        brief = conductor.render_worker_brief(child, policy="max", retry_number=0)

    assert "not the conductor and not a Garden relay\nsession" in brief
    assert '"allowed_surfaces": [\n    "component/allowed"' in brief
    assert '"accepted_commit": "commit-parent"' in brief
    assert '"model_policy": "max"' in brief
    assert [event["event"] for event in events] == ["claim_accepted", "packet_expanded"]


def test_three_child_headless_run_recovers_cancels_and_accepts_distillates_only(
    tmp_path: Path,
) -> None:
    """SPEC D.2 114 and P3 require SYM5 killed/cancelled/completed headless acceptance."""

    killed_one = tmp_path / "killed-one"
    killed_two = tmp_path / "killed-two"
    cancelled = tmp_path / "cancelled"
    completed = tmp_path / "completed"
    for location in (killed_one, killed_two, cancelled, completed):
        location.mkdir()

    events: list[dict[str, object]] = []
    inherited_environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "OPENROUTER_API_KEY": "must-not-reach-worker",
        "GOOGLE_APPLICATION_CREDENTIALS": "/secret/provider.json",
    }
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(
            supervisor=supervisor,
            event_sink=events.append,
            environment=inherited_environment,
        )
        conductor.claim(_claim(("component/killed", "component/cancelled", "component/completed")))
        conductor.expand(
            (
                _child("killed", "component/killed", killed_one),
                _child("cancelled", "component/cancelled", cancelled, blast="compounding"),
                _child("completed", "component/completed", completed),
            )
        )

        killed = conductor.dispatch(
            "killed",
            (
                sys.executable,
                "-c",
                "from pathlib import Path; import time; "
                "Path('uncertain.txt').write_text('attempt-one'); time.sleep(30)",
            ),
        )
        cancel_payload = _result(
            status="cancelled",
            claim="",
            evidence="partial work preserved at the SIGTERM boundary",
            artifact="partial.txt",
        )
        conductor.dispatch(
            "cancelled",
            (
                sys.executable,
                "-c",
                "import signal,sys,time\nfrom pathlib import Path\n"
                f"payload={cancel_payload!r}\n"
                "def stop(*_):\n"
                " Path('partial.txt').write_text('partial evidence')\n"
                " Path('distillate.json').write_text(payload)\n"
                " sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "Path('ready').write_text('ready')\n"
                "time.sleep(30)",
            ),
        )
        complete_payload = _result(
            status="completed",
            claim="the ordinary child completed",
            evidence="distillate.json",
            artifact="environment.json",
        )
        complete = conductor.dispatch(
            "completed",
            (
                sys.executable,
                "-c",
                "import json,os; from pathlib import Path; "
                f"payload={complete_payload!r}; "
                "Path('environment.json').write_text(json.dumps(sorted(os.environ))); "
                "Path('distillate.json').write_text(payload)",
            ),
        )

        assert killed.model_policy == "elbow"
        assert complete.model_policy == "elbow"
        assert conductor.child_status("cancelled") is ChildStatus.RUNNING
        _wait_for(killed_one / "uncertain.txt")
        _wait_for(cancelled / "ready")

        os.killpg(killed.pid, signal.SIGKILL)
        _wait_stopped(conductor, "killed")
        assert conductor.certify_failure("killed") is ChildStatus.FAILED
        recovered_payload = _result(
            status="completed",
            claim="the killed child recovered from accepted truth",
            evidence="fresh attempt distillate",
        )
        recovered = conductor.retry(
            "killed",
            (
                sys.executable,
                "-c",
                "from pathlib import Path; "
                f"Path('distillate.json').write_text({recovered_payload!r})",
            ),
            fresh_location=killed_two,
        )
        assert recovered.retry_number == 1
        assert recovered.accepted_commit == "commit-parent"
        assert not (killed_two / "uncertain.txt").exists()

        assert conductor.request_cancel("cancelled") is CancellationState.REQUESTED
        assert (
            conductor.begin_draining("cancelled", boundary=IrreversibleBoundary.CLEAR)
            is CancellationState.DRAINING
        )

        _wait_for(killed_two / "distillate.json")
        _wait_for(cancelled / "distillate.json")
        _wait_for(completed / "distillate.json")
        for child_id in ("killed", "cancelled", "completed"):
            _wait_stopped(conductor, child_id)

        conductor.accept_distillate("killed", killed_two / "distillate.json")
        conductor.accept_distillate("cancelled", cancelled / "distillate.json")
        conductor.accept_distillate("completed", completed / "distillate.json")

        assert conductor.child_status("killed") is ChildStatus.COMPLETED
        assert conductor.child_status("cancelled") is ChildStatus.CANCELLED
        assert conductor.child_status("completed") is ChildStatus.COMPLETED
        assert conductor.cancellation_state("cancelled") is CancellationState.CANCELLED
        assert len(conductor.results()) == 3

    worker_environment = json.loads((completed / "environment.json").read_text())
    assert "OPENROUTER_API_KEY" not in worker_environment
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in worker_environment
    accepted = [event for event in events if event["event"] == "distillate_accepted"]
    assert len(accepted) == 3
    cancelled_event = next(event for event in accepted if event["child_id"] == "cancelled")
    assert cancelled_event["memory_admissible"] is False
    assert not any("stdout" in event for event in accepted)


def test_uncertain_irreversible_boundary_cannot_pretend_cancellation_is_terminal(
    tmp_path: Path,
) -> None:
    """SPEC D.2 114 and P3 require G20 to reconcile irreversible work before cancel."""

    location = tmp_path / "worker"
    location.mkdir()
    payload = _result(
        status="cancelled",
        claim="",
        evidence="partial evidence preserved after reconciliation",
    )
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(supervisor=supervisor, event_sink=lambda _event: None)
        conductor.claim(_claim(("component/cancel",)))
        conductor.expand((_child("cancel", "component/cancel", location),))
        conductor.dispatch(
            "cancel",
            (
                sys.executable,
                "-c",
                "import signal,sys,time\nfrom pathlib import Path\n"
                f"payload={payload!r}\n"
                "def stop(*_):\n"
                " Path('distillate.json').write_text(payload)\n"
                " sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "Path('ready').write_text('ready')\n"
                "time.sleep(30)",
            ),
        )
        _wait_for(location / "ready")
        conductor.request_cancel("cancel")
        with pytest.raises(ConductorError, match="must reconcile"):
            conductor.begin_draining(
                "cancel",
                boundary=IrreversibleBoundary.UNCERTAIN,
            )
        assert conductor.cancellation_state("cancel") is CancellationState.REQUESTED
        assert conductor.child_status("cancel") is ChildStatus.RUNNING

        conductor.begin_draining("cancel", boundary=IrreversibleBoundary.RECONCILED)
        _wait_for(location / "distillate.json")
        _wait_stopped(conductor, "cancel")
        conductor.accept_distillate("cancel", location / "distillate.json")
        assert conductor.child_status("cancel") is ChildStatus.CANCELLED


def test_two_failed_retries_flag_without_a_fourth_attempt(tmp_path: Path) -> None:
    """SPEC D.2 114 and P3 require G7 retry two then flag, never unbounded respawn."""

    locations = [tmp_path / f"attempt-{number}" for number in range(3)]
    for location in locations:
        location.mkdir()
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(supervisor=supervisor, event_sink=lambda _event: None)
        conductor.claim(_claim(("component/retry",)))
        conductor.expand((_child("retry", "component/retry", locations[0]),))
        failed_payload = _result(
            status="failed",
            claim="the first attempt could not complete",
            evidence="typed failure evidence",
        )
        conductor.dispatch(
            "retry",
            (
                sys.executable,
                "-c",
                f"from pathlib import Path; Path('distillate.json').write_text({failed_payload!r})",
            ),
        )
        _wait_for(locations[0] / "distillate.json")
        _wait_stopped(conductor, "retry")
        conductor.accept_distillate("retry", locations[0] / "distillate.json")
        assert conductor.child_status("retry") is ChildStatus.FAILED
        assert len(conductor.results()) == 1

        for location in locations[1:]:
            conductor.retry(
                "retry",
                (sys.executable, "-c", "raise SystemExit(9)"),
                fresh_location=location,
            )
            _wait_stopped(conductor, "retry")
            status = conductor.certify_failure("retry")

        assert status is ChildStatus.FLAGGED
        assert conductor.child_status("retry") is ChildStatus.FLAGGED


def _search_attempt(
    attempt_id: str,
    approach: str,
    location: Path,
    *,
    cost: str = "0.60",
    seconds: float = 10.0,
    children: int = 0,
) -> SearchAttemptBrief:
    return SearchAttemptBrief(
        attempt_id=attempt_id,
        approach=approach,
        charge=f"Try {approach} and return direct evidence.",
        location=location,
        estimated_completion_cost_usd=Decimal(cost),
        estimated_completion_seconds=seconds,
        planned_children=children,
    )


def _search_child(parent: Path, attempts: tuple[SearchAttemptBrief, ...]) -> ChildCharge:
    return ChildCharge(
        child_id="hard-step",
        title="The declared hard step",
        charge="Search three distinct approaches without adding scope.",
        surfaces=("component/hard-step",),
        evidence_requirements=("Compile/coherence smoke, then typed completion evidence.",),
        location=parent,
        search=SearchNodeDeclaration(attempts=attempts),
    )


def test_unmarked_child_cannot_emerge_as_expensive_search(tmp_path: Path) -> None:
    """SPEC D.2 114 and P3 require Symphony expense to be opt-in at deliberation."""

    location = tmp_path / "ordinary"
    location.mkdir()
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(
            supervisor=supervisor,
            event_sink=lambda _event: None,
            search_spend_reader=lambda _packet, _child: Decimal(0),
        )
        conductor.claim(_claim(("component/ordinary",)))
        conductor.expand((_child("ordinary", "component/ordinary", location),))
        with pytest.raises(ConductorError, match="opt-in"):
            conductor.explode_search("ordinary", {})


def test_marked_search_explodes_three_attempts_smoke_prunes_then_narrows(
    tmp_path: Path,
) -> None:
    """SPEC D.2 114, ADR-017, and P3 require SYM7 staged search under R22 brakes."""

    parent = tmp_path / "parent"
    locations = [tmp_path / name for name in ("risk", "simple", "novel")]
    parent.mkdir()
    for location in locations:
        location.mkdir()
    attempts = (
        _search_attempt("risk", "risk-first", locations[0]),
        _search_attempt("simple", "minimal-first", locations[1]),
        _search_attempt("novel", "independent alternative", locations[2]),
    )
    smoke_payloads = {
        "risk": json.dumps(
            {
                "schema_version": 1,
                "status": "pass",
                "score": 0.90,
                "checks": ["compiles", "coherent"],
                "evidence_refs": ["smoke.json"],
            }
        ),
        "simple": json.dumps(
            {
                "schema_version": 1,
                "status": "pass",
                "score": 0.70,
                "checks": ["compiles", "coherent"],
                "evidence_refs": ["smoke.json"],
            }
        ),
        "novel": json.dumps(
            {
                "schema_version": 1,
                "status": "fail",
                "score": 0.20,
                "checks": ["compiles", "coherent"],
                "evidence_refs": ["smoke.json"],
            }
        ),
    }
    spend = {"value": Decimal("0")}
    now = {"value": 100.0}
    events: list[dict[str, object]] = []
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(
            supervisor=supervisor,
            event_sink=events.append,
            search_spend_reader=lambda _packet, _child: spend["value"],
            search_clock=lambda: now["value"],
        )
        conductor.claim(_claim(("component/hard-step",)))
        conductor.expand((_search_child(parent, attempts),))
        handles = conductor.explode_search(
            "hard-step",
            {
                attempt_id: (
                    sys.executable,
                    "-c",
                    f"from pathlib import Path; Path('smoke.json').write_text({payload!r})",
                )
                for attempt_id, payload in smoke_payloads.items()
            },
        )
        assert len(handles) == 3
        assert all("do not perform completion" in handle.brief for handle in handles)
        for attempt, location in zip(attempts, locations, strict=True):
            _wait_for(location / "smoke.json")
            deadline = time.monotonic() + 10
            while conductor.observe_search_attempt("hard-step", attempt.attempt_id) is (
                SearchAttemptStatus.SMOKE_RUNNING
            ):
                assert time.monotonic() < deadline
                time.sleep(0.01)
            conductor.accept_smoke_gate("hard-step", attempt.attempt_id, location / "smoke.json")

        assert conductor.search_attempt_status("hard-step", "novel") is (
            SearchAttemptStatus.SMOKE_FAILED
        )
        with pytest.raises(ConductorError, match="beam-admitted"):
            conductor.dispatch_search_completion(
                "hard-step", "novel", (sys.executable, "-c", "raise SystemExit(0)")
            )

        spend["value"] = Decimal("8.90")
        selected = conductor.narrow_search_beam("hard-step")
        assert [attempt.attempt_id for attempt in selected] == ["risk"]
        assert conductor.search_attempt_status("hard-step", "simple") is (
            SearchAttemptStatus.BEAM_PRUNED
        )

        completion_payload = _result(
            status="completed",
            claim="risk-first completion is coherent",
            evidence="completion evidence",
        )
        conductor.dispatch_search_completion(
            "hard-step",
            "risk",
            (
                sys.executable,
                "-c",
                "from pathlib import Path; "
                f"Path('distillate.json').write_text({completion_payload!r})",
            ),
        )
        _wait_for(locations[0] / "distillate.json")
        deadline = time.monotonic() + 10
        while conductor.observe_search_attempt("hard-step", "risk") is (
            SearchAttemptStatus.COMPLETION_RUNNING
        ):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        conductor.accept_search_distillate("hard-step", "risk", locations[0] / "distillate.json")

        assert conductor.child_status("hard-step") is ChildStatus.AWAITING_DISTILLATE
        assert len(conductor.search_results("hard-step")) == 1
    assert sum(event["event"] == "search_worker_admitted" for event in events) == 4
    assert any(
        event["event"] == "search_smoke_decided" and event["status"] == "fail" for event in events
    )
    assert any(
        event["event"] == "search_beam_narrowed" and event["pruned"] == ["simple"]
        for event in events
    )


def test_search_dual_brakes_stop_live_smoke_workers(tmp_path: Path) -> None:
    """SPEC D.2 114 and P3 require R22's spend and clock walls to stop search."""

    parent = tmp_path / "parent"
    locations = [tmp_path / f"attempt-{index}" for index in range(3)]
    parent.mkdir()
    for location in locations:
        location.mkdir()
    attempts = tuple(
        _search_attempt(f"a{index}", f"approach {index}", location)
        for index, location in enumerate(locations)
    )
    spend = {"value": Decimal("0")}
    now = {"value": 0.0}
    events: list[dict[str, object]] = []
    with WorkerSupervisor(tmp_path / "supervisor") as supervisor:
        conductor = Conductor(
            supervisor=supervisor,
            event_sink=events.append,
            search_spend_reader=lambda _packet, _child: spend["value"],
            search_clock=lambda: now["value"],
        )
        conductor.claim(_claim(("component/hard-step",)))
        conductor.expand((_search_child(parent, attempts),))
        handles = conductor.explode_search(
            "hard-step",
            {
                attempt.attempt_id: (sys.executable, "-c", "import time; time.sleep(30)")
                for attempt in attempts
            },
        )
        spend["value"] = Decimal("10")
        now["value"] = 1800.0
        snapshot = conductor.enforce_search_brakes("hard-step")
        assert snapshot.brake is SearchBrake.SPEND_AND_CLOCK
        assert all(
            conductor.search_attempt_status("hard-step", attempt.attempt_id)
            is SearchAttemptStatus.DRAINING
            for attempt in attempts
        )
        deadline = time.monotonic() + 10
        while any(supervisor.heartbeat(handle.worker_id) for handle in handles):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert all(
            conductor.observe_search_attempt("hard-step", attempt.attempt_id)
            is SearchAttemptStatus.CANCELLED
            for attempt in attempts
        )
        with pytest.raises(SearchBudgetExceeded, match="wall"):
            conductor.narrow_search_beam("hard-step")
    assert any(
        event["event"] == "search_brake_engaged" and event["brake"] == "spend_and_clock"
        for event in events
    )


@pytest.mark.parametrize(
    ("budget", "round_number", "depth", "children", "message"),
    [
        (SearchBudget(max_rounds=1), 2, 0, 0, "max_rounds"),
        (SearchBudget(depth_cap=1), 1, 2, 0, "depth_cap"),
        (SearchBudget(children_per_attempt=1), 1, 0, 2, "children_per_attempt"),
    ],
)
def test_search_declaration_enforces_round_depth_and_children_caps(
    tmp_path: Path,
    budget: SearchBudget,
    round_number: int,
    depth: int,
    children: int,
    message: str,
) -> None:
    """SPEC D.2 114 and P3 require charge-declared R22 shape caps to be mechanical."""

    locations = [tmp_path / f"attempt-{index}" for index in range(3)]
    for location in locations:
        location.mkdir()
    attempts = tuple(
        _search_attempt(
            f"a{index}",
            f"approach {index}",
            location,
            children=children if index == 0 else 0,
        )
        for index, location in enumerate(locations)
    )
    with pytest.raises(ValueError, match=message):
        SearchNodeDeclaration(
            budget=budget,
            round_number=round_number,
            depth=depth,
            attempts=attempts,
        )
