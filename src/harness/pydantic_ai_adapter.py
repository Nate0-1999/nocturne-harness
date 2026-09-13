"""The single adapter from harness capabilities to pydantic-ai v2."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import BinaryContent, RunContext, ToolReturn
from pydantic_ai.capabilities import Capability
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.tools import Tool
from pydantic_ai_harness.compaction import SummarizingCompaction
from pydantic_ai_harness.compaction._shared import estimate_token_count
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
    "If a tool refuses a boundary crossing, explain the wall plainly; do not retry around it."
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
        replace(message, parts=[
            part for part in message.parts
            if not isinstance(part, ToolReturnPart) or part.tool_name != "delegate_task"
        ]) if isinstance(message, ModelRequest) else message
        for message in messages
    ]


class MemoryCompaction(SummarizingCompaction):
    """Adopt the upstream summary strategy; triage and persistence remain ours."""

    def __init__(self, service, emit, window: int, on_result=None):
        # D.2 153: the existing Context Bars working line is 80% of the model maximum.
        super().__init__(
            max_fraction=0.8, context_window=window,
            keep_tokens=window // 5, tokenizer=cl100k_token_count,
            preserve_first_user_message=False,
        )
        self.service = service
        self.emit = emit
        self.completed = False
        self.on_result = on_result

    async def before_model_request(self, ctx, request_context):
        before = estimate_token_count(own_history(request_context.messages), self.tokenizer)
        if before <= int(self.context_window * self.max_fraction):
            return request_context
        await self.emit.event({"event_kind": "compaction_started", "before_tokens": before})
        # Keep the upstream cutoff, tool-call integrity, anchored summary and retained tail.
        compacted = await self.compact(list(request_context.messages), ctx)
        if compacted != request_context.messages:
            self.completed = True
            event_uid = generate_ulid()
            self.service._journal.append_compaction_history(
                str(ctx.deps.thread_id), self.emit.run_id, to_jsonable_python(compacted),
            )
            await self.emit.event({
                "event_kind": "compaction_completed", "before_tokens": before,
                "after_tokens": estimate_token_count(own_history(compacted), self.tokenizer),
                "event_uid": event_uid,
            })
            try:
                await self.service._spine.notify_compaction(event_uid, ctx.deps.thread_id)
            except SpineClientError:
                await self.emit.event({
                    "event_kind": "compaction_optimizer_unavailable",
                    "message": "History compacted; the Palace could not start optimization.",
                })
        request_context.messages = compacted
        return request_context

    async def _summarize(self, messages, ctx, *, previous_summary=None):
        prompt = _format_messages(
            messages, skip_previous_summary=previous_summary is not None,
        )
        if previous_summary:
            prompt += (
                "\nUpdate this earlier summary in place: preserve still-true details, "
                "remove stale details, and merge new facts.\n" + previous_summary
            )
        result = await self.service.triage(
            ctx.deps.thread_id, prompt, tail=self.emit.run_id, origin="compaction",
            model=ctx.model, usage=ctx.usage, on_result=self.on_result,
        )
        await self.emit.event({
            "event_kind": "compaction_memories", "candidate_count": len(result.cards),
            "working_summary": result.working_summary, "open_loops": result.open_loops,
        })
        return result.working_summary + (
            "\n\n## Open questions\n" + "\n".join(result.open_loops) if result.open_loops else ""
        )
