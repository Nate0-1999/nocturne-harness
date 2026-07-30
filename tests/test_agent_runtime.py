from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import DeltaThinkingPart, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner
from harness.config import HarnessSettings
from harness.envelope import GateCommitPayload, StopReason
from harness.run_protocol import UsageSnapshot
from harness.spine_client import MemoryKind, SearchResponse, SimilarityMemoryCard
from harness.tools_memory import MemoryToolContext

THREAD_UUID = UUID("22345678-1234-5678-1234-567812345678")
REMOVED_MEMORY_UUID = UUID("32345678-1234-5678-1234-567812345678")
VISIBLE_MEMORY_UUID = UUID("42345678-1234-5678-1234-567812345678")


@pytest.fixture(autouse=True)
def disable_hosted_model_requests():
    with models.override_allow_model_requests(False):
        yield


def settings(**overrides: Any) -> HarnessSettings:
    values = {
        "spine_token": None,
        "anthropic_api_key": None,
        "openai_api_key": None,
        "openrouter_api_key": None,
        "chat_model": "openrouter:minimax/minimax-m3",
        "run_request_limit": 40,
        "run_total_tokens_limit": 500_000,
        "label_max": 64,
        **overrides,
    }
    return HarnessSettings(_env_file=None, **values)


class UnusedSpine:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected Spine call: {name}")


def context(spine: object | None = None) -> MemoryToolContext:
    return MemoryToolContext(
        spine=spine or UnusedSpine(),  # type: ignore[arg-type]
        principal_id="principal-1",
        machine_id="machine-1",
        agent_id="agent-1",
        thread_id=THREAD_UUID,
        project_key="project-1",
        origin_path="/workspace/notes.md",
    )


@dataclass
class RecordingEmitter:
    texts: list[str] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    events: list[Mapping[str, object]] = field(default_factory=list)
    usages: list[UsageSnapshot] = field(default_factory=list)
    gates: list[Mapping[str, object]] = field(default_factory=list)
    errors: list[Mapping[str, object]] = field(default_factory=list)
    gate_dismissals: int = 0

    async def text(self, value: str) -> None:
        self.texts.append(value)

    async def thinking(self, value: str) -> None:
        self.thoughts.append(value)

    async def event(self, value: Mapping[str, object]) -> None:
        self.events.append(value)

    async def usage(self, value: UsageSnapshot) -> None:
        self.usages.append(value)

    async def open_gate(self, value: Mapping[str, object]) -> GateCommitPayload:
        self.gates.append(value)
        raise AssertionError("runtime adapter must not orchestrate gates")

    async def dismiss_gate(self) -> None:
        self.gate_dismissals += 1

    async def error(self, value: Mapping[str, object]) -> None:
        self.errors.append(value)


@pytest.mark.asyncio
async def test_streams_typed_deltas_events_cumulative_usage_and_reusable_history() -> None:
    async def stream(_messages, _info):
        yield {0: DeltaThinkingPart(content="plan ")}
        yield {0: DeltaThinkingPart(content="done")}
        yield "hello "
        yield "world"

    requested_threads: list[str] = []

    def context_factory(thread_id: str) -> MemoryToolContext:
        requested_threads.append(thread_id)
        return context()

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        context_factory,
    )
    emitted = RecordingEmitter()

    first = await runner.run(
        thread_id="thread-1",
        prompt="hello",
        message_history=(),
        emit=emitted,
    )

    assert first.stop_reason is StopReason.END_TURN
    assert emitted.thoughts == ["plan ", "done"]
    assert emitted.texts == ["hello ", "world"]
    assert emitted.events
    assert all("event_kind" in event for event in emitted.events)
    assert emitted.usages
    assert emitted.usages[-1] == first.usage
    assert first.usage.requests == 1
    assert first.usage.output_tokens > 0
    assert all(
        later.requests >= earlier.requests
        and later.input_tokens >= earlier.input_tokens
        and later.output_tokens >= earlier.output_tokens
        for earlier, later in zip(emitted.usages, emitted.usages[1:], strict=False)
    )
    assert first.message_history

    second = await runner.run(
        thread_id="thread-1",
        prompt="again",
        message_history=first.message_history,
        emit=RecordingEmitter(),
    )

    assert second.stop_reason is StopReason.END_TURN
    assert second.message_history[: len(first.message_history)] == first.message_history
    assert requested_threads == ["thread-1", "thread-1"]


