"""Connect signed Conversation recipes to the conductor, supervisor and judge panel."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from harness.conductor import (
    AuthoritativeClaim,
    ChildCharge,
    Conductor,
    JudgeCharter,
    ModelPolicyByBlastRadius,
    SearchAttemptBrief,
    SearchBudget,
    SearchNodeDeclaration,
    SmokeGateResult,
    TypedDistillate,
)
from harness.context_window import bounds_from
from harness.envelope import generate_ulid
from harness.judge_panel import FeedbackPacketReceipt, JudgeLaunch, JudgePanel, stopped_verdict
from harness.memory_bridge import SymphonyMemoryBridge
from harness.rounds import AcceptedWork, GraftReceipt, RoundAttemptPlan, SymphonyRounds
from harness.spine_client import JudgedContext, MemoryKind, MemoryStatus, PatchMemoryRequest
from harness.supervisor import WorkerSupervisor
from harness.symphony_experience import SymphonyAttemptRecord


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def _publish_result(root: Path, symphony_id: str, checkpoint: str) -> str:
    """Keep judged work on a reviewable branch without moving the user's checkout."""
    branch = f"symphony/{symphony_id}"
    _git(root, "branch", branch, checkpoint)
    return branch


def _carry_environment(root: Path, location: Path) -> None:
    """M3SF / M3EX-10: an attempt gets the project's ignored .venv, pointed at itself."""
    source = root / ".venv"
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", ".venv"])
    if not source.is_dir() or ignored.returncode != 0:
        return
    target = location / ".venv"
    clone = ("-c",) if sys.platform == "darwin" else ()  # APFS clone where the disk has it
    subprocess.run(["cp", *clone, "-R", str(source), str(target)], check=True)
    old, new = f"{root}/".encode(), f"{location}/".encode()
    for path in (*target.glob("bin/*"), *target.glob("lib/python*/site-packages/*.pth")):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if old in data and b"\0" not in data:
                path.write_bytes(data.replace(old, new))


def _graft(graft_root: Path, commits: list[str]) -> str:
    """M3SF: passing attempts combine; where they overlap, the earlier attempt's lines stand."""
    for commit in commits:
        try:
            _git(
                graft_root,
                "-c",
                "user.name=Nocturne",
                "-c",
                "user.email=nocturne@localhost",
                "cherry-pick",
                "--keep-redundant-commits",
                "-X",
                "ours",
                commit,
            )
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                "The judges passed different attempts whose changes cannot be combined."
            ) from exc
    return _git(graft_root, "rev-parse", "HEAD")


