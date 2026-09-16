"""The pydantic-ai runtime adapter for the framework-neutral run loop."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from pydantic_ai import ModelHTTPError, ModelRetry, UsageLimitExceeded, capture_run_messages
from pydantic_ai.capabilities import Capability
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
    UserPromptPart,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from harness.agent import HarnessAgent
from harness.commands import browser_open_web_command, remember_command_text
from harness.conductor import _MAX_DISTILLATE_BYTES
from harness.context_window import ContextWindowTracker
from harness.envelope import ProviderErrorPayload, StopReason, generate_ulid
from harness.extraction import ExtractionService
from harness.model_policy import ThreadModelResolution
from harness.model_router import model_settings_for
from harness.proposed_response import (
    BLOCK_OPEN,
    PROPOSED_RESPONSE_INSTRUCTION,
    parse_proposed_response_output,
    proposed_response_event,
)
from harness.pydantic_ai_adapter import DelegateCapability
from harness.pydantic_harness_adapter import CompactionPolicy, MemoryCompaction
from harness.receipt_queue import SpendReceiptQueue
from harness.run_protocol import (
    DynamicSystemInstructions,
    RunEmitter,
    TurnOutcome,
    UsageSnapshot,
    run_error_message,
)
from harness.spend import (
    SpendGateway,
    SpendLineage,
    SpendPurpose,
    model_response_receipts,
)
from harness.tools_memory import MemoryToolContext
from harness.toolset import PermissionJudge
from harness.toolset_runtime import LazyStandardToolset

type ContextFactory = Callable[[str], MemoryToolContext]


def _configure_compaction(policy: CompactionPolicy, argument: str) -> CompactionPolicy:
    """The owner's per-thread controls are journaled, including instruction generations."""
    command, _, value = argument.partition(" ")
    values = policy.model_dump()
    if command == "strategy":
        values["strategy"] = value
    elif command == "policy":
        name, _, fraction = value.partition(" ")
        values.update(
            policy=name, fraction=float(fraction) if fraction else 0.5 if name == "cost" else 0.8
        )
    elif command == "instructions" and "{messages}" in value:
        values["instructions"] = value
    else:
        # D.2 153: reject unsupported controls without changing the saved policy.
        raise ValueError("Unknown compaction control")
    return CompactionPolicy.model_validate(values)


logger = logging.getLogger(__name__)

_INTERRUPTED_TOOL_CONTENT = "Tool execution interrupted by run cancellation."
_MEMORY_BLOCK_OPEN = "<memory_system>\n"
_MEMORY_BLOCK_CLOSE = "\n</memory_system>"
_MAX_PROVIDER_MESSAGE = 1_000


