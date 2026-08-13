from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai import ModelHTTPError, models
from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import DeltaThinkingPart, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage, RunUsage

from harness.agent import REMEMBER_SPLIT_GUIDANCE, HarnessAgent, RememberResult
from harness.agent_runtime import (
    PydanticAITurnRunner,
    _cacheable_prefix_tokens,
    _usage_snapshot,
)
from harness.config import HarnessSettings
from harness.context_window import ContextWindowTracker
from harness.envelope import GateCommitPayload, StopReason
from harness.model_policy import ThreadModelResolution
from harness.receipt_queue import SpendReceiptQueue
from harness.run_protocol import UsageSnapshot
from harness.spine_client import (
    MemoryKind,
    MemorySplitRequest,
    MemorySplitResponse,
    SearchResponse,
    SimilarityMemoryCard,
    SpendEventsRequest,
    SpendEventsResponse,
)
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
    run_id: str = "01K1M2A0000000000000000001"
    prompt_id: str = "01K1M2A0000000000000000002"
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


@dataclass
class RecordingSpend:
    requests: list[SpendEventsRequest] = field(default_factory=list)

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        self.requests.append(request)
        return SpendEventsResponse(accepted=len(request.events))


class FailingSpend:
    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        del request
        raise RuntimeError("ledger unavailable")


@pytest.mark.asyncio
async def test_successful_model_response_is_receipted_before_turn_returns() -> None:
    """A successful response exposes final text for A-036 after A-027 receipts."""

    async def stream(_messages: object, _info: object):
        yield "answer"

    spend = RecordingSpend()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(),
        spend,
    )

    outcome = await runner.run(
        thread_id=str(THREAD_UUID),
        prompt="hello",
        message_history=(),
        emit=RecordingEmitter(),
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.assistant_text == "answer"
    assert len(spend.requests) == 1
    request = spend.requests[0]
    assert "output" in {event.quantity_type for event in request.events}
    assert {event.purpose for event in request.events} == {"building"}
    assert {event.thread_id for event in request.events} == {THREAD_UUID}


@pytest.mark.asyncio
async def test_image_turn_sends_text_then_exact_binary_content_to_pydantic_ai() -> None:
    """A-052 is defended by verifying the runtime sends one text part before exact image bytes;
    this prevents adapter coercion, URL substitution, or silent attachment loss.
    """
    observed: list[object] = []

    async def stream(messages, _info):
        request = messages[-1]
        assert isinstance(request, ModelRequest)
        part = request.parts[-1]
        assert isinstance(part, UserPromptPart)
        observed.extend(part.content)
        yield "visual answer"

    image = BinaryContent(data=b"\x89PNG\r\n\x1a\nimage", media_type="image/png")
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(),
    )

    outcome = await runner.run(
        thread_id=str(THREAD_UUID),
        prompt="Inspect this",
        image=image,
        message_history=(),
        emit=RecordingEmitter(),
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert observed == ["Inspect this", image]


@pytest.mark.asyncio
async def test_dead_ledger_queues_estimate_and_never_retracts_answer(tmp_path: Path) -> None:
    """SPEC B.6 rule 11 requires a dead ledger never to brick or retract a completed turn."""

    async def stream(_messages: object, _info: object):
        yield "answer"

    emitted = RecordingEmitter()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(),
        FailingSpend(),
        receipt_queue=SpendReceiptQueue(tmp_path / "receipt-queue"),
    )

    outcome = await runner.run(
        thread_id=str(THREAD_UUID),
        prompt="hello",
        message_history=(),
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.assistant_text == "answer"
    assert emitted.errors[0]["code"] == "spend_pending"
    assert "Answer delivered" in str(emitted.errors[0]["message"])


@pytest.mark.asyncio
async def test_streams_typed_deltas_events_cumulative_usage_and_reusable_history() -> None:
    """ADR-013 is defended by verifying that streams typed deltas events cumulative usage and
    reusable history; this prevents drift in the streaming model runtime and history
    boundary.
    """

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
async def test_openrouter_route_settings_are_fresh_sticky_and_price_sorted() -> None:
    """ADR-013 is defended by verifying that openrouter route settings are fresh sticky and
    price sorted; this prevents drift in the streaming model runtime and history boundary.
    """
    observed_settings: list[dict[str, Any] | None] = []

    async def stream(_messages, info):
        observed_settings.append(info.model_settings)
        yield "answer"

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(),
    )
    resolution = ThreadModelResolution(
        model="openrouter:minimax/minimax-m3",
        context_tokens=1_000_000,
        policy="elbow",
        price_sorted=True,
    )
    for prompt in ("first", "second"):
        await runner.run(
            thread_id="thread-sticky",
            prompt=prompt,
            message_history=(),
            emit=RecordingEmitter(),
            model_resolution=resolution,
        )

    assert observed_settings == [
        {
            "extra_body": {"session_id": "thread-sticky"},
            "openrouter_usage": {"include": True},
            "openrouter_provider": {"sort": "price"},
        },
        {
            "extra_body": {"session_id": "thread-sticky"},
            "openrouter_usage": {"include": True},
            "openrouter_provider": {"sort": "price"},
        },
    ]
    assert observed_settings[0] is not observed_settings[1]


