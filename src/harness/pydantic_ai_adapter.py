"""The single adapter from harness capabilities to pydantic-ai v2."""

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import BinaryContent, ModelRetry, RunContext, ToolReturn
from pydantic_ai.capabilities import AbstractCapability, Capability
from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart
from pydantic_ai.tools import Tool, ToolDefinition
from spine.tokens import cl100k_token_count

from harness.capability import CapabilityHandler, CapabilityTool, HarnessCapability
from harness.context_window import ContextCut, cut_notice
from harness.memory_capability import DEFAULT_MEMORY_FEATURE
from harness.pydantic_harness_adapter import adopted_skills, message_tokens
from harness.tools_memory import MemoryToolContext
from harness.toolset import ToolName, ToolsetError

WORKSPACE_INSTRUCTIONS = (
    "To edit or write a file, you must use move in its own tool step to enter that file's "
    "directory first. Reads are free. Bash may modify files only within the current location's "
    "subtree; git commands on this repository work from any folder inside it. "
    "When the user names a discoverable skill, call load_capability with that skill's id "
    "before following its instructions or reading its bundled resources. "
    "Never ask a permission question in chat. The PermissionJudge handles outside-file requests. "
    "Reserved owner decisions go to the Deck. Never retry around a refused wall."
    " Browser tools are headless and default to localhost or files beneath the current location."
    " Never ask the owner for consent inside a tool call; a refused open-web request must wait"
    " for the owner's exact `/browser allow-web` command."
    # M3W5B-06, Codex M3W5A-03 and -13: no invented results, no plan in place of a change.
    " Report only what tool results showed: never say you moved, changed or ran something"
    " without its tool result, and when a search finds nothing, say so instead of naming"
    " files you have not seen. When the user asks for a change, make it with the tools;"
    " do not stop at a plan unless the user asked for one."
)


def _replace_flag(ctx: RunContext[MemoryToolContext]) -> dict[str, bool]:
    """M3W5B-01: the user's own words, never the model's, allow replacing most of a file."""

    latest = next(
        (
            part.content
            for message in reversed(ctx.messages)
            for part in reversed(getattr(message, "parts", ()))
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        ),
        "",
    )
    prompt = [ctx.prompt] if isinstance(ctx.prompt, str) else list(ctx.prompt or ())
    request = "\n".join([*(item for item in prompt if isinstance(item, str)), latest])
    said = re.search(r"\b(?:replace|rewrite|overwrite)", request, re.IGNORECASE) is not None
    return {"replace": True} if said else {}


class PendingSteering(Capability[MemoryToolContext]):
    """A correction arriving during final text still gets a model request. [FL-075]"""

    def __init__(self, pending: Callable[[], bool]):
        super().__init__()
        self.pending = pending

    async def after_model_request(self, ctx, *, request_context, response):
        if not response.tool_calls and self.pending():
            raise ModelRetry("Apply the new human instruction before finishing.")
        return response


_PROMISED_WORK = re.compile(
    r"\b(?:I will|I'll|I am going to|I'm going to|would you like me to|shall I|should I)\b",
    re.IGNORECASE,
)


class FinishWhatWasAsked(Capability[MemoryToolContext]):
    """Codex M3W5A-13; the M3CL2 walk on gpt-4.1-mini: answers ending "To fix this, I will…"
    and "Would you like me to proceed with committing?" ended the turn with the asked-for work
    undone. Once per run, such an ending is sent back: finish it, or say plainly why not; never
    on the budget's last, tool-less request."""

    def __init__(self) -> None:
        super().__init__()
        self.sent = False

    async def after_model_request(self, ctx, *, request_context, response):
        last = not request_context.model_request_parameters.function_tools
        if (
            self.sent
            or last
            or response.tool_calls
            or not _PROMISED_WORK.search(response.text[-400:])
        ):
            return response
        self.sent = True
        raise ModelRetry(
            "Your answer ends by promising or asking about work the user already asked for. "
            "Do it now with the tools; if you cannot, say plainly what is not done and why."
        )


class FinishFactCheck(Capability[MemoryToolContext]):
    """Gate ruling 2026-10-01 (M3CL2): gpt-4.1-mini told the user it had added a test it had
    only written into a memory edit. Once per turn that changed the repository, the final
    answer is checked against the repository as it is, by the loop, before the turn ends."""

    def __init__(self, facts: Callable[[], str | None]) -> None:
        super().__init__()
        self.facts = facts
        self.sent = False

    async def after_model_request(self, ctx, *, request_context, response):
        last = not request_context.model_request_parameters.function_tools
        if self.sent or last or response.tool_calls or (facts := self.facts()) is None:
            return response
        self.sent = True
        raise ModelRetry(
            f"Before you finish, check your answer against the repository as it is now. {facts} "
            "Correct anything your answer claims that these facts do not show; if something "
            "asked for is not done, do it now or say plainly why not. If your answer already "
            "matches, reply only: Checked."
        )


