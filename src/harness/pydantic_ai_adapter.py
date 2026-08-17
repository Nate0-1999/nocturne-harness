"""The single adapter from harness capabilities to pydantic-ai v2."""

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext
from pydantic_ai.capabilities import Capability
from pydantic_ai.tools import Tool

from harness.capability import CapabilityHandler, CapabilityTool, HarnessCapability
from harness.memory_capability import DEFAULT_MEMORY_FEATURE
from harness.spine_client import MemoryKind
from harness.tools_memory import MemoryToolContext
from harness.toolset import ToolName, ToolsetError

WORKSPACE_INSTRUCTIONS = (
    "Use move in its own tool step before edit, write, or bash in another directory. "
    "Reads are free. Writes and bash are confined to the current location. "
    "If a tool refuses a boundary crossing, explain the wall plainly; do not retry around it."
)


def _adapt_save(handler: CapabilityHandler) -> Tool[MemoryToolContext]:
    async def adapted_save(
        ctx: RunContext[MemoryToolContext],
        label: str,
        body: str,
        kind: MemoryKind,
        *,
        keywords: list[str] | None = None,
        project_scoped: bool,
        force: bool = False,
    ) -> str:
        return await handler(
            ctx.deps,
            label=label,
            body=body,
            kind=kind,
            keywords=keywords,
            project_scoped=project_scoped,
            force=force,
        )

    return Tool(adapted_save)


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
    "save_memory": _adapt_save,
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
            raise ValueError("MemoryCapability requires exactly the three C.6 memory tools")
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
    """Replace exact text in a file inside the current location."""
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
    """Create or replace a file inside the current location."""
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


WORKSPACE_TOOLS = (read, edit, write, grep, find, ls, bash, move)


class WorkspaceCapability(Capability[MemoryToolContext]):
    """The adopted PI file and shell tools inside the existing owner loop."""

    def __init__(self) -> None:
        super().__init__(
            id="workspace",
            defer_loading=False,
            instructions=[WORKSPACE_INSTRUCTIONS],
            tools=[Tool(function) for function in WORKSPACE_TOOLS],
        )