@pytest.mark.asyncio
async def test_resolution_epochs_break_and_then_repin_openrouter_session_stickiness() -> None:
    """ADR-013 is defended by verifying that resolution epochs break and then repin openrouter
    session stickiness; this prevents drift in the streaming model runtime and history
    boundary.
    """
    observed_settings: list[dict[str, Any] | None] = []

    async def stream(_messages, info):
        observed_settings.append(info.model_settings)
        yield "answer"

    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(),
    )
    for epoch in (0, 1, 2):
        await runner.run(
            thread_id="thread-sticky",
            prompt=f"epoch {epoch}",
            message_history=(),
            emit=RecordingEmitter(),
            model_resolution=ThreadModelResolution(
                model="openrouter:minimax/minimax-m3",
                context_tokens=1_000_000,
                policy="human_command" if epoch else "pinned:openrouter:minimax/minimax-m3",
                stickiness_epoch=epoch,
            ),
        )

    assert [settings["extra_body"] for settings in observed_settings if settings is not None] == [
        {"session_id": "thread-sticky"},
        {"session_id": "thread-sticky:epoch:1"},
        {"session_id": "thread-sticky:epoch:2"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "price_sorted", "expected"),
    [
        (
            "openrouter:minimax/minimax-m3",
            False,
            {
                "extra_body": {"session_id": "thread-1"},
                "openrouter_usage": {"include": True},
            },
        ),
        ("anthropic:claude-sonnet-4-6", False, None),
    ],
)
async def test_pinned_routes_only_receive_provider_settings_they_can_use(
    model: str,
    price_sorted: bool,
    expected: dict[str, Any] | None,
) -> None:
    """ADR-013 is defended by verifying that pinned routes only receive provider settings they
    can use; this prevents drift in the streaming model runtime and history boundary.
    """
    observed: list[dict[str, Any] | None] = []

    async def stream(_messages, info):
        observed.append(info.model_settings)
        yield "answer"

    runner = PydanticAITurnRunner(
        HarnessAgent(
            settings(chat_model=model),
            model=FunctionModel(stream_function=stream),
        ),
        lambda _: context(),
    )
    await runner.run(
        thread_id="thread-1",
        prompt="hello",
        message_history=(),
        emit=RecordingEmitter(),
        model_resolution=ThreadModelResolution(
            model=model,
            context_tokens=100_000,
            policy=f"pinned:{model}",
            price_sorted=price_sorted,
        ),
    )

    assert observed == [expected]


