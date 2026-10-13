from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from spine.tokens import cl100k_token_count

from harness.agent import (
    EXTRACTION_INSTRUCTION,
    LEAVE_SECRET_OUT,
    REMEMBER_DRAFT_INSTRUCTION,
    REMEMBER_SPLIT_INSTRUCTION,
    TOO_LONG,
    ChatResult,
    ExtractionCandidateDraft,
    ExtractionDraft,
    HarnessAgent,
    ModelConfigurationError,
    RememberDraft,
    RememberResult,
    RememberSplitDraft,
    fact_problems,
    resolve_model,
)
from harness.config import HarnessSettings
from harness.envelope import EnvelopeFactory
from harness.memory_outbox import MemoryOutbox
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    CreateMemoryRequest,
    CreateMemorySplitResponse,
    DuplicateMemoryConflict,
    LabelConflict,
    ListMemoriesParams,
    MemoryKind,
    MemorySplitRequest,
    MemorySplitResponse,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryRequest,
    PatchMemoryResponse,
    ProblemDetail,
    SimilarMemoriesResponse,
    SpineClientError,
    SpineProblemError,
    SpineTransportError,
)
from harness.tools_memory import MemoryToolContext
from harness.toolset import ToolExecutionResult, ToolName

MEMORY_ID = UUID("12345678-1234-5678-1234-567812345678")
THREAD_ID = UUID("22345678-1234-5678-1234-567812345678")
SPLIT_SOURCE_ID = UUID("32345678-1234-5678-1234-567812345678")
SPLIT_CHILD_ONE_ID = UUID("42345678-1234-5678-1234-567812345678")
SPLIT_CHILD_TWO_ID = UUID("52345678-1234-5678-1234-567812345678")
SPLIT_CHILD_THREE_ID = UUID("62345678-1234-5678-1234-567812345678")
LIVE_OPERATION_HEAD = (
    "This verification dossier contains three independent facts that must remain separate. "
)
LIVE_FACT_ONE = (
    "The temporary observatory ledger uses a silver cover, and its only purpose is to "
    "record nightly calibration checks for this run; it must never be treated as owner biography. "
)
LIVE_FACT_TWO = (
    "The temporary calibration lantern is stored on the eastern shelf, is tagged with "
    "the code LANTERN-SEVEN, and is returned there after every measurement; this location is "
    "unrelated to the ledger. "
)
LIVE_FACT_THREE = (
    "The disposable weather card says that a north wind pauses the calibration procedure "
    "until the instrument settles, and that card is destroyed when verification ends. "
)
LIVE_OPERATION_TAIL = (
    "These facts describe different objects, different duties, and different lifetimes. "
    "Preserve all of their meaning and provenance, but split them into atomic durable memories "
    "instead of truncating or blending them. The entire paragraph is intentionally above the "
    "single-memory cap so the guided split behavior is observable."
)
LIVE_SPLIT_SOURCE = (
    LIVE_OPERATION_HEAD + LIVE_FACT_ONE + LIVE_FACT_TWO + LIVE_FACT_THREE + LIVE_OPERATION_TAIL
)


@dataclass
class FakeSpine:
    outcome: CreatedMemoryResponse | SimilarMemoriesResponse | SpineClientError
    split_outcome: CreateMemorySplitResponse | SpineClientError | None = None
    create_requests: list[CreateMemoryRequest] = field(default_factory=list)
    split_requests: list[MemorySplitRequest] = field(default_factory=list)
    memories: list[MemoryUnit] = field(default_factory=list)
    patch_outcome: PatchMemoryResponse | SpineClientError | None = None
    list_requests: list[ListMemoriesParams] = field(default_factory=list)
    patch_requests: list[tuple[UUID, PatchMemoryRequest]] = field(default_factory=list)

    async def create_memory(
        self, request: CreateMemoryRequest
    ) -> CreatedMemoryResponse | SimilarMemoriesResponse:
        self.create_requests.append(request)
        if isinstance(self.outcome, SpineClientError):
            raise self.outcome
        return self.outcome

    async def create_memory_split(self, request: MemorySplitRequest) -> CreateMemorySplitResponse:
        self.split_requests.append(request)
        if self.split_outcome is None:
            raise AssertionError("unexpected split call")
        if isinstance(self.split_outcome, SpineClientError):
            raise self.split_outcome
        return self.split_outcome

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        self.list_requests.append(params)
        return PagedMemoryListResponse(
            items=self.memories[params.offset : params.offset + params.limit],
            total=len(self.memories),
            limit=params.limit,
            offset=params.offset,
        )

    async def search(self, request):
        from harness.spine_client import SearchResponse, SimilarityMemoryCard

        return SearchResponse(
            results=[
                SimilarityMemoryCard(
                    memory_id=item.memory_id,
                    label=item.label,
                    body=item.body,
                    kind=item.kind,
                    pin=item.pin,
                    score=1.0,
                    features=None,
                    rank=None,
                )
                for item in self.memories
                if item.body == request.query
            ]
        )

    async def patch_memory(
        self,
        memory_id: UUID,
        request: PatchMemoryRequest,
    ) -> PatchMemoryResponse:
        self.patch_requests.append((memory_id, request))
        if self.patch_outcome is None:
            raise AssertionError("unexpected patch call")
        if isinstance(self.patch_outcome, SpineClientError):
            raise self.patch_outcome
        return self.patch_outcome


def settings(**overrides: Any) -> HarnessSettings:
    values = {
        "spine_token": None,
        "anthropic_api_key": None,
        "openai_api_key": None,
        "openrouter_api_key": None,
        "chat_model": "openrouter:minimax/minimax-m3",
        "run_request_limit": 40,
        "run_total_tokens_limit": 500_000,
        "label_max": 64,
        **overrides,
    }
    return HarnessSettings(_env_file=None, **values)


def memory_unit(
    *,
    memory_id: UUID = MEMORY_ID,
    label: str = "Editor preference",
    body: str = "Use tabs.",
    status: MemoryStatus = MemoryStatus.ACTIVE,
    revision: int = 1,
    reinforcements: int | None = None,
) -> MemoryUnit:
    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    return MemoryUnit(
        memory_id=memory_id,
        principal_id="principal-1",
        label=label,
        body=body,
        kind=MemoryKind.FACT,
        keywords=[],
        project_key=None,
        thread_origin=str(THREAD_ID),
        origin_thread_id=THREAD_ID,
        origin_path="/workspace/notes.md",
        pin=False,
        status=status,
        revision=revision,
        stats={} if reinforcements is None else {"reinforcements": reinforcements},
        bias=0,
        embedding_model="text-embedding-3-small",
        created_at=now,
        updated_at=now,
    )


def similar_response() -> SimilarMemoriesResponse:
    return SimilarMemoriesResponse(
        created=None,
        similar=[
            {
                "memory_id": MEMORY_ID,
                "label": "Existing preference",
                "body": "Use tabs.",
                "kind": "preference",
                "pin": False,
                "score": 0.86,
                "features": None,
                "rank": None,
            }
        ],
    )


