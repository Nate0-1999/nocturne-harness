from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from harness.agent import (
    REMEMBER_DRAFT_INSTRUCTION,
    REMEMBER_SPLIT_GUIDANCE,
    REMEMBER_SPLIT_INSTRUCTION,
    ChatResult,
    HarnessAgent,
    ModelConfigurationError,
    RememberDraft,
    RememberResult,
    RememberSplitDraft,
    resolve_model,
)
from harness.config import HarnessSettings
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

    monkeypatch.setattr("harness.agent.infer_provider", missing_provider_dependency)

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
            "save_memory",
            "search_memory",
            "edit_memory",
        ]
        for _, info in calls
    )
    assert spine.create_requests == []


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
    """F027, A-049, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    The semantic splitter must be a separate tools-free boundary that preserves complete claims.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {
                "safe_to_save": True,
                "candidates": [
                    {
                        "label": "Garden cadence",
                        "body": "The garden review happens weekly.",
                        "keywords": ["garden", "cadence"],
                    }
                ],
                "coverage": [
                    {
                        "text": "The garden review happens weekly.",
                        "classification": "durable",
                        "candidate_index": 0,
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
    assert "without summarizing" in calls[0][1].instructions
    assert "prefer 2-5 words and under 40 characters" in calls[0][1].instructions
    assert "at most 128 cl100k_base tokens" in calls[0][1].instructions
    assert "never as durable facts or candidates" in calls[0][1].instructions
    assert "concatenates byte-for-byte to the complete source" in calls[0][1].instructions
    assert "never emit a blank or whitespace-only segment" in calls[0][1].instructions
    assert "internal reference is resolved" in calls[0][1].instructions
    assert "First, Second, and Third" in calls[0][1].instructions
    assert "MUST still appear byte-for-byte in coverage" in calls[0][1].instructions
    assert "retain them byte-for-byte in that candidate body" in calls[0][1].instructions
    assert "JSON strings must never trim it" in calls[0][1].instructions
    assert "safe_to_save true only" in calls[0][1].instructions
    schema = RememberSplitDraft.model_json_schema()
    candidate_label = schema["$defs"]["RememberSplitCandidate"]["properties"]["label"]
    coverage_text = schema["$defs"]["RememberCoverageSegment"]["properties"]["text"]
    assert candidate_label["maxLength"] == 64
    assert "Never whitespace-only" in coverage_text["description"]
    assert "Never trim it" in coverage_text["description"]


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
async def test_a049_oversized_multi_claim_uses_one_atomic_split_with_exact_source() -> None:
    """F027, A-049, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    An oversized multi-claim source must become one linked atomic request with exact provenance.
    """
    source = LIVE_SPLIT_SOURCE
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {
                "safe_to_save": True,
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
                "coverage": [
                    {
                        "text": LIVE_OPERATION_HEAD,
                        "classification": "operation",
                        "candidate_index": None,
                    },
                    {
                        "text": LIVE_FACT_ONE,
                        "classification": "durable",
                        "candidate_index": 0,
                    },
                    {
                        "text": LIVE_FACT_TWO,
                        "classification": "durable",
                        "candidate_index": 1,
                    },
                    {
                        "text": LIVE_FACT_THREE,
                        "classification": "durable",
                        "candidate_index": 2,
                    },
                    {
                        "text": LIVE_OPERATION_TAIL,
                        "classification": "operation",
                        "candidate_index": None,
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
                "safe_to_save": True,
                "candidates": [
                    {
                        "label": "Garden cadence",
                        "body": source,
                        "keywords": ["Garden", "cadence"],
                    }
                ],
                "coverage": [
                    {
                        "text": source,
                        "classification": "durable",
                        "candidate_index": 0,
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
async def test_a049_single_atomic_oversized_claim_guides_without_any_write() -> None:
    """F027, A-049, ADR-022, and SPEC B.6 rule 12 are defended here.
    One oversized indivisible claim is never shortened and receives enacted owner guidance.
    """
    source = ("The complete indivisible claim retains this qualifier. " * 80).strip()
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = structured_sequence_model(
        [
            {
                "safe_to_save": False,
                "candidates": [
                    {
                        "label": "Indivisible claim",
                        "body": source,
                        "keywords": ["indivisible", "qualifier"],
                    }
                ],
                "coverage": [
                    {
                        "text": source,
                        "classification": "durable",
                        "candidate_index": 0,
                    }
                ],
            }
        ],
        calls,
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result == RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
    assert len(calls) == 1
    assert spine.create_requests == []
    assert spine.split_requests == []


@pytest.mark.asyncio
async def test_a050_single_fitting_candidate_never_persists_excluded_operation_text() -> None:
    """F027, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    Exact-source fallback may create only when the sole durable extract equals the whole source.
    """
    source = "Remember this: The observatory ledger has a silver cover."
    model = structured_sequence_model(
        [
            {"label": "L" * 65, "keywords": ["ledger", "silver"]},
            {
                "safe_to_save": True,
                "candidates": [
                    {
                        "label": "Observatory ledger cover",
                        "body": "The observatory ledger has a silver cover.",
                        "keywords": ["ledger", "silver"],
                    }
                ],
                "coverage": [
                    {
                        "text": "Remember this: ",
                        "classification": "operation",
                        "candidate_index": None,
                    },
                    {
                        "text": "The observatory ledger has a silver cover.",
                        "classification": "durable",
                        "candidate_index": 0,
                    },
                ],
            },
        ],
        [],
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result == RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
    assert spine.create_requests == []
    assert spine.split_requests == []


@pytest.mark.asyncio
async def test_a050_label_triggered_unsafe_single_candidate_guides_without_write() -> None:
    """F027, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    A fitting extractive draft that cannot satisfy standalone semantics must never be created.
    """
    source = "The lantern is east, and the separate ledger is silver."
    model = structured_sequence_model(
        [
            {"label": "L" * 65, "keywords": ["lantern", "ledger"]},
            {
                "safe_to_save": False,
                "candidates": [
                    {
                        "label": "Unsafe combined facts",
                        "body": source,
                        "keywords": ["lantern", "ledger"],
                    }
                ],
                "coverage": [
                    {
                        "text": source,
                        "classification": "durable",
                        "candidate_index": 0,
                    }
                ],
            },
        ],
        [],
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result == RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
    assert spine.create_requests == []
    assert spine.split_requests == []


@pytest.mark.asyncio
async def test_a049_split_near_similar_copy_never_offers_nonexistent_force() -> None:
    """F027, A-049, ADR-022, and SPEC B.6 rule 12 are defended here.
    An atomic split 200 names the no-write result and a lawful remedy without a force fiction.
    """
    source = "Fact one. Fact two."
    model = structured_sequence_model(
        [
            {
                "safe_to_save": True,
                "candidates": [
                    {"label": "First", "body": "Fact one.", "keywords": ["fact", "one"]},
                    {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
                ],
                "coverage": [
                    {
                        "text": "Fact one. ",
                        "classification": "durable",
                        "candidate_index": 0,
                    },
                    {
                        "text": "Fact two.",
                        "classification": "durable",
                        "candidate_index": 1,
                    },
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
                {
                    "label": "First",
                    "body": "one two three four five six",
                    "keywords": ["fact", "one"],
                },
                {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
            ],
            id="over-limit-child",
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
async def test_a049_invalid_split_draft_uses_safe_guidance_and_zero_writes(
    candidates: list[dict[str, object]],
) -> None:
    """F027, A-049, ADR-022, and SPEC B.6 rule 12 are defended here.
    Invalid split drafts cannot become partial writes, mechanical chunks, or raw limit errors.
    """
    coverage = [
        {
            "text": str(candidate["body"]) + (" " if index + 1 < len(candidates) else ""),
            "classification": "durable",
            "candidate_index": index,
        }
        for index, candidate in enumerate(candidates)
    ]
    source = "".join(str(segment["text"]) for segment in coverage)
    model = structured_sequence_model(
        [{"candidates": candidates, "coverage": coverage, "safe_to_save": True}],
        [],
    )
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(memory_max_tokens=5), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result == RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
    assert spine.create_requests == []
    assert spine.split_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "reordered",
        "duplicated",
        "blank",
        "operation-index",
        "durable-no-index",
        "out-of-range",
        "decreasing",
        "uncovered",
        "body-mismatch",
        "non-exact",
    ],
)
async def test_a050_invalid_coverage_witness_guides_before_any_write(case: str) -> None:
    """F027, A-050, ADR-022, and SPEC B.6 rule 12 are defended here.
    Every malformed, incomplete, or body-inconsistent exact-source witness must fail closed.
    """
    source = "Fact one. Fact two."
    draft: dict[str, object] = {
        "safe_to_save": True,
        "candidates": [
            {"label": "First", "body": "Fact one.", "keywords": ["fact", "one"]},
            {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
        ],
        "coverage": [
            {
                "text": "Fact one. ",
                "classification": "durable",
                "candidate_index": 0,
            },
            {
                "text": "Fact two.",
                "classification": "durable",
                "candidate_index": 1,
            },
        ],
    }
    coverage = deepcopy(draft["coverage"])
    assert isinstance(coverage, list)
    candidates = deepcopy(draft["candidates"])
    assert isinstance(candidates, list)
    if case == "missing":
        draft.pop("coverage")
    elif case == "reordered":
        draft["coverage"] = list(reversed(coverage))
    elif case == "duplicated":
        draft["coverage"] = [coverage[0], coverage[0], coverage[1]]
    elif case == "blank":
        draft["coverage"] = [
            {"text": "Fact one.", "classification": "durable", "candidate_index": 0},
            {"text": " ", "classification": "operation", "candidate_index": None},
            coverage[1],
        ]
    elif case == "operation-index":
        coverage[0]["classification"] = "operation"
        draft["coverage"] = coverage
    elif case == "durable-no-index":
        coverage[0]["candidate_index"] = None
        draft["coverage"] = coverage
    elif case == "out-of-range":
        coverage[1]["candidate_index"] = 2
        draft["coverage"] = coverage
    elif case == "decreasing":
        coverage[0]["candidate_index"] = 1
        coverage[1]["candidate_index"] = 0
        draft["coverage"] = coverage
    elif case == "uncovered":
        coverage[1]["candidate_index"] = 0
        candidates[0]["body"] = source
        draft["coverage"] = coverage
        draft["candidates"] = candidates
    elif case == "body-mismatch":
        candidates[0]["body"] = "A hallucinated fact."
        draft["candidates"] = candidates
    elif case == "non-exact":
        coverage[1]["text"] = "Fact three."
        draft["coverage"] = coverage

    model = structured_sequence_model([draft], [])
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(settings(memory_max_tokens=4), model=model)

    result = await agent.remember(source, context=context(spine))

    assert result == RememberResult(False, REMEMBER_SPLIT_GUIDANCE)
    assert spine.create_requests == []
    assert spine.split_requests == []


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
    "keywords",
    [
        [],
        ["only"],
        ["same", "SAME"],
        ["one", "two", "three", "four", "five", "six"],
        ["one", "   "],
    ],
)
async def test_invalid_generated_keywords_are_rejected_without_calling_spine(
    keywords: list[str],
) -> None:
    """ADR-013 is defended by verifying that invalid generated keywords are rejected without
    calling spine; this prevents drift in the agent composition and explicit model boundary.
    """
    calls: list[tuple[list[ModelMessage], AgentInfo]] = []
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()))
    agent = HarnessAgent(
        settings(),
        model=remember_model("Editor preference", keywords, calls),
    )

    result = await agent.remember("Use tabs.", context=context(spine))

    assert result.ok is False
    assert "2-5 distinct nonblank terms" in result.message
    assert len(calls) == 1
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
        (problem_error(), "Spine unavailable: try later"),
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
    assert len(spine.create_requests) == 1


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
async def test_remember_near_duplicate_guides_edit_without_transport_details() -> None:
    """F038, SPEC C.4, and B.6 r12 require a near duplicate to guide the owner
    toward the existing edit boundary without scores, JSON, or an automatic force write.
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
    assert "0.86" not in result.message
    assert "force=true" not in result.message
    assert str(MEMORY_ID) not in result.message
    assert spine.patch_requests == []


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
        "save_memory",
        "search_memory",
        "edit_memory",
    ]
    assert spine.create_requests == []