def test_provider_cache_usage_is_retained_by_the_existing_usage_adapter() -> None:
    """ADR-013 is defended by verifying that provider cache usage is retained by the existing
    usage adapter; this prevents drift in the streaming model runtime and history boundary.
    """
    assert _usage_snapshot(
        RunUsage(
            requests=1,
            input_tokens=20,
            output_tokens=4,
            cache_read_tokens=12,
            cache_write_tokens=3,
        )
    ) == UsageSnapshot(
        requests=1,
        input_tokens=20,
        output_tokens=4,
        cache_read_tokens=12,
        cache_write_tokens=3,
    )


def test_cacheable_prefix_uses_only_the_terminal_provider_response() -> None:
    """ADR-013 is defended by verifying that cacheable prefix uses only the terminal provider
    response; this prevents drift in the streaming model runtime and history boundary.
    """
    messages = (
        ModelResponse(
            parts=[TextPart("tool request")],
            usage=RunUsage(input_tokens=100, output_tokens=10),
        ),
        ModelResponse(
            parts=[TextPart("final")],
            usage=RunUsage(input_tokens=140, output_tokens=7),
        ),
    )

    assert _cacheable_prefix_tokens(messages) == 147


@pytest.mark.asyncio
async def test_remember_dispatch_receives_the_same_thread_model_and_routing_settings() -> None:
    """ADR-013 is defended by verifying that remember dispatch receives the same thread model
    and routing settings; this prevents drift in the streaming model runtime and history
    boundary.
    """
    marker = FunctionModel(function=lambda _messages, _info: ModelResponse(parts=[TextPart("x")]))

    class RememberSpyAgent:
        def __init__(self) -> None:
            self.selected_names: list[str | None] = []
            self.dispatch_calls: list[dict[str, Any]] = []

        def model_for(self, name: str | None):
            self.selected_names.append(name)
            return marker

        async def dispatch(self, _prompt: str, **kwargs: Any) -> RememberResult:
            self.dispatch_calls.append(kwargs)
            return RememberResult(True, "remembered")

    spy = RememberSpyAgent()
    resolution = ThreadModelResolution(
        model="openrouter:vendor/selected",
        context_tokens=131_072,
        policy="max",
        price_sorted=True,
    )
    emitted = RecordingEmitter()
    runner = PydanticAITurnRunner(spy, lambda _: context())  # type: ignore[arg-type]

    outcome = await runner.run(
        thread_id="thread-remember",
        prompt="/remember durable fact",
        message_history=(),
        emit=emitted,
        model_resolution=resolution,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert emitted.texts == ["remembered"]
    assert spy.selected_names == [resolution.model]
    assert len(spy.dispatch_calls) == 1
    assert spy.dispatch_calls[0]["model"] is marker
    assert spy.dispatch_calls[0]["model_settings"] == {
        "extra_body": {"session_id": "thread-remember"},
        "openrouter_usage": {"include": True},
        "openrouter_provider": {"sort": "price"},
    }


@pytest.mark.asyncio
async def test_final_memory_block_is_system_adjacent_not_user_prompt_text() -> None:
    """ADR-013 is defended by verifying that final memory block is system adjacent not user
    prompt text; this prevents drift in the streaming model runtime and history boundary.
    """
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
    """ADR-013 is defended by verifying that updated memory block replaces stale provider
    history; this prevents drift in the streaming model runtime and history boundary.
    """
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
    """ADR-013 is defended by verifying that history sanitizing error path does not duplicate
    or recount old turn; this prevents drift in the streaming model runtime and history
    boundary.
    """
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
    """ADR-013 is defended by verifying that turn exclusions are applied to model visible
    search results; this prevents drift in the streaming model runtime and history boundary.
    """
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
    """ADR-013 is defended by verifying that remember uses dispatch and emits its visible
    result; this prevents drift in the streaming model runtime and history boundary.
    """
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
async def test_a049_label_and_split_share_one_two_request_runtime_usage_wall() -> None:
    """F027, A-049, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    Label fallback and semantic split share usage, emit once, and stop at two model requests.
    """
    source_id = UUID("52345678-1234-5678-1234-567812345678")
    child_one_id = UUID("62345678-1234-5678-1234-567812345678")
    child_two_id = UUID("72345678-1234-5678-1234-567812345678")
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)

    def unit(memory_id: UUID, label: str, body: str, status: str) -> dict[str, object]:
        return {
            "memory_id": memory_id,
            "principal_id": "principal-1",
            "label": label,
            "body": body,
            "kind": "fact",
            "keywords": ["fact", "garden"],
            "project_key": None,
            "thread_origin": str(THREAD_UUID),
            "origin_path": "/workspace/notes.md",
            "pin": False,
            "status": status,
            "revision": 1,
            "stats": {},
            "bias": 0.0,
            "embedding_model": "text-embedding-3-small",
            "created_at": now,
            "updated_at": now,
        }

    class SplitSpine:
        def __init__(self) -> None:
            self.requests: list[MemorySplitRequest] = []

        async def create_memory_split(self, request: MemorySplitRequest) -> MemorySplitResponse:
            self.requests.append(request)
            return MemorySplitResponse(
                source=unit(source_id, "Split source", request.source_body, "tombstoned"),
                created=[
                    unit(child_one_id, "First fact", "Fact one.", "active"),
                    unit(child_two_id, "Second fact", "Fact two.", "active"),
                ],
            )

    outputs = [
        {"label": "L" * 65, "keywords": ["fact", "garden"]},
        {
            "safe_to_save": True,
            "candidates": [
                {"label": "First fact", "body": "Fact one.", "keywords": ["fact", "one"]},
                {"label": "Second fact", "body": "Fact two.", "keywords": ["fact", "two"]},
            ],
            "coverage": [
                {
                    "text": "Fact one. ",
                    "classification": "durable",
                    "candidate_index": 0,
                },
                {
                    "text": "Fact two.",
                    "classification": "durable",
                    "candidate_index": 1,
                },
            ],
        },
    ]

    async def respond(_messages, _info) -> ModelResponse:
        return ModelResponse(parts=[TextPart(json.dumps(outputs.pop(0)))])

    spine = SplitSpine()
    emitted = RecordingEmitter()
    spend = RecordingSpend()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(function=respond)),
        lambda _: context(spine),
        spend,
    )

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="/remember Fact one. Fact two.",
        message_history=(),
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.usage.requests == 2
    assert emitted.texts == ["Remembered 2 linked memories: 'First fact', 'Second fact'."]
    assert len(spine.requests) == 1
    assert outputs == []
    assert len(spend.requests) == 1
    receipt_events = spend.requests[0].events
    assert len({event.ref for event in receipt_events}) == 2
    assert {event.memory_id for event in receipt_events} == {source_id}
    assert {event.purpose for event in receipt_events} == {"remember"}


