"""The pydantic-ai runtime adapter for the framework-neutral run loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from pydantic_ai import UsageLimitExceeded, capture_run_messages
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from harness.agent import HarnessAgent, RememberResult
from harness.commands import remember_command_text
from harness.envelope import StopReason
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.tools_memory import MemoryToolContext

type ContextFactory = Callable[[str], MemoryToolContext]

_INTERRUPTED_TOOL_CONTENT = "Tool execution interrupted by run cancellation."


class PydanticAITurnRunner:
    """Stream one bounded HarnessAgent turn into the daemon's owned protocol."""

    def __init__(self, agent: HarnessAgent, context_factory: ContextFactory) -> None:
        self._agent = agent
        self._context_factory = context_factory

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        system_instructions: str | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome:
        """Execute a turn and convert every terminal path to a stable outcome."""

        prior_history = tuple(message_history)
        captured: list[ModelMessage] = []
        run_usage = RunUsage()
        bridge = _EventBridge(emit)
        is_remember = remember_command_text(prompt) is not None

        try:
            context = replace(
                self._context_factory(thread_id),
                excluded_memory_ids=frozenset(excluded_memory_ids),
            )
            if is_remember:
                with capture_run_messages() as captured:
                    dispatched = await self._agent.dispatch(
                        prompt,
                        context=context,
                        usage=run_usage,
                        raise_model_errors=True,
                    )
                if not isinstance(dispatched, RememberResult):  # pragma: no cover - seam guard
                    raise TypeError("/remember dispatch returned ordinary chat")
                await emit.text(dispatched.message)
                usage = _failure_usage(run_usage, captured, ())
                await bridge.publish_usage(usage)
                return TurnOutcome(StopReason("end_turn"), prior_history, usage)

            with capture_run_messages() as captured:
                result = await self._agent.chat_agent.run(
                    prompt,
                    deps=context,
                    instructions=system_instructions,
                    message_history=cast(Sequence[ModelMessage], message_history),
                    usage_limits=self._agent.usage_limits,
                    usage=run_usage,
                    event_stream_handler=bridge.handle,
                )
            if not isinstance(result.output, str):
                raise TypeError("chat agent returned a non-text output")
            usage = _usage_snapshot(result.usage)
            await bridge.publish_usage(usage)
            return TurnOutcome(
                StopReason("end_turn"),
                tuple(result.all_messages()),
                usage,
            )
        except asyncio.CancelledError:
            usage = _failure_usage(run_usage, captured, prior_history)
            await bridge.publish_usage(usage)
            history = prior_history if is_remember else _captured_history(prior_history, captured)
            return TurnOutcome(
                StopReason("cancelled"),
                _repair_cancelled_tool_calls(history),
                usage,
            )
        except UsageLimitExceeded:
            usage = _failure_usage(run_usage, captured, prior_history)
            await bridge.publish_usage(usage)
            return TurnOutcome(
                StopReason("budget_exceeded"),
                _captured_history(prior_history, captured),
                usage,
            )
        except Exception:
            usage = _failure_usage(run_usage, captured, prior_history)
            await bridge.publish_usage(usage)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                history = (
                    prior_history if is_remember else _captured_history(prior_history, captured)
                )
                return TurnOutcome(
                    StopReason("cancelled"),
                    _repair_cancelled_tool_calls(history),
                    usage,
                )
            return TurnOutcome(
                StopReason("error"),
                _captured_history(prior_history, captured),
                usage,
            )


