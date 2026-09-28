from __future__ import annotations

import subprocess
from pathlib import Path

from harness.symphony_runtime import _carry_environment


def _repo(root: Path, ignore: str) -> None:
    root.mkdir()
    (root / ".gitignore").write_text(ignore)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"],
        check=True,
    )
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (root / ".venv" / "bin").mkdir()
    (root / ".venv" / "bin" / "pytest").write_text(f"#!{root}/.venv/bin/python\n")
    (site / "_editable_project.pth").write_text(f"{root}/src")
    (site / "_editable_sibling.pth").write_text(f"{root.parent}/sibling/src")


def test_an_attempt_carries_the_project_environment_pointed_at_itself(tmp_path: Path) -> None:
    """M3SF / M3EX-10: the attempt's tests import the attempt's code, from its own .venv."""
    root = (tmp_path / "project").resolve()
    _repo(root, ".venv/\n")
    attempt = root / ".nocturne-worktrees" / "run" / "attempt-1"
    attempt.parent.mkdir(parents=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(attempt)])

    _carry_environment(root, attempt)

    site = attempt / ".venv" / "lib" / "python3.12" / "site-packages"
    assert (site / "_editable_project.pth").read_text() == f"{attempt}/src"
    assert (site / "_editable_sibling.pth").read_text() == f"{root.parent}/sibling/src"
    assert (attempt / ".venv" / "bin" / "pytest").read_text() == f"#!{attempt}/.venv/bin/python\n"
    assert (root / ".venv" / "bin" / "pytest").read_text() == f"#!{root}/.venv/bin/python\n"
    status = subprocess.check_output(["git", "-C", str(attempt), "status", "--porcelain"])
    assert status == b""


def test_an_environment_git_would_commit_is_never_carried(tmp_path: Path) -> None:
    """M3SF: an unignored .venv would ride the attempt's commit into the owner's repo."""
    root = (tmp_path / "project").resolve()
    _repo(root, "")
    attempt = root.parent / "attempt"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(attempt)])

    _carry_environment(root, attempt)

    assert not (attempt / ".venv").exists()