@pytest.mark.asyncio
async def test_a049_invalid_structured_split_guides_instead_of_failing_the_turn() -> None:
    """F027, A-049, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    Malformed model structure is an invalid draft, so it guides with zero writes rather than ERROR.
    """
    outputs = [json.dumps({"label": "L" * 65, "keywords": ["fact", "garden"]}), "not-json"]

    async def respond(_messages, _info) -> ModelResponse:
        return ModelResponse(parts=[TextPart(outputs.pop(0))])

    emitted = RecordingEmitter()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(function=respond)),
        lambda _: context(),
    )

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="/remember Fact one. Fact two.",
        message_history=(),
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.usage.requests == 2
    assert emitted.texts == [REMEMBER_SPLIT_GUIDANCE]
    assert outputs == []


@pytest.mark.asyncio
async def test_f047_split_planner_timeout_ends_once_with_guidance_and_zero_writes() -> None:
    """F047, F039, ADR-022, and SPEC D.2 112 require the over-cap split timeout
    row to end once with no partial save or browser-side terminal fiction.
    """
    cancelled = asyncio.Event()

    async def never_finishes(_messages, _info) -> ModelResponse:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    emitted = RecordingEmitter()
    runner = PydanticAITurnRunner(
        HarnessAgent(
            settings(memory_max_tokens=1, remember_split_timeout_seconds=0.01),
            model=FunctionModel(function=never_finishes),
        ),
        lambda _: context(),
    )

    outcome = await asyncio.wait_for(
        runner.run(
            thread_id="thread-1",
            prompt="/remember Fact one. Fact two. Fact three.",
            message_history=(),
            emit=emitted,
        ),
        timeout=1,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.message_history == ()
    assert emitted.texts == [REMEMBER_SPLIT_GUIDANCE]
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["incomplete", "suspended", "interrupted"])
async def test_f047_nonterminal_split_outcome_uses_the_same_guidance_matrix_row(
    state: str,
) -> None:
    """F047, F039, ADR-022, and SPEC D.2 112 require every nonterminal split
    provider state to converge on the same one-voice, zero-write outcome.
    """
    output = {
        "safe_to_save": True,
        "candidates": [
            {"label": "First fact", "body": "Fact one.", "keywords": ["fact", "one"]},
            {"label": "Second fact", "body": "Fact two.", "keywords": ["fact", "two"]},
        ],
        "coverage": [
            {"text": "Fact one. ", "classification": "durable", "candidate_index": 0},
            {"text": "Fact two.", "classification": "durable", "candidate_index": 1},
        ],
    }

    async def nonterminal(_messages, _info) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart(json.dumps(output))],
            finish_reason="length",
            state=state,  # type: ignore[arg-type]
        )

    emitted = RecordingEmitter()
    outcome = await PydanticAITurnRunner(
        HarnessAgent(
            settings(memory_max_tokens=1),
            model=FunctionModel(function=nonterminal),
        ),
        lambda _: context(),
    ).run(
        thread_id="thread-1",
        prompt="/remember Fact one. Fact two.",
        message_history=(),
        emit=emitted,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert emitted.texts == [REMEMBER_SPLIT_GUIDANCE]


@pytest.mark.asyncio
async def test_a049_split_provider_failure_keeps_runtime_error_semantics() -> None:
    """F027, A-049, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    Provider transport failure is not an invalid draft and must retain the ordinary ERROR outcome.
    """

    def fail_split(_messages, _info):
        raise RuntimeError("split provider failed")

    runner = PydanticAITurnRunner(
        HarnessAgent(
            settings(memory_max_tokens=1),
            model=FunctionModel(function=fail_split),
        ),
        lambda _: context(),
    )

    outcome = await runner.run(
        thread_id="thread-1",
        prompt="/remember Fact one. Fact two.",
        message_history=(),
        emit=RecordingEmitter(),
    )

    assert outcome.stop_reason is StopReason.ERROR


@pytest.mark.asyncio
async def test_remember_label_budget_maps_to_budget_exceeded_with_usage() -> None:
    """ADR-013 is defended by verifying that remember label budget maps to budget exceeded with
    usage; this prevents drift in the streaming model runtime and history boundary.
    """
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
    """ADR-013 is defended by verifying that remember label provider failure maps to error;
    this prevents drift in the streaming model runtime and history boundary.
    """

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
    """ADR-013 is defended by verifying that usage limit maps to budget exceeded with partial
    history; this prevents drift in the streaming model runtime and history boundary.
    """
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
    """ADR-013 is defended by verifying that provider failure maps to error and preserves
    capture without cancel repair; this prevents drift in the streaming model runtime and
    history boundary.
    """

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


@pytest.mark.asyncio
async def test_f034_context_refusal_keeps_class_words_remedy_and_last_measurement() -> None:
    """F034 and v2.52 are defended by verifying that a structured context refusal keeps its
    class, plain archive remedy, and prior measured Context Bars observation without retry.
    """
    calls = 0

    async def stream(_messages, _info):
        nonlocal calls
        calls += 1
        raise ModelHTTPError(
            status_code=400,
            model_name="rekaai/reka-edge",
            body={
                "error": {
                    "code": 400,
                    "message": "Maximum context length is 16384 tokens; this request has 17002.",
                    "metadata": {
                        "error_type": "invalid_request",
                        "provider_code": "context_length_exceeded",
                    },
                }
            },
        )
        yield  # pragma: no cover - keeps this an async generator

    tracker = ContextWindowTracker()
    emitter = RecordingEmitter()
    runner = PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=stream)),
        lambda _: context(),
        context_windows=tracker,
    )
    resolution = ThreadModelResolution(
        model="openrouter:rekaai/reka-edge",
        context_tokens=16_384,
        policy="pinned:rekaai/reka-edge",
    )
    tracker.record(
        thread_id=str(THREAD_UUID),
        captured=[
            ModelResponse(
                parts=[TextPart("ACK")],
                usage=RequestUsage(input_tokens=11_644, output_tokens=8),
            )
        ],
        resolution=resolution,
        memory_block=None,
    )
    measured = tracker.snapshot(str(THREAD_UUID)).aggregate
    assert measured is not None

    refused = await runner.run(
        thread_id=str(THREAD_UUID),
        prompt="cross the real limit",
        message_history=(),
        emit=emitter,
    )

    assert calls == 1
    assert refused.stop_reason is StopReason.ERROR
    assert refused.provider_error is not None
    assert refused.provider_error.classification == "context_length"
    assert refused.provider_error.code == "invalid_request"
    assert refused.provider_error.provider_code == "context_length_exceeded"
    assert refused.provider_error.status_code == 400
    assert refused.provider_error.message == (
        "Maximum context length is 16384 tokens; this request has 17002."
    )
    assert emitter.events[-1]["event_kind"] == "provider_refusal"
    assert emitter.texts[-1].strip() == (
        "This thread has reached rekaai/reka-edge's context limit. "
        "Archive it, then continue in a fresh thread."
    )
    assert tracker.snapshot(str(THREAD_UUID)).aggregate == measured


