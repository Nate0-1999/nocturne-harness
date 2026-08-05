import ast
import inspect
from pathlib import Path

import pydantic_ai
import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.capabilities import Capability
from pydantic_ai.models.test import TestModel

from harness.capability import (
    CapabilityDefinition,
    CapabilityEventStreamTap,
    CapabilityHistoryTransform,
    CapabilityInstruction,
    CapabilityLifecycleHook,
    CapabilityTool,
)
from harness.memory_capability import DEFAULT_MEMORY_FEATURE, MEMORY_INSTRUCTION
from harness.pydantic_ai_adapter import MemoryCapability
from harness.tools_memory import MemoryToolContext, edit_memory, save_memory, search_memory

EXPECTED_MEMORY_INSTRUCTION = (
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


def test_capability_contract_is_owned_typed_and_frozen() -> None:
    """ADR-005 is defended by verifying that capability contract is owned typed and frozen;
    this prevents drift in the owned memory capability seam.
    """
    definition = DEFAULT_MEMORY_FEATURE.definition

    assert isinstance(definition, CapabilityDefinition)
    assert set(CapabilityInstruction.model_fields) == {"text"}
    assert set(CapabilityTool.model_fields) == {"name", "description", "handler"}
    assert set(CapabilityDefinition.model_fields) == {
        "id",
        "instructions",
        "tools",
        "lifecycle_hooks",
        "history_transforms",
        "event_stream_taps",
    }
    assert definition.id == "memory"
    assert [instruction.text for instruction in definition.instructions] == [
        EXPECTED_MEMORY_INSTRUCTION
    ]
    assert [tool.name for tool in definition.tools] == [
        "save_memory",
        "search_memory",
        "edit_memory",
    ]
    assert [tool.handler for tool in definition.tools] == [save_memory, search_memory, edit_memory]
    assert [tool.description for tool in definition.tools] == [
        save_memory.__doc__.strip(),
        search_memory.__doc__.strip(),
        edit_memory.__doc__.strip(),
    ]
    assert definition.lifecycle_hooks == ()
    assert definition.history_transforms == ()
    assert definition.event_stream_taps == ()
    assert set(CapabilityLifecycleHook.model_fields) == {"name", "handler"}
    assert set(CapabilityHistoryTransform.model_fields) == {"name", "handler"}
    assert set(CapabilityEventStreamTap.model_fields) == {"name", "handler"}

    with pytest.raises(ValidationError):
        definition.id = "changed"
    with pytest.raises(ValidationError):
        definition.instructions[0].text = "changed"
    with pytest.raises(ValidationError):
        CapabilityInstruction(text="ok", unexpected=True)


def test_c6_memory_instruction_is_verbatim() -> None:
    """ADR-005 is defended by verifying that c6 memory instruction is verbatim; this prevents
    drift in the owned memory capability seam.
    """
    assert MEMORY_INSTRUCTION == EXPECTED_MEMORY_INSTRUCTION


def test_owned_save_handler_keeps_project_scope_required_and_force_optional() -> None:
    """ADR-005 is defended by verifying that owned save handler keeps project scope required
    and force optional; this prevents drift in the owned memory capability seam.
    """
    parameters = inspect.signature(save_memory).parameters

    assert parameters["project_scoped"].default is inspect.Parameter.empty
    assert parameters["force"].default is False


@pytest.mark.asyncio
async def test_vanilla_agent_discovers_three_memory_tools_and_instruction() -> None:
    """ADR-005 is defended by verifying that vanilla agent discovers three memory tools and
    instruction; this prevents drift in the owned memory capability seam.
    """
    assert pydantic_ai.__version__ == "2.12.0"
    model = TestModel(call_tools=[], custom_output_text="ok")
    capability = MemoryCapability()
    agent = Agent(
        model,
        deps_type=MemoryToolContext,
        capabilities=[capability],
    )

    result = await agent.run("hello", deps=object())

    assert result.output == "ok"
    parameters = model.last_model_request_parameters
    assert parameters is not None
    assert [tool.name for tool in parameters.function_tools] == [
        "save_memory",
        "search_memory",
        "edit_memory",
    ]
    assert [part.content for part in parameters.instruction_parts or []] == [
        EXPECTED_MEMORY_INSTRUCTION
    ]
    assert isinstance(capability, Capability)
    assert capability.id == "memory"
    assert capability.defer_loading is False


@pytest.mark.asyncio
async def test_adapted_tool_schemas_defaults_descriptions_and_capability_id() -> None:
    """ADR-005 is defended by verifying that adapted tool schemas defaults descriptions and
    capability id; this prevents drift in the owned memory capability seam.
    """
    model = TestModel(call_tools=[], custom_output_text="ok")
    agent = Agent(model, deps_type=MemoryToolContext, capabilities=[MemoryCapability()])
    await agent.run("hello", deps=object())
    parameters = model.last_model_request_parameters
    assert parameters is not None
    tools = {tool.name: tool for tool in parameters.function_tools}

    save_schema = tools["save_memory"].parameters_json_schema
    assert set(save_schema["properties"]) == {
        "label",
        "body",
        "kind",
        "keywords",
        "project_scoped",
        "force",
    }
    assert set(save_schema["required"]) == {"label", "body", "kind", "project_scoped"}
    assert save_schema["properties"]["keywords"]["default"] is None
    assert save_schema["properties"]["force"]["default"] is False
    assert save_schema["properties"]["kind"] == {"$ref": "#/$defs/MemoryKind"}
    assert save_schema["$defs"]["MemoryKind"]["enum"] == [
        "fact",
        "preference",
        "procedure",
        "project_note",
        "persona",
        "pinned",
    ]

    search_schema = tools["search_memory"].parameters_json_schema
    assert set(search_schema["properties"]) == {"query", "k"}
    assert search_schema["required"] == ["query"]
    assert search_schema["properties"]["k"]["default"] == 5

    edit_schema = tools["edit_memory"].parameters_json_schema
    assert set(edit_schema["properties"]) == {"label_or_id", "new_body", "reason"}
    assert set(edit_schema["required"]) == {"label_or_id", "new_body", "reason"}

    expected_descriptions = {
        "save_memory": save_memory.__doc__.strip(),
        "search_memory": search_memory.__doc__.strip(),
        "edit_memory": edit_memory.__doc__.strip(),
    }
    for name, tool in tools.items():
        assert tool.description == expected_descriptions[name]
        assert tool.capability_id == "memory"


def test_pydantic_ai_capability_imports_are_fenced_to_adapter() -> None:
    """ADR-005 is defended by verifying that pydantic ai capability imports are fenced to
    adapter; this prevents drift in the owned memory capability seam.
    """
    package_root = Path(__file__).parents[1] / "src" / "harness"
    offenders: list[str] = []
    capability_modules = (
        "pydantic_ai.capabilities",
        "pydantic_ai.tools",
        "pydantic_ai.toolsets",
    )
    capability_names = {
        "AbstractCapability",
        "AgentCapability",
        "Capability",
        "ProcessEventStream",
        "ProcessHistory",
        "RunContext",
        "Tool",
        "ToolDefinition",
        "capabilities",
        "tools",
        "toolsets",
    }

    for path in package_root.rglob("*.py"):
        if path.name == "pydantic_ai_adapter.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imports_capability_module = node.module.startswith(capability_modules)
                imports_capability_name = node.module == "pydantic_ai" and any(
                    alias.name in capability_names for alias in node.names
                )
                if imports_capability_module or imports_capability_name:
                    offenders.append(str(path.relative_to(package_root)))
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "pydantic_ai" or alias.name.startswith(capability_modules)
                    for alias in node.names
                ):
                    offenders.append(str(path.relative_to(package_root)))

    assert offenders == []


