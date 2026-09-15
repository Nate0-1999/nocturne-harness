"""The single adapter from harness capabilities to pydantic-ai v2."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import BinaryContent, RunContext, ToolReturn
from pydantic_ai.capabilities import Capability
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.tools import Tool
from pydantic_ai_harness.compaction import (
    SlidingWindowCompaction,
    SummarizingCompaction,
    TieredCompaction,
    compact_now,
    estimate_context_tokens,
    estimate_token_count,
    reinject_pinned,
    resolve_context_window,
)
from pydantic_ai_harness.compaction._receipts import is_receipt_part
from pydantic_ai_harness.compaction._shared import find_safe_cutoff
from pydantic_ai_harness.compaction._summarizing_compaction import (
    _DEFAULT_SUMMARY_PROMPT as COMPACTION_SUMMARY_PROMPT,
)
from pydantic_ai_harness.compaction._summarizing_compaction import _format_messages
from pydantic_core import to_jsonable_python
from spine.tokens import cl100k_token_count

from harness.capability import CapabilityHandler, CapabilityTool, HarnessCapability
from harness.envelope import generate_ulid
from harness.memory_capability import DEFAULT_MEMORY_FEATURE
from harness.pydantic_harness_adapter import adopted_skills
from harness.spine_client import SpineClientError
from harness.tools_memory import MemoryToolContext
from harness.toolset import ToolName, ToolsetError

WORKSPACE_INSTRUCTIONS = (
    "To edit or write a file, you must use move in its own tool step to enter that file's "
    "directory first. Reads are free. Bash may modify files only within the current location's "
    "subtree. "
    "When the user names a discoverable skill, call load_capability with that skill's id "
    "before following its instructions or reading its bundled resources. "
    "Never ask a permission question in chat. The PermissionJudge handles outside-file requests. "
    "Reserved owner decisions go to the Deck. Never retry around a refused wall."
    " Browser tools are headless and default to localhost or files beneath the current location."
    " Never ask the owner for consent inside a tool call; a refused open-web request must wait"
    " for the owner's exact `/browser allow-web` command."
)


def _adapt_search(handler: CapabilityHandler) -> Tool[MemoryToolContext]:
    async def adapted_search(
        ctx: RunContext[MemoryToolContext],
        query: str,
        k: int = 5,
    ) -> str:
        return await handler(ctx.deps, query=query, k=k)

    return Tool(adapted_search)


def _adapt_edit(handler: CapabilityHandler) -> Tool[MemoryToolContext]:
    async def adapted_edit(
        ctx: RunContext[MemoryToolContext],
        label_or_id: str,
        new_body: str,
        reason: str,
    ) -> str:
        return await handler(
            ctx.deps,
            label_or_id=label_or_id,
            new_body=new_body,
            reason=reason,
        )

    return Tool(adapted_edit)


_CONTEXTUAL_ADAPTERS = {
    "search_memory": _adapt_search,
    "edit_memory": _adapt_edit,
}


def _adapt_tool(spec: CapabilityTool) -> Tool[MemoryToolContext]:
    """Pair an owned tool spec with its explicit contextual schema."""
    try:
        adapter = _CONTEXTUAL_ADAPTERS[spec.name]
    except KeyError as exc:
        raise ValueError(f"unsupported memory tool: {spec.name}") from exc
    tool = adapter(spec.handler)
    tool.name = spec.name
    tool.description = spec.description
    return tool


class MemoryCapability(Capability[MemoryToolContext]):
    """Standard pydantic-ai capability backed by the harness memory feature."""

    def __init__(self, feature: HarnessCapability = DEFAULT_MEMORY_FEATURE) -> None:
        definition = feature.definition
        if definition.id != "memory":
            raise ValueError("MemoryCapability requires the memory feature")
        if tuple(tool.name for tool in definition.tools) != tuple(_CONTEXTUAL_ADAPTERS):
            raise ValueError("MemoryCapability requires search and edit memory tools")
        if (
            definition.lifecycle_hooks
            or definition.history_transforms
            or definition.event_stream_taps
        ):
            raise ValueError(
                "MemoryCapability does not define lifecycle, history, or event behavior"
            )

        super().__init__(
            id=definition.id,
            defer_loading=False,
            instructions=[instruction.text for instruction in definition.instructions],
            tools=[_adapt_tool(tool) for tool in definition.tools],
        )


def adopted_skill_capabilities(
    directories: Sequence[Path],
) -> tuple[Capability[MemoryToolContext], ...]:
    """Translate upstream skill data through the one Pydantic AI capability adapter."""

    return tuple(
        Capability[MemoryToolContext](
            id=skill.id,
            description=skill.description,
            instructions=skill.instructions,
            defer_loading=True,
        )
        for skill in adopted_skills(directories)
    )


class EditReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_text: str
    new_text: str


async def _execute_workspace_tool(
    ctx: RunContext[MemoryToolContext],
    tool_name: ToolName,
    arguments: dict[str, object],
) -> str:
    toolset = ctx.deps.toolset
    if toolset is None:
        return f"{tool_name} unavailable: this owner session has no workspace toolset"
    try:
        result = await toolset.execute(tool_name, arguments)
    except (ToolsetError, OSError, ValueError) as exc:
        return f"{tool_name} refused: {str(exc).strip() or type(exc).__name__}"
    prefix = "" if result.success else f"{tool_name} refused: "
    if result.boundary is not None and ctx.deps.boundary_review is not None:
        return await ctx.deps.boundary_review(result.boundary, result.content)
    return prefix + result.content


async def read(
    ctx: RunContext[MemoryToolContext], path: str, offset: int = 1, limit: int = 2000
) -> str:
    """Read text from a file. Reads may inspect beyond the current location."""
    return await _execute_workspace_tool(
        ctx, "read", {"path": path, "offset": offset, "limit": limit}
    )


async def edit(ctx: RunContext[MemoryToolContext], path: str, edits: list[EditReplacement]) -> str:
    """Replace exact text in a file in the current directory."""
    return await _execute_workspace_tool(
        ctx,
        "edit",
        {
            "path": path,
            "edits": [
                {"oldText": replacement.old_text, "newText": replacement.new_text}
                for replacement in edits
            ],
        },
    )


async def write(ctx: RunContext[MemoryToolContext], path: str, content: str) -> str:
    """Create or replace a file in the current directory."""
    return await _execute_workspace_tool(ctx, "write", {"path": path, "content": content})


async def grep(
    ctx: RunContext[MemoryToolContext],
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    ignore_case: bool = False,
    literal: bool = False,
    context: int = 0,
    limit: int = 100,
) -> str:
    """Search file contents and return matching lines."""
    arguments: dict[str, Any] = {
        "pattern": pattern,
        "path": path,
        "ignoreCase": ignore_case,
        "literal": literal,
        "context": context,
        "limit": limit,
    }
    if glob is not None:
        arguments["glob"] = glob
    return await _execute_workspace_tool(ctx, "grep", arguments)


async def find(
    ctx: RunContext[MemoryToolContext], pattern: str, path: str = ".", limit: int = 1000
) -> str:
    """Find files by glob pattern."""
    return await _execute_workspace_tool(
        ctx, "find", {"pattern": pattern, "path": path, "limit": limit}
    )


async def ls(ctx: RunContext[MemoryToolContext], path: str = ".", limit: int = 500) -> str:
    """List a directory."""
    return await _execute_workspace_tool(ctx, "ls", {"path": path, "limit": limit})


async def bash(
    ctx: RunContext[MemoryToolContext], command: str, timeout: float | None = None
) -> str:
    """Run a shell command inside the current location's OS sandbox."""
    arguments: dict[str, object] = {"command": command}
    if timeout is not None:
        arguments["timeout"] = timeout
    return await _execute_workspace_tool(ctx, "bash", arguments)


