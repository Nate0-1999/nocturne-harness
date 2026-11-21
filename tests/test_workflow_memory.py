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


@pytest.mark.asyncio
async def test_workflow_without_a_memory_scope_asks_the_palace_nothing():
    """SPEC C.6 / M3SJ: scope none runs twice with no prepare and no gate. The scoped run
    meets the real Palace in tests/contract (A-088); a mock here once hid F138.
    """
    spine, delegate, emitter = RecordingSpine(), RecordingDelegate(), RecordingEmitter()
    runner = MemoryGateTurnRunner(
        delegate, spine, context_factory(spine), model_context_tokens=1000
    )
    for _ in range(2):
        await runner.run_workflow(
            memory_scope="none",
            thread_id=THREAD_ID,
            prompt="check",
            message_history=(),
            emit=emitter,
        )
    assert len(delegate.calls) == 2
    assert not emitter.gate_values and not spine.commit_requests
    assert not spine.prepare_requests


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
