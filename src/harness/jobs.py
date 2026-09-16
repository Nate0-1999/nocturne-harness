"""M3SJ / SD-059: the daemon runs saved recipes through its ordinary thread loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from spine.jobs import WorkflowDefinition

from harness.envelope import MessageType, generate_ulid
from harness.model_policy import ModelPolicyResolver, parse_model_policy
from harness.spend_walls import workflow_budget
from harness.spine_client import MemoryGraphQuery, SpineClientError


class WorkflowTurnRunner:
    def __init__(self, delegate, definitions):
        self.delegate, self.definitions = delegate, definitions

    async def run(self, **kwargs):
        definition = self.definitions.get(kwargs["thread_id"])
        if definition is None:
            return await self.delegate.run(**kwargs)
        with workflow_budget(definition.budget_usd):
            return await self.delegate.run_workflow(memory_scope=definition.memory_scope, **kwargs)


class WorkflowModelResolver:
    """Resolve a saved policy before the ordinary loop opens its new thread."""

    def __init__(self, delegate, definitions, settings, catalog):
        self.delegate, self.definitions = delegate, definitions
        self.settings, self.catalog = settings, catalog
        self.resolvers = {}

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    async def resolve(self, thread_id):
        definition = self.definitions.get(thread_id)
        if definition is None:
            return await self.delegate.resolve(thread_id)
        if thread_id not in self.resolvers:
            self.resolvers[thread_id] = ModelPolicyResolver(
                policy=definition.model_policy,
                static_model=self.settings.chat_model,
                static_context_tokens=self.settings.model_context_tokens,
                catalog=self.catalog,
            )
        return await self.resolvers[thread_id].resolve(thread_id)


class WorkflowSave(BaseModel):
    definition: WorkflowDefinition
    expected_revision: int = 0
    enabled: bool = True


class JobScheduler:
    def __init__(self, *, spine, settings, loop, definitions, toolset_for):
        self.spine, self.settings, self.loop = spine, settings, loop
        self.definitions, self.toolset_for = definitions, toolset_for
        self.tasks: dict[str, asyncio.Task] = {}
        self.active: dict[str, dict] = {}
        self.error: str | None = None
        self._task: asyncio.Task | None = None

    def start(self):
        self._task = asyncio.create_task(self._watch(), name="workflow-scheduler")

    async def stop(self):
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def snapshot(self):
        snapshot = await self.spine.jobs(self.settings.machine_id)
        for run in snapshot["runs"]:
            if run["run_id"] in self.active:
                run.update(self.active[run["run_id"]])
        snapshot["scheduler_error"] = self.error
        return snapshot

    async def cursor(self, definition):
        if definition.trigger == "file":
            path = Path(definition.trigger_path).expanduser()
            root = Path(definition.folder).resolve(strict=True)
            path = (path if path.is_absolute() else root / path).resolve()
            if not path.is_relative_to(root):
                raise ValueError("The watched file must be inside the workflow folder.")
            return (
                hashlib.sha256(await asyncio.to_thread(path.read_bytes)).hexdigest()
                if path.is_file()
                else "missing"
            )
        if definition.trigger == "queue":
            queue = await self.spine.approval_queue(self.settings.principal_id)
            return max((card.item_uid for card in queue.cards), default="")
        if definition.trigger == "palace":
            graph = await self.spine.memory_graph(
                MemoryGraphQuery(principal_id=self.settings.principal_id, memory_ids=None)
            )
            revisions = sorted(
                (str(node["memory"]["memory_id"]), node["memory"]["revision"])
                for node in graph.nodes
            )
            return hashlib.sha256(json.dumps(revisions).encode()).hexdigest()
        return None

    async def save(self, job_id, body):
        definition = body.definition
        root = Path(definition.folder).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Choose an existing workflow folder.")
        parse_model_policy(definition.model_policy)
        definition = definition.model_copy(update={"folder": str(root)})
        return await self.spine.job_write(
            "PUT",
            f"v1/jobs/{job_id}",
            {
                "machine_id": self.settings.machine_id,
                "definition": definition.model_dump(mode="json"),
                "expected_revision": body.expected_revision,
                "enabled": body.enabled,
                "trigger_cursor": await self.cursor(definition),
            },
        )

    async def launch(self, job, *, manual=False, cursor=None):
        definition = WorkflowDefinition.model_validate(job["definition"])
        run_id, thread_id = generate_ulid(), str(uuid4())
        scheduled = job.get("next_run_at")
        if scheduled:
            scheduled = datetime.fromisoformat(scheduled).isoformat()
        key = scheduled if not manual and definition.cron else run_id
        run = await self.spine.job_write(
            "POST",
            f"v1/jobs/{job['job_id']}/runs",
            {
                "machine_id": self.settings.machine_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "trigger_key": key,
                "expected_revision": job["revision"],
                "trigger_cursor": cursor,
                "manual": manual,
            },
        )
        self.definitions[thread_id] = definition
        task = asyncio.create_task(self._execute(run, definition), name=f"job-{run_id}")
        self.tasks[run_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(run_id, None))
        return run

    async def _watch(self):
        recovered = False
        while True:
            try:
                snapshot = await self.spine.jobs(self.settings.machine_id)
                if not recovered:
                    for run in snapshot["runs"]:
                        self.definitions[run["thread_id"]] = WorkflowDefinition.model_validate(
                            run["definition"]
                        )
                        if run["state"] == "running" and run["run_id"] not in self.tasks:
                            await self._finish(
                                run["run_id"],
                                "interrupted",
                                "Daemon stopped during this run; "
                                "inspect its journal before rerunning.",
                            )
                    recovered = True
                running = {run["job_id"] for run in snapshot["runs"] if run["state"] == "running"}
                for job in snapshot["jobs"]:
                    if not job["enabled"] or job["job_id"] in running:
                        continue
                    definition = WorkflowDefinition.model_validate(job["definition"])
                    cursor = await self.cursor(definition)
                    due = job["next_run_at"] and datetime.fromisoformat(
                        job["next_run_at"]
                    ) <= datetime.now(UTC)
                    changed = cursor is not None and cursor != job["trigger_cursor"]
                    if definition.trigger == "queue":
                        changed = cursor > (job["trigger_cursor"] or "")
                    if due or changed:
                        await self.launch(job, cursor=cursor)
                self.error = None
            except (SpineClientError, OSError, ValueError) as exc:
                self.error = f"Jobs unavailable: {exc}"
            await asyncio.sleep(5)

    async def _finish(self, run_id, state, verdict):
        await self.spine.job_write(
            "POST",
            f"v1/job-runs/{run_id}/finish",
            {
                "machine_id": self.settings.machine_id,
                "state": state,
                "verdict": verdict,
            },
        )

    async def _execute(self, run, definition):
        run_id, thread_id = run["run_id"], run["thread_id"]
        done = asyncio.get_running_loop().create_future()
        loop_run_id = None

        async def observe(envelope):
            payload = envelope.model_dump(mode="json")["payload"]
            if envelope.type == MessageType.RUN_DONE and not done.done():
                done.set_result(payload)
            if envelope.type == MessageType.RUN_DELTA:
                event = payload.get("event", {})
                if event.get("event_kind") == "boundary_card":
                    self.active[run_id] = {"state": "waiting", "verdict": event.get("reason")}

        state, verdict = "failed", "Workflow did not complete."
        try:
            await self.loop.request_snapshot(thread_id, observe, workspace_root=definition.folder)
            prompt = (
                definition.prompt
                + "\n\nComplete the work so this exit check succeeds:\n"
                + definition.exit_condition
            )
            loop_run_id = await self.loop.submit(
                thread_id=thread_id, prompt_id=generate_ulid(), prompt=prompt, sink=observe
            )
            result = await done
            if result["stop_reason"] == "end_turn":
                marker = f"NOCTURNE_JOB_CHECK_{run_id}"
                await self.toolset_for(thread_id).move(Path(definition.folder))
                checked = await self.toolset_for(thread_id).execute(
                    "bash",
                    {
                        "command": f"({definition.exit_condition}) && printf '\\n{marker}\\n'",
                    },
                )
                passed = checked.success and checked.content.strip().endswith(marker)
                state = "completed" if passed else "failed"
                verdict = (
                    "Exit check passed." if passed else f"Exit check failed: {checked.content}"
                )
            else:
                state = "cancelled" if result["stop_reason"] == "cancelled" else "failed"
                verdict = f"Run ended: {result['stop_reason']}."
        except asyncio.CancelledError:
            if loop_run_id is not None:
                await self.loop.cancel(thread_id=thread_id, run_id=loop_run_id)
            state, verdict = "cancelled", "Stopped explicitly or during daemon shutdown."
        except Exception as exc:
            verdict = f"Workflow failed: {exc}"
        finally:
            await self.loop.detach(observe)
            self.active.pop(run_id, None)
            try:
                await self._finish(run_id, state, verdict)
            except SpineClientError as exc:
                self.error = f"Run result awaiting recovery: {exc}"

    def mount(self, app: FastAPI):
        @app.get("/v1/jobs")
        async def read_jobs():
            try:
                return await self.snapshot()
            except SpineClientError as exc:
                raise HTTPException(503, "Jobs need an updated, reachable Palace.") from exc

        @app.put("/v1/jobs/{job_id}")
        async def save_job(job_id: str, body: WorkflowSave):
            try:
                return await self.save(job_id, body)
            except (ValueError, OSError, SpineClientError) as exc:
                raise HTTPException(409, str(exc)) from exc

        @app.post("/v1/jobs")
        async def create_job(body: WorkflowSave):
            return await save_job(generate_ulid(), body)

        @app.post("/v1/jobs/{job_id}/run")
        async def run_job(job_id: str):
            try:
                snapshot = await self.snapshot()
                job = next((job for job in snapshot["jobs"] if job["job_id"] == job_id), None)
                if job is None:
                    raise HTTPException(404, "Workflow not found.")
                return await self.launch(job, manual=True)
            except SpineClientError as exc:
                raise HTTPException(409, str(exc)) from exc

        @app.post("/v1/job-runs/{run_id}/stop")
        async def stop_job(run_id: str):
            task = self.tasks.get(run_id)
            if task is None:
                raise HTTPException(404, "This job is not running here.")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return {"stopped": True}

        app.router.add_event_handler("startup", self.start)
        app.router.on_shutdown.insert(0, self.stop)
