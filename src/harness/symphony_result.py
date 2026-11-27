"""Review a published Symphony result in the project where its attempts ran."""

import re
import subprocess
from pathlib import Path

from pydantic import BaseModel

from harness.symphony_experience import SymphonyStackRecord


class ResultReview(BaseModel):
    project: str
    branch: str
    head: str
    commit: str


def project_result(stack: SymphonyStackRecord, approved: ResultReview | None = None) -> dict:
    # F154 / ADR-012: completion publishes the judged commit. Only its owner can apply it.
    if stack.state != "completed":
        raise ValueError("Wait for the judges to finish this Symphony.")
    match = re.search(r" Result commit: ([a-f0-9]{40}|[a-f0-9]{64})$", stack.result or "")
    roots = {
        parent.parent
        for attempt in stack.attempts
        for location in attempt.partial_evidence
        for parent in Path(location).parents
        if parent.name == ".nocturne-worktrees"
        and Path(location).is_absolute()
        and Path(location).relative_to(parent).parts[0] == stack.symphony_id
    }
    if not match or len(roots) != 1:
        raise ValueError("The run has no verifiable project and result commit.")
    root = roots.pop()
    commit = match[1]
    source = f"refs/heads/symphony/{stack.symphony_id}"

    def git(*args):
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)

    if git("rev-parse", "--show-toplevel").stdout.rstrip("\n") != str(root):
        raise ValueError("The original project checkout is unavailable.")
    if git("rev-parse", "--verify", source).stdout.strip() != commit:
        raise ValueError("The result branch no longer points to the commit the judges accepted.")
    head = git("rev-parse", "--verify", "HEAD").stdout.strip()
    branch = git("symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    review = ResultReview(project=str(root), branch=branch, head=head, commit=commit)
    base = git("merge-base", head, commit).stdout.strip()
    diff = git("diff", "--no-ext-diff", "--stat", base, commit, "--")
    message = ""
    if approved and approved != review:
        message = "The checkout changed after review. Review the result again."
    elif base == commit:
        message = "This result is already in the project."
    elif not branch:
        message = "Check out the project branch you want to update, then review again."
    elif base != head:
        message = "The histories have diverged. The result branch is available for manual review."
    else:
        status = git("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none")
        git_dir = Path(git("rev-parse", "--absolute-git-dir").stdout.strip())
        if status.returncode or status.stdout:
            message = "The project has uncommitted work or could not be checked. Review it first."
        elif any(
            (git_dir / name).exists()
            for name in (
                "MERGE_HEAD",
                "CHERRY_PICK_HEAD",
                "REVERT_HEAD",
                "rebase-merge",
                "rebase-apply",
                "sequencer",
                "BISECT_START",
            )
        ):
            message = "Finish the Git operation already in progress, then review again."
    if diff.returncode and not message:
        message = "Git could not preview the result. Check the project before trying again."
    if approved and not message:
        merged = git(
            "-c",
            f"branch.{branch}.mergeOptions=",
            "merge",
            "--ff-only",
            "--no-squash",
            "--no-autostash",
            "--no-overwrite-ignore",
            commit,
        )
        message = (
            f"Brought the result into {branch} at {commit[:12]}."
            if not merged.returncode
            else "Git refused the fast-forward. Check for local files in the way and review again."
        )
    return {"review": review.model_dump(), "files": diff.stdout, "message": message}
