"""The pydantic-ai runtime adapter for the framework-neutral run loop."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic_ai import ModelHTTPError, UsageLimitExceeded, capture_run_messages
from pydantic_ai.messages import (
    AgentStreamEvent,
    BinaryContent,
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
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from harness.agent import HarnessAgent, RememberResult
from harness.commands import browser_open_web_command, remember_command_text
from harness.context_window import ContextWindowTracker
from harness.envelope import ProviderErrorPayload, StopReason
from harness.model_policy import ThreadModelResolution
from harness.model_router import model_settings_for
from harness.proposed_response import (
    BLOCK_OPEN,
    PROPOSED_RESPONSE_INSTRUCTION,
    parse_proposed_response_output,
    proposed_response_event,
)
from harness.receipt_queue import SpendReceiptQueue
from harness.run_protocol import DynamicSystemInstructions, RunEmitter, TurnOutcome, UsageSnapshot
from harness.spend import (
    SpendGateway,
    SpendLineage,
    SpendPurpose,
    model_response_receipts,
)
from harness.tools_memory import MemoryToolContext

type ContextFactory = Callable[[str], MemoryToolContext]

_INTERRUPTED_TOOL_CONTENT = "Tool execution interrupted by run cancellation."
_MEMORY_BLOCK_OPEN = "<memory_system>\n"
_MEMORY_BLOCK_CLOSE = "\n</memory_system>"
_MAX_PROVIDER_MESSAGE = 1_000
_CONTEXT_CODES = frozenset(
    {
        "context_length_exceeded",
        "context_window_exceeded",
        "max_context_length_exceeded",
        "prompt_too_long",
        "prompt_is_too_long",
        "too_many_tokens",
    }
)
_CONTEXT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bcontext (?:length|window|limit)\b.*\b(?:exceed|maximum|max|too (?:large|long))",
        r"\b(?:exceed|maximum|max|too (?:large|long))\b.*\bcontext (?:length|window|limit)\b",
        r"\b(?:prompt|input) (?:is )?too long\b",
        r"\btoo many (?:input )?tokens\b",
        r"\btoken limit\b.*\b(?:exceed|maximum|max|reached)",
    )
)


class PydanticAITurnRunner:
    """Stream one bounded HarnessAgent turn into the daemon's owned protocol."""

    def __init__(
        self,
        agent: HarnessAgent,
        context_factory: ContextFactory,
        spend: SpendGateway | None = None,
        receipt_queue: SpendReceiptQueue | None = None,
        context_windows: ContextWindowTracker | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._agent = agent
        self._context_factory = context_factory
        self._spend = spend
        self._receipt_queue = receipt_queue
        self._context_windows = context_windows
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
        system_instructions: str | None = None,
        dynamic_instructions: DynamicSystemInstructions | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
        image: BinaryContent | None = None,
    ) -> TurnOutcome:
        """Execute a turn and convert every terminal path to a stable outcome."""

        prior_history = tuple(message_history)
        captured: list[ModelMessage] = []
        run_usage = RunUsage()
        bridge = _EventBridge(emit)
        is_remember = remember_command_text(prompt) is not None
        is_browser_consent = browser_open_web_command(prompt)
        context: MemoryToolContext | None = None
        remembered_memory_id: UUID | None = None
        selected_model = self._agent.model_for(
            model_resolution.model if model_resolution is not None else None
        )
        model_settings = _model_settings(model_resolution, thread_id)

        try:
            context = replace(
                self._context_factory(thread_id),
                excluded_memory_ids=frozenset(excluded_memory_ids),
            )
            if is_browser_consent:
                message = "Open-web browser access is allowed for this thread."
                if image is not None:
                    message = "Send `/browser allow-web` without an image to cross this wall."
                else:
                    grant = getattr(context.toolset, "grant_open_web", None)
                    if not callable(grant):
                        raise RuntimeError("this owner session has no browser consent boundary")
                    grant(thread_id)
                await emit.text(message)
                return TurnOutcome(
                    StopReason("end_turn"),
                    prior_history,
                    UsageSnapshot(),
                    assistant_text=message,
                    model_visible=False,
                )
            if is_remember:
                with capture_run_messages() as captured:
                    dispatched = await self._agent.dispatch(
                        prompt,
                        context=context,
                        model=selected_model,
                        model_settings=model_settings,
                        usage=run_usage,
                        raise_model_errors=True,
                        captured_messages=captured,
                    )
                if not isinstance(dispatched, RememberResult):  # pragma: no cover - seam guard
                    raise TypeError("/remember dispatch returned ordinary chat")
                remembered_memory_id = dispatched.memory_id
                await emit.text(dispatched.message)
                usage = _failure_usage(run_usage, captured, ())
                await bridge.publish_usage(usage)
                return TurnOutcome(StopReason("end_turn"), prior_history, usage)

            prior_history = _strip_all_proposed_response_blocks(
                _strip_all_memory_blocks(prior_history)
            )
            user_prompt = prompt if image is None else [prompt, image]

            async def current_instructions(_context: object) -> str | None:
                if dynamic_instructions is None:  # pragma: no cover - only passed dynamically
                    return None
                return await dynamic_instructions.render()

            instructions: list[object] = [PROPOSED_RESPONSE_INSTRUCTION]
            if system_instructions is not None:
                instructions.append(system_instructions)
            if dynamic_instructions is not None:
                instructions.append(current_instructions)
            with capture_run_messages() as captured:
                result = await self._agent.chat_agent.run(
                    user_prompt,
                    deps=context,
                    instructions=instructions,
                    message_history=cast(Sequence[ModelMessage], prior_history),
                    model=selected_model,
                    model_settings=model_settings,
                    usage_limits=self._agent.usage_limits,
                    usage=run_usage,
                    event_stream_handler=bridge.handle,
                )
            if not isinstance(result.output, str):
                raise TypeError("chat agent returned a non-text output")
            visible_output = await bridge.finalize(
                result.output,
                run_id=emit.run_id,
                created_at=self._clock(),
            )
            usage = _usage_snapshot(result.usage)
            await bridge.publish_usage(usage)
            history = tuple(result.all_messages())
            return TurnOutcome(
                StopReason("end_turn"),
                history,
                usage,
                cacheable_prefix_tokens=_cacheable_prefix_tokens(history),
                assistant_text=visible_output,
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
        except Exception as exc:
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
            provider_error = _provider_error(exc, selected_model.model_name)
            if provider_error is not None:
                message = _provider_refusal_copy(provider_error)
                await emit.event(
                    {
                        "event_kind": "provider_refusal",
                        **provider_error.model_dump(mode="json", exclude_none=True),
                    }
                )
                await emit.text(f"\n\n{message}")
                return TurnOutcome(
                    StopReason("error"),
                    _captured_history(prior_history, captured),
                    usage,
                    assistant_text=message,
                    provider_error=provider_error,
                )
            return TurnOutcome(
                StopReason("error"),
                _captured_history(prior_history, captured),
                usage,
            )
        finally:
            if self._context_windows is not None and not is_remember:
                self._context_windows.record(
                    thread_id=thread_id,
                    captured=captured,
                    resolution=model_resolution,
                    memory_block=(
                        dynamic_instructions.memory_block
                        if dynamic_instructions is not None
                        else system_instructions
                    ),
                    workspace_block=(
                        dynamic_instructions.workspace_block
                        if dynamic_instructions is not None
                        else None
                    ),
                    memory_allocation=(
                        getattr(dynamic_instructions, "memory_allocation", None)
                        if dynamic_instructions is not None
                        else None
                    ),
                )
            await self._record_spend(
                captured,
                prior_history=prior_history,
                context=context,
                emit=emit,
                purpose="remember" if is_remember else "building",
                memory_id=remembered_memory_id,
            )

    async def _record_spend(
        self,
        captured: Sequence[ModelMessage],
        *,
        prior_history: Sequence[object],
        context: MemoryToolContext | None,
        emit: RunEmitter,
        purpose: SpendPurpose,
        memory_id: UUID | None,
    ) -> None:
        if self._spend is None or context is None:
            return
        responses = [
            message
            for message in _new_captured_messages(captured, prior_history)
            if isinstance(message, ModelResponse)
        ]
        if not responses:
            return
        run_id = getattr(emit, "run_id", None)
        prompt_id = getattr(emit, "prompt_id", None)
        if not isinstance(run_id, str) or not isinstance(prompt_id, str):
            raise RuntimeError("spend-enabled emitter must expose run_id and prompt_id")
        if context.thread_id is None:
            raise RuntimeError("spend-enabled model call requires a thread_id")
        request = model_response_receipts(
            responses,
            lineage=SpendLineage(
                principal_id=context.principal_id,
                machine_id=context.machine_id,
                origin_agent=context.agent_id,
                thread_id=context.thread_id,
                run_id=run_id,
                prompt_id=prompt_id,
                memory_id=memory_id,
            ),
            purpose=purpose,
        )
        if request is None:
            return
        if self._receipt_queue is not None:
            await self._receipt_queue.flush(self._spend)
        try:
            result = await self._spend.record_spend_events(request)
            if result.accepted != len(request.events):
                raise RuntimeError("Spine accepted an incomplete spend receipt batch")
        except Exception:
            durable = False
            if self._receipt_queue is not None:
                durable = await self._receipt_queue.enqueue(request)
            pending = (
                self._receipt_queue.snapshot().pending_lines
                if self._receipt_queue is not None
                else len(request.events)
            )
            location = "durably on disk" if durable else "in degraded memory"
            await emit.error(
                {
                    "code": "spend_pending",
                    "phase": "receipt",
                    "message": f"Answer delivered; {pending} spend receipt line(s) are "
                    f"waiting for the ledger ({location}).",
                }
            )
            return


def _provider_error(exc: Exception, fallback_model: str) -> ProviderErrorPayload | None:
    """Retain only structured provider HTTP evidence; never relabel product faults. [A-054]"""

    if not isinstance(exc, ModelHTTPError):
        return None
    body = _decoded_provider_body(exc.body)
    message = _provider_message(body)
    if message is None:
        message = f"HTTP {exc.status_code} from {exc.model_name or fallback_model}"
    message = _bounded_provider_text(message)
    code = _provider_code(body)
    provider_code = _native_provider_code(body)
    classification = (
        "context_length"
        if _is_context_length(code=code, provider_code=provider_code, message=message)
        else "provider_refusal"
    )
    return ProviderErrorPayload(
        classification=classification,
        message=message,
        model=exc.model_name or fallback_model,
        status_code=exc.status_code,
        code=code,
        provider_code=provider_code,
    )


def _decoded_provider_body(body: object | None) -> object | None:
    if not isinstance(body, str):
        return body
    stripped = body.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, RecursionError):
            pass
    return stripped


