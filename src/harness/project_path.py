"""Canonical artificial project paths for M2 project context."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, StrictStr

SEEDED_PROJECT_PATH = "build-test"
PROJECT_PATH_MAX_LENGTH = 4096


def validate_artificial_project_path(value: str) -> str:
    """Return a canonical folder scope key or a tolerated legacy typed project."""

    if not isinstance(value, str):
        raise ValueError("project path must be a string")
    if not value or not value.strip():
        raise ValueError("project path must not be blank")
    if value != value.strip():
        raise ValueError("project path must not have surrounding whitespace")
    if len(value) > PROJECT_PATH_MAX_LENGTH:
        raise ValueError(f"project path must be at most {PROJECT_PATH_MAX_LENGTH} characters")
    if "\\" in value:
        raise ValueError("project path must use POSIX separators")
    segments = value[1:].split("/") if value.startswith("/") else value.split("/")
    if any(segment == "" for segment in segments):
        raise ValueError("project path must not contain empty segments")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("project path must not contain dot segments")
    if value.startswith("/") and not value.startswith("//"):
        return value
    if value.startswith("//"):
        raise ValueError("project path must have one absolute root")
    return value


ArtificialProjectPath = Annotated[StrictStr, AfterValidator(validate_artificial_project_path)]


def repository_root(folder: Path) -> Path | None:
    """The git root holding folder (v2.125, F136); None outside a repository."""

    for candidate in (folder, *folder.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def project_environment(folder: Path, workspace_root: Path) -> Path | None:
    """M3W5B-02: the nearest .venv from folder up to the workspace root, for the shell."""

    for candidate in (folder, *folder.parents):
        if (candidate / ".venv" / "bin").is_dir():
            return candidate / ".venv"
        if candidate == workspace_root:
            return None
    return None


def repository_state(folder: Path) -> str | None:
    """M3CL2 (Codex M3W5A-13; gate ruling 2026-10-01): an agent wrote a test into a stray file
    and reported it added; every request now carries the facts a final answer must match."""

    root = repository_root(folder)
    if root is None:
        return None

    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    try:
        head = git("log", "-1", "--name-only", "--format=%h %s")
        status = git("status", "--porcelain")
    except (OSError, subprocess.SubprocessError):
        return None
    if head.returncode or status.returncode:
        return None
    commit_lines = [line for line in head.stdout.splitlines() if line.strip()]
    files = commit_lines[1:]
    commit = (
        f"last commit {commit_lines[0]} ({', '.join(files[:6])}{', …' if len(files) > 6 else ''})"
        if commit_lines
        else "no commits yet"
    )
    changes = [line.strip() for line in status.stdout.splitlines() if line.strip()]
    pending = ", ".join(changes[:8]) + (", …" if len(changes) > 8 else "")
    return f"Repository now: {commit}; uncommitted: {pending or 'none'}."


def repository_identity(root: Path) -> str | None:
    """F135 (M3EX-14): a repository's first commit names it wherever it moves."""

    try:
        found = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    roots = sorted(found.stdout.split())
    return roots[0] if found.returncode == 0 and roots else None


def find_moved_repository(missing: Path, identity: str) -> Path | None:
    """Look beside a vanished repository root for the same repository, renamed or moved."""

    try:
        candidates = [path for path in missing.parent.iterdir() if (path / ".git").exists()]
    except OSError:
        return None
    return next((path for path in candidates if repository_identity(path) == identity), None)