def context(spine: FakeSpine) -> MemoryToolContext:
    return MemoryToolContext(
        spine=spine,
        principal_id="principal-1",
        machine_id="machine-1",
        agent_id="agent-1",
        thread_id=THREAD_ID,
        project_key="project-that-remember-must-ignore",
        origin_path="/workspace/notes.md",
    )


@dataclass
class FakeWorkspaceToolset:
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    async def execute(
        self, tool_name: ToolName, arguments: dict[str, object]
    ) -> ToolExecutionResult:
        self.calls.append((tool_name, arguments))
        return ToolExecutionResult(tool_name=tool_name, content="Wrote note.txt", success=True)


def conflict_response() -> httpx.Response:
    return httpx.Response(
        409,
        request=httpx.Request("POST", "http://spine.test/v1/memories"),
    )


def response_model(text: str, calls: list[tuple[list[ModelMessage], AgentInfo]]) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append((list(messages), info))
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(respond, model_name=f"local:{text[:12]}")


def remember_model(
    label: str,
    keywords: list[str],
    calls: list[tuple[list[ModelMessage], AgentInfo]],
) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append((list(messages), info))
        return ModelResponse(parts=[TextPart(json.dumps({"label": label, "keywords": keywords}))])

    return FunctionModel(respond, model_name=f"local:{label[:12]}")


def structured_sequence_model(
    outputs: list[dict[str, object]],
    calls: list[tuple[list[ModelMessage], AgentInfo]],
) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append((list(messages), info))
        if not outputs:
            raise AssertionError("unexpected model request")
        return ModelResponse(parts=[TextPart(json.dumps(outputs.pop(0)))])

    return FunctionModel(respond, model_name="local:remember-sequence")


def split_response(source: str) -> MemorySplitResponse:
    return MemorySplitResponse(
        source=memory_unit(
            memory_id=SPLIT_SOURCE_ID,
            label="Split source",
            body=source,
            status=MemoryStatus.TOMBSTONED,
        ),
        created=[
            memory_unit(
                memory_id=SPLIT_CHILD_ONE_ID,
                label="Observatory ledger duty",
                body=LIVE_FACT_ONE.strip(),
            ),
            memory_unit(
                memory_id=SPLIT_CHILD_TWO_ID,
                label="Calibration lantern location",
                body=LIVE_FACT_TWO.strip(),
            ),
            memory_unit(
                memory_id=SPLIT_CHILD_THREE_ID,
                label="North-wind calibration pause",
                body=LIVE_FACT_THREE.strip(),
            ),
        ],
    )


@pytest.mark.parametrize(
    ("model_name", "key_field", "environment_name", "provider_name"),
    [
        ("openrouter:minimax/minimax-m3", "openrouter_api_key", "OPENROUTER_API_KEY", "openrouter"),
        ("anthropic:claude-sonnet-4-6", "anthropic_api_key", "ANTHROPIC_API_KEY", "anthropic"),
        ("openai:gpt-4o-mini", "openai_api_key", "OPENAI_API_KEY", "openai"),
        ("openai-chat:gpt-4o-mini", "openai_api_key", "OPENAI_API_KEY", "openai"),
        ("openai-responses:gpt-4o-mini", "openai_api_key", "OPENAI_API_KEY", "openai"),
    ],
)
def test_resolve_model_uses_settings_key_not_ambient_environment(
    monkeypatch,
    model_name: str,
    key_field: str,
    environment_name: str,
    provider_name: str,
) -> None:
    """ADR-013 is defended by verifying that resolve model uses settings key not ambient
    environment; this prevents drift in the agent composition and explicit model boundary.
    """
    monkeypatch.setenv(environment_name, "ambient-key-must-not-win")
    resolved = resolve_model(model_name, settings(**{key_field: "settings-owned-key"}))

    assert resolved.provider is not None
    assert resolved.provider.name == provider_name
    assert resolved.provider.client.api_key == "settings-owned-key"


@pytest.mark.parametrize(
    ("model_name", "environment_name"),
    [
        ("openrouter:minimax/minimax-m3", "OPENROUTER_API_KEY"),
        ("anthropic:claude-sonnet-4-6", "ANTHROPIC_API_KEY"),
        ("openai:gpt-4o-mini", "OPENAI_API_KEY"),
        ("openai-chat:gpt-4o-mini", "OPENAI_API_KEY"),
        ("openai-responses:gpt-4o-mini", "OPENAI_API_KEY"),
    ],
)
def test_resolve_model_rejects_missing_settings_key_even_if_ambient_key_exists(
    monkeypatch, model_name: str, environment_name: str
) -> None:
    """ADR-013 is defended by verifying that resolve model rejects missing settings key even if
    ambient key exists; this prevents drift in the agent composition and explicit model
    boundary.
    """
    monkeypatch.setenv(environment_name, "ambient-key-must-not-win")

    with pytest.raises(ModelConfigurationError, match=f"{environment_name} is required"):
        resolve_model(model_name, settings())


def test_resolve_model_uses_pydantic_provider_registry_for_other_model_strings(
    monkeypatch,
) -> None:
    """ADR-013 is defended by verifying that resolve model uses pydantic provider registry for
    other model strings; this prevents drift in the agent composition and explicit model
    boundary.
    """
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")

    resolved = resolve_model("ollama:llama3.2", settings())

    assert resolved.provider is not None
    assert resolved.provider.name == "ollama"


def test_resolve_model_rejects_a_string_unknown_to_pydantic_ai() -> None:
    """ADR-013 is defended by verifying that resolve model rejects a string unknown to pydantic
    ai; this prevents drift in the agent composition and explicit model boundary.
    """
    with pytest.raises(ModelConfigurationError, match="Unknown provider"):
        resolve_model("not-a-provider:model", settings())


def test_resolve_model_normalizes_a_missing_optional_provider_dependency(
    monkeypatch,
) -> None:
    """ADR-013 is defended by verifying that resolve model normalizes a missing optional
    provider dependency; this prevents drift in the agent composition and explicit model
    boundary.
    """

    def missing_provider_dependency(name: str) -> None:
        raise ImportError(f"missing optional dependency for {name}")

    monkeypatch.setattr("harness.model_router.infer_provider", missing_provider_dependency)

    with pytest.raises(
        ModelConfigurationError,
        match="provider dependency is unavailable.*bedrock",
    ):
        resolve_model("bedrock:anthropic.claude-v2", settings())


def test_agent_lazily_resolves_only_the_selected_model() -> None:
    """ADR-013 is defended by verifying that agent lazily resolves only the selected model;
    this prevents drift in the agent composition and explicit model boundary.
    """
    agent = HarnessAgent(
        settings(
            chat_model="anthropic:claude-sonnet-4-6",
            anthropic_api_key=None,
            openrouter_api_key="test-openrouter-key",
        )
    )

    selected = agent.model_for("openrouter:minimax/minimax-m3")

    assert selected is agent.model_for("openrouter:minimax/minimax-m3")