def _provider_message(body: object | None) -> str | None:
    if isinstance(body, str):
        return body or None
    if isinstance(body, Mapping):
        error = body.get("error")
        if error is not None:
            nested = _provider_message(error)
            if nested is not None:
                return nested
        message = body.get("message")
        metadata = body.get("metadata")
        if isinstance(metadata, Mapping):
            raw = metadata.get("raw")
            if raw is not None:
                nested = _provider_message(_decoded_provider_body(raw))
                if nested is not None and (
                    not isinstance(message, str)
                    or message.strip().lower() in {"provider returned error", "provider error"}
                ):
                    return nested
        if isinstance(message, str) and message.strip():
            return message
    return None


def _provider_code(body: object | None) -> str | None:
    if not isinstance(body, Mapping):
        return None
    error = body.get("error")
    if isinstance(error, Mapping):
        nested = _provider_code(error)
        if nested is not None:
            return nested
    error_type = body.get("error_type")
    if isinstance(error_type, str) and error_type.strip():
        return _bounded_provider_text(error_type, limit=128)
    metadata = body.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("error_type", "provider_code"):
            candidate = metadata.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return _bounded_provider_text(candidate, limit=128)
        raw = metadata.get("raw")
        if raw is not None:
            nested = _provider_code(_decoded_provider_body(raw))
            if nested is not None:
                return nested
    code = body.get("code")
    if isinstance(code, str) and code.strip():
        return _bounded_provider_text(code, limit=128)
    return None


