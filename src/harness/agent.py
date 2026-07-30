"""Bounded pydantic-ai chat and the direct C.6 `/remember` command."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, StrictStr
from pydantic_ai import Agent, PromptedOutput, UsageLimits
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model, infer_model
from pydantic_ai.providers import Provider, infer_provider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from harness.commands import remember_command_text
from harness.config import HarnessSettings
from harness.pydantic_ai_adapter import MemoryCapability
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    SpineClientError,
)
from harness.tools_memory import (
    MemoryToolContext,
    create_remembered_memory,
    render_create_conflict,
    render_create_response,
    render_spine_error,
)

REMEMBER_DRAFT_INSTRUCTION = (
    "Generate one short label and 2-5 lowercase searchable keywords for the "
    "supplied memory. Keywords must be distinct nouns or terms. Return only "
    "the requested structured result with no commentary."
)


class ModelConfigurationError(ValueError):
    """The selected model cannot be constructed from its provider configuration."""


class RememberDraft(BaseModel):
    """One tools-free model completion for a `/remember` write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr
    keywords: list[StrictStr]


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Framework-neutral output plus the opaque history needed by the next turn."""

    output: str
    message_history: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class RememberResult:
    """A truthful chat confirmation or visible non-save result."""

    ok: bool
    message: str
    memory_id: UUID | None = None
    label: str | None = None


type DispatchResult = ChatResult | RememberResult


class HarnessAgent:
    """Own the chat agent, tools-free remember agent, and C.5 usage walls."""

    def __init__(
        self,
        settings: HarnessSettings,
        *,
        model: Model | None = None,
    ) -> None:
        self._settings = settings
        self._default_model = model
        self._models_by_name: dict[str, Model] = (
            {settings.chat_model: model} if model is not None else {}
        )
        self._usage_limits = UsageLimits(
            request_limit=settings.run_request_limit,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        self._label_usage_limits = UsageLimits(
            request_limit=1,
            total_tokens_limit=settings.run_total_tokens_limit,
        )
        self._chat_agent = Agent(
            self._default_model,
            deps_type=MemoryToolContext,
            capabilities=[MemoryCapability()],
            name="harness-chat",
        )
        self._label_agent = Agent(
            self._default_model,
            output_type=PromptedOutput(RememberDraft),
            instructions=REMEMBER_DRAFT_INSTRUCTION,
            name="harness-memory-label",
        )

    @property
    def chat_agent(self) -> Agent[MemoryToolContext, str]:
        """Expose the vanilla agent for inspection and later daemon assembly."""

        return self._chat_agent

    @property
    def label_agent(self) -> Agent[None, RememberDraft]:
        """Expose the separate, tools-free remember agent for inspection."""

        return self._label_agent

    @property
    def usage_limits(self) -> UsageLimits:
        return self._usage_limits

    def model_for(self, model: Model | str | None = None) -> Model:
        """Return one cached settings-owned model instance for a resolved route."""

        return self._select_model(model)

    async def chat(
        self,
        prompt: str,
        *,
        context: MemoryToolContext,
        message_history: Sequence[Any] | None = None,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
    ) -> ChatResult:
        """Run one ordinary chat turn with memory tools and bounded usage."""

        result = await self._chat_agent.run(
            prompt,
            deps=context,
            message_history=message_history,
            model=self._select_model(model),
            model_settings=model_settings,
            usage_limits=self._usage_limits,
        )
        if not isinstance(result.output, str):
            raise TypeError("chat agent returned a non-text output")
        return ChatResult(
            output=result.output,
            message_history=tuple(result.all_messages()),
        )

    async def remember(
        self,
        text: str,
        *,
        context: MemoryToolContext,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
        usage: RunUsage | None = None,
        raise_model_errors: bool = False,
    ) -> RememberResult:
        """Generate one valid draft, save one global user fact, and confirm honestly."""

        body = text.strip()
        if not body:
            return RememberResult(False, "Nothing to remember; add text after /remember.")

        selected_model = self._select_model(model)
        try:
            draft_result = await self._label_agent.run(
                f"Memory:\n{body}",
                model=selected_model,
                model_settings=model_settings,
                usage_limits=self._label_usage_limits,
                usage=usage,
            )
        except Exception:
            if raise_model_errors:
                raise
            return RememberResult(False, "Could not remember: metadata generation failed.")

        draft = draft_result.output
        if not isinstance(draft, RememberDraft):  # pragma: no cover - pydantic-ai type guard
            return RememberResult(
                False,
                "Could not remember: metadata generation returned no data.",
            )
        label = draft.label.strip()
        if not label:
            return RememberResult(False, "Could not remember: the generated label was blank.")
        if "\n" in label or "\r" in label:
            return RememberResult(
                False,
                "Could not remember: the generated label was not one line.",
            )
        if len(label) > self._settings.label_max:
            return RememberResult(
                False,
                "Could not remember: the generated label exceeded "
                f"{self._settings.label_max} characters.",
            )
        keywords = _normalize_keywords(draft.keywords)
        if keywords is None:
            return RememberResult(
                False,
                "Could not remember: generated keywords must contain 2-5 distinct nonblank terms.",
            )

        try:
            response = await create_remembered_memory(
                context,
                label=label,
                body=body,
                keywords=keywords,
            )
        except CreateMemoryConflictError as exc:
            return RememberResult(False, f"Could not remember: {render_create_conflict(exc)}")
        except SpineClientError as exc:
            return RememberResult(False, f"Could not remember: {render_spine_error('save', exc)}")

        if not isinstance(response, CreatedMemoryResponse):
            return RememberResult(False, f"Not saved: {render_create_response(response)}")
        created = response.created
        return RememberResult(
            True,
            f"Remembered {created.label!r} ({created.memory_id}).",
            memory_id=created.memory_id,
            label=created.label,
        )

    async def dispatch(
        self,
        text: str,
        *,
        context: MemoryToolContext,
        message_history: Sequence[Any] | None = None,
        model: Model | str | None = None,
        model_settings: ModelSettings | None = None,
        usage: RunUsage | None = None,
        raise_model_errors: bool = False,
    ) -> DispatchResult:
        """Route only the exact `/remember` command; all other text is chat."""

        remembered_text = remember_command_text(text)
        if remembered_text is not None:
            return await self.remember(
                remembered_text,
                context=context,
                model=model,
                model_settings=model_settings,
                usage=usage,
                raise_model_errors=raise_model_errors,
            )
        return await self.chat(
            text,
            context=context,
            message_history=message_history,
            model=model,
            model_settings=model_settings,
        )

    def _select_model(self, model: Model | str | None) -> Model:
        if model is None:
            model = self._settings.chat_model
        if not isinstance(model, str):
            return model
        resolved = self._models_by_name.get(model)
        if resolved is None:
            resolved = resolve_model(model, self._settings)
            self._models_by_name[model] = resolved
        return resolved


def resolve_model(model: Model | str, settings: HarnessSettings) -> Model:
    """Resolve default routes from settings and explicit others through Pydantic AI."""

    if not isinstance(model, str):
        return model
    if not model or model != model.strip():
        raise ModelConfigurationError("chat model must be nonblank without surrounding whitespace")

    def provider_factory(name: str) -> Provider[Any]:
        if name == "openrouter":
            return OpenRouterProvider(
                api_key=_required_secret(settings.openrouter_api_key, "OPENROUTER_API_KEY")
            )
        if name == "anthropic":
            return AnthropicProvider(
                api_key=_required_secret(settings.anthropic_api_key, "ANTHROPIC_API_KEY")
            )
        if name in {"openai", "openai-chat", "openai-responses"}:
            return OpenAIProvider(
                api_key=_required_secret(settings.openai_api_key, "OPENAI_API_KEY")
            )
        return infer_provider(name)

    try:
        return infer_model(model, provider_factory=provider_factory)
    except ModelConfigurationError:
        raise
    except (UserError, ValueError) as exc:
        raise ModelConfigurationError(str(exc)) from exc
    except ImportError as exc:
        raise ModelConfigurationError(
            f"provider dependency is unavailable for {model!r}: {exc}"
        ) from exc


def _required_secret(value: SecretStr | None, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise ModelConfigurationError(f"{name} is required for the selected model provider")
    return value.get_secret_value()


def _normalize_keywords(values: Sequence[str]) -> list[str] | None:
    keywords: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in seen:
            keywords.append(normalized)
            seen.add(normalized)
    return keywords if 2 <= len(keywords) <= 5 else None