@pytest.mark.asyncio
async def test_chat_returns_output_and_reusable_full_history_with_exact_limits() -> None:
    """ADR-013 is defended by verifying that chat returns output and reusable full history with
    exact limits; this prevents drift in the agent composition and explicit model boundary.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append((list(messages), info))
        return ModelResponse(parts=[TextPart(f"turn-{len(calls)}")])

    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=FunctionModel(respond))

    first = await agent.chat("hello", context=context(spine))
    second = await agent.chat(
        "again",
        context=context(spine),
        message_history=first.message_history,
    )

    assert first.output == "turn-1"
    assert second.output == "turn-2"
    assert second.message_history[: len(first.message_history)] == first.message_history
    assert len(second.message_history) > len(first.message_history)
    assert agent.usage_limits.request_limit == 40
    assert agent.usage_limits.total_tokens_limit == 500_000
    assert all(
        [tool.name for tool in info.function_tools]
        == [
            "search_memory",
            "edit_memory",
            "read",
            "edit",
            "write",
            "grep",
            "find",
            "ls",
            "bash",
            "start_shell",
            "read_shell",
            "stop_shell",
            "move",
            "navigate",
            "click",
            "type",
            "read_page",
            "screenshot",
        ]
        for _, info in calls
    )
    assert spine.create_requests == []


@pytest.mark.asyncio
async def test_disabled_toolset_removes_workspace_and_skills_from_model_request(
    tmp_path: Path,
) -> None:
    """ADR-013 / PLAN M3TH removes the adopted tool unit at the provider boundary."""
    skill = tmp_path / "verification"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: verification\ndescription: A verification skill.\n---\nRead marker.txt.\n"
    )
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    agent = HarnessAgent(settings(), model=response_model("No workspace tools.", calls))
    owner_context = replace(
        context(FakeSpine(CreatedMemoryResponse(created=memory_unit()))),
        toolset_enabled=False,
        skill_directories=(tmp_path,),
    )

    result = await agent.chat("List the tools you can use.", context=owner_context)

    assert result.output == "No workspace tools."
    assert [tool.name for tool in calls[0][1].function_tools] == [
        "search_memory",
        "edit_memory",
    ]


@pytest.mark.asyncio
async def test_chat_executes_adopted_workspace_tool_inside_the_existing_owner_loop() -> None:
    """ADR-015 keeps adopted file acts inside the existing owner-loop authority."""

    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        has_result = any(
            isinstance(message, ModelRequest)
            and any(isinstance(part, ToolReturnPart) for part in message.parts)
            for message in messages
        )
        if has_result:
            return ModelResponse(parts=[TextPart("The file is ready.")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "write",
                    {"path": "note.txt", "content": "owner text\n"},
                    "workspace-call-1",
                )
            ]
        )

    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    toolset = FakeWorkspaceToolset()
    owner_context = context(spine)
    owner_context = MemoryToolContext(
        spine=owner_context.spine,
        principal_id=owner_context.principal_id,
        machine_id=owner_context.machine_id,
        agent_id=owner_context.agent_id,
        thread_id=owner_context.thread_id,
        project_key=owner_context.project_key,
        origin_path=owner_context.origin_path,
        toolset=toolset,  # type: ignore[arg-type]
    )
    agent = HarnessAgent(settings(), model=FunctionModel(respond))

    result = await agent.chat("Write my note.", context=owner_context)

    assert result.output == "The file is ready."
    assert toolset.calls == [("write", {"path": "note.txt", "content": "owner text\n"})]


@pytest.mark.asyncio
async def test_label_agent_is_separate_and_has_no_tools() -> None:
    """ADR-013 is defended by verifying that label agent is separate and has no tools; this
    prevents drift in the agent composition and explicit model boundary.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = remember_model("Short label", ["short", "label"], calls)
    agent = HarnessAgent(settings(), model=model)

    result = await agent.label_agent.run("label this")

    assert result.output == RememberDraft(
        label="Short label",
        keywords=["short", "label"],
    )
    assert len(calls) == 1
    assert calls[0][1].function_tools == []
    assert calls[0][1].output_tools == []
    assert calls[0][1].instructions is not None
    assert calls[0][1].instructions.startswith(REMEMBER_DRAFT_INSTRUCTION)
    assert '"label"' in calls[0][1].instructions
    assert '"keywords"' in calls[0][1].instructions
    assert agent.label_agent is not agent.chat_agent