@pytest.mark.asyncio
async def test_adapter_executes_the_owned_feature_handler() -> None:
    """ADR-005 is defended by verifying that adapter executes the owned feature handler; this
    prevents drift in the owned memory capability seam.
    """
    calls: list[tuple[str, int, str]] = []

    async def owned_search(
        context: MemoryToolContext,
        query: str,
        k: int = 5,
    ) -> str:
        calls.append((query, k, context.principal_id))
        return "owned search result"

    definition = DEFAULT_MEMORY_FEATURE.definition.model_copy(
        update={
            "tools": tuple(
                tool.model_copy(update={"handler": owned_search})
                if tool.name == "search_memory"
                else tool
                for tool in DEFAULT_MEMORY_FEATURE.definition.tools
            )
        }
    )

    class OwnedFeature:
        @property
        def definition(self) -> CapabilityDefinition:
            return definition

    model = TestModel(call_tools=["search_memory"])
    agent = Agent(
        model,
        deps_type=MemoryToolContext,
        capabilities=[MemoryCapability(OwnedFeature())],
    )
    context = MemoryToolContext(
        spine=object(),
        principal_id="principal-owned",
        machine_id="machine-1",
        agent_id="agent-1",
    )

    result = await agent.run("find the memory", deps=context)

    assert calls == [("a", 5, "principal-owned")]
    assert "owned search result" in result.output