async def move(ctx: RunContext[MemoryToolContext], path: str) -> str:
    """Move the agent's current location to a directory inside this workspace."""
    return await _execute_workspace_tool(ctx, "move", {"path": path})


async def _execute_browser_tool(
    ctx: RunContext[MemoryToolContext],
    tool_name: ToolName,
    arguments: dict[str, object],
) -> str | ToolReturn:
    toolset = ctx.deps.toolset
    if toolset is None or ctx.deps.thread_id is None:
        return f"{tool_name} unavailable: this owner session has no browser toolset"
    arguments["_thread_id"] = str(ctx.deps.thread_id)
    try:
        result = await toolset.execute(tool_name, arguments)
    except (ToolsetError, OSError, ValueError) as exc:
        return f"{tool_name} refused: {str(exc).strip() or type(exc).__name__}"
    if not result.success:
        return f"{tool_name} refused: {result.content}"
    if result.image is None:
        return result.content
    if result.media_type is None:  # pragma: no cover - adapter contract guard
        raise ValueError("browser image result requires a media type")
    return ToolReturn(
        return_value=result.content,
        content=[result.content, BinaryContent(data=result.image, media_type=result.media_type)],
        metadata={"tool": tool_name, "media_type": result.media_type},
    )


async def navigate(ctx: RunContext[MemoryToolContext], url: str) -> str | ToolReturn:
    """Open an allowed URL in this thread's headless browser."""
    return await _execute_browser_tool(ctx, "navigate", {"url": url})


