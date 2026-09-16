"""SPEC C.7 / M3SJ: workflow completion crosses the real typed envelope boundary."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from spine.jobs import WorkflowDefinition
from test_run_loop import RecordingResolver

from harness.envelope import EnvelopeFactory, StopReason, generate_ulid
from harness.jobs import JobScheduler
from harness.model_policy import ThreadModelResolution
from harness.run_loop import RunLoop
from harness.run_protocol import TurnOutcome
from harness.toolset_runtime import LazyStandardToolset


@pytest.mark.asyncio
async def test_workflow_receives_typed_events_and_finishes_exit_check(tmp_path):
    """SPEC C.7 / M3SJ: typed deltas must not silently disconnect the completion observer."""

    class Runner:
        async def run(self, *, emit, **kwargs):
            await emit.event({"event_kind": "tool_result", "result": "done"})
            await emit.text("Done.")
            return TurnOutcome(StopReason.END_TURN, (), assistant_text="Done.")

    class Palace:
        finished = []

        async def job_write(self, method, path, body):
            self.finished.append(body)

    thread_id, model = str(uuid4()), "openrouter:openai/gpt-4.1"
    resolution = ThreadModelResolution(model=model, context_tokens=1000, policy=f"pinned:{model}")
    loop = RunLoop(
        Runner(),
        EnvelopeFactory(machine_id="workflow-test"),
        model_resolver=RecordingResolver({thread_id: resolution}, {model: resolution}),
    )
    tools = LazyStandardToolset(
        cwd=tmp_path,
        workspace_root=tmp_path,
        agent_id="workflow-test",
        machine_id="test",
    )
    palace = Palace()
    scheduler = JobScheduler(
        spine=palace,
        settings=SimpleNamespace(machine_id="test", chat_model=model, model_context_tokens=1000),
        loop=loop,
        definitions={},
        toolset_for=lambda _: tools,
    )
    recipe = WorkflowDefinition(
        name="Check",
        prompt="Check",
        folder=str(tmp_path),
        model_policy=f"pinned:{model}",
        budget_usd="0.01",
        memory_scope="none",
        exit_condition="true",
    )
    try:
        await asyncio.wait_for(
            scheduler._execute(
                {"run_id": generate_ulid(), "thread_id": thread_id},
                recipe,
            ),
            timeout=10,
        )
        assert palace.finished == [
            {
                "machine_id": "test",
                "state": "completed",
                "verdict": "Exit check passed.",
            }
        ]
    finally:
        await loop.close()
        await tools.close()
