import io
from types import SimpleNamespace

import pytest

from harness import onboarding


@pytest.fixture
def threshold(monkeypatch):
    monkeypatch.setattr(onboarding, "memory_threshold_bytes", lambda: 2 * 1024**3)
    monkeypatch.setattr(onboarding, "system_memory_bytes", lambda: 20 * 1024**3)


def _preflight(memory_bytes):
    return onboarding.DaemonPreflight(
        existing=memory_bytes is not None,
        web_assets="ready",
        port="8765",
        toolchain="none",
        failures=(),
        memory_bytes=memory_bytes,
    )


def test_doctor_shows_the_daemon_memory_against_its_threshold(threshold):
    """FL-166 (M3HW): doctor showed no app-memory line; it now names the daemon's memory and
    the threshold (10% of this machine's memory), and warns past it."""
    lines = []
    for used in (None, 1024**3, 3 * 1024**3):
        out = io.StringIO()
        onboarding._print_daemon_preflight(_preflight(used), stdout=out)
        lines.append([line for line in out.getvalue().splitlines() if "emory" in line])
    limit = "warning above 2.0 GiB (10% of this machine's 20.0 GiB)"
    assert lines[0] == [f"Nocturne memory: not running; {limit}"]
    assert lines[1] == [f"Nocturne memory: 1.0 GiB; {limit}"]
    assert lines[2][0] == f"Nocturne memory: 3.0 GiB; {limit}"
    assert lines[2][1].startswith("Warning: Nocturne is using more memory than its threshold.")


def test_up_says_once_when_the_daemon_passes_its_threshold(threshold, monkeypatch, capsys):
    """FL-166 (M3HW): the daemon reached 4 GB with no prompt; `nocturne up` now says so once
    per crossing, checking the daemon's memory every minute."""
    clock = {"now": 0.0}
    readings = iter([3, 3, 1, 3])  # GiB at each minute's check

    def monotonic():
        clock["now"] += 30
        return clock["now"]

    polls = iter([None] * 40 + [0])
    daemon = SimpleNamespace(pid=42, poll=lambda: next(polls))
    monkeypatch.setattr(onboarding.time, "monotonic", monotonic)
    monkeypatch.setattr(onboarding.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(onboarding.signal, "signal", lambda *_args: None)  # keep pytest's
    monkeypatch.setattr(onboarding, "current_rss_bytes", lambda pid: next(readings, 1) * 1024**3)
    with pytest.raises(onboarding.OnboardingError, match="exited"):
        onboarding._supervise((daemon,))
    warnings = [line for line in capsys.readouterr().out.splitlines() if line.startswith("Warning")]
    assert len(warnings) == 2
    assert warnings[0].startswith("Warning: Nocturne is using 3.0 GiB; warning above 2.0 GiB")