@pytest.mark.asyncio
async def test_a049_remember_splitter_is_tools_free_and_lossless_by_instruction() -> None:
    """F027, A-049, v2.133 and SPEC B.6 rule 12 are defended here.
    The semantic splitter is a separate tools-free boundary; the application keeps the source.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {
                "candidates": [
                    {
                        "label": "Garden cadence",
                        "body": "The garden review happens weekly.",
                        "keywords": ["garden", "cadence"],
                    }
                ],
            }
        ],
        calls,
    )
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember_splitter_agent.run("split this", model=model)

    assert isinstance(result.output, RememberSplitDraft)
    assert len(calls) == 1
    assert calls[0][1].function_tools == []
    assert calls[0][1].output_tools == []
    assert calls[0][1].instructions is not None
    assert calls[0][1].instructions.startswith(REMEMBER_SPLIT_INSTRUCTION)
    assert "self-contained fact sentence that names its own subject" in calls[0][1].instructions
    assert "Split only where there is more than one distinct fact" in calls[0][1].instructions
    assert "broken at its cleanest seam into finer facts" in calls[0][1].instructions
    assert "only repetition is shortened" in calls[0][1].instructions
    assert "prefer 2-5 words and under 40 characters" in calls[0][1].instructions
    assert "never facts" in calls[0][1].instructions
    assert "The application keeps the exact source" in calls[0][1].instructions
    assert "coverage" not in calls[0][1].instructions
    schema = RememberSplitDraft.model_json_schema()
    assert set(schema["properties"]) == {"candidates"}
    assert schema["$defs"]["RememberSplitCandidate"]["properties"]["label"]["maxLength"] == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/remember", "/remember ", "/remember\n\t"])
async def test_empty_remember_command_is_visible_and_does_not_call_model_or_spine(
    command: str,
) -> None:
    """ADR-013 is defended by verifying that empty remember command is visible and does not
    call model or spine; this prevents drift in the agent composition and explicit model
    boundary.
    """
    model = TestModel(call_tools=[], custom_output_text="must not run")
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.dispatch(command, context=context(spine))

    assert result == RememberResult(
        ok=False,
        message="Nothing to remember; add text after /remember.",
    )
    assert model.last_model_request_parameters is None
    assert spine.create_requests == []


@pytest.mark.asyncio
async def test_remember_allows_framework_metadata_retry_within_run_limits() -> None:
    """F075: a structured-output retry must not hit a bespoke one-request budget."""
    calls = []
    model = structured_sequence_model(
        [
            {"label": "Retry needs keywords"},
            {"label": "Editor preference", "keywords": ["editor", "tabs"]},
        ],
        calls,
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    usage = RunUsage()
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(
        "Use tabs.",
        context=context(spine),
        usage=usage,
        raise_model_errors=True,
    )

    assert result.ok
    assert len(calls) == usage.requests == 2
    assert len(spine.create_requests) == 1
    assert spine.create_requests[0].body == "Use tabs."
    assert agent.usage_limits.total_tokens_limit == agent._settings.run_total_tokens_limit


@pytest.mark.asyncio
async def test_remember_uses_selected_model_once_without_tools_and_maps_project_user_fact() -> None:
    """F046/F041 and ADR-005 require remember to inherit the trusted thread project while
    the metadata call remains tools-free and on the explicit selected model.
    """
    default_model = TestModel(call_tools=[], custom_output_text="wrong model")
    selected_calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    selected_model = remember_model(
        "Editor preference",
        ["Editor", "tabs", "editor"],
        selected_calls,
    )
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit(label="Editor preference", body="Use tabs."))
    )
    agent = HarnessAgent(settings(), model=default_model)
    routing_settings = {
        "extra_body": {"session_id": "thread-remember"},
        "openrouter_provider": {"sort": "price"},
    }

    result = await agent.dispatch(
        "/remember   Use tabs.  ",
        context=context(spine),
        model=selected_model,
        model_settings=routing_settings,
    )

    assert result == RememberResult(
        ok=True,
        message=f"Remembered 'Editor preference' ({MEMORY_ID}).",
        memory_id=MEMORY_ID,
        label="Editor preference",
    )
    assert len(selected_calls) == 1
    assert selected_calls[0][1].function_tools == []
    assert selected_calls[0][1].output_tools == []
    assert selected_calls[0][1].instructions is not None
    assert selected_calls[0][1].instructions.startswith(REMEMBER_DRAFT_INSTRUCTION)
    assert selected_calls[0][1].model_settings == routing_settings
    assert default_model.last_model_request_parameters is None
    assert len(spine.create_requests) == 1
    request = spine.create_requests[0]
    assert request.principal_id == "principal-1"
    assert request.label == "Editor preference"
    assert request.body == "Use tabs."
    assert request.kind is MemoryKind.FACT
    assert request.keywords == ["editor", "tabs"]
    assert request.project_key == "project-that-remember-must-ignore"
    assert request.thread_origin == str(THREAD_ID)
    assert request.origin_path == "/workspace/notes.md"
    assert request.editor == "user"
    assert request.machine_id == "machine-1"
    assert request.force is False
    assert spine.split_requests == []


@pytest.mark.asyncio
async def test_m3fd_long_single_fact_shortens_without_splitting() -> None:
    """SPEC B.6 / SD-062: length alone never turns one fact into a split family."""
    source = ("The verification release color is amber. " * 30).strip()
    body = "The verification release color is amber."
    model = structured_sequence_model(
        [
            {
                "candidates": [
                    {"label": "Release color", "body": body, "keywords": ["release", "amber"]}
                ],
            }
        ],
        [],
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))

    result = await HarnessAgent(settings(), model=model).remember(source, context=context(spine))

    assert result.ok
    assert [request.body for request in spine.create_requests] == [body]
    assert spine.split_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_draft", ["over-cap", "malformed"])
async def test_over_cap_single_fact_uses_remaining_request_to_finish_shortening(
    invalid_draft: str,
) -> None:
    """SPEC C.6 / v2.133 / FL-002: an over-cap draft goes back with the owner's words; a
    malformed one is retried; either way the fact is saved."""
    source = ("The verification release color is amber. " * 30).strip()
    body = "The verification release color is amber."
    calls = []
    drafts = [
        {
            "candidates": [
                {"label": "Release color", "body": text, "keywords": ["release", "amber"]}
            ],
        }
        for text in (source, body)
    ]
    if invalid_draft == "malformed":
        drafts[0] = {}
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=structured_sequence_model(drafts, calls))
    result = await agent.remember(source, context=context(spine))
    assert result.ok
    assert len(calls) == 2
    if invalid_draft == "over-cap":
        repair = calls[1][0][-1].parts[-1].content
        assert repair.startswith("This memory is too long, break it down into finer pieces.")
    assert [request.body for request in spine.create_requests] == [body]
    assert spine.split_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stalled_requests", [1, 2])
async def test_long_remember_retries_a_stall_without_exceeding_its_budget(
    stalled_requests: int,
) -> None:
    """SPEC B.6 / F178: a live first-request stall must not consume both permitted attempts."""
    body = "The verification release color is amber."
    calls = []

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append((messages, info))
        if len(calls) <= stalled_requests:
            await asyncio.Event().wait()
        return ModelResponse(
            parts=[
                TextPart(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "label": "Release color",
                                    "body": body,
                                    "keywords": ["release", "amber"],
                                }
                            ],
                        }
                    )
                )
            ]
        )

    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    usage = RunUsage()
    agent = HarnessAgent(settings(remember_split_timeout_seconds=0.2), model=FunctionModel(respond))
    result = await asyncio.wait_for(
        agent.remember((body + " ") * 30, context=context(spine), usage=usage),
        timeout=1,
    )
    assert len(calls) == 2
    assert result.ok == (stalled_requests == 1)
    assert [request.body for request in spine.create_requests] == (
        [body] if stalled_requests == 1 else []
    )
    if stalled_requests == 1:
        assert usage.requests == 2
    else:
        assert "took too long" in result.message


@pytest.mark.asyncio
async def test_m3fd_two_short_facts_split_even_below_body_cap() -> None:
    """SPEC B.6 / SD-062: fact count, not paragraph length, determines a split."""
    source = "Release color is amber. Review day is Tuesday."
    model = structured_sequence_model(
        [
            {"label": "Release facts", "keywords": ["release", "review"], "multiple_facts": True},
            {
                "candidates": [
                    {
                        "label": "Release color",
                        "body": "Release color is amber.",
                        "keywords": ["release", "amber"],
                    },
                    {
                        "label": "Review day",
                        "body": "Review day is Tuesday.",
                        "keywords": ["review", "tuesday"],
                    },
                ],
            },
        ],
        [],
    )
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit()), split_outcome=split_response(source)
    )

    result = await HarnessAgent(settings(), model=model).remember(source, context=context(spine))

    assert result.ok
    assert spine.create_requests == []
    assert len(spine.split_requests) == 1
    assert spine.split_requests[0].source_body == source
    assert len(spine.split_requests[0].children) == 2


@pytest.mark.asyncio
async def test_two_short_facts_joined_by_a_semicolon_are_saved() -> None:
    """M3EX-16 / F080: "a; b." saves as "a." and "b."; the separator is not a changed fact."""
    source = "Web tests run with npm test; Python tests run with pytest -q."
    model = structured_sequence_model(
        [
            {"label": "Test commands", "keywords": ["tests", "npm"], "multiple_facts": True},
            {
                "candidates": [
                    {
                        "label": "Web test command",
                        "body": "Web tests run with npm test.",
                        "keywords": ["web", "npm"],
                    },
                    {
                        "label": "Python test command",
                        "body": "Python tests run with pytest -q.",
                        "keywords": ["python", "pytest"],
                    },
                ],
            },
        ],
        [],
    )
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit()), split_outcome=split_response(source)
    )

    result = await HarnessAgent(settings(), model=model).remember(source, context=context(spine))

    assert result.ok
    assert [child.body for child in spine.split_requests[0].children] == [
        "Web tests run with npm test.",
        "Python tests run with pytest -q.",
    ]


@pytest.mark.asyncio
async def test_a049_oversized_multi_claim_uses_one_atomic_split_with_exact_source() -> None:
    """F027, A-049, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    An oversized multi-claim source must become one linked atomic request with exact provenance.
    """
    source = LIVE_SPLIT_SOURCE
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {
                "candidates": [
                    {
                        "label": "Observatory ledger duty",
                        "body": LIVE_FACT_ONE.strip(),
                        "keywords": ["observatory", "ledger"],
                    },
                    {
                        "label": "Calibration lantern location",
                        "body": LIVE_FACT_TWO.strip(),
                        "keywords": ["lantern", "shelf"],
                    },
                    {
                        "label": "North-wind calibration pause",
                        "body": LIVE_FACT_THREE.strip(),
                        "keywords": ["weather", "calibration"],
                    },
                ],
            }
        ],
        calls,
    )
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit()),
        split_outcome=split_response(source),
    )
    usage = RunUsage()
    agent = HarnessAgent(settings(), model=model)

    result = await agent.dispatch(
        f"/remember   {source}  ",
        context=context(spine),
        usage=usage,
    )

    assert result == RememberResult(
        ok=True,
        message=(
            "Remembered 3 linked memories: 'Observatory ledger duty', "
            "'Calibration lantern location', 'North-wind calibration pause'."
        ),
        memory_id=SPLIT_SOURCE_ID,
        label="Split source",
    )
    assert len(calls) == 1
    assert usage.requests == 1
    assert spine.create_requests == []
    assert len(spine.split_requests) == 1
    request = spine.split_requests[0]
    assert request.source_body == source
    assert [child.model_dump() for child in request.children] == [
        {
            "label": "Observatory ledger duty",
            "body": LIVE_FACT_ONE.strip(),
            "keywords": ["observatory", "ledger"],
        },
        {
            "label": "Calibration lantern location",
            "body": LIVE_FACT_TWO.strip(),
            "keywords": ["lantern", "shelf"],
        },
        {
            "label": "North-wind calibration pause",
            "body": LIVE_FACT_THREE.strip(),
            "keywords": ["weather", "calibration"],
        },
    ]
    assert request.principal_id == "principal-1"
    assert request.thread_origin == str(THREAD_ID)
    assert request.origin_path == "/workspace/notes.md"
    assert request.editor == "user"
    assert request.machine_id == "machine-1"


@pytest.mark.asyncio
async def test_a049_overlong_label_single_claim_reuses_exact_source_through_ordinary_create() -> (
    None
):
    """F027, A-049, ADR-022, and SPEC B.6 rule 12 are defended here.
    An overlong label gets one fallback while a fitting single claim keeps exact-body creation.
    """
    source = "The garden review happens weekly."
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {"label": "L" * 65, "keywords": ["garden", "cadence"]},
            {
                "candidates": [
                    {
                        "label": "Garden cadence",
                        "body": source,
                        "keywords": ["Garden", "cadence"],
                    }
                ],
            },
        ],
        calls,
    )
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit(label="Garden cadence", body=source))
    )
    usage = RunUsage()
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine), usage=usage)

    assert result.ok is True
    assert len(calls) == 2
    assert usage.requests == 2
    assert len(spine.create_requests) == 1
    assert spine.create_requests[0].body == source
    assert spine.create_requests[0].label == "Garden cadence"
    assert spine.create_requests[0].keywords == ["garden", "cadence"]
    assert spine.split_requests == []


@pytest.mark.asyncio
async def test_a049_single_atomic_oversized_claim_is_saved_after_three_repairs() -> None:
    """SPEC C.6 / v2.133 / FL-002: repairs that never fit still save the shortest valid form; the
    fact is never refused."""
    source = ("The complete indivisible claim retains this qualifier. " * 80).strip()
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    draft = {
        "candidates": [
            {
                "label": "Indivisible claim",
                "body": source,
                "keywords": ["indivisible", "qualifier"],
            }
        ],
    }
    model = structured_sequence_model([draft] * 4, calls)
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result.ok
    assert len(calls) == 4
    assert all(
        "this memory is too long, break it down into finer pieces"
        in str(call[0][-1].parts[-1].content).lower()
        for call in calls[1:]
    )
    [saved] = [request.body for request in spine.create_requests]
    assert cl100k_token_count(saved) <= 128
    assert source.startswith(saved.removesuffix("\u2026"))


@pytest.mark.asyncio
async def test_a050_single_fitting_candidate_never_persists_excluded_operation_text() -> None:
    """F027, A-050, v2.133: the saved fact leaves out the directions about remembering it."""
    source = "Remember this: The observatory ledger has a silver cover."
    model = structured_sequence_model(
        [
            {"label": "L" * 65, "keywords": ["ledger", "silver"]},
            {
                "candidates": [
                    {
                        "label": "Observatory ledger cover",
                        "body": "The observatory ledger has a silver cover.",
                        "keywords": ["ledger", "silver"],
                    }
                ],
            },
        ],
        [],
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result.ok
    assert [request.body for request in spine.create_requests] == [
        "The observatory ledger has a silver cover."
    ]
    assert spine.split_requests == []


@pytest.mark.asyncio
async def test_a050_label_triggered_single_candidate_is_saved_not_refused() -> None:
    """SPEC C.6 / v2.133: a draft the code checks pass is saved; never a bare refusal."""
    source = "The lantern is east, and the separate ledger is silver."
    model = structured_sequence_model(
        [
            {"label": "L" * 65, "keywords": ["lantern", "ledger"]},
            {
                "candidates": [
                    {
                        "label": "Unsafe combined facts",
                        "body": source,
                        "keywords": ["lantern", "ledger"],
                    }
                ],
            },
        ],
        [],
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result.ok
    assert [request.body for request in spine.create_requests] == [source]


@pytest.mark.asyncio
async def test_a049_split_near_similar_copy_never_offers_nonexistent_force() -> None:
    """F027, A-049, ADR-022, and SPEC B.6 rule 12 are defended here.
    An atomic split 200 names the no-write result and a lawful remedy without a force fiction.
    """
    source = "Fact one. Fact two."
    model = structured_sequence_model(
        [
            {
                "candidates": [
                    {"label": "First", "body": "Fact one.", "keywords": ["fact", "one"]},
                    {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
                ],
            }
        ],
        [],
    )
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit()),
        split_outcome=similar_response(),
    )
    agent = HarnessAgent(settings(memory_max_tokens=4), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result.message == (
        "Not saved: a proposed split memory is similar to existing memory "
        f"'Existing preference' ({MEMORY_ID}), so none of the split was saved. "
        "Review or update the existing memory as needed, remove that already-covered claim "
        "from the source, then try /remember again with the remaining facts."
    )
    assert result.ok is False
    assert "force" not in result.message.lower()
    assert spine.create_requests == []
    assert len(spine.split_requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidates",
    [
        pytest.param(
            [
                {"label": "Same", "body": "Fact one.", "keywords": ["fact", "one"]},
                {"label": "Same", "body": "Fact two.", "keywords": ["fact", "two"]},
            ],
            id="duplicate-label",
        ),
        pytest.param(
            [
                {"label": "First", "body": "Same fact.", "keywords": ["fact", "one"]},
                {"label": "Second", "body": "Same fact.", "keywords": ["fact", "two"]},
            ],
            id="duplicate-body",
        ),
        pytest.param(
            [
                {"label": "First\nline", "body": "Fact one.", "keywords": ["fact", "one"]},
                {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
            ],
            id="multiline-label",
        ),
        pytest.param(
            [
                {
                    "label": "First",
                    "body": "Fact one.",
                    "keywords": ["same", "SAME", "other"],
                },
                {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
            ],
            id="duplicate-keyword",
        ),
    ],
)
async def test_a049_imperfect_split_draft_is_repaired_in_code_and_saved(
    candidates: list[dict[str, object]],
) -> None:
    """SPEC C.6 / v2.133 / A-049: label, keyword and repeat slips are repaired in code and the
    facts are saved beside their exact source; never a refusal."""
    source = " ".join(str(candidate["body"]) for candidate in candidates)
    model = structured_sequence_model([{"candidates": candidates}], [])
    spine = FakeSpine(
        CreatedMemoryResponse(created=memory_unit()), split_outcome=split_response(source)
    )
    agent = HarnessAgent(settings(memory_max_tokens=5), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result.ok
    children = (
        spine.split_requests[0].children
        if spine.split_requests
        else [request for request in spine.create_requests]
    )
    assert len({child.body for child in children}) == len(children)
    assert len({child.label for child in children}) == len(children)
    assert all("\n" not in child.label for child in children)
    assert all(child.keywords == [word.lower() for word in child.keywords] for child in children)
    assert all(len(set(child.keywords)) == len(child.keywords) for child in children)
    if spine.split_requests:
        assert spine.split_requests[0].source_body == source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("   ", "generated label was blank"),
        ("first line\nsecond line", "generated label was not one line"),
    ],
)
async def test_invalid_generated_label_is_rejected_without_calling_spine(
    label: str, expected: str
) -> None:
    """ADR-013 is defended by verifying that invalid generated label is rejected without
    calling spine; this prevents drift in the agent composition and explicit model boundary.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(
        settings(),
        model=remember_model(label, ["editor", "tabs"], calls),
    )

    result = await agent.remember("Use tabs.", context=context(spine))

    assert result.ok is False
    assert expected in result.message
    assert len(calls) == 1
    assert spine.create_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("keywords", "saved"),
    [
        ([], ["editor", "preference"]),
        (["only"], ["only", "editor"]),
        (["same", "SAME"], ["same", "editor"]),
        (["one", "two", "three", "four", "five", "six"], ["one", "two", "three", "four", "five"]),
        (["one", "   "], ["one", "editor"]),
    ],
)
async def test_f165_generated_keywords_that_break_the_rule_are_retried_then_trimmed(
    keywords: list[str], saved: list[str]
) -> None:
    """F165 is defended by verifying that generated keywords outside the 2-5 distinct rule are
    generated once more, then cut to the first five distinct terms, with the label's words
    filling a short list, so the fact is saved rather than refused.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(
        settings(),
        model=remember_model("Editor preference", keywords, calls),
    )

    result = await agent.remember("Use tabs.", context=context(spine))

    assert result.ok is True
    assert len(calls) == 2
    assert [request.keywords for request in spine.create_requests] == [saved]


@pytest.mark.asyncio
async def test_f165_the_flags_refused_sentence_is_remembered() -> None:
    """F165 is defended by verifying that the exact /remember the walk saw refused is saved when
    both generations break the keyword rule: the first five distinct terms are kept.
    """
    sentence = "The M3UI2 walk project keeps one icon size of 16 pixels in every module."
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit(body=sentence)))
    agent = HarnessAgent(
        settings(),
        model=structured_sequence_model(
            [
                {
                    "label": "M3UI2 icon size",
                    "keywords": ["m3ui2", "icon", "size", "16", "pixels", "module"],
                },
                {"label": "M3UI2 icon size", "keywords": ["icon"]},
            ],
            calls,
        ),
    )

    result = await agent.dispatch(f"/remember {sentence}", context=context(spine))

    assert result.ok is True
    assert len(calls) == 2
    assert [
        (request.label, request.body, request.keywords) for request in spine.create_requests
    ] == [("M3UI2 icon size", sentence, ["icon", "m3ui2", "size", "16", "pixels"])]


@pytest.mark.asyncio
async def test_f165_a_fact_too_short_to_file_is_refused_with_a_way_on() -> None:
    """F165 is defended by verifying that a one-word fact, which cannot carry two distinct
    keywords (A-049), is refused with words the person can act on and nothing is saved.
    """
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=remember_model("Tabs", ["tabs"], []))

    result = await agent.remember("tabs", context=context(spine))

    assert result == RememberResult(
        False, "Could not remember: add a few words to the fact so it can be found again."
    )
    assert spine.create_requests == []


def duplicate_conflict() -> CreateMemoryConflictError:
    duplicate = similar_response().similar[0]
    return CreateMemoryConflictError(
        conflict_response(),
        DuplicateMemoryConflict(duplicate_of=duplicate),
    )


def label_conflict() -> CreateMemoryConflictError:
    return CreateMemoryConflictError(
        conflict_response(),
        LabelConflict(label_conflict={"memory_id": MEMORY_ID, "label": "Existing preference"}),
    )


def problem_error() -> SpineProblemError:
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "http://spine.test/v1/memories"),
    )
    return SpineProblemError(
        response,
        ProblemDetail(title="Spine unavailable", detail="try later", status=503),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (similar_response(), "looks similar"),
        (label_conflict(), "label already belongs"),
        (problem_error(), "try later"),
        (SpineTransportError(), "memory service unavailable"),
    ],
    ids=["similar", "label", "problem", "transport"],
)
async def test_remember_failures_are_truthful_visible_non_success(
    outcome: CreatedMemoryResponse | SimilarMemoriesResponse | SpineClientError,
    expected: str,
) -> None:
    """ADR-013 is defended by verifying that remember failures are truthful visible non
    success; this prevents drift in the agent composition and explicit model boundary.
    """
    spine = FakeSpine(outcome)
    agent = HarnessAgent(
        settings(),
        model=TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"label": "New fact", "keywords": ["new", "fact"]}),
        ),
    )

    result = await agent.remember("A durable fact.", context=context(spine))

    assert result.ok is False
    assert expected in result.message
    assert not result.message.startswith("Remembered ")
    assert result.memory_id is None
    assert result.label is None
    assert len(spine.create_requests) == (2 if expected == "label already belongs" else 1)


@pytest.mark.asyncio
async def test_remember_hard_duplicate_records_plain_reinforcement() -> None:
    """F038, SPEC C.4 v2.14, and B.6 r12 require `/remember` hard duplicates to
    become one auditable reinforcement instead of raw transport JSON.
    """
    existing = memory_unit(label="Existing preference")
    reinforced = memory_unit(label="Existing preference", revision=2, reinforcements=1)
    spine = FakeSpine(
        duplicate_conflict(),
        memories=[existing],
        patch_outcome=reinforced,
    )
    agent = HarnessAgent(
        settings(),
        model=TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"label": "New fact", "keywords": ["new", "fact"]}),
        ),
    )

    result = await agent.remember("A durable fact.", context=context(spine))

    assert result == RememberResult(
        True,
        "Already known — reinforced 'Existing preference'.",
        memory_id=MEMORY_ID,
        label="Existing preference",
    )
    assert spine.list_requests == [
        ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200, offset=0)
    ]
    assert spine.patch_requests == [
        (
            MEMORY_ID,
            PatchMemoryRequest(
                expected_revision=1,
                body="Use tabs.",
                editor="user",
                reason="remember/reinforce",
                machine_id="machine-1",
            ),
        )
    ]


@pytest.mark.asyncio
async def test_two_clause_resave_reinforces_whole_before_splitting() -> None:
    """M3MQ / F158: metadata must not split a fact that already exists whole."""
    body = "Use tabs. Run the checks before committing."
    existing = memory_unit(body=body)
    reinforced = memory_unit(body=body, revision=2, reinforcements=1)
    spine = FakeSpine(duplicate_conflict(), memories=[existing], patch_outcome=reinforced)
    calls = []
    model = structured_sequence_model(
        [{"label": "Workflow", "keywords": ["tabs", "checks"], "multiple_facts": True}], calls
    )

    result = await HarnessAgent(settings(), model=model).remember(body, context=context(spine))

    assert result.ok and "reinforced" in result.message
    assert len(calls) == 1
    assert spine.create_requests == spine.split_requests == []
    assert spine.patch_requests[0][1].body == body


@pytest.mark.asyncio
async def test_remember_near_duplicate_guides_edit_without_transport_details() -> None:
    """M4MW and SPEC C.4 require the similarity and explicit save-anyway choice;
    displaying the choice must never itself authorize a force write.
    """
    spine = FakeSpine(similar_response())
    agent = HarnessAgent(
        settings(),
        model=TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"label": "New fact", "keywords": ["new", "fact"]}),
        ),
    )

    result = await agent.remember("A durable fact.", context=context(spine))

    assert result.ok is False
    assert "Open Memory and edit" in result.message
    assert "0.860" in result.message
    assert "/remember --save-anyway A durable fact." in result.message
    assert "force=true" not in result.message
    assert str(MEMORY_ID) not in result.message
    assert spine.patch_requests == []
    assert spine.create_requests[0].force is False

    spine.outcome = CreatedMemoryResponse(created=memory_unit(body="A durable fact."))
    confirmed = await agent.dispatch(
        "/remember --save-anyway A durable fact.", context=context(spine)
    )
    assert confirmed.ok
    assert spine.create_requests[-1].body == "A durable fact."
    assert spine.create_requests[-1].force is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ordinary_text",
    ["/remembered", "/remembering this", "/remember: this", " /remember this", "/Remember this"],
)
async def test_near_miss_remember_commands_are_ordinary_chat(ordinary_text: str) -> None:
    """ADR-013 is defended by verifying that near miss remember commands are ordinary chat;
    this prevents drift in the agent composition and explicit model boundary.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=response_model("ordinary chat", calls))

    result = await agent.dispatch(ordinary_text, context=context(spine))

    assert isinstance(result, ChatResult)
    assert result.output == "ordinary chat"
    assert result.message_history
    assert len(calls) == 1
    assert [tool.name for tool in calls[0][1].function_tools] == [
        "search_memory",
        "edit_memory",
        "read",
        "edit",
        "write",
        "grep",
        "find",
        "ls",
        "bash",
        "start_shell",
        "read_shell",
        "stop_shell",
        "move",
        "navigate",
        "click",
        "type",
        "read_page",
        "screenshot",
    ]
    assert spine.create_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verdict,targets",
    [("merge", [str(SPLIT_SOURCE_ID)]), ("new", [str(MEMORY_ID)]), ("merge", [])],
)
async def test_extraction_cannot_invent_write_targets(verdict, targets) -> None:
    """ADR-022: model-generated extraction decisions cannot write outside reviewed neighbors.
    M3EX-22: an unusable verdict becomes the owner's new card instead of failing the archive.
    """
    agent = HarnessAgent(
        settings(),
        model=TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"verdict": verdict, "target_ids": targets}),
        ),
    )
    candidate = ExtractionCandidateDraft(
        label="Fact",
        body="A fact",
        kind="fact",
        keywords=["fact", "test"],
    )
    result = await agent.propose_extraction_verdict(candidate, [{"memory_id": str(MEMORY_ID)}])
    assert (result.verdict, result.target_ids) == ("new", [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update,message",
    [
        ({"label": " "}, "seed splitter produced an invalid label"),
        ({"keywords": ["same", "SAME"]}, "seed splitter produced invalid keywords"),
    ],
)
async def test_seed_draft_walls_fail_before_returning_a_write_batch(update, message: str) -> None:
    """A-033 / ADR-022: an invalid generated seed must not become an approved write batch. M3GD /
    SPEC B.6 r14: exercised refusals: "seed splitter produced an invalid label"; "seed
    splitter produced invalid keywords". An over-cap child is repaired instead (v2.133).
    """
    candidate = {"label": "Fact", "body": "A fact", "kind": "fact", "keywords": ["fact", "test"]}
    agent = HarnessAgent(
        settings(),
        model=TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"candidates": [{**candidate, **update}]}),
        ),
    )
    with pytest.raises(ValueError, match=message):
        await agent.split_seed("test.md", "A fact")


