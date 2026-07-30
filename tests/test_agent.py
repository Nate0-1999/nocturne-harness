from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from harness.agent import (
    REMEMBER_DRAFT_INSTRUCTION,
    ChatResult,
    HarnessAgent,
    ModelConfigurationError,
    RememberDraft,
    RememberResult,
    resolve_model,
)
from harness.config import HarnessSettings
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    CreateMemoryRequest,
    DuplicateMemoryConflict,
    LabelConflict,
    MemoryKind,
    MemoryUnit,
    ProblemDetail,
    SimilarMemoriesResponse,
    SpineClientError,
    SpineProblemError,
    SpineTransportError,
)
from harness.tools_memory import MemoryToolContext

MEMORY_ID = UUID("12345678-1234-5678-1234-567812345678")
THREAD_ID = UUID("22345678-1234-5678-1234-567812345678")


@dataclass
class FakeSpine:
    outcome: CreatedMemoryResponse | SimilarMemoriesResponse | SpineClientError
    create_requests: list[CreateMemoryRequest] = field(default_factory=list)

    async def create_memory(
        self, request: CreateMemoryRequest
    ) -> CreatedMemoryResponse | SimilarMemoriesResponse:
        self.create_requests.append(request)
        if isinstance(self.outcome, SpineClientError):
            raise self.outcome
        return self.outcome


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


def memory_unit(*, label: str = "Editor preference", body: str = "Use tabs.") -> MemoryUnit:
    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    return MemoryUnit(
        memory_id=MEMORY_ID,
        principal_id="principal-1",
        label=label,
        body=body,
        kind=MemoryKind.FACT,
        keywords=[],
        project_key=None,
        thread_origin=str(THREAD_ID),
        origin_path="/workspace/notes.md",
        pin=False,
        status="active",
        revision=1,
        stats={},
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


@pytest.mark.parametrize(
    ("model_name", "key_field", "environment_name", "provider_name"),
    [
        ("openrouter:minimax/minimax-m3", "openrouter_api_key", "OPENROUTER_API_KEY", "openrouter"),
        ("anthropic:claude-sonnet-4-6", "anthropic_api_key", "ANTHROPIC_API_KEY", "anthropic"),
        ("openai:gpt-4o-mini", "openai_api_key", "OPENAI_API_KEY", "openai"),
    ],
)
def test_resolve_model_uses_settings_key_not_ambient_environment(
    monkeypatch,
    model_name: str,
    key_field: str,
    environment_name: str,
    provider_name: str,
) -> None:
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
    ],
)
def test_resolve_model_rejects_missing_settings_key_even_if_ambient_key_exists(
    monkeypatch, model_name: str, environment_name: str
) -> None:
    monkeypatch.setenv(environment_name, "ambient-key-must-not-win")

    with pytest.raises(ModelConfigurationError, match=f"{environment_name} is required"):
        resolve_model(model_name, settings())


def test_resolve_model_rejects_unknown_provider_instead_of_using_ambient_credentials(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-key-must-not-win")

    with pytest.raises(
        ModelConfigurationError,
        match="use openrouter, anthropic, or openai",
    ):
        resolve_model("google-gla:gemini-2.5-pro", settings())


@pytest.mark.asyncio
async def test_chat_returns_output_and_reusable_full_history_with_exact_limits() -> None:
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
@pytest.mark.parametrize("command", ["/remember", "/remember ", "/remember\n\t"])
async def test_empty_remember_command_is_visible_and_does_not_call_model_or_spine(
    command: str,
) -> None:
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
async def test_remember_uses_selected_model_once_without_tools_and_maps_global_user_fact() -> None:
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

    result = await agent.dispatch(
        "/remember   Use tabs.  ",
        context=context(spine),
        model=selected_model,
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
    assert default_model.last_model_request_parameters is None
    assert len(spine.create_requests) == 1
    request = spine.create_requests[0]
    assert request.principal_id == "principal-1"
    assert request.label == "Editor preference"
    assert request.body == "Use tabs."
    assert request.kind is MemoryKind.FACT
    assert request.keywords == ["editor", "tabs"]
    assert request.project_key is None
    assert request.thread_origin == str(THREAD_ID)
    assert request.origin_path == "/workspace/notes.md"
    assert request.editor == "user"
    assert request.machine_id == "machine-1"
    assert request.force is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("   ", "generated label was blank"),
        ("first line\nsecond line", "generated label was not one line"),
        ("é" * 65, "generated label exceeded 64 characters"),
    ],
)
async def test_invalid_generated_label_is_rejected_without_calling_spine(
    label: str, expected: str
) -> None:
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
        (similar_response(), "similar memory exists"),
        (duplicate_conflict(), "duplicate memory exists"),
        (label_conflict(), "label already exists"),
        (problem_error(), "Spine unavailable: try later"),
        (SpineTransportError(), "memory service unavailable"),
    ],
    ids=["similar", "duplicate", "label", "problem", "transport"],
)
async def test_remember_failures_are_truthful_visible_non_success(
    outcome: CreatedMemoryResponse | SimilarMemoriesResponse | SpineClientError,
    expected: str,
) -> None:
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
@pytest.mark.parametrize(
    "ordinary_text",
    ["/remembered", "/remembering this", "/remember: this", " /remember this", "/Remember this"],
)
async def test_near_miss_remember_commands_are_ordinary_chat(ordinary_text: str) -> None:
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