async def click(ctx: RunContext[MemoryToolContext], selector: str) -> str | ToolReturn:
    """Click one element selected with a Playwright locator string."""
    return await _execute_browser_tool(ctx, "click", {"selector": selector})


async def type(ctx: RunContext[MemoryToolContext], selector: str, text: str) -> str | ToolReturn:
    """Replace the value of one selected form field."""
    return await _execute_browser_tool(ctx, "type", {"selector": selector, "text": text})


async def read_page(ctx: RunContext[MemoryToolContext]) -> str | ToolReturn:
    """Read the current page URL, title, and visible body text."""
    return await _execute_browser_tool(ctx, "read_page", {})


async def screenshot(ctx: RunContext[MemoryToolContext]) -> str | ToolReturn:
    """Capture the current page and send the PNG back as model-visible image input."""
    return await _execute_browser_tool(ctx, "screenshot", {})


WORKSPACE_TOOLS = (
    read,
    edit,
    write,
    grep,
    find,
    ls,
    bash,
    move,
    navigate,
    click,
    type,
    read_page,
    screenshot,
)


class WorkspaceCapability(Capability[MemoryToolContext]):
    """The adopted coding and browser tools inside the existing owner loop."""

    def __init__(self) -> None:
        super().__init__(
            id="workspace",
            defer_loading=False,
            instructions=[WORKSPACE_INSTRUCTIONS],
            tools=[Tool(function) for function in WORKSPACE_TOOLS],
        )


class DelegateCapability(Capability[MemoryToolContext]):
    """One bounded worker return through the ordinary Pydantic AI tool seam."""

    def __init__(self) -> None:
        async def delegate_task(ctx: RunContext[MemoryToolContext], task: str) -> str:
            """Delegate a self-contained task; receive a concise result with full work journaled."""
            return await ctx.deps.delegate(task)

        super().__init__(id="delegate", tools=[Tool(delegate_task)], defer_loading=False)


def own_history(messages):
    """D.2 153: worker returns do not contribute to the main thread's fill."""
    return [
        replace(
            message,
            parts=[
                part
                for part in message.parts
                if not isinstance(part, ToolReturnPart) or part.tool_name != "delegate_task"
            ],
        )
        if isinstance(message, ModelRequest)
        else message
        for message in messages
    ]