@pytest.mark.asyncio
async def test_an_over_cap_seed_child_goes_back_through_the_seed_prompt() -> None:
    """SPEC C.6 / v2.133: document ingest shares the check loop; an over-cap child is split
    finer."""
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    child = {"label": "Fact", "kind": "fact", "keywords": ["fact", "test"]}
    model = structured_sequence_model(
        [
            {"candidates": [{**child, "body": "The seed fact repeats. " * 60}]},
            {
                "candidates": [
                    {**child, "label": "First", "body": "The seed fact has a first part."},
                    {**child, "label": "Second", "body": "The seed fact has a second part."},
                ]
            },
        ],
        calls,
    )
    agent = HarnessAgent(settings(), model=model)

    draft = await agent.split_seed("test.md", "A long fact")

    assert [candidate.label for candidate in draft.candidates] == ["First", "Second"]
    assert calls[1][1].instructions == calls[0][1].instructions.split("\n\n")[0] or (
        calls[1][1].instructions.startswith(calls[0][1].instructions.split("\n")[0])
    )
    assert "too long, break it down into finer pieces" in str(calls[1][0][-1].parts[-1].content)


def test_the_code_check_names_each_rule_a_fact_breaks() -> None:
    """SPEC C.6 / v2.133: fits the cap, names its own subject, one claim — checked in code."""
    assert fact_problems("The release color is amber.", 128) == []
    assert fact_problems("This repository uses uv.", 128) == []
    assert fact_problems("amber " * 200, 128) == [TOO_LONG]
    assert fact_problems("It runs on port 8000.", 128) == [
        "this memory does not name its own subject; begin it with the thing it is about"
    ]
    assert fact_problems("The rules:\n- tabs\n- no semicolons", 128) == [
        "this memory lists several claims; give each claim its own memory"
    ]