class _BoundaryCardReleased(Exception):
    """End a boundary turn after the judge releases its durable Deck card."""


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
        extraction: ExtractionService | None = None,
    ) -> None:
        self._agent = agent
        self._context_factory = context_factory
        self._spend = spend
        self._receipt_queue = receipt_queue
        self._context_windows = context_windows
        self._clock = clock or (lambda: datetime.now(UTC))
        self._extraction = extraction

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
        boundary_messages: list[ModelMessage] = []
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

        async def review_boundary(wall: str, reason: str) -> str:
            if not PermissionJudge.needs_owner(wall):
                return reason + " The PermissionJudge says to move within the existing workspace."
            await emit.event(
                {
                    "event_kind": "boundary_card",
                    "judge": "PermissionJudge",
                    "policy": "ADR-015 boundary list",
                    "decision": "owner_action",
                    "wall": wall,
                    "reason": reason,
                    "run_id": emit.run_id,
                    "created_at": self._clock().isoformat(),
                    "action": "Use a separate thread rooted at the required folder."
                    if wall == "workspace"
                    else "Perform this action explicitly outside Nocturne.",
                }
            )
            # WALL workspace / F083: stop the turn after releasing its boundary card.
            raise _BoundaryCardReleased()

        async def record_extraction(messages):
            await self._record_spend(
                messages,
                prior_history=(),
                context=context,
                emit=emit,
                purpose="extraction",
                memory_id=None,
            )

        compaction = (
            MemoryCompaction(
                self._extraction,
                emit,
                model_resolution.context_tokens if model_resolution else None,
                record_extraction,
                policy=CompactionPolicy.model_validate(
                    self._extraction._journal.compaction_policy(thread_id)
                ),
                model_settings=model_settings,
            )
            if self._extraction is not None
            else None
        )

        def failed_history():
            if is_remember:
                return prior_history
            if compaction is not None and compaction.completed:
                history = _repair_cancelled_tool_calls(tuple(captured or compaction.history))
                self._extraction._journal.append_compaction_history(
                    thread_id,
                    emit.run_id,
                    to_jsonable_python(history),
                )
                return history
            if compaction is not None and compaction.original_history:
                return tuple(compaction.original_history)
            return _captured_history(prior_history, captured)

        try:
            context = replace(
                self._context_factory(thread_id),
                excluded_memory_ids=frozenset(excluded_memory_ids),
                boundary_review=review_boundary,
            )
            if prompt == "/compact" or prompt.startswith("/compact "):
                if compaction is None:
                    message = "Compaction is unavailable without the conversation journal."
                    history = prior_history
                elif prompt == "/compact":
                    history = tuple(
                        await compaction.manual(
                            prior_history,
                            model=selected_model,
                            deps=context,
                            usage=run_usage,
                        )
                    )
                    message = (
                        "Context compacted with " + compaction.policy.strategy + "."
                        if compaction.completed
                        else "No older context to compact yet."
                    )
                else:
                    history = prior_history
                    try:
                        policy = _configure_compaction(compaction.policy, prompt[9:].strip())
                        self._extraction._journal.append_compaction_policy(
                            thread_id,
                            policy.model_dump(),
                        )
                        compaction.policy = policy
                        message = (
                            f"Compaction: {policy.strategy}; {policy.policy} policy at "
                            f"{policy.fraction:.1%} of the model window."
                        )
                    except ValueError:
                        message = (
                            "Use /compact, /compact strategy truncate|summarize|memories-then-drop|"
                            "human-and-final-only, /compact policy performance|cost [fraction], "
                            "or /compact instructions <summary prompt containing {messages}>."
                        )
                await emit.text(message)
                usage = _usage_snapshot(run_usage)
                await bridge.publish_usage(usage)
                return TurnOutcome(
                    StopReason("end_turn"),
                    history,
                    usage,
                    assistant_text=message,
                    model_visible=False,
                )

            from spine.tokens import cl100k_token_count

            worker_budget = min(
                _MAX_DISTILLATE_BYTES // 4,
                (model_resolution.context_tokens if model_resolution else 200_000) // 10,
            )
            worker_budget -= sum(
                cl100k_token_count(str(part.content))
                for message in prior_history
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, ToolReturnPart) and part.tool_name == "delegate_task"
            )

            async def delegate(task: str) -> str:
                nonlocal worker_budget
                worker_id = generate_ulid()
                location = context.toolset.location() if context.toolset is not None else None
                toolset = (
                    None
                    if location is None
                    else LazyStandardToolset(
                        cwd=location.cwd,
                        workspace_root=location.workspace_root,
                        agent_id=f"{context.agent_id}/{worker_id}",
                        machine_id=context.machine_id,
                        fence_reads=location.fence_reads,
                    )
                )
                worker_context = replace(
                    context,
                    toolset=toolset,
                    delegate=None,
                    boundary_review=None,
                    agent_id=f"{context.agent_id}/{worker_id}",
                )
                try:
                    result = await self._agent.worker_agent.run(
                        task,
                        deps=worker_context,
                        model=selected_model,
                        model_settings=model_settings,
                        usage=run_usage,
                        usage_limits=self._agent.usage_limits,
                    )
                    full = result.output
                    self._extraction._journal.append_worker_return(
                        thread_id,
                        worker_id,
                        full,
                        to_jsonable_python(result.all_messages()),
                    )
                    await self._record_spend(
                        result.all_messages(),
                        prior_history=(),
                        context=worker_context,
                        emit=emit,
                        purpose="building",
                        memory_id=None,
                    )
                    encoded = full.encode("utf-8")
                    marker = "\n[Return capped; full result is in the conversation journal.]"
                    # WALL main context / D.2 153: worker bulk must not force compaction.
                    distilled = (
                        full
                        if len(encoded) <= _MAX_DISTILLATE_BYTES
                        else (
                            encoded[: _MAX_DISTILLATE_BYTES - len(marker.encode())].decode(
                                "utf-8", errors="ignore"
                            )
                            + marker
                        )
                    )
                    # One shared allowance covers all worker returns already in this history.
                    limit = max(0, worker_budget)
                    if cl100k_token_count(distilled) > limit:
                        low, high = 0, len(distilled)
                        while low < high:
                            middle = (low + high + 1) // 2
                            if cl100k_token_count(distilled[:middle] + marker) <= limit:
                                low = middle
                            else:
                                high = middle - 1
                        distilled = distilled[:low] + marker if low else ""
                    worker_budget -= cl100k_token_count(distilled)
                    await emit.event(
                        {
                            "event_kind": "worker_return",
                            "worker_id": worker_id,
                            "full_bytes": len(encoded),
                            "returned_bytes": len(distilled.encode()),
                            "capped": distilled != full,
                        }
                    )
                    return distilled
                finally:
                    if toolset is not None:
                        await toolset.close()

            if self._extraction is not None:
                context = replace(context, delegate=delegate)
            if is_browser_consent:
                message = "Open-web browser access is allowed for this thread."
                if image is not None:
                    message = "Send `/browser allow-web` without an image to cross this wall."
                else:
                    context.toolset.grant_open_web(thread_id)
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
                remembered_memory_id = dispatched.memory_id
                await emit.text(dispatched.message)
                usage = _failure_usage(run_usage, captured, ())
                await bridge.publish_usage(usage)
                return TurnOutcome(StopReason("end_turn"), prior_history, usage)

            if context.toolset is not None and _explicit_outside_path(prompt, context):
                location = context.toolset.location()
                with capture_run_messages() as boundary_messages:
                    judged = await self._agent.judge_boundary(
                        f"Workspace root: {location.workspace_root}\n"
                        f"Current location: {location.cwd}\nUser request:\n{prompt}",
                        model=selected_model,
                        usage=run_usage,
                        model_settings=model_settings,
                    )
                await emit.event(
                    {
                        "event_kind": "boundary_judgment",
                        "judge": "PermissionJudge",
                        "model": selected_model.model_name,
                        **judged.output.model_dump(),
                    }
                )
                if judged.output.needs_owner:
                    await review_boundary("workspace", judged.output.reason)

            prior_history = _strip_all_proposed_response_blocks(
                _strip_all_memory_blocks(prior_history)
            )
            user_prompt = prompt if image is None else [prompt, image]

            applied_steering = ""

            class PendingSteering(Capability[MemoryToolContext]):
                async def after_model_request(self, ctx, *, request_context, response):
                    # A correction arriving during a final response still gets a request.
                    pending = getattr(emit, "steering_instructions", lambda: "")()
                    if not response.tool_calls and pending != applied_steering:
                        raise ModelRetry("Apply the new human instruction before finishing.")
                    return response

            async def current_instructions(run_context) -> str | None:
                nonlocal applied_steering
                blocks = []
                if dynamic_instructions is not None:
                    blocks.append(await dynamic_instructions.render())
                steering = getattr(emit, "steering_instructions", lambda: "")()
                if steering and steering != applied_steering:
                    run_context.messages[-1].parts.append(UserPromptPart(
                        "New human instruction for this current run:\n"
                        + steering[len(applied_steering):].strip()
                    ))
                    applied_steering = steering
                    await emit.event({"event_kind": "human_interjection_applied"})
                return "\n\n".join(block for block in blocks if block) or None

            instructions: list[object] = [PROPOSED_RESPONSE_INSTRUCTION]
            if system_instructions is not None:
                instructions.append(system_instructions)
            instructions.append(current_instructions)
            with capture_run_messages() as captured:
                result = await self._agent.chat_agent.run(
                    user_prompt,
                    deps=context,
                    instructions=instructions,
                    capabilities=[
                        PendingSteering(),
                        *self._agent.tool_capabilities(context),
                        *(
                            [DelegateCapability()]
                            if compaction is not None and context.toolset_enabled
                            else []
                        ),
                        *([compaction] if compaction is not None else []),
                    ],
                    message_history=cast(Sequence[ModelMessage], prior_history),
                    model=selected_model,
                    model_settings=model_settings,
                    usage_limits=self._agent.usage_limits,
                    usage=run_usage,
                    event_stream_handler=bridge.handle,
                )
            visible_output = await bridge.finalize(
                "".join(
                    part.content
                    for message in result.new_messages()
                    if isinstance(message, ModelResponse)
                    for part in message.parts
                    if isinstance(part, TextPart)
                ),
                run_id=emit.run_id,
                created_at=self._clock(),
            )
            usage = _usage_snapshot(result.usage)
            await bridge.publish_usage(usage)
            history = tuple(result.all_messages())
            if compaction is not None and compaction.completed:
                self._extraction._journal.append_compaction_history(
                    thread_id,
                    emit.run_id,
                    to_jsonable_python(history),
                )
            return TurnOutcome(
                StopReason("end_turn"),
                history,
                usage,
                cacheable_prefix_tokens=_cacheable_prefix_tokens(history),
                assistant_text=visible_output,
            )
        except _BoundaryCardReleased:
            usage = _failure_usage(run_usage, captured, prior_history)
            await bridge.publish_usage(usage)
            message = "Boundary review is on the Deck. No action was taken across the wall."
            await emit.text(message)
            return TurnOutcome(
                StopReason("end_turn"),
                _repair_cancelled_tool_calls(failed_history(), content=message),
                usage,
                assistant_text=message,
            )
        except asyncio.CancelledError:
            usage = _failure_usage(run_usage, captured, prior_history)
            await bridge.publish_usage(usage)
            history = prior_history if is_remember else failed_history()
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
                failed_history(),
                usage,
            )
        except Exception as exc:
            usage = _failure_usage(run_usage, captured, prior_history)
            await bridge.publish_usage(usage)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                history = prior_history if is_remember else failed_history()
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
                    failed_history(),
                    usage,
                    assistant_text=message,
                    provider_error=provider_error,
                )
            logger.exception("Model turn failed: run=%s thread=%s", emit.run_id, thread_id)
            return TurnOutcome(
                StopReason("error"),
                failed_history(),
                usage,
                error_message=run_error_message(exc),
            )
        finally:
            if self._context_windows is not None and not is_remember:
                self._context_windows.record(
                    thread_id=thread_id,
                    compaction_fraction=compaction.policy.fraction if compaction else 0.8,
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
            await self._record_spend(
                boundary_messages,
                prior_history=(),
                context=context,
                emit=emit,
                purpose="judge",
                memory_id=None,
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
        request = model_response_receipts(
            responses,
            lineage=SpendLineage(
                principal_id=context.principal_id,
                machine_id=context.machine_id,
                origin_agent=context.agent_id,
                thread_id=context.thread_id,
                run_id=emit.run_id,
                prompt_id=emit.prompt_id,
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
            # WALL money: B.6 r11 keeps unacknowledged receipts queued for reconciliation.
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


def _explicit_outside_path(prompt: str, context: MemoryToolContext) -> bool:
    """Screen boundary references only; ordinary in-wall work never incurs a judge call."""
    paths = re.findall(r"(?:^|[\s'\"`])((?:/|\.\./|~/)[^\s'\"`]+)", prompt)
    outside = re.search(r"\b(?:outside|beyond) (?:the |this |my )?(?:workspace|folder)\b", prompt)
    if not paths:
        return bool(outside)
    location = context.toolset.location()
    for raw in paths:
        path = Path(raw.rstrip(".,;:!?")).expanduser()
        if not (location.cwd / path).resolve().is_relative_to(location.workspace_root):
            return True
    return bool(outside)


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
    # INCIDENT F034 / A-054: bounded public refusal evidence excludes full provider payloads.
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


_THINKING_DELIMITERS = {
    "<mm:think>": "</mm:think>",
    "<think>": "</think>",
    "<thinking>": "</thinking>",
}


class _VisibleModelText:
    """Keep tagged reasoning private even when a delimiter spans stream chunks."""

    def __init__(self) -> None:
        self.pending = ""
        self.closing: str | None = None

    def feed(self, value: str) -> str:
        self.pending += value
        visible = ""
        while self.pending:
            markers = (self.closing,) if self.closing else tuple(_THINKING_DELIMITERS)
            matches = [(self.pending.find(marker), marker) for marker in markers]
            matches = [(index, marker) for index, marker in matches if index >= 0]
            if matches:
                index, marker = min(matches)
                if self.closing is None:
                    visible += self.pending[:index]
                    self.closing = _THINKING_DELIMITERS[marker]
                else:
                    self.closing = None
                self.pending = self.pending[index + len(marker) :]
                continue
            retained = max(_marker_prefix_suffix_length(self.pending, marker) for marker in markers)
            safe = len(self.pending) - retained
            if self.closing is None:
                visible += self.pending[:safe]
            self.pending = self.pending[safe:]
            break
        return visible


class _EventBridge:
    """Translate pydantic-ai events and mutable usage into owned run events."""

    def __init__(self, emit: RunEmitter) -> None:
        self._emit = emit
        self._last_usage = UsageSnapshot()
        self._pending_text = ""
        self._visible_text = ""
        self._proposal_started = False
        self._model_text = _VisibleModelText()

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
        value = self._model_text.feed(value)
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
        """Reconcile all new assistant TextParts, in order, excluding prior history.

        This is the same concatenation streamed by handle, including text before tools.
        The terminal proposal is hidden from both projections.
        """

        terminal = _VisibleModelText()
        clean_output = terminal.feed(output)
        if terminal.closing is None:
            clean_output += terminal.pending
        visible, proposal = parse_proposed_response_output(clean_output)
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
        self._last_usage = usage
        await self._emit.usage(usage)


def _json_event(event: AgentStreamEvent) -> Mapping[str, object]:
    value = to_jsonable_python(event)
    part = value.get("part")
    if isinstance(part, dict) and part.get("part_kind") == "text":
        part["content"] = _VisibleModelText().feed(part["content"])
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
    # SDK normalization can merge requests or repair tool pairs in the old prefix.
    # Response/run identities survive that normalization; positions do not.
    prior_runs = {message.run_id for message in prior_history if getattr(message, "run_id", None)}
    prior_responses = {
        (message.provider_name, message.provider_response_id)
        for message in prior_history
        if isinstance(message, ModelResponse) and message.provider_response_id
    }
    return [
        message
        for message in captured
        if message.run_id not in prior_runs
        and not (
            isinstance(message, ModelResponse)
            and (message.provider_name, message.provider_response_id) in prior_responses
        )
        and (
            message.run_id is not None
            or not any(message is old or message == old for old in prior_history)
        )
    ]


def _captured_history(
    prior_history: Sequence[object], captured: Sequence[ModelMessage]
) -> tuple[object, ...]:
    # capture_run_messages contains the complete, normalized history, even on failure.
    return tuple(captured or prior_history)


def _repair_cancelled_tool_calls(
    history: Sequence[object],
    *,
    content: str = _INTERRUPTED_TOOL_CONTENT,
) -> tuple[object, ...]:
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
            content=content,
            tool_call_id=call.tool_call_id,
            metadata={"harness_state": "cancelled"},
            timestamp=response.timestamp,
            outcome="interrupted",
        )
        for call, response in unanswered
    ]
    last_response = unanswered[-1][1]
    if isinstance(history[-1], ModelRequest) and not history[-1].parts:
        return (*history[:-1], replace(history[-1], parts=returns))
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