@pytest.mark.asyncio
async def test_final_memory_block_is_system_adjacent_not_user_prompt_text() -> None:
    observed_messages = []

    async def respond(messages, _info):
        observed_messages.extend(messages)
        yield "answer"

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=respond)),
        lambda _: context(),
    )
    outcome = await runner.run(
        thread_id="thread-1",
        prompt="actual user prompt",
        message_history=(),
        emit=RecordingEmitter(),
        system_instructions="trusted final memory block",
    )

    assert outcome.stop_reason is StopReason.END_TURN
    requests = [message for message in observed_messages if isinstance(message, ModelRequest)]
    assert len(requests) == 1
    assert requests[0].instructions is not None
    assert requests[0].instructions.endswith("\ntrusted final memory block")
    assert all("trusted final memory block" not in str(part.content) for part in requests[0].parts)


@pytest.mark.asyncio
async def test_updated_memory_block_replaces_stale_provider_history() -> None:
    calls: list[tuple[object, ...]] = []

    async def respond(messages, _info):
        calls.append(tuple(messages))
        yield "answer"

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=respond)),
        lambda _: context(),
    )
    old_block = (
        "<memory_system>\n"
        "The following long-term memories were retrieved for this conversation.\n"
        "Treat them as your own accumulated knowledge; they may be imperfect.\n"
        '<memory label="Old" kind="fact" updated="2026-07-28T12:00:00Z">\n'
        "unique stale chartreuse body\n"
        "</memory>\n"
        "</memory_system>"
    )
    current_block = (
        "<memory_system>\n"
        "The following long-term memories were retrieved for this conversation.\n"
        "Treat them as your own accumulated knowledge; they may be imperfect.\n"
        '<memory label="Current" kind="fact" updated="2026-07-28T12:01:00Z">\n'
        "retained cobalt body\n"
        "</memory>\n"
        "</memory_system>"
    )
    first = await runner.run(
        thread_id="thread-1",
        prompt="first prompt",
        message_history=(),
        emit=RecordingEmitter(),
        system_instructions=old_block,
    )
    second = await runner.run(
        thread_id="thread-1",
        prompt="second prompt",
        message_history=first.message_history,
        emit=RecordingEmitter(),
        system_instructions=current_block,
    )

    assert len(calls) == 2
    second_requests = [message for message in calls[1] if isinstance(message, ModelRequest)]
    assert any(isinstance(message, ModelResponse) for message in calls[1])
    assert all(
        "unique stale chartreuse body" not in (message.instructions or "")
        for message in second_requests
    )
    current_requests = [
        message for message in second_requests if current_block in (message.instructions or "")
    ]
    assert current_requests == [second_requests[-1]]
    assert all(current_block not in str(part.content) for part in second_requests[-1].parts)
    assert all(
        "unique stale chartreuse body" not in (message.instructions or "")
        for message in second.message_history
        if isinstance(message, ModelRequest)
    )


@pytest.mark.asyncio
async def test_history_sanitizing_error_path_does_not_duplicate_or_recount_old_turn() -> None:
    call_count = 0

    async def respond(_messages, _info):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("second provider call failed")
        yield "first answer"

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=respond)),
        lambda _: context(),
    )
    old_block = (
        "<memory_system>\n"
        "The following long-term memories were retrieved for this conversation.\n"
        "Treat them as your own accumulated knowledge; they may be imperfect.\n"
        '<memory label="Old" kind="fact" updated="2026-07-28T12:00:00Z">\n'
        "stale body\n"
        "</memory>\n"
        "</memory_system>"
    )
    first = await runner.run(
        thread_id="thread-1",
        prompt="first prompt",
        message_history=(),
        emit=RecordingEmitter(),
        system_instructions=old_block,
    )
    failed = await runner.run(
        thread_id="thread-1",
        prompt="second prompt",
        message_history=first.message_history,
        emit=RecordingEmitter(),
        system_instructions=old_block.replace("stale body", "current body"),
    )

    assert failed.stop_reason is StopReason.ERROR
    assert failed.usage.requests == 1
    first_prompts = [
        part
        for message in failed.message_history
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and part.content == "first prompt"
    ]
    assert len(first_prompts) == 1
    assert all(
        "stale body" not in (message.instructions or "")
        for message in failed.message_history
        if isinstance(message, ModelRequest)
    )