class _EventBridge:
    """Translate pydantic-ai events and mutable usage into owned run events."""

    def __init__(self, emit: RunEmitter) -> None:
        self._emit = emit
        self._last_usage = UsageSnapshot()

    async def handle(
        self,
        context: Any,
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        async for event in events:
            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                if event.part.content:
                    await self._emit.text(event.part.content)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                if event.delta.content_delta:
                    await self._emit.text(event.delta.content_delta)
            elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
                if event.part.content:
                    await self._emit.thinking(event.part.content)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
                if event.delta.content_delta:
                    await self._emit.thinking(event.delta.content_delta)
            else:
                await self._emit.event(_json_event(event))
            await self.publish_usage(_usage_snapshot(context.usage))
        await self.publish_usage(_usage_snapshot(context.usage))

    async def publish_usage(self, usage: UsageSnapshot) -> None:
        if usage == self._last_usage:
            return
        if (
            usage.requests < self._last_usage.requests
            or usage.input_tokens < self._last_usage.input_tokens
            or usage.output_tokens < self._last_usage.output_tokens
        ):  # pragma: no cover - pydantic-ai promises cumulative usage
            raise ValueError("pydantic-ai usage decreased during a run")
        self._last_usage = usage
        await self._emit.usage(usage)


def _json_event(event: AgentStreamEvent) -> Mapping[str, object]:
    value = to_jsonable_python(event)
    if not isinstance(value, dict):  # pragma: no cover - all AgentStreamEvent values are objects
        raise TypeError("pydantic-ai emitted a non-object event")
    return cast(dict[str, object], value)


def _usage_snapshot(usage: RunUsage) -> UsageSnapshot:
    return UsageSnapshot(
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )


def _failure_usage(
    usage: RunUsage,
    captured: Sequence[ModelMessage],
    prior_history: Sequence[object],
) -> UsageSnapshot:
    """Retain partial response usage that may not have reached RunUsage on unwind."""

    new_messages = _new_captured_messages(captured, prior_history)
    responses = [message for message in new_messages if isinstance(message, ModelResponse)]
    captured_usage = UsageSnapshot(
        requests=len(responses),
        input_tokens=sum(message.usage.input_tokens for message in responses),
        output_tokens=sum(message.usage.output_tokens for message in responses),
    )
    current = _usage_snapshot(usage)
    return UsageSnapshot(
        requests=max(current.requests, captured_usage.requests),
        input_tokens=max(current.input_tokens, captured_usage.input_tokens),
        output_tokens=max(current.output_tokens, captured_usage.output_tokens),
    )


def _new_captured_messages(
    captured: Sequence[ModelMessage], prior_history: Sequence[object]
) -> Sequence[ModelMessage]:
    if len(captured) >= len(prior_history) and all(
        captured[index] is old or captured[index] == old for index, old in enumerate(prior_history)
    ):
        return captured[len(prior_history) :]
    return captured


def _captured_history(
    prior_history: Sequence[object], captured: Sequence[ModelMessage]
) -> tuple[object, ...]:
    if not captured:
        return tuple(prior_history)
    if len(captured) >= len(prior_history) and all(
        captured[index] is old or captured[index] == old for index, old in enumerate(prior_history)
    ):
        return tuple(captured)
    return (*prior_history, *captured)


def _repair_cancelled_tool_calls(history: Sequence[object]) -> tuple[object, ...]:
    """Append interrupted returns for every regular call left unanswered."""

    open_calls: dict[str, tuple[ToolCallPart, ModelResponse]] = {}
    shadowed: list[tuple[ToolCallPart, ModelResponse]] = []
    for message in history:
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    if previous := open_calls.get(part.tool_call_id):
                        shadowed.append(previous)
                    open_calls[part.tool_call_id] = (part, message)
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart) or (
                    isinstance(part, RetryPromptPart) and part.tool_name is not None
                ):
                    open_calls.pop(part.tool_call_id, None)

    unanswered = [*shadowed, *open_calls.values()]
    if not unanswered:
        return tuple(history)

    returns = [
        ToolReturnPart(
            tool_name=call.tool_name,
            content=_INTERRUPTED_TOOL_CONTENT,
            tool_call_id=call.tool_call_id,
            metadata={"harness_state": "cancelled"},
            timestamp=response.timestamp,
            outcome="interrupted",
        )
        for call, response in unanswered
    ]
    last_response = unanswered[-1][1]
    return (
        *history,
        ModelRequest(
            returns,
            run_id=last_response.run_id,
            conversation_id=last_response.conversation_id,
        ),
    )
