from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from harness.supervisor import (
    SupervisorAlreadyRunning,
    SupervisorError,
    SupervisorJournalUnavailable,
    WorkerStatus,
    WorkerStillAlive,
    WorkerSupervisor,
)


def _wait_for(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def _wait_for_exit(supervisor: WorkerSupervisor, worker_id: str, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not supervisor.heartbeat(worker_id):
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {worker_id} to exit")


def test_only_one_supervisor_owns_worker_liveness(tmp_path: Path) -> None:
    """SPEC D.2 114 makes the supervisor the single liveness authority, never a peer model."""

    first = WorkerSupervisor(tmp_path / "state")
    try:
        with pytest.raises(SupervisorAlreadyRunning, match="owns worker liveness"):
            WorkerSupervisor(tmp_path / "state")
    finally:
        first.close()


def test_live_process_cannot_be_death_certified(tmp_path: Path) -> None:
    """SPEC D.2 114 requires process evidence before the supervisor certifies death."""

    location = tmp_path / "worker"
    location.mkdir()
    supervisor = WorkerSupervisor(tmp_path / "state")
    attempt = supervisor.spawn(
        "worker-live",
        (sys.executable, "-c", "import time; time.sleep(30)"),
        location=location,
        accepted_commit="accepted-001",
    )
    try:
        assert supervisor.heartbeat("worker-live")
        with pytest.raises(WorkerStillAlive, match="process identity"):
            supervisor.certify_dead("worker-live")
    finally:
        assert attempt.pid is not None
        os.killpg(attempt.pid, signal.SIGKILL)
        _wait_for_exit(supervisor, "worker-live")
        supervisor.close()


def test_killed_worker_recovers_from_checkpoint_without_replay(tmp_path: Path) -> None:
    """SPEC D.2 114 and P3 require G14 recovery to quarantine uncertain mutations."""

    state = tmp_path / "state"
    accepted = tmp_path / "accepted"
    dead_location = tmp_path / "attempt-one"
    fresh_location = tmp_path / "attempt-two"
    accepted.mkdir()
    dead_location.mkdir()
    fresh_location.mkdir()
    (accepted / "checkpoint.txt").write_text("accepted\n", encoding="utf-8")

    first = WorkerSupervisor(state)
    attempt_one = first.spawn(
        "worker-c3",
        (
            sys.executable,
            "-c",
            "from pathlib import Path; import time; "
            "Path('uncertain.txt').write_text('attempt-one\\n'); time.sleep(30)",
        ),
        location=dead_location,
        accepted_commit="commit-c2",
    )
    _wait_for(dead_location / "uncertain.txt")
    first.close()

    restarted = WorkerSupervisor(state)
    try:
        assert restarted.latest("worker-c3").status is WorkerStatus.RUNNING
        assert attempt_one.pid is not None
        os.killpg(attempt_one.pid, signal.SIGKILL)
        _wait_for_exit(restarted, "worker-c3")
        certificate = restarted.certify_dead("worker-c3")
        assert certificate.reason == "process_absent"
        assert certificate.accepted_commit == "commit-c2"
        assert list(fresh_location.iterdir()) == []
        assert (accepted / "checkpoint.txt").read_text(encoding="utf-8") == "accepted\n"

        attempt_two = restarted.recover(
            "worker-c3",
            (
                sys.executable,
                "-c",
                "from pathlib import Path; Path('result.txt').write_text('attempt-two\\n')",
            ),
            location=fresh_location,
            accepted_commit="commit-c2",
        )
        _wait_for(fresh_location / "result.txt")
        _wait_for_exit(restarted, "worker-c3")

        attempts = restarted.attempts("worker-c3")
        assert [item.status for item in attempts] == [
            WorkerStatus.QUARANTINED,
            WorkerStatus.EXIT_OBSERVED,
        ]
        assert attempt_two.recovery_of == attempt_one.attempt_id
        assert (dead_location / "uncertain.txt").read_text() == "attempt-one\n"
        assert (fresh_location / "result.txt").read_text() == "attempt-two\n"
        assert (accepted / "checkpoint.txt").read_text() == "accepted\n"
        events = [json.loads(line) for line in (state / "events.jsonl").read_text().splitlines()]
        assert [event["event"] for event in events].count("death_certified") == 1
        assert [event["event"] for event in events].count("quarantined") == 1
        assert all("command" not in event for event in events)
    finally:
        restarted.close()


def test_recovery_refuses_the_dead_location(tmp_path: Path) -> None:
    """SPEC D.2 114 keeps uncertain worker residue quarantined instead of inheriting it."""

    location = tmp_path / "worker"
    location.mkdir()
    supervisor = WorkerSupervisor(tmp_path / "state")
    attempt = supervisor.spawn(
        "worker-residue",
        (sys.executable, "-c", "pass"),
        location=location,
        accepted_commit="accepted-001",
    )
    try:
        _wait_for_exit(supervisor, "worker-residue")
        supervisor.certify_dead("worker-residue")
        with pytest.raises(SupervisorError, match="fresh location"):
            supervisor.recover(
                "worker-residue",
                (sys.executable, "-c", "pass"),
                location=location,
                accepted_commit="accepted-001",
            )
    finally:
        if attempt.pid is not None:
            try:
                os.killpg(attempt.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        supervisor.close()


def test_corrupt_journal_fails_closed(tmp_path: Path) -> None:
    """Invariant 10 prevents an unreadable liveness history from becoming guessed state."""

    state = tmp_path / "state"
    state.mkdir()
    (state / "events.jsonl").write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(SupervisorJournalUnavailable, match="invalid JSON"):
        WorkerSupervisor(state)