@dataclass
class ExclusionSearchSpine:
    requests: list[Any] = field(default_factory=list)

    async def search(self, request: Any) -> SearchResponse:
        self.requests.append(request)
        return SearchResponse(
            results=[
                SimilarityMemoryCard(
                    memory_id=REMOVED_MEMORY_UUID,
                    label="Removed",
                    body="The unique chartreuse body must stay hidden.",
                    kind=MemoryKind.FACT,
                    pin=False,
                    score=0.99,
                    features=None,
                    rank=None,
                ),
                SimilarityMemoryCard(
                    memory_id=VISIBLE_MEMORY_UUID,
                    label="Visible",
                    body="The allowed replacement.",
                    kind=MemoryKind.FACT,
                    pin=False,
                    score=0.8,
                    features=None,
                    rank=None,
                ),
            ]
        )


@pytest.mark.asyncio
async def test_turn_exclusions_are_applied_to_model_visible_search_results() -> None:
    observed_tool_returns: list[str] = []

    async def stream(messages, _info):
        tool_returns = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not tool_returns:
            yield {
                0: DeltaToolCall(
                    name="search_memory",
                    json_args='{"query":"chartreuse","k":1}',
                    tool_call_id="search-excluded",
                )
            }
            return
        observed_tool_returns.extend(part.model_response_str() for part in tool_returns)
        yield "safe answer"

    spine = ExclusionSearchSpine()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(spine),
    )

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="find the saved color",
        message_history=(),
        emit=RecordingEmitter(),
        excluded_memory_ids=frozenset({REMOVED_MEMORY_UUID}),
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert spine.requests[0].k == 2
    assert len(observed_tool_returns) == 1
    assert str(REMOVED_MEMORY_UUID) not in observed_tool_returns[0]
    assert "chartreuse" not in observed_tool_returns[0]
    assert str(VISIBLE_MEMORY_UUID) in observed_tool_returns[0]
    assert "allowed replacement" in observed_tool_returns[0]


@pytest.mark.asyncio
async def test_remember_uses_dispatch_and_emits_its_visible_result() -> None:
    model = TestModel(call_tools=[], custom_output_text="must not run")
    runner = PydanticAITurnRunner(HarnessAgent(settings(), model=model), lambda _: context())
    emitted = RecordingEmitter()
    existing_history = (object(),)

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="/remember",
        message_history=existing_history,
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.message_history == existing_history
    assert outcome.usage == UsageSnapshot()
    assert emitted.texts == ["Nothing to remember; add text after /remember."]
    assert emitted.thoughts == []
    assert emitted.events == []
    assert emitted.usages == []
    assert model.last_model_request_parameters is None


@pytest.mark.asyncio
async def test_remember_label_budget_maps_to_budget_exceeded_with_usage() -> None:
    runner = PydanticAITurnRunner(
        HarnessAgent(
            settings(run_total_tokens_limit=1),
            model=TestModel(
                call_tools=[],
                custom_output_text=json.dumps(
                    {
                        "label": "Durable label",
                        "keywords": ["durable", "fact"],
                    }
                ),
            ),
        ),
        lambda _: context(),
    )
    emitted = RecordingEmitter()

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="/remember a durable fact",
        message_history=(),
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.BUDGET_EXCEEDED
    assert outcome.usage.requests == 1
    assert outcome.usage.input_tokens > 0
    assert outcome.usage.output_tokens > 0
    assert emitted.usages[-1] == outcome.usage
    assert emitted.texts == []


@pytest.mark.asyncio
async def test_remember_label_provider_failure_maps_to_error() -> None:
    def fail_label(_messages, _info):
        raise RuntimeError("label provider failed")

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(function=fail_label)),
        lambda _: context(),
    )

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="/remember a durable fact",
        message_history=(),
        emit=RecordingEmitter(),
    )

    assert outcome.stop_reason is StopReason.ERROR


