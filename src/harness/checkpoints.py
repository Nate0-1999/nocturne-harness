"""ADR-016: a shadow git directory over the workspace, outside its real history."""

import hashlib
import subprocess
from pathlib import Path


class WorkspaceCheckpoints:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, workspace: str, *arguments: str) -> str:
        identity = hashlib.sha256(workspace.encode()).hexdigest()
        git_dir = self.root / identity
        result = subprocess.run(
            [
                "git",
                f"--git-dir={git_dir}",
                f"--work-tree={workspace}",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Nocturne checkpoints",
                "-c",
                "user.email=checkpoint@localhost",
                *arguments,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def capture(self, workspace: str, message: str) -> str:
        """Preserve nonignored file state without moving the real repo's HEAD or index."""
        self.root.mkdir(parents=True, exist_ok=True)
        self._git(workspace, "init", "--quiet")
        self._git(workspace, "add", "--all", "--", ".")
        self._git(workspace, "commit", "--quiet", "--allow-empty", "-m", message)
        return self._git(workspace, "rev-parse", "HEAD")

    def restore(self, workspace: str, checkpoint: str) -> str:
        """Retain the abandoned file state before restoring the selected turn."""
        abandoned = self.capture(workspace, "Before rewind")
        self._git(workspace, "read-tree", "--reset", "-u", checkpoint)
        return abandoned

    @staticmethod
    def repository_head(workspace: str) -> str | None:
        """M3W6B-49: the real repository's HEAD, so a rewind can name commits it leaves in place."""
        result = subprocess.run(
            ["git", "-C", workspace, "rev-parse", "--verify", "--quiet", "HEAD"],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None if result.returncode == 0 else None

    @staticmethod
    def commits_since(workspace: str, head: str) -> list[str]:
        """The real repository's commits after `head`, newest first, as `<short sha> <subject>`."""
        result = subprocess.run(
            ["git", "-C", workspace, "log", "--format=%h %s", f"{head}..HEAD"],
            capture_output=True,
            text=True,
        )
        return result.stdout.splitlines() if result.returncode == 0 else []