class CompactionPolicy(BaseModel):
    """Per-thread strategy and model-portable fill policy, persisted in the journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    strategy: Literal["truncate", "summarize", "memories-then-drop", "human-and-final-only"] = (
        "memories-then-drop"
    )
    policy: Literal["performance", "cost"] = "performance"
    fraction: float = Field(default=0.8, gt=0, lt=1, allow_inf_nan=False)
    instructions: str = COMPACTION_SUMMARY_PROMPT


class _HumanFinalCompaction(SlidingWindowCompaction):
    """Our drop strategy in the package slot; pins, pair safety and receipts are upstream."""

    async def compact(self, messages, ctx):
        # Keep the in-flight tool exchange intact, as well as the last final answer.
        cutoff = find_safe_cutoff(messages, 1)
        final = next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, ModelResponse)
                and any(isinstance(part, TextPart) for part in message.parts)
                and not any(isinstance(part, ToolCallPart) for part in message.parts)
            ),
            None,
        )
        retained = []
        for index, message in enumerate(messages):
            if index >= cutoff or message is final:
                retained.append(message)
            elif isinstance(message, ModelRequest):
                parts = [
                    part
                    for part in message.parts
                    if isinstance(part, (UserPromptPart, SystemPromptPart))
                    and not is_receipt_part(part)
                ]
                if parts:
                    retained.append(
                        message if parts == message.parts else replace(message, parts=parts)
                    )
        retained = reinject_pinned(messages, retained)
        if self._without_receipts(retained) == self._without_receipts(messages):
            return messages
        retained = self._without_receipts(retained)
        return [self._receipt_message(self._dropped_messages(messages, retained), ctx), *retained]


class _PreparedSummary(SummarizingCompaction):
    summary: str = ""

    async def _summarize(self, messages, ctx, *, previous_summary=None):
        return self.summary


class _MemoryStrategy:
    def __init__(self, owner):
        self.owner = owner

    async def compact(self, messages, ctx):
        owner = self.owner
        if owner.completed:
            return messages
        window = owner.context_window or resolve_context_window(ctx.model) or 200_000
        options = dict(
            max_messages=1,
            keep_tokens=max(1, window // 5),
            tokenizer=cl100k_token_count,
            receipts=True,
            preserve_first_user_message=False,
        )
        strategy = owner.policy.strategy
        engine = (
            _PreparedSummary(**options)
            if strategy == "summarize"
            else SlidingWindowCompaction(**options)
            if strategy == "truncate"
            else _HumanFinalCompaction(**options)
        )
        # A no-op must not manufacture extraction events on every subsequent tool step.
        if strategy != "summarize":
            proposed = await engine.compact(messages, ctx)
            if proposed == messages:
                return messages
        before = estimate_context_tokens(messages, cl100k_token_count)
        owner.original_history = list(messages)
        await owner.emit.event(
            {"event_kind": "compaction_started", "before_tokens": before, "strategy": strategy}
        )
        result = await owner.service.triage(
            ctx.deps.thread_id,
            _format_messages(own_history(messages)),
            tail=owner.emit.run_id,
            origin="compaction",
            model=ctx.model,
            usage=ctx.usage,
            on_result=owner.on_result,
            model_settings=owner.model_settings,
            summary_prompt=owner.policy.instructions,
        )
        # Admission must finish before any drop; a failed queue write leaves history intact.
        if strategy == "summarize":
            engine.summary = result.working_summary + "\n\n" + "\n".join(result.open_loops)
            proposed = await engine.compact(messages, ctx)
        if proposed == messages:
            return messages
        owner.completed = True
        owner.history = proposed
        event_uid = generate_ulid()
        owner.service._journal.append_compaction_history(
            str(ctx.deps.thread_id),
            owner.emit.run_id,
            to_jsonable_python(proposed),
        )
        await owner.emit.event(
            {
                "event_kind": "compaction_memories",
                "candidate_count": len(result.cards),
                "working_summary": result.working_summary,
                "open_loops": result.open_loops,
            }
        )
        await owner.emit.event(
            {
                "event_kind": "compaction_completed",
                "before_tokens": before,
                "after_tokens": estimate_token_count(proposed, cl100k_token_count),
                "event_uid": event_uid,
                "strategy": strategy,
            }
        )
        try:
            await owner.service._spine.notify_compaction(event_uid, ctx.deps.thread_id)
        except SpineClientError:
            await owner.emit.event(
                {
                    "event_kind": "compaction_optimizer_unavailable",
                    "message": "History compacted; the Palace could not start optimization.",
                }
            )
        return proposed


class MemoryCompaction(TieredCompaction):
    """Upstream escalation/usage accounting with our queue-before-drop strategy."""

    def __init__(
        self, service, emit, window=None, on_result=None, *, policy=None, model_settings=None
    ):
        self.policy = policy or CompactionPolicy()
        self.service, self.emit, self.on_result = service, emit, on_result
        self.model_settings = model_settings
        self.completed = False
        self.history = []
        self.original_history = []
        super().__init__(
            tiers=[_MemoryStrategy(self)],
            target_fraction=self.policy.fraction,
            context_window=window,
            tokenizer=cl100k_token_count,
        )

    def compaction_transcript_handle(self):
        return self.emit.run_id

    async def before_model_request(self, ctx, request_context):
        messages = request_context.messages
        worker_tokens = estimate_token_count(messages, self.tokenizer) - estimate_token_count(
            own_history(messages),
            self.tokenizer,
        )
        # D.2 153: worker bulk cannot cause the main thread's entropy event.
        own_tokens = (
            estimate_context_tokens(
                messages,
                self.tokenizer,
                model_request_parameters=request_context.model_request_parameters,
            )
            - worker_tokens
        )
        target = self._target(request_context.model)
        if target is None or own_tokens <= target:
            return request_context
        return await super().before_model_request(ctx, request_context)

    async def manual(self, messages, *, model, deps, usage):
        return await compact_now(
            self.tiers[0],
            list(messages),
            model=model,
            deps=deps,
            usage=usage,
            tokenizer=self.tokenizer,
        )
