from __future__ import annotations

import subprocess
from pathlib import Path

from harness.symphony_runtime import _carry_environment, _graft, _publish_result


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
    (site / "dependency.py").write_text("value = 1\n")


def test_an_attempt_carries_the_project_environment_pointed_at_itself(tmp_path: Path) -> None:
    """F137 / M3SF / M3EX-10: the attempt's tests import the attempt's code, from its own .venv."""
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
    dependency = site / "dependency.py"
    assert dependency.is_symlink()
    assert dependency.resolve() == root / ".venv/lib/python3.12/site-packages/dependency.py"
    status = subprocess.check_output(["git", "-C", str(attempt), "status", "--porcelain"])
    assert status == b""


def test_an_environment_git_would_commit_is_never_carried(tmp_path: Path) -> None:
    """F137 / M3SF: an unignored .venv would ride the attempt's commit into the owner's repo."""
    root = (tmp_path / "project").resolve()
    _repo(root, "")
    attempt = root.parent / "attempt"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(attempt)])

    _carry_environment(root, attempt)

    assert not (attempt / ".venv").exists()


def _commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def test_result_branch_preserves_the_users_checkout_and_new_uncommitted_work(tmp_path):
    """F154 / P3 / M3SF2: publishing a result never merges or overwrites the user's work."""
    root = tmp_path / "repo"
    _repo(root, ".venv/\n")
    base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    attempt = tmp_path / "attempt"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(attempt)], check=True
    )
    (attempt / "result.txt").write_text("judged result")
    result = _commit(attempt, "Add the requested result")
    (root / "owner.txt").write_text("work started during the Symphony")

    branch = _publish_result(root, "test-run", result)

    assert (
        subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        == base
    )
    assert (
        subprocess.check_output(["git", "-C", str(root), "rev-parse", branch], text=True).strip()
        == result
    )
    assert (root / "owner.txt").read_text() == "work started during the Symphony"
    assert not (root / "result.txt").exists()


def test_passing_alternatives_graft_with_the_most_chosen_lines(tmp_path: Path) -> None:
    """F137 / M3SF: judges passing two attempts that edit one line no longer block round two."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "cli.py").write_text("help = None\n")
    base = _commit(repo, "base")
    (repo / "cli.py").write_text("help = 'from attempt one'\n")
    first = _commit(repo, "attempt one")
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", base], check=True)
    (repo / "cli.py").write_text("help = 'from attempt two'\n")
    (repo / "test_cli.py").write_text("def test_help(): pass\n")
    second = _commit(repo, "attempt two")
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", base], check=True)
    (repo / "cli.py").write_text("help = 'only the line'\n")
    same_line = _commit(repo, "attempt three")
    graft = tmp_path / "graft"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(graft), base])

    head = _graft(graft, [first, second, same_line])

    assert (graft / "cli.py").read_text() == "help = 'from attempt one'\n"
    assert (graft / "test_cli.py").exists()
    assert (
        head
        == subprocess.check_output(
            ["git", "-C", str(graft), "rev-parse", "HEAD"], text=True
        ).strip()
    )