def test_compaction_prompt_has_the_owners_shape_and_no_count_cap() -> None:
    """SPEC C.6 / v2.133 / SD-083: a normal agentic compaction prompt; the five-fact cap and
    'prefer zero candidates' are gone."""
    assert "an agent continuing this problem in the future would want" in EXTRACTION_INSTRUCTION
    assert "self-contained fact sentence" in EXTRACTION_INSTRUCTION
    assert "break it at the cleanest place" in EXTRACTION_INSTRUCTION
    assert "Keep what the user stated, decided or corrected" in EXTRACTION_INSTRUCTION
    assert "tool result that verified it" in EXTRACTION_INSTRUCTION
    assert "begins with 'Unverified:'" in EXTRACTION_INSTRUCTION
    assert "not even to say that one was shared" in EXTRACTION_INSTRUCTION
    assert "at most five" not in EXTRACTION_INSTRUCTION
    assert "Prefer zero" not in EXTRACTION_INSTRUCTION
    fact = {"label": "Fact", "body": "The fact holds.", "kind": "fact", "keywords": ["a", "b"]}
    draft = ExtractionDraft(working_summary="", open_loops=[], candidates=[fact] * 9)
    assert len(draft.candidates) == 9


@pytest.mark.asyncio
async def test_a_remembered_fact_leaning_on_a_pronoun_is_repaired_before_the_palace() -> None:
    """SPEC C.6 / v2.133: /remember shares the check; the rule it broke goes back to the
    splitter and the repaired fact is saved."""
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {"label": "Port", "keywords": ["port", "server"]},
            {
                "candidates": [
                    {"label": "Port", "body": "It runs on 8000.", "keywords": ["port", "server"]}
                ]
            },
            {
                "candidates": [
                    {
                        "label": "Palace port",
                        "body": "The local Palace runs on port 8000.",
                        "keywords": ["port", "palace"],
                    }
                ]
            },
        ],
        calls,
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))

    result = await HarnessAgent(settings(), model=model).remember(
        "It runs on port 8000.", context=context(spine)
    )

    assert result.ok
    assert "does not name its own subject" in str(calls[2][0][-1].parts[-1].content)
    assert [request.body for request in spine.create_requests] == [
        "The local Palace runs on port 8000."
    ]


