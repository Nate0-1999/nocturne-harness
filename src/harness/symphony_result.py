"""Review a published Symphony result in the project where its attempts ran."""

import json
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


def worktree_project(location: str, symphony_id: str) -> Path | None:
    path = Path(location)
    if path.is_absolute():
        for parent in path.parents:
            if parent.name == symphony_id and parent.parent.name == ".nocturne-worktrees":
                return parent.parent.parent
    return None


def _starting_commit(home: Path, symphony_id: str) -> str:
    # The first step's conductor claim records HEAD before any worker or graft advances it.
    with (home / "symphonies" / symphony_id / "events.jsonl").open() as events:
        for line in events:
            event = json.loads(line)
            if (
                isinstance(event, dict)
                and event.get("event") == "claim_accepted"
                and event.get("packet_id") == symphony_id
                and event.get("bead_id") == "step-1-round-1"
            ):
                commit = event.get("accepted_commit")
                if isinstance(commit, str) and re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit):
                    return commit
                break
    raise ValueError("Missing launch claim")


def project_result(
    stack: SymphonyStackRecord, home: Path, approved: ResultReview | None = None
) -> dict:
    # F154 / ADR-012: completion publishes the judged commit. Only its owner can apply it.
    if stack.state != "completed":
        raise ValueError("Wait for the judges to finish this Symphony.")
    match = re.search(r" Result commit: ([a-f0-9]{40}|[a-f0-9]{64})$", stack.result or "")
    roots = {
        project
        for attempt in stack.attempts
        for location in attempt.partial_evidence
        if (project := worktree_project(location, stack.symphony_id)) is not None
    }
    if not match or len(roots) != 1:
        raise ValueError("The run has no verifiable project and result commit.")
    root = roots.pop()
    commit = match[1]
    result_branch = f"symphony/{stack.symphony_id}"
    source = f"refs/heads/{result_branch}"

    def git(*args):
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)

    if git("rev-parse", "--show-toplevel").stdout.rstrip("\n") != str(root):
        raise ValueError("The original project checkout is unavailable.")
    if git("rev-parse", "--verify", source).stdout.strip() != commit:
        raise ValueError("The result branch no longer points to the commit the judges accepted.")
    head = git("rev-parse", "--verify", "HEAD").stdout.strip()
    branch = git("symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    review = ResultReview(project=str(root), branch=branch, head=head, commit=commit)
    try:
        start = _starting_commit(home, stack.symphony_id)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not verify the starting commit. Review {result_branch}.") from exc
    diff = git("diff", "--no-ext-diff", "--stat", start, commit, "--")
    message = ""
    if git("merge-base", "--is-ancestor", commit, head).returncode == 0:
        message = "This result is already in the project."
    elif head != start:
        message = (
            f"The project changed since this Symphony started. Review the saved result on "
            f"{result_branch}."
        )
    elif approved and approved != review:
        message = "The project changed after your review. Review the result again."
    elif not branch:
        message = "No project branch is selected. Choose the branch you want to update."
    else:
        status = git("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none")
        git_dir = Path(git("rev-parse", "--absolute-git-dir").stdout.strip())
        if any(
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
            message = "A Git operation is in progress. Finish it before bringing in this result."
        elif status.returncode:
            message = "Git could not check the project. Open the project and check its status."
        elif status.stdout:
            message = "The project has uncommitted changes. Commit your work and review again."
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
            else "Git could not update the project. Check for local files at the listed paths."
        )
    return {"review": review.model_dump(), "files": diff.stdout, "message": message}
