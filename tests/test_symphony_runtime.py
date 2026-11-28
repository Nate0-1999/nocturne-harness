from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from harness.config import HarnessSettings
from harness.envelope import generate_ulid
from harness.spine_client import (
    ProblemDetail,
    SpineBusyError,
    SpineProblemError,
    SpineResponseError,
    SpineTransportError,
)
from harness.supervisor import WorkerSupervisor
from harness.symphony_experience import SymphonyExperience
from harness.symphony_runtime import SymphonyExecution, _carry_environment, _graft, _publish_result
from tests.test_judge_panel import _distillate, _judge_command
from tests.test_symphony_experience import launch


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


def test_only_the_reviewed_checkout_can_receive_the_judged_commit(tmp_path):
    """FL-085 / F154: only human consent to the reviewed fast-forward can change project files."""
    from functools import partial
    from types import SimpleNamespace

    from harness.symphony_result import ResultReview, project_result

    root = (tmp_path / "project").resolve()
    _repo(root, ".venv/\nresult.txt\n")
    run = "finished"
    attempt = root / ".nocturne-worktrees" / run / "step" / "winner"

    def git(*args):
        return subprocess.check_output(["git", "-C", root, *args], text=True).strip()

    git("branch", "-m", "main")
    git("branch", "release")
    c0 = git("rev-parse", "release")
    (root / "main.txt").write_text("main only")
    start = _commit(root, "Main advanced before the Symphony started")
    git("worktree", "add", "--detach", str(attempt))
    (attempt / "result.txt").write_text("judged")
    subprocess.run(["git", "-C", attempt, "add", "-f", "result.txt"], check=True)
    commit = _commit(attempt, "Judged result")
    git("worktree", "remove", str(attempt))
    branch = _publish_result(root, run, commit)
    stack = SimpleNamespace(
        state="completed",
        symphony_id=run,
        result=f" Result commit: {commit}",
        attempts=[SimpleNamespace(partial_evidence=[str(attempt)])],
    )
    journal = tmp_path / "symphonies" / run / "events.jsonl"
    journal.parent.mkdir(parents=True)
    claim = {
        "event": "claim_accepted",
        "packet_id": run,
        "bead_id": "step-1-round-1",
        "accepted_commit": start,
    }
    journal.write_text(json.dumps(claim) + "\n")
    review = partial(project_result, stack, tmp_path)
    before = git("rev-parse", "HEAD")
    preview = review()
    assert "result.txt" in preview["files"] and not preview["message"]
    assert git("rev-parse", "HEAD") == before
    approved = ResultReview(**preview["review"])

    git("switch", "release")
    release = review()
    approval = review(ResultReview(**release["review"]))
    for response in (release, approval, review(approved)):
        assert "changed since" in response["message"] and branch in response["message"]
    assert git("rev-parse", "HEAD") == git("rev-parse", "release") == c0
    assert not (root / "main.txt").exists() and git("rev-parse", branch) == commit
    assert "main.txt" not in release["files"] and "result.txt" in release["files"]
    git("switch", "main")
    assert git("rev-parse", "HEAD") == start

    (root / "draft").write_text("owner")
    assert "commit" in review(approved)["message"].lower()
    assert (root / "draft").read_text() == "owner"
    (root / "draft").unlink()
    (root / "result.txt").write_text("ignored owner work")
    assert "local files" in review(approved)["message"]
    assert (root / "result.txt").read_text() == "ignored owner work"
    (root / "result.txt").unlink()

    git("switch", "--detach", before)
    detached = review()
    assert not detached["review"]["branch"] and "choose" in detached["message"].lower()
    git("switch", approved.branch)
    git("bisect", "start")
    assert "finish" in review(approved)["message"].lower()
    git("bisect", "reset")
    git("switch", "-c", "other")
    assert "changed" in review(approved)["message"]
    (root / "different").write_text("new owner commit")
    other = _commit(root, "Owner advanced")
    message = review()["message"]
    assert "changed" in message and branch in message and "review" in message.lower()
    assert git("rev-parse", "HEAD") == other
    git("switch", approved.branch)
    assert "Brought" in review(approved)["message"]
    assert git("rev-parse", "HEAD") == git("rev-parse", branch) == commit
    assert (root / "result.txt").read_text() == "judged"
    assert review()["message"] == "This result is already in the project."
    (root / "later.txt").write_text("owner work after the result")
    _commit(root, "Owner continued after bringing in the result")
    assert review()["message"] == "This result is already in the project."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["stage transport", "resolve 503", "stage 422", "resolve reply lost"]
)
async def test_palace_failure_keeps_the_judged_result(tmp_path, monkeypatch, fault):
    """A-059 / M8SY: losing the lesson service after a unanimous pass must not lose the work."""
    root = tmp_path / "project"
    _repo(root, ".venv/\n")
    winner = "round-1-attempt-1"
    spawn = WorkerSupervisor.spawn

    def controlled_worker(supervisor, worker_id, command, *, location, **kwargs):
        out = Path(command[-1]).parent
        if out.name == "smoke":
            result = dict(
                schema_version=1, status="pass", score=1, checks=["ready"], evidence_refs=["work"]
            )
        elif out.name == "completion":
            (location / "result.txt").write_text("finished work")
            result = json.loads(_distillate(winner))
            result["product"]["commit"] = _commit(location, "Finish the work")
            lessons = [
                dict(label=text, body=text, kind="fact", keywords=[]) for text in ("One", "Two")
            ]
            (out / "memories.json").write_text(json.dumps(lessons))
        else:
            return spawn(
                supervisor, worker_id, _judge_command("pass", winner), location=location, **kwargs
            )
        (out / "result.json").write_text(json.dumps(result))
        return spawn(
            supervisor, worker_id, [sys.executable, "-c", "pass"], location=location, **kwargs
        )

    monkeypatch.setattr(WorkerSupervisor, "spawn", controlled_worker)
    staged = set()

    async def stage(request):
        if request.label == "Two" and fault == "stage 422":
            raise SpineProblemError(
                httpx.Response(422), ProblemDetail(detail="The lesson is too long.")
            )
        staged.add(request.memory_id)
        if request.label == "Two" and fault == "stage transport":
            raise SpineTransportError()  # The Palace stored it but its reply was lost.
        return SimpleNamespace(memory=SimpleNamespace(memory_id=request.memory_id))

    async def cleanup(memory_id, request):
        if fault == "stage transport":
            raise SpineTransportError()  # The Palace is still unreachable during cleanup.
        if fault == "resolve reply lost":
            raise SpineResponseError(
                httpx.Response(409), "The batch already advanced to revision 2"
            )
        staged.discard(memory_id)

    palace = SimpleNamespace(
        restore_injection=AsyncMock(return_value=None),
        stage_symphony_memory=stage,
        resolve_symphony_run=AsyncMock(
            side_effect=SpineTransportError()
            if fault == "resolve reply lost"
            else SpineBusyError(httpx.Response(503))
        ),
        patch_memory=AsyncMock(side_effect=cleanup),
    )
    context = SimpleNamespace(
        toolset=SimpleNamespace(location=lambda: SimpleNamespace(workspace_root=root)),
        spine=palace,
        project_key=str(root),
        principal_id="fixture",
        machine_id="fixture",
        agent_id="fixture",
    )
    execution = SymphonyExecution(
        settings=HarnessSettings(_env_file=None, model_policy_chat="max"),
        home=tmp_path,
        context_factory=lambda _: context,
        model_context=AsyncMock(return_value=32000),
    )
    experience = SymphonyExperience(id_factory=generate_ulid)
    experience.bind(execution, AsyncMock())
    charge = launch("fixture")
    charge = charge.model_copy(
        update={"authority": charge.authority.model_copy(update={"attempts": 1, "max_rounds": 1})}
    )
    stack = experience._new_stack(str(uuid4()), charge)
    experience._stacks[stack.symphony_id] = stack
    await experience._execute(stack)

    final = experience._stacks[stack.symphony_id]
    assert any(e.get("winner_attempt_id") == winner for e in final.evidence)
    assert final.state == "completed", final.blocked_reason
    assert final.attempts[0].state == "completed" and not final.attempts[0].memories_admitted
    assert "proof:passed" in final.timeline
    branch = f"symphony/{stack.symphony_id}"
    assert (
        subprocess.check_output(["git", "-C", root, "show", f"{branch}:result.txt"], text=True)
        == "finished work"
    )
    reason = next(
        e["reason"] for e in final.evidence if e.get("attempt_id") == winner and "reason" in e
    )
    if fault == "resolve reply lost":
        assert "did not confirm whether lessons were queued" in reason
    else:
        assert "not queued" in reason.lower()
        assert ("did not answer" if fault == "stage transport" else fault.split()[1]) in reason
        if fault == "stage 422":
            assert "The lesson is too long." in reason
    assert palace.resolve_symphony_run.await_count == int(fault.startswith("resolve"))
    for call in palace.patch_memory.await_args_list:
        patch = call.args[1]
        assert patch.expected_revision == 1 and patch.status == "tombstoned"
    if fault in {"stage transport", "resolve reply lost"}:
        assert staged == {args.args[0] for args in palace.patch_memory.await_args_list}
    else:
        assert not staged