@pytest.mark.asyncio
async def test_a_fact_carrying_a_secret_never_reaches_the_palace() -> None:
    """SPEC C.6 / v2.133 (owner 2026-10-07, the planted secret 3/3): a credential goes back
    with the rule; a fact that was only the secret is withdrawn, any left is replaced."""
    assert fact_problems("The staging API token is sk-test-ABC123XYZ.", 128) == [LEAVE_SECRET_OUT]
    fact = {"label": "Token", "kind": "fact", "keywords": ["staging", "token"]}
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {
                "working_summary": "",
                "open_loops": [],
                "candidates": [
                    {**fact, "body": "The staging API token is sk-test-ABC123XYZ."},
                    {**fact, "label": "Key", "body": "The deploy key is ghp_" + "a1" * 10 + "."},
                ],
            },
            {"candidates": []},
            *[{"candidates": [{**fact, "label": "Key", "body": "Key ghp_" + "b2" * 10}]}] * 3,
        ],
        calls,
    )

    draft = await HarnessAgent(settings(), model=model).extract_thread("A token was shared.")

    assert [candidate.body for candidate in draft.candidates] == ["Key [secret left out]"]
    assert "leave the secret out" in str(calls[1][0][-1].parts[-1].content)


def unreached(cause: Exception) -> SpineTransportError:
    error = SpineTransportError()
    error.__cause__ = cause
    return error