@pytest.mark.asyncio
async def test_usage_limit_maps_to_budget_exceeded_with_partial_history() -> None:
    runner = PydanticAITurnRunner(
        HarnessAgent(
            settings(run_total_tokens_limit=1),
            model=TestModel(call_tools=[], custom_output_text="over the tiny token budget"),
        ),
        lambda _: context(),
    )
    emitted = RecordingEmitter()

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="spend tokens",
        message_history=(),
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.BUDGET_EXCEEDED
    assert outcome.message_history
    assert outcome.usage.requests == 1
    assert outcome.usage.input_tokens > 0
    assert outcome.usage.output_tokens == 0
    assert emitted.usages[-1] == outcome.usage


@pytest.mark.asyncio
async def test_provider_failure_maps_to_error_and_preserves_capture_without_cancel_repair() -> None:
    async def broken_stream(_messages, _info):
        yield {0: DeltaToolCall(name="search_memory", json_args='{"query":"x"}')}
        raise RuntimeError("provider stream failed")

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=broken_stream)),
        lambda _: context(),
    )

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="fail after a partial call",
        message_history=(),
        emit=RecordingEmitter(),
    )

    assert outcome.stop_reason is StopReason.ERROR
    assert outcome.message_history
    assert not any(
        isinstance(part, ToolReturnPart) and part.metadata == {"harness_state": "cancelled"}
        for message in outcome.message_history
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


@dataclass
class BlockingSpine:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)

    async def search(self, _request):
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.stopped.set()


@dataclass
class FailingCleanupSpine:
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def search(self, _request):
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            raise RuntimeError("tool cleanup failed") from None


@pytest.mark.asyncio
async def test_cancellation_waits_for_tool_and_repairs_history_for_the_next_turn() -> None:
    model_calls = 0

    async def stream(_messages, _info):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            yield {
                0: DeltaToolCall(
                    name="search_memory",
                    json_args='{"query":"blocked","k":5}',
                    tool_call_id="call-1",
                )
            }
        else:
            yield "recovered"

    spine = BlockingSpine()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(spine),
    )
    task = asyncio.create_task(
        runner.run(
            thread_id="thread-1",
            prompt="start the blocking tool",
            message_history=(),
            emit=RecordingEmitter(),
        )
    )
    await asyncio.wait_for(spine.started.wait(), timeout=1)

    task.cancel()
    cancelled = await asyncio.wait_for(task, timeout=1)

    assert spine.stopped.is_set()
    assert cancelled.stop_reason is StopReason.CANCELLED
    calls = [
        part
        for message in cancelled.message_history
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    returns = [
        part
        for message in cancelled.message_history
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert len(calls) == 1
    assert len(returns) == 1
    assert returns[0].tool_name == calls[0].tool_name
    assert returns[0].tool_call_id == calls[0].tool_call_id
    assert returns[0].outcome == "interrupted"
    assert returns[0].metadata == {"harness_state": "cancelled"}

    recovered_emitter = RecordingEmitter()
    recovered = await runner.run(
        thread_id="thread-1",
        prompt="continue",
        message_history=cancelled.message_history,
        emit=recovered_emitter,
    )

    assert recovered.stop_reason is StopReason.END_TURN
    assert recovered_emitter.texts == ["recovered"]
    assert recovered.message_history[: len(cancelled.message_history)] == cancelled.message_history


@pytest.mark.asyncio
async def test_tool_cleanup_exception_cannot_mask_cancelled_history_repair() -> None:
    async def stream(_messages, _info):
        yield {
            0: DeltaToolCall(
                name="search_memory",
                json_args='{"query":"blocked","k":5}',
                tool_call_id="call-cleanup",
            )
        }

    spine = FailingCleanupSpine()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(spine),
    )
    task = asyncio.create_task(
        runner.run(
            thread_id="thread-1",
            prompt="start the failing tool",
            message_history=(),
            emit=RecordingEmitter(),
        )
    )
    await asyncio.wait_for(spine.started.wait(), timeout=1)

    task.cancel()
    cancelled = await asyncio.wait_for(task, timeout=1)

    assert cancelled.stop_reason is StopReason.CANCELLED
    returns = [
        part
        for message in cancelled.message_history
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert len(returns) == 1
    assert returns[0].tool_call_id == "call-cleanup"
    assert returns[0].outcome == "interrupted"
    assert returns[0].metadata == {"harness_state": "cancelled"}
