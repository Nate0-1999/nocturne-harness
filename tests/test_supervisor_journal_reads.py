import json
import sys
import time
from pathlib import Path

from harness import supervisor as supervisor_module
from harness.supervisor import WorkerStatus, WorkerSupervisor


def test_a_heartbeat_reads_only_what_was_appended(tmp_path: Path, monkeypatch) -> None:
    """P3 / M3HW: each heartbeat re-parsed the whole journal three times, so a 15-minute Symphony's
    6,319 heartbeats held the event loop near 40%; a heartbeat now parses only new rows, and a
    restarted supervisor still rebuilds the same registry from the whole journal."""
    supervisor = WorkerSupervisor(tmp_path / "state")
    location = tmp_path / "work"
    location.mkdir()
    supervisor.spawn(
        "worker-a",
        (sys.executable, "-c", "import time; time.sleep(30)"),
        location=location,
        accepted_commit="commit-a",
    )
    for _ in range(50):
        assert supervisor.heartbeat("worker-a")
    parsed = []
    real_loads = json.loads
    monkeypatch.setattr(
        supervisor_module.json,
        "loads",
        lambda raw, **kwargs: parsed.append(raw) or real_loads(raw, **kwargs),
    )
    assert supervisor.heartbeat("worker-a")
    assert len(parsed) <= 2  # the one heartbeat row it appended (read back once at most)
    monkeypatch.setattr(supervisor_module.json, "loads", real_loads)
    latest = supervisor.latest("worker-a")
    assert latest.status is WorkerStatus.RUNNING
    supervisor.request_termination("worker-a")
    deadline = time.monotonic() + 10
    while supervisor.heartbeat("worker-a") and time.monotonic() < deadline:
        time.sleep(0.05)
    supervisor.close()
    restarted = WorkerSupervisor(tmp_path / "state")
    try:
        assert [a.status for a in restarted.attempts("worker-a")] == [
            a.status for a in supervisor.attempts("worker-a")
        ]
        lines = (tmp_path / "state" / "events.jsonl").read_text().splitlines()
        assert sum(json.loads(line)["event"] == "heartbeat" for line in lines) >= 51
    finally:
        restarted.close()