def label_model() -> TestModel:
    return TestModel(
        call_tools=[],
        custom_output_text=json.dumps({"label": "Boat mooring", "keywords": ["boat", "pier"]}),
    )


@pytest.mark.asyncio
async def test_unreached_remember_waits_in_the_outbox_and_replays_through_the_palace(
    tmp_path,
) -> None:
    """ADR-003 / A-079: a /remember the Palace never received is saved locally and shown
    waiting; on reconnect the same request meets the Palace's create law.
    """
    spine = FakeSpine(unreached(httpx.ConnectError("refused")))
    outbox = MemoryOutbox(tmp_path, ids=EnvelopeFactory(machine_id="machine-1"))
    held = replace(context(spine), outbox=outbox)

    result = await HarnessAgent(settings(), model=label_model()).remember(
        "The keeper's boat is moored at pier four.", context=held
    )

    assert result.ok and result.message.startswith("Saved on this machine")
    assert "1 waiting for the Palace" in result.message
    [item] = outbox.waiting()
    assert (item.kind, item.label, item.payload["shape"]) == ("remember", "Boat mooring", "single")

    spine.outcome = CreatedMemoryResponse(created=memory_unit())
    assert await HarnessAgent.replay_remember(context(spine), item.payload) is None
    assert spine.create_requests[1] == spine.create_requests[0]

    spine.outcome = similar_response()
    refusal = await HarnessAgent.replay_remember(context(spine), item.payload)
    assert refusal is not None and refusal.startswith("Not saved: this looks similar to")


@pytest.mark.asyncio
async def test_a_remember_that_may_have_landed_still_fails_loudly(tmp_path) -> None:
    """A-079 / F165: after a timeout the Palace may hold the fact, so a resend could count it
    twice (owner, FL-173); the outbox takes only what never reached the Palace.
    """
    spine = FakeSpine(unreached(httpx.ReadTimeout("sent, no answer")))
    outbox = MemoryOutbox(tmp_path, ids=EnvelopeFactory(machine_id="machine-1"))

    result = await HarnessAgent(settings(), model=label_model()).remember(
        "The keeper's boat is moored at pier four.", context=replace(context(spine), outbox=outbox)
    )

    assert not result.ok and result.message.startswith("Could not remember")
    assert outbox.waiting() == []

    spine.outcome = unreached(httpx.ConnectError("refused"))
    with pytest.raises(SpineTransportError):
        await HarnessAgent.replay_remember(
            context(spine),
            {"shape": "single", "request": spine.create_requests[0].model_dump(mode="json")},
        )


@pytest.mark.asyncio
async def test_a_queued_remember_has_passed_the_check_and_carries_no_secret(tmp_path) -> None:
    """A-079 / v2.133: the outbox holds only what the check before the Palace let through, so
    a credential the check withdrew never waits on this machine for the Palace.
    """
    entry = {"label": "Staging host", "keywords": ["staging", "host"]}
    model = structured_sequence_model(
        [
            {**entry, "multiple_facts": False},
            {
                "candidates": [
                    {**entry, "body": "The staging host is build-7; token sk-test-ABC123XYZ."}
                ]
            },
            {"candidates": [{**entry, "body": "The staging host is build-7."}]},
        ],
        [],
    )
    spine = FakeSpine(unreached(httpx.ConnectError("refused")))
    outbox = MemoryOutbox(tmp_path, ids=EnvelopeFactory(machine_id="machine-1"))

    result = await HarnessAgent(settings(), model=model).remember(
        "The staging host is build-7; token sk-test-ABC123XYZ.",
        context=replace(context(spine), outbox=outbox),
    )

    assert result.ok and result.message.startswith("Saved on this machine")
    [item] = outbox.waiting()
    assert item.payload["request"]["body"] == "The staging host is build-7."
    assert "sk-test" not in json.dumps(item.payload)