def _native_provider_code(body: object | None) -> str | None:
    if not isinstance(body, Mapping):
        return None
    error = body.get("error")
    if isinstance(error, Mapping):
        nested = _native_provider_code(error)
        if nested is not None:
            return nested
    metadata = body.get("metadata")
    if isinstance(metadata, Mapping):
        candidate = metadata.get("provider_code")
        if isinstance(candidate, str) and candidate.strip():
            return _bounded_provider_text(candidate, limit=128)
        raw = metadata.get("raw")
        if raw is not None:
            return _native_provider_code(_decoded_provider_body(raw))
    return None


def _bounded_provider_text(value: str, *, limit: int = _MAX_PROVIDER_MESSAGE) -> str:
    normalized = " ".join(value.replace("\x00", "").split())
    if not normalized:
        return "Provider request failed without a message"
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _is_context_length(*, code: str | None, provider_code: str | None, message: str) -> bool:
    normalized_codes = {
        value.strip().lower().replace("-", "_")
        for value in (code, provider_code)
        if value is not None
    }
    if normalized_codes & _CONTEXT_CODES:
        return True
    return any(pattern.search(message) is not None for pattern in _CONTEXT_PATTERNS)


def _provider_refusal_copy(error: ProviderErrorPayload) -> str:
    if error.classification == "context_length":
        return (
            f"This thread has reached {error.model}'s context limit. "
            "Archive it, then continue in a fresh thread."
        )
    punctuation = "" if error.message.endswith((".", "!", "?")) else "."
    return f"The provider refused: {error.message}{punctuation} Retry this turn or switch models."