class SymphonyExecution:
    """One execution seam; the existing conductor remains the search authority."""

    def __init__(self, *, settings, home: Path, context_factory):
        self.settings = settings
        self.home = home
        self.context_factory = context_factory
        self.live = {}

    def preflight(self, thread_id: str) -> Path:
        root = self.context_factory(thread_id).toolset.location().workspace_root
        _git(root, "rev-parse", "HEAD")
        if _git(root, "status", "--porcelain"):
            raise ValueError("Commit or save this folder's changes before signing a Symphony.")
        return root

    async def run(self, stack, update):
        context = self.context_factory(stack.thread_id)
        root = self.preflight(stack.thread_id)
        run_home = self.home / "symphonies" / stack.symphony_id
        run_home.mkdir(parents=True, exist_ok=True)
        checkpoint = _git(root, "rev-parse", "HEAD")
        worktrees = root / ".nocturne-worktrees" / stack.symphony_id
        exclude = Path(_git(root, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = root / exclude
        existing = exclude.read_text() if exclude.exists() else ""
        if "\n/.nocturne-worktrees/\n" not in "\n" + existing:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a") as stream:
                stream.write("\n/.nocturne-worktrees/\n")
        settings_path = run_home / "env"
        # The supervised process receives only this private settings path, never a shell secret.
        from dotenv import set_key

        settings_path.touch(mode=0o600)
        for key, value in self.settings.model_dump().items():
            if value is not None:
                raw = value.get_secret_value() if hasattr(value, "get_secret_value") else value
                set_key(str(settings_path), key.upper(), str(raw))
        started = time.monotonic()
        supervisor = WorkerSupervisor(run_home / "supervisor")
        state = {"supervisor": supervisor, "workers": {}, "followups": {}, "cancelled": set()}
        self.live[stack.symphony_id] = state
        authority = stack.launch.authority

        def record(event):
            with (run_home / "events.jsonl").open("a") as stream:
                stream.write(json.dumps(event, default=str) + "\n")

        def cost():
            meters = [json.loads(path.read_text()) for path in run_home.rglob("meter.json")]
            if any(meter["unpriced"] for meter in meters):
                raise ValueError(
                    "A worker returned unpriced usage; execution paused for accounting."
                )
            return sum(
                (Decimal(meter["cost_usd"]) for meter in meters),
                Decimal(0),
            )

        async def wait(handles):
            measured = None
            while True:
                alive = any(supervisor.heartbeat(handle.worker_id) for handle in handles)
                spent = cost()
                if spent != measured:
                    await update("running", {"spend_usd": str(spent)})
                    measured = spent
                if spent >= authority.spend_wall_usd:
                    raise ValueError("The Symphony reached its signed spend wall.")
                if time.monotonic() - started >= authority.duration_minutes * 60:
                    raise ValueError("The Symphony reached its signed time wall.")
                if not alive:
                    return
                await asyncio.sleep(0.1)

        def command(location, stage, brief, model_policy, origin_agent, name):
            output = run_home / name
            assignment = output / "assignment.json"
            _json(
                assignment,
                {
                    "stage": stage,
                    "step_title": step.title,
                    "brief": brief
                    + "\nSigned authority and charters:\n"
                    + json.dumps(
                        {
                            "authority": authority.model_dump(mode="json"),
                            "judge_charters": [
                                c.model_dump(mode="json") for c in stack.launch.judge_charters
                            ],
                        }
                    ),
                    "model_policy": model_policy,
                    "origin_agent": origin_agent,
                    "thread_id": stack.thread_id,
                    "project_key": str(root),
                    "run_id": round_run,
                    "prompt_id": generate_ulid(),
                    "home": str(self.home),
                    "env_file": str(settings_path),
                    "followups": str(run_home / "followups.json"),
                    "attempt_id": location.name,
                    "workspace_root": str(location.parent if stage == "judge" else location),
                },
            )
            return (sys.executable, "-m", "harness.symphony_worker", str(assignment)), output

        def mint(draft):
            _json(run_home / "feedback" / f"{draft.packet_id}.json", draft.model_dump())
            return FeedbackPacketReceipt(
                packet_id=draft.packet_id,
                bead_id=draft.packet_id,
                charge_digest=hashlib.sha256(draft.charge.encode()).hexdigest(),
                minter_role="judge",
            )

        bridge = SymphonyMemoryBridge(
            context.spine,
            principal_id=context.principal_id,
            machine_id=context.machine_id,
            thread_id=UUID(stack.thread_id),
        )
        last_decision = None
        unresolved = []
        passed_work = []
        try:
            for step_index, step in enumerate(stack.launch.recipe):
                feedback = ""
                prior_decision = None
                strategies = step.stratagems or (
                    "Direct: implement the simplest solution from the acceptance criteria.",
                    "Test first: encode the acceptance criteria before implementing.",
                    "Boundary first: check edge cases, then build the smallest solution.",
                )
                count = min(authority.attempts, len(strategies)) if step.search else 1
                budget = SearchBudget(
                    attempts=count,
                    spend_wall_usd=authority.spend_wall_usd,
                    max_rounds=authority.max_rounds,
                    depth_cap=authority.depth_cap,
                    children_per_attempt=authority.children_per_attempt,
                    duration_seconds=float(authority.duration_minutes * 60),
                )
                rounds = SymphonyRounds(
                    packet_id=stack.symphony_id,
                    initial_search_child_id=f"step-{step_index + 1}-round-1",
                    initial_checkpoint=checkpoint,
                    budget=budget,
                    event_sink=record,
                    passed_work=passed_work,
                )
                for round_number in range(1, authority.max_rounds + 1):
                    round_run = generate_ulid()
                    child_id = f"step-{step_index + 1}-round-{round_number}"
                    record({"event": "round_run", "child_id": child_id, "run_id": round_run})
                    parent = run_home / child_id
                    parent.mkdir()
                    graft = None
                    survivors = ()
                    if prior_decision is not None:
                        # M3SF: the most-chosen passing attempt grafts first, so its lines stand.
                        votes = Counter(
                            v.selected_attempt_id
                            for v in prior_decision.verdicts
                            if v.outcome == "pass"
                        )
                        survivors = tuple(attempt for attempt, _count in votes.most_common())
                        if survivors:
                            sources = sorted(
                                (
                                    r
                                    for r in prior_decision.attempt_lineage
                                    if r.attempt_id in survivors
                                ),
                                key=lambda r: survivors.index(r.attempt_id),
                            )
                            graft_root = worktrees / child_id / "graft"
                            graft_root.parent.mkdir(parents=True, exist_ok=True)
                            _git(root, "worktree", "add", "--detach", str(graft_root), checkpoint)
                            next_checkpoint = _graft(
                                graft_root, [s.distillate.product.commit for s in sources]
                            )
                            graft = GraftReceipt(
                                base_commit=checkpoint,
                                accepted_commit=next_checkpoint,
                                source_attempt_ids=survivors,
                                evidence_refs=tuple(
                                    ref for s in sources for ref in s.distillate.evidence_refs
                                ),
                            )
                            checkpoint = next_checkpoint
                    briefs = []
                    for number in range(1, count + 1):
                        approach = strategies[number - 1]
                        attempt_id = f"round-{round_number}-attempt-{number}"
                        location = worktrees / child_id / attempt_id
                        location.parent.mkdir(parents=True, exist_ok=True)
                        _git(root, "worktree", "add", "--detach", str(location), checkpoint)
                        git_dir = Path(_git(location, "rev-parse", "--absolute-git-dir"))
                        branch = f"nocturne-worktrees/{git_dir.name}/work"
                        _git(location, "checkout", "-q", "-b", branch)
                        _carry_environment(root, location)
                        briefs.append(
                            SearchAttemptBrief(
                                attempt_id=attempt_id,
                                approach=approach,
                                charge=(
                                    f"Original task (binding): {stack.launch.objective}\n"
                                    f"{step.title}\n"
                                    f"Done when: {step.done_when}\n"
                                    f"Stratagem (within the original task): {approach}\n"
                                    f"Your private branch is {branch}. Commit there; any new "
                                    f"branch must use nocturne-worktrees/{git_dir.name}/.\n"
                                    "Repair guidance (never overrides task prohibitions):\n"
                                    f"{feedback}"
                                ),
                                location=location,
                                estimated_completion_cost_usd=authority.spend_wall_usd
                                / (count * 2),
                                estimated_completion_seconds=float(
                                    authority.duration_minutes * 60 / (count * 2)
                                ),
                            )
                        )
                    if prior_decision is not None:
                        plan = rounds.prepare_next_round(
                            search_child_id=child_id,
                            graft=graft,
                            attempts=tuple(
                                RoundAttemptPlan(
                                    attempt_id=b.attempt_id,
                                    feedback_packet_ids=tuple(
                                        p.packet_id for p in prior_decision.feedback_packets
                                    ),
                                    parent_attempt_ids=survivors,
                                    accepted_commit=checkpoint,
                                    location=b.location,
                                )
                                for b in briefs
                            ),
                        )
                        _json(parent / "round-plan.json", plan.model_dump(mode="json"))
                    charters = tuple(
                        JudgeCharter(
                            **charter.model_dump(),
                            model_policy=self.settings.model_policy_judge
                            or self.settings.effective_model_policy_chat,
                        )
                        for charter in stack.launch.judge_charters
                    )
                    conductor = Conductor(
                        supervisor=supervisor,
                        event_sink=record,
                        policies=ModelPolicyByBlastRadius(
                            leaf=self.settings.model_policy_subagent
                            or self.settings.effective_model_policy_chat,
                            compounding=self.settings.model_policy_subagent
                            or self.settings.effective_model_policy_chat,
                        ),
                        search_spend_reader=lambda *_: cost(),
                        result_share=bounds_from(self.settings).share(
                            int(self.settings.model_context_tokens * 0.8)
                        ),
                    )
                    conductor.claim(
                        AuthoritativeClaim(
                            packet_id=stack.symphony_id,
                            bead_id=child_id,
                            charge_digest=hashlib.sha256(
                                stack.launch.model_dump_json().encode()
                            ).hexdigest(),
                            claim_token=stack.launch.draft_id,
                            accepted_commit=checkpoint,
                            motivation_chain=(stack.launch.motivation,),
                            scope=(".",),
                            status="in_progress",
                        )
                    )
                    conductor.expand(
                        (
                            ChildCharge(
                                child_id=child_id,
                                title=step.title,
                                charge=briefs[0].charge,
                                surfaces=(".",),
                                evidence_requirements=(step.done_when,),
                                location=parent,
                                search=SearchNodeDeclaration(
                                    round_number=round_number,
                                    attempts=tuple(briefs),
                                    judge_charters=charters,
                                    budget=budget,
                                ),
                            ),
                        )
                    )
                    outputs = {}
                    commands = {}
                    for number, brief in enumerate(briefs, 1):
                        origin = f"{round_run}/root.{number}"
                        commands[brief.attempt_id], outputs[brief.attempt_id] = command(
                            brief.location,
                            "smoke",
                            brief.charge,
                            self.settings.model_policy_subagent
                            or self.settings.effective_model_policy_chat,
                            origin,
                            f"{child_id}/{brief.attempt_id}/smoke",
                        )
                    handles = conductor.explode_search(child_id, commands)
                    state["workers"] = {
                        brief.attempt_id: handle.worker_id
                        for brief, handle in zip(briefs, handles, strict=True)
                    }
                    await update(
                        "running",
                        {
                            "timeline": (f"{child_id}:workers_started",),
                            "attempts": tuple(
                                SymphonyAttemptRecord(
                                    attempt_id=b.attempt_id,
                                    state="running",
                                    partial_evidence=(str(b.location),),
                                )
                                for b in briefs
                            ),
                            "evidence": [
                                handle.model_dump(mode="json", exclude={"brief"})
                                for handle in handles
                            ],
                        },
                    )
                    await wait(handles)
                    for brief in briefs:
                        path = outputs[brief.attempt_id] / "result.json"
                        if brief.attempt_id in state["cancelled"] or not path.exists():
                            _json(
                                path,
                                {
                                    "schema_version": 1,
                                    "status": "fail",
                                    "score": "0",
                                    "checks": ["Worker exited without a readiness result."],
                                    "evidence_refs": [str(brief.location)],
                                },
                            )
                        conductor.accept_smoke_gate(
                            child_id,
                            brief.attempt_id,
                            SmokeGateResult.model_validate_json(path.read_text()),
                        )
                    selected = conductor.narrow_search_beam(child_id)
                    if not selected:
                        causes = "; ".join(
                            check
                            for result in conductor.search_results(child_id)
                            if result.smoke is not None
                            for check in result.smoke.checks
                        )
                        raise ValueError(
                            "No attempt can start. Resolve these prerequisites before retrying: "
                            + causes
                        )
                    await update(
                        "running",
                        {
                            "stopped_attempt_ids": [
                                b.attempt_id for b in briefs if b not in selected
                            ],
                        },
                    )
                    handles = []
                    for number, brief in enumerate(selected, 1):
                        origin = f"{round_run}/root.{briefs.index(brief) + 1}"
                        cmd, output = command(
                            brief.location,
                            "completion",
                            brief.charge,
                            self.settings.model_policy_subagent
                            or self.settings.effective_model_policy_chat,
                            origin,
                            f"{child_id}/{brief.attempt_id}/completion",
                        )
                        outputs[brief.attempt_id] = output
                        handle = conductor.dispatch_search_completion(
                            child_id, brief.attempt_id, cmd
                        )
                        handles.append(handle)
                        state["workers"][brief.attempt_id] = handle.worker_id
                    await wait(handles)
                    for brief in selected:
                        blocked = outputs[brief.attempt_id] / "blocked.json"
                        if blocked.exists():
                            # WALL money / D.2 102: do not respawn a worker against the same fence.
                            raise ValueError(json.loads(blocked.read_text())["reason"])
                        path = outputs[brief.attempt_id] / "result.json"
                        cancelled = brief.attempt_id in state["cancelled"]
                        if cancelled or not path.exists():
                            _json(
                                path,
                                {
                                    "schema_version": 1,
                                    "status": "cancelled" if cancelled else "failed",
                                    "claims": [],
                                    "evidence_refs": [str(brief.location)],
                                    "uncertainties": [
                                        "Worker stopped without a completed result; "
                                        "partial files have not passed judges."
                                    ],
                                    "metrics_refs": [],
                                    "artifacts": [],
                                    "patch": None,
                                    "product": {"kind": "commit", "commit": checkpoint},
                                },
                            )
                            _json(outputs[brief.attempt_id] / "memories.json", [])
                        conductor.accept_search_distillate(
                            child_id,
                            brief.attempt_id,
                            TypedDistillate.model_validate_json(path.read_text()),
                        )
                    await update(
                        "running",
                        {
                            "stopped_attempt_ids": [
                                item.attempt_id
                                for item in conductor.search_results(child_id)
                                if item.distillate is not None
                                and item.distillate.status != "completed"
                            ]
                        },
                    )
                    panel = JudgePanel(
                        conductor=conductor,
                        search_child_id=child_id,
                        supervisor=supervisor,
                        event_sink=record,
                        feedback_minter=mint,
                    )
                    launches = {}
                    judge_outputs = {}
                    for charter in charters:
                        location = worktrees / child_id / f"judge-{charter.seat}"
                        location.mkdir()
                        cmd, output = command(
                            location,
                            "judge",
                            "Judge the signed work against your charter.",
                            charter.model_policy,
                            f"{round_run}/root",
                            f"{child_id}/judge-{charter.seat}",
                        )
                        launches[charter.seat] = JudgeLaunch(command=cmd, location=location)
                        judge_outputs[charter.seat] = output
                    sessions = panel.dispatch(launches)
                    await wait(sessions)
                    for session in sessions:
                        verdict_path = session.brief_path.with_name("judge-verdict.json")
                        if not verdict_path.exists():
                            # M3SF: a judge process that died still leaves a FAIL with its reason.
                            _json(
                                verdict_path,
                                stopped_verdict(
                                    session.model_dump(),
                                    charter=next(c for c in charters if c.seat == session.seat),
                                    reason="the judge process stopped before returning",
                                    evidence_ref=str(judge_outputs[session.seat]),
                                ).model_dump(mode="json"),
                            )
                        panel.accept_verdict(session.seat)
                    decision = panel.resolve()
                    rounds.accept_panel_decision(decision)
                    prior_decision = decision
                    last_decision = decision
                    await update(
                        "running",
                        {
                            "timeline": (f"{child_id}:judged",),
                            "evidence": [decision.model_dump(mode="json")],
                            "spend_usd": str(cost()),
                        },
                    )
                    if decision.winner_attempt_id is not None:
                        winner = next(
                            item
                            for item in conductor.search_results(child_id)
                            if item.attempt_id == decision.winner_attempt_id
                        )
                        checkpoint = winner.distillate.product.commit
                        memory_run = round_run
                        origins = {}
                        staged = []
                        for number, brief in enumerate(selected, 1):
                            if brief.attempt_id in state["cancelled"]:
                                continue
                            origin = f"{memory_run}/root.{briefs.index(brief) + 1}"
                            origins[brief.attempt_id] = origin
                            memories = json.loads(
                                (outputs[brief.attempt_id] / "memories.json").read_text()
                            )
                            for memory in memories:
                                response = await bridge.stage(
                                    memory_id=uuid4(),
                                    run_id=memory_run,
                                    origin_agent=origin,
                                    label=memory["label"],
                                    body=memory["body"],
                                    kind=MemoryKind(memory["kind"]),
                                    keywords=memory["keywords"],
                                    project_key=str(root),
                                    origin_path=".",
                                    origin_location=str(root),
                                )
                                staged.append(response.memory.memory_id)
                                unresolved.append(response.memory.memory_id)
                        winner_memories = json.loads(
                            (outputs[decision.winner_attempt_id] / "memories.json").read_text()
                        )
                        if staged and winner_memories:
                            resolution = await bridge.resolve(
                                run_id=memory_run,
                                batch_uid=uuid4(),
                                winner_origin_agent=origins[decision.winner_attempt_id],
                                judged_context=JudgedContext(
                                    verdict="unanimous_pass",
                                    summary=step.done_when,
                                    judge_ids=[v.judge_session_id for v in decision.verdicts],
                                    evidence_refs=[
                                        str(judge_outputs[v.seat] / "result.json")
                                        for v in decision.verdicts
                                    ],
                                ),
                            )
                            record(
                                {
                                    "event": "memory_resolution",
                                    "resolution": resolution.model_dump(mode="json"),
                                }
                            )
                            unresolved.clear()
                            await update(
                                "running",
                                {
                                    "timeline": ("winner_memories_queued",),
                                    "admitted_attempt_id": decision.winner_attempt_id,
                                    "evidence": [resolution.model_dump(mode="json")],
                                },
                            )
                        passed_work.append(
                            AcceptedWork(
                                child_id=step.step_id,
                                attempt_id=winner.attempt_id,
                                accepted_commit=checkpoint,
                                evidence_refs=winner.distillate.evidence_refs,
                            )
                        )
                        await update("running", {"timeline": (f"{step.step_id}:passed",)})
                        break
                    feedback = "\n".join(
                        json.loads(
                            (run_home / "feedback" / f"{packet.packet_id}.json").read_text()
                        )["charge"]
                        for packet in decision.feedback_packets
                    )
                else:
                    # M3SF: the stop carries what the judges said, so the card states the reason.
                    failures = " ".join(
                        f"{v.seat.capitalize()} judge: {' '.join(v.rationale.split())}"
                        for v in prior_decision.verdicts
                        if v.outcome == "fail"
                    )
                    raise ValueError(
                        "The judges did not pass the work within the signed round limit. "
                        + (failures or "They chose different attempts.")
                    )
            branch = _publish_result(root, stack.symphony_id, checkpoint)
            await update(
                "completed",
                {
                    "timeline": ("judge_panel_unanimous", "completed"),
                    "result": (
                        f"Judges accepted the work on branch {branch}. "
                        f"{last_decision.selection_rule} Result commit: {checkpoint}"
                    ),
                    "spend_usd": str(cost()),
                    "evidence": [last_decision.model_dump(mode="json")],
                },
            )
        finally:
            for attempt in supervisor.attempts():
                if supervisor.heartbeat(attempt.worker_id):
                    supervisor.request_termination(attempt.worker_id)
            deadline = time.monotonic() + 10
            while any(supervisor.heartbeat(item.worker_id) for item in supervisor.attempts()):
                if time.monotonic() > deadline:
                    # INCIDENT F135 (M3EX-13): a worker that ignores its stop must not hold
                    # Ctrl-C forever or outlive Nocturne.
                    for item in supervisor.attempts():
                        if item.pid is not None and supervisor.heartbeat(item.worker_id):
                            try:
                                os.killpg(item.pid, signal.SIGKILL)
                            except OSError:
                                pass
                    break
                await asyncio.sleep(0.1)
            supervisor.close()
            self.live.pop(stack.symphony_id, None)
            settings_path.unlink(missing_ok=True)
            for memory_id in unresolved:
                await context.spine.patch_memory(
                    memory_id,
                    PatchMemoryRequest(
                        expected_revision=1,
                        status=MemoryStatus.TOMBSTONED,
                        editor=f"agent:{context.agent_id}",
                        reason="symphony/unresolved-tombstone",
                        machine_id=context.machine_id,
                    ),
                )

    async def cancel_attempt(self, symphony_id, attempt_id):
        state = self.live[symphony_id]
        worker_id = state["workers"][attempt_id]
        supervisor = state["supervisor"]
        if not supervisor.heartbeat(worker_id):
            raise ValueError("This attempt has already returned; the judges are reviewing it.")
        state["cancelled"].add(attempt_id)
        supervisor.request_termination(worker_id)
        while supervisor.heartbeat(worker_id):
            await asyncio.sleep(0.1)

    def clarify(self, symphony_id, attempt_id, instruction):
        state = self.live[symphony_id]
        state["followups"].setdefault(attempt_id, []).append(instruction)
        _json(self.home / "symphonies" / symphony_id / "followups.json", state["followups"])


def remove_kept_worktrees(home: Path, completed: list[str], keep: int) -> list[Path]:
    """M3HW (M3W5B-13): seven small Symphonies left 17 GB of worktrees, each with its own
    environment. A completed Symphony's result is already on the branch, so its worktrees go,
    oldest first, leaving the newest `keep`; each attempt's last commit stays reachable under
    refs/nocturne/symphonies/ so pruned work remains auditable. Evidence under home stays."""
    removed = []
    for symphony_id in completed[: max(0, len(completed) - keep)]:
        run_home = home / "symphonies" / symphony_id
        assignments = sorted(run_home.rglob("assignment.json"))
        if not assignments:
            continue
        root = Path(json.loads(assignments[0].read_text())["project_key"])
        target = root / ".nocturne-worktrees" / symphony_id
        if target.is_symlink() or not target.is_dir():
            continue
        for marker in sorted(target.glob("*/*/.git")):
            name = marker.parent.relative_to(target).as_posix()
            head = subprocess.run(
                ["git", "-C", str(marker.parent), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            if head.returncode == 0:
                ref = f"refs/nocturne/symphonies/{symphony_id}/{name}"
                _git(root, "update-ref", ref, head.stdout.strip())
                result = run_home / name / "completion/result.json"
                if result.is_file():
                    commit = json.loads(result.read_text())["product"]["commit"]
                    _git(root, "update-ref", f"{ref}-product", commit)
                git_dir = Path(_git(marker.parent, "rev-parse", "--absolute-git-dir"))
                namespace = f"refs/heads/nocturne-worktrees/{git_dir.name}/"
                for branch in _git(
                    root, "for-each-ref", "--format=%(refname)", namespace
                ).splitlines():
                    _git(root, "update-ref", "-d", branch)
        shutil.rmtree(target)
        subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)
        removed.append(target)
    return removed
