import json
import subprocess
from pathlib import Path

from harness.symphony_runtime import remove_kept_worktrees


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_completed_symphony_worktrees_leave_and_their_commits_stay_reachable(tmp_path):
    """P3 / M3HW (M3W5B-13): seven small Symphonies left 17 GB of worktrees; a completed one's
    worktrees are removed beyond the newest `keep`, each attempt's commit kept under a ref."""
    root, home = tmp_path / "project", tmp_path / "home"
    root.mkdir()
    _git(root, "init", "-q")
    _git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "base",
    )
    commits = {}
    for symphony_id in ("older", "newer", "running"):
        attempt = root / ".nocturne-worktrees" / symphony_id / "step-1-round-1" / "attempt-1"
        _git(root, "worktree", "add", "-q", "--detach", str(attempt), "HEAD")
        (attempt / "work.txt").write_text(symphony_id)
        _git(attempt, "add", "work.txt")
        _git(
            attempt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", symphony_id
        )
        commits[symphony_id] = _git(attempt, "rev-parse", "HEAD")
        (attempt.parent / "judge-motivation").mkdir()
        assignment = home / "symphonies" / symphony_id / "step-1-round-1" / "attempt-1"
        assignment.mkdir(parents=True)
        (assignment / "assignment.json").write_text(json.dumps({"project_key": str(root)}))

    removed = remove_kept_worktrees(home, ["older", "newer"], keep=1)

    worktrees = root / ".nocturne-worktrees"
    assert removed == [worktrees / "older"]
    assert not (worktrees / "older").exists()
    assert (worktrees / "newer" / "step-1-round-1" / "attempt-1" / "work.txt").exists()
    assert (worktrees / "running").exists()
    assert "/.nocturne-worktrees/older/" not in _git(root, "worktree", "list")
    ref = "refs/nocturne/symphonies/older/step-1-round-1/attempt-1"
    assert _git(root, "rev-parse", ref) == commits["older"]
    assert (home / "symphonies" / "older" / "step-1-round-1" / "attempt-1").exists()
    assert remove_kept_worktrees(home, ["older", "newer"], keep=0) == [worktrees / "newer"]