class _EventBridge:
    """Translate pydantic-ai events and mutable usage into owned run events."""

    def __init__(self, emit: RunEmitter) -> None:
        self._emit = emit
        self._last_usage = UsageSnapshot()
        self._pending_text = ""
        self._visible_text = ""
        self._proposal_started = False

    async def handle(
        self,
        context: Any,
        events: AsyncIterable[AgentStreamEvent],
    ) -> None:
        async for event in events:
            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                if event.part.content:
                    await self._accept_text(event.part.content)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                if event.delta.content_delta:
                    await self._accept_text(event.delta.content_delta)
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

    async def _accept_text(self, value: str) -> None:
        if self._proposal_started:
            self._pending_text += value
            return
        self._pending_text += value
        marker = self._pending_text.find(BLOCK_OPEN)
        if marker >= 0:
            await self._publish_visible(self._pending_text[:marker])
            self._pending_text = self._pending_text[marker:]
            self._proposal_started = True
            return
        retained = _marker_prefix_suffix_length(self._pending_text, BLOCK_OPEN)
        safe_length = len(self._pending_text) - retained
        await self._publish_visible(self._pending_text[:safe_length])
        self._pending_text = self._pending_text[safe_length:]

    async def _publish_visible(self, value: str) -> None:
        if not value:
            return
        self._visible_text += value
        await self._emit.text(value)

    async def finalize(self, output: str, *, run_id: str, created_at: datetime) -> str:
        """Reconcile the streamed answer and publish one same-turn proposal event."""

        visible, proposal = parse_proposed_response_output(output)
        if not visible.startswith(self._visible_text):
            raise RuntimeError("terminal model text differs from streamed model text")
        await self._publish_visible(visible[len(self._visible_text) :])
        self._pending_text = ""
        if proposal is not None:
            await self._emit.event(
                proposed_response_event(proposal, run_id=run_id, created_at=created_at)
            )
        return visible

    async def publish_usage(self, usage: UsageSnapshot) -> None:
        if usage == self._last_usage:
            return
        if (
            usage.requests < self._last_usage.requests
            or usage.input_tokens < self._last_usage.input_tokens
            or usage.output_tokens < self._last_usage.output_tokens
            or usage.cache_read_tokens < self._last_usage.cache_read_tokens
            or usage.cache_write_tokens < self._last_usage.cache_write_tokens
        ):  # pragma: no cover - pydantic-ai promises cumulative usage
            raise ValueError("pydantic-ai usage decreased during a run")
        self._last_usage = usage
        await self._emit.usage(usage)