@pytest.mark.asyncio
async def test_f034_unknown_provider_http_failure_keeps_its_words_without_guessing() -> None:
    """F034 and v2.52 are defended by verifying that an unknown provider HTTP class keeps the
    provider's bounded words and retry-or-switch remedy rather than guessing a context ceiling.
    """

    async def refused(_messages, _info):
        raise ModelHTTPError(
            status_code=429,
            model_name="provider/model",
            body='{"error":{"code":"rate_limited","message":"Capacity is briefly full."}}',
        )
        yield  # pragma: no cover - keeps this an async generator

    emitter = RecordingEmitter()
    outcome = await PydanticAITurnRunner(
        HarnessAgent(settings(), model=FunctionModel(stream_function=refused)),
        lambda _: context(),
    ).run(
        thread_id=str(THREAD_UUID),
        prompt="hello",
        message_history=(),
        emit=emitter,
    )

    assert outcome.stop_reason is StopReason.ERROR
    assert outcome.provider_error is not None
    assert outcome.provider_error.classification == "provider_refusal"
    assert outcome.provider_error.code == "rate_limited"
    assert emitter.texts[-1].strip() == (
        "The provider refused: Capacity is briefly full. Retry this turn or switch models."
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
    """ADR-013 is defended by verifying that cancellation waits for tool and repairs history
    for the next turn; this prevents drift in the streaming model runtime and history
    boundary.
    """
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
    """ADR-013 is defended by verifying that tool cleanup exception cannot mask cancelled
    history repair; this prevents drift in the streaming model runtime and history boundary.
    """

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
