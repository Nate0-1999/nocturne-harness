"""Framework-free definition of the C.6 memory capability."""

from harness.capability import CapabilityDefinition, CapabilityInstruction, CapabilityTool
from harness.tools_memory import edit_memory, search_memory

MEMORY_INSTRUCTION = (
    "Search existing memories when useful and edit them to correct an established fact. "
    "New memories are proposed only when this conversation is compacted or closed. "
    "The owner can explicitly save with /remember. Do not claim a new memory was saved "
    "during a chat turn. Never store secrets or credentials."
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
        tools=tuple(_tool(handler) for handler in (search_memory, edit_memory)),
    )


DEFAULT_MEMORY_FEATURE = MemoryFeature()
