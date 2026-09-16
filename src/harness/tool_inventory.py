"""Describe the installed tool unit and the skills actually available to a thread."""

from importlib.metadata import version
from typing import Literal

from pydantic import BaseModel

from harness.memory_capability import DEFAULT_MEMORY_FEATURE
from harness.pydantic_ai_adapter import WORKSPACE_TOOLS
from harness.pydantic_harness_adapter import adopted_skills
from harness.tools_memory import MemoryToolContext


class ToolsetSelection(BaseModel):
    toolset: Literal["pydantic", "none"] = "pydantic"


class ToolInventoryEntry(BaseModel):
    name: str
    kind: Literal["tool", "skill"]
    source: str
    version: str
    description: str
    enabled: bool


class ToolInventory(BaseModel):
    thread_id: str
    toolset: Literal["pydantic", "none"]
    entries: list[ToolInventoryEntry]


def inventory(context: MemoryToolContext) -> ToolInventory:
    """Use the same tool functions and adopted skill catalog as the runner. [PLAN M3TH]"""
    harness_version = version("nocturne-harness")
    upstream_version = version("pydantic-ai-harness")
    browser_version = version("playwright")
    entries = []
    own_source = f"https://github.com/Nate0-1999/nocturne-harness/tree/v{harness_version}"
    for tool in DEFAULT_MEMORY_FEATURE.definition.tools:
        entries.append(ToolInventoryEntry(
            name=tool.name, kind="tool", source=own_source, version=harness_version,
            description=tool.description, enabled=True,
        ))
    for function in WORKSPACE_TOOLS:
        name = function.__name__
        if name in {"navigate", "click", "type", "read_page", "screenshot"}:
            release, source = browser_version, "https://github.com/microsoft/playwright-python"
        elif name == "move":
            release, source = harness_version, "https://github.com/Nate0-1999/nocturne-harness"
        else:
            release, source = upstream_version, "https://github.com/pydantic/pydantic-ai-harness"
        entries.append(ToolInventoryEntry(
            name=name, kind="tool", source=f"{source}/tree/v{release}", version=release,
            description=function.__doc__ or "", enabled=context.toolset_enabled,
        ))
    skills = adopted_skills(context.skill_directories)
    entries.append(ToolInventoryEntry(
        name="delegate_task", kind="tool", source=own_source, version=harness_version,
        description="Delegate a bounded task and receive its concise result.",
        enabled=context.toolset_enabled,
    ))
    if skills:
        runtime_version = version("pydantic-ai")
        entries.append(ToolInventoryEntry(
            name="load_capability", kind="tool",
            source=f"https://github.com/pydantic/pydantic-ai/tree/v{runtime_version}",
            version=runtime_version, description="Load a deferred skill.",
            enabled=context.toolset_enabled,
        ))
    for skill in skills:
        entries.append(ToolInventoryEntry(
            name=skill.id, kind="skill", source=skill.source, version=skill.version,
            description=skill.description or "", enabled=context.toolset_enabled,
        ))
    return ToolInventory(
        thread_id=str(context.thread_id),
        toolset="pydantic" if context.toolset_enabled else "none", entries=entries,
    )