def _json_event(event: AgentStreamEvent) -> Mapping[str, object]:
    value = to_jsonable_python(event)
    if not isinstance(value, dict):  # pragma: no cover - all AgentStreamEvent values are objects
        raise TypeError("pydantic-ai emitted a non-object event")
    return cast(dict[str, object], value)


def _marker_prefix_suffix_length(value: str, marker: str) -> int:
    maximum = min(len(value), len(marker) - 1)
    for length in range(maximum, 0, -1):
        if value.endswith(marker[:length]):
            return length
    return 0


def _usage_snapshot(usage: RunUsage) -> UsageSnapshot:
    return UsageSnapshot(
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
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
        cache_read_tokens=sum(message.usage.cache_read_tokens for message in responses),
        cache_write_tokens=sum(message.usage.cache_write_tokens for message in responses),
    )
    current = _usage_snapshot(usage)
    return UsageSnapshot(
        requests=max(current.requests, captured_usage.requests),
        input_tokens=max(current.input_tokens, captured_usage.input_tokens),
        output_tokens=max(current.output_tokens, captured_usage.output_tokens),
        cache_read_tokens=max(current.cache_read_tokens, captured_usage.cache_read_tokens),
        cache_write_tokens=max(current.cache_write_tokens, captured_usage.cache_write_tokens),
    )


def _cacheable_prefix_tokens(messages: Sequence[object]) -> int:
    """Return the terminal provider request plus response token footprint."""

    response = next(
        (message for message in reversed(messages) if isinstance(message, ModelResponse)),
        None,
    )
    if response is None:
        return 0
    return response.usage.input_tokens + response.usage.output_tokens


def _model_settings(
    resolution: ThreadModelResolution | None,
    thread_id: str,
) -> ModelSettings | None:
    """Compatibility wrapper over the completion adapter's request shape."""

    return model_settings_for(resolution, thread_id)


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


def _strip_all_memory_blocks(history: Sequence[object]) -> tuple[object, ...]:
    """Remove dynamic C.6 instructions from history before adding the current block."""

    return tuple(_strip_request_memory_block(message) for message in history)


def _strip_all_proposed_response_blocks(history: Sequence[object]) -> tuple[object, ...]:
    """Keep hidden Deck control blocks out of later provider context."""

    cleaned: list[object] = []
    for message in history:
        if not isinstance(message, ModelResponse):
            cleaned.append(message)
            continue
        parts = []
        changed = False
        for part in message.parts:
            if not isinstance(part, TextPart):
                parts.append(part)
                continue
            visible, proposal = parse_proposed_response_output(part.content)
            if proposal is None and BLOCK_OPEN not in part.content:
                parts.append(part)
                continue
            parts.append(replace(part, content=visible))
            changed = True
        cleaned.append(replace(message, parts=parts) if changed else message)
    return tuple(cleaned)


def _strip_request_memory_block(message: object) -> object:
    if not isinstance(message, ModelRequest) or not _has_memory_block(message.instructions):
        return message
    instructions = message.instructions
    assert instructions is not None
    cleaned = _remove_memory_blocks(instructions)
    return replace(message, instructions=cleaned or None)


def _has_memory_block(instructions: str | None) -> bool:
    if instructions is None:
        return False
    start = instructions.find(_MEMORY_BLOCK_OPEN)
    return start >= 0 and instructions.find(_MEMORY_BLOCK_CLOSE, start) >= 0


def _remove_memory_blocks(instructions: str) -> str:
    value = instructions
    while True:
        start = value.find(_MEMORY_BLOCK_OPEN)
        if start < 0:
            return value
        end = value.find(_MEMORY_BLOCK_CLOSE, start + len(_MEMORY_BLOCK_OPEN))
        if end < 0:
            return value
        end += len(_MEMORY_BLOCK_CLOSE)
        remove_from = start - 1 if start > 0 and value[start - 1] == "\n" else start
        value = value[:remove_from] + value[end:]