class TurnBudgetNotice(Capability[MemoryToolContext]):
    """Gate ruling 2026-10-01 (M3CL2): runs that spun into the 500,000-token wall fail, and a
    soft notice did not stop gpt-4.1-mini. When this request and one more of its size would
    cross the turn's token limit, or it is the last request the count allows, it goes out with
    no tools and asks for a plain account, so the turn ends inside its budget."""

    async def before_model_request(self, ctx, request_context):
        limits, usage, latest = ctx.usage_limits, ctx.usage, request_context.messages[-1]
        if limits is None or not isinstance(latest, ModelRequest):
            return request_context
        requests, tokens = limits.request_limit, limits.total_tokens_limit
        size = message_tokens(request_context.messages)
        last = (requests and usage.requests + 1 >= requests) or (
            tokens and usage.total_tokens + 2 * size >= tokens
        )
        if not last:
            return request_context
        latest.parts.append(
            UserPromptPart(
                f"This is the last model request this turn's budget allows ({usage.requests} "
                f"requests and {usage.total_tokens:,} tokens used; the turn stops at "
                f"{requests or 'no'} requests or {tokens or 'no'} tokens), so tools are off for "
                "it. Tell the user plainly what is done, what is not, and why; they can send "
                '"continue" to go on.'
            )
        )
        return replace(
            request_context,
            model_request_parameters=replace(
                request_context.model_request_parameters, function_tools=[]
            ),
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


async def _prepare_memory_tool(
    ctx: RunContext[MemoryToolContext],
    definition: ToolDefinition,
) -> ToolDefinition | None:
    return definition if getattr(ctx.deps, "memory_enabled", True) else None


def _adapt_tool(spec: CapabilityTool) -> Tool[MemoryToolContext]:
    """Pair an owned tool spec with its explicit contextual schema."""
    try:
        adapter = _CONTEXTUAL_ADAPTERS[spec.name]
    except KeyError as exc:
        raise ValueError(f"unsupported memory tool: {spec.name}") from exc
    tool = adapter(spec.handler)
    tool.name = spec.name
    tool.description = spec.description
    tool.prepare = _prepare_memory_tool
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
            **_replace_flag(ctx),
        },
    )


async def write(ctx: RunContext[MemoryToolContext], path: str, content: str) -> str:
    """Create or replace a file in the current directory."""
    return await _execute_workspace_tool(
        ctx,
        "write",
        {"path": path, "content": content, **_replace_flag(ctx)},
    )


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
    """Run a shell command inside the current location's OS sandbox and wait for it to finish.

    The turn waits for it, so never use it for anything meant to keep running; use start_shell.
    """
    # M3W5B-08: "start a background shell" in plain words ran here and blocked the turn.
    arguments: dict[str, object] = {"command": command}
    if timeout is not None:
        arguments["timeout"] = timeout
    return await _execute_workspace_tool(ctx, "bash", arguments)


async def move(ctx: RunContext[MemoryToolContext], path: str) -> str:
    """Move the agent's current location to a directory inside this workspace."""
    return await _execute_workspace_tool(ctx, "move", {"path": path})


async def start_shell(ctx: RunContext[MemoryToolContext], command: str) -> str:
    """Start a background shell and return at once with its ID; it keeps running across turns.

    Use it whenever the user asks for a background shell, a server, a watcher or a loop that
    keeps running. It stops with stop_shell or when Nocturne exits.
    """
    return await _execute_workspace_tool(ctx, "start_shell", {"command": command})


async def read_shell(ctx: RunContext[MemoryToolContext], command_id: str) -> str:
    """Read the state and output of a background shell belonging to this thread."""
    return await _execute_workspace_tool(ctx, "read_shell", {"command_id": command_id})


async def stop_shell(ctx: RunContext[MemoryToolContext], command_id: str) -> str:
    """Explicitly stop a background shell and return its final output."""
    return await _execute_workspace_tool(ctx, "stop_shell", {"command_id": command_id})


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
    start_shell,
    read_shell,
    stop_shell,
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
        async def delegate_task(
            ctx: RunContext[MemoryToolContext], task: str, share_percent: float | None = None
        ) -> str:
            """Delegate a self-contained task; receive a concise result with full work journaled.

            share_percent: how much of the compaction limit the return may take, within the
            system bounds; the default share applies when omitted.
            """
            return await ctx.deps.delegate(task, share_percent)

        super().__init__(id="delegate", tools=[Tool(delegate_task)], defer_loading=False)


class ReturnShareCapability(AbstractCapability[MemoryToolContext]):
    """FL-198: a query result over its share is not delivered; an error with a head is."""

    id: str | None = "return_share"

    async def after_tool_execute(
        self,
        ctx: RunContext[MemoryToolContext],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        share = ctx.deps.return_share
        if share is None or call.tool_name == "delegate_task":
            return result
        text = result.return_value if isinstance(result, ToolReturn) else result
        if not isinstance(text, str):
            return result
        size = cl100k_token_count(text)
        if size <= share.tokens:
            return result
        cut = ContextCut(
            thread_id=str(ctx.deps.thread_id),
            agent_id=ctx.deps.agent_id,
            at=datetime.now(UTC),
            kind="query",
            source=call.tool_name,
            size_tokens=size,
            share=share,
            action="cut",
        )
        if ctx.deps.record_cut is not None:
            await ctx.deps.record_cut(cut, text)
        return cut_notice(cut, text, journaled=ctx.deps.record_cut is not None)
