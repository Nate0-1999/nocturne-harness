"""Framework-free definition of the C.6 memory capability."""

from harness.capability import CapabilityDefinition, CapabilityInstruction, CapabilityTool
from harness.tools_memory import edit_memory, save_memory, search_memory

MEMORY_INSTRUCTION = (
    "Save a memory when you learn a durable user preference, a correction to "
    "something you got wrong, a stable project fact, or a procedure the user "
    "wants repeated. Keep every memory ATOMIC: one fact per unit, at most a "
    "few sentences (hard cap 128 tokens); split larger content into multiple "
    "units. ALWAYS include 2-5 lowercase keywords (searchable nouns/terms — "
    "a memory without keywords is handicapped in retrieval). Prefer editing "
    "an existing memory over creating a near-duplicate. "
    "When a project-scoped save reports that no current project exists, surface "
    "that result and do not retry the save globally in the same turn. A global "
    "fallback requires explicit user confirmation in a later user turn. Never "
    "save secrets or credentials."
)


def _tool(handler: object) -> CapabilityTool:
    """Build a tool spec from the handler's sole model-facing description."""
    name = getattr(handler, "__name__", None)
    description = getattr(handler, "__doc__", None)
    if not isinstance(name, str) or not isinstance(description, str) or not description.strip():
        raise TypeError("memory tool handlers must have a name and model-facing docstring")
    return CapabilityTool(name=name, description=description.strip(), handler=handler)


class MemoryFeature:
    """Harness-owned memory feature consumed through ``HarnessCapability``."""

    definition = CapabilityDefinition(
        id="memory",
        instructions=(CapabilityInstruction(text=MEMORY_INSTRUCTION),),
        tools=tuple(_tool(handler) for handler in (save_memory, search_memory, edit_memory)),
    )


DEFAULT_MEMORY_FEATURE = MemoryFeature()
