"""PLAN M3SJ: a saved recipe grants scoped automatic preparation, not a human gate."""

from dataclasses import replace

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from test_agent import FakeSpine, context, settings
from test_memory_gate import (
    THREAD_ID,
    RecordingDelegate,
    RecordingEmitter,
    RecordingSpine,
    context_factory,
)

from harness.agent import HarnessAgent
from harness.memory_gate import MemoryGateTurnRunner
from harness.memory_panel import EMPTY_MEMORY_BLOCK


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["workspace", "none"])
async def test_workflow_memory_does_not_wait_for_steering(scope):
    """SPEC C.6 / M3SJ: an explicit saved scope runs twice without invented feedback."""
    spine, delegate, emitter = RecordingSpine(), RecordingDelegate(), RecordingEmitter()
    spine.prepare_response = spine.prepare_response.model_copy(
        update={"final_block": EMPTY_MEMORY_BLOCK}
    )
    runner = MemoryGateTurnRunner(
        delegate, spine, context_factory(spine), model_context_tokens=1000
    )
    for _ in range(2):
        await runner.run_workflow(
            memory_scope=scope,
            thread_id=THREAD_ID,
            prompt="check",
            message_history=(),
            emit=emitter,
        )
    assert len(delegate.calls) == 2
    assert not emitter.gate_values and not spine.commit_requests
    assert len(spine.prepare_requests) == (2 if scope == "workspace" else 0)
    assert all(request.mode == "autonomous" for request in spine.prepare_requests)
    assert all(request.project_key == "project-1" for request in spine.prepare_requests)


@pytest.mark.asyncio
async def test_no_memory_scope_omits_memory_tools():
    """SPEC C.6 / M3SJ: a recipe without memory exposes no memory read or edit tool."""

    def respond(messages, info):
        assert not {tool.name for tool in info.function_tools} & {"search_memory", "edit_memory"}
        return ModelResponse(parts=[TextPart("No memory access.")])

    agent = HarnessAgent(settings(), model=FunctionModel(respond))
    await agent.chat(
        "Check", context=replace(context(FakeSpine(outcome=None)), memory_enabled=False)
    )


@pytest.mark.asyncio
async def test_workflow_refuses_missing_autonomous_context():
    """A-069 / P4.1: missing Palace preparation must not run an uninformed job."""
    spine, delegate, emitter = RecordingSpine(), RecordingDelegate(), RecordingEmitter()
    runner = MemoryGateTurnRunner(
        delegate, spine, context_factory(spine), model_context_tokens=1000
    )
    with pytest.raises(ValueError, match="The Palace did not return an autonomous memory block."):
        await runner.run_workflow(
            memory_scope="workspace",
            thread_id=THREAD_ID,
            prompt="check",
            message_history=(),
            emit=emitter,
        )
    assert not delegate.calls
