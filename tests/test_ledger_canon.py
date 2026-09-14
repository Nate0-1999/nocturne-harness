"""Coverage is part of the exit canon (PLAN M3LM / SPEC B.6)."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ui_canon", Path(__file__).resolve().parents[1] / "scripts/run_ui_canon.py"
)
canon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canon)


def test_exit_canon_propagates_missing_ledger_evidence(tmp_path, monkeypatch):
    """SPEC B.6 / PLAN M3LM: a failed verifier must prevent a green exit canon."""
    garden = tmp_path / "garden"
    (garden / "bin").mkdir(parents=True)
    (garden / "bin/ledger").write_text(
        "import sys\nprint('Handoff REFUSED')\nsys.exit(1 if sys.argv[1] == 'verify' else 0)\n"
    )
    monkeypatch.setenv("GARDEN_ROOT", str(garden))
    canon.check_ledger(None)
    with pytest.raises(subprocess.CalledProcessError):
        canon.check_ledger(tmp_path / "verification/m3lm")


def test_browser_only_mode_cannot_be_combined_with_handoff(monkeypatch):
    """PLAN M3LM / SPEC B.6: browser-only CI cannot bypass handoff evidence."""
    monkeypatch.setattr("sys.argv", ["canon", "--ui-only", "--packet-dir", "verification/x"])
    with pytest.raises(SystemExit) as result:
        canon.main()
    assert result.value.code == 2
