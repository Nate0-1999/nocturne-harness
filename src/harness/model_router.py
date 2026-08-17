"""Swappable completion-router seam with OpenRouter as the first adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from pydantic_ai.providers import Provider, infer_provider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from harness.config import HarnessSettings
from harness.model_policy import (
    ModelCatalog,
    ModelCatalogLoader,
    ModelCatalogUnavailable,
    ModelRoute,
    NamedModelResolutionError,
    OpenRouterCatalogClient,
    ThreadModelResolution,
)
from harness.openrouter_runtime import PreservingOpenRouterModel


class ModelConfigurationError(ValueError):
    """The selected model cannot be constructed from its adapter configuration."""


class CompletionAdapter(Protocol):
    """One provider/router implementation behind Nocturne's model seam."""

    def accepts(self, model: str) -> bool: ...

    def build_model(self, model: str) -> Model: ...

    def request_settings(
        self,
        resolution: ThreadModelResolution,
        thread_id: str,
    ) -> ModelSettings | None: ...


class OpenRouterCompletionAdapter:
    """OpenRouter adapter #1: model construction, catalog, and request metadata."""

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key.strip() if api_key is not None else None
        self._catalog: ModelCatalogLoader | None = (
            OpenRouterCatalogClient(self._api_key) if self._api_key else None
        )

    @property
    def catalog_available(self) -> bool:
        return self._catalog is not None

    def accepts(self, model: str) -> bool:
        return model.startswith("openrouter:")

    def build_model(self, model: str) -> Model:
        api_key = _required_key(self._api_key, "OPENROUTER_API_KEY")
        return PreservingOpenRouterModel(
            model.removeprefix("openrouter:"),
            provider=OpenRouterProvider(api_key=api_key),
        )

    def request_settings(
        self,
        resolution: ThreadModelResolution,
        thread_id: str,
    ) -> ModelSettings:
        common = _common_request_settings(resolution)
        session_id = thread_id
        if resolution.stickiness_epoch:
            session_id = f"{thread_id}:epoch:{resolution.stickiness_epoch}"
        settings: OpenRouterModelSettings = {
            **common,
            "extra_body": {"session_id": session_id},
            "openrouter_usage": {"include": True},
        }
        if resolution.request_parameters.effort is not None:
            settings["openrouter_reasoning"] = {"effort": resolution.request_parameters.effort}
        if resolution.price_sorted:
            settings["openrouter_provider"] = {"sort": "price"}
        return cast(ModelSettings, settings)

    async def load(self) -> ModelCatalog:
        if self._catalog is None:
            raise ModelCatalogUnavailable("OPENROUTER_API_KEY is unavailable for catalog lookup")
        return await self._catalog.load()

    async def load_named_route(self, model_id: str) -> tuple[ModelRoute, datetime]:
        if self._catalog is None:
            raise ModelCatalogUnavailable("OPENROUTER_API_KEY is unavailable for catalog lookup")
        return await self._catalog.load_named_route(model_id)

    def qualify_model(self, model_id: str) -> str:
        return f"openrouter:{model_id}"

    def parse_named_model(self, model: str) -> str:
        if (
            not isinstance(model, str)
            or not model.startswith("openrouter:")
            or model != model.strip()
            or not model.removeprefix("openrouter:")
        ):
            raise NamedModelResolutionError("model must be an openrouter:<broker-model-id> string")
        return model.removeprefix("openrouter:")

    async def aclose(self) -> None:
        catalog = self._catalog
        close = getattr(catalog, "aclose", None)
        if callable(close):
            await close()


class DirectCompletionAdapter:
    """Policy-off adapter for one directly configured provider model and key."""

    def __init__(self, settings: HarnessSettings) -> None:
        self._settings = settings

    def accepts(self, model: str) -> bool:
        return not model.startswith("openrouter:")

    def build_model(self, model: str) -> Model:
        return infer_model(model, provider_factory=self._provider)

    def request_settings(
        self,
        resolution: ThreadModelResolution,
        thread_id: str,
    ) -> ModelSettings | None:
        del thread_id
        settings = _common_request_settings(resolution)
        return settings or None

    def _provider(self, name: str) -> Provider[Any]:
        if name == "anthropic":
            return AnthropicProvider(
                api_key=_required_secret(self._settings.anthropic_api_key, "ANTHROPIC_API_KEY")
            )
        if name in {"openai", "openai-chat", "openai-responses"}:
            return OpenAIProvider(
                api_key=_required_secret(self._settings.openai_api_key, "OPENAI_API_KEY")
            )
        return infer_provider(name)


class CompletionRouter:
    """Own adapter selection while callers depend on one stable internal interface."""

    def __init__(self, settings: HarnessSettings) -> None:
        openrouter_key = (
            settings.openrouter_api_key.get_secret_value()
            if settings.openrouter_api_key is not None
            else None
        )
        self._openrouter = OpenRouterCompletionAdapter(openrouter_key)
        self._direct = DirectCompletionAdapter(settings)
        self._adapters: tuple[CompletionAdapter, ...] = (self._openrouter, self._direct)

    @property
    def catalog(self) -> ModelCatalogLoader | None:
        """Expose catalog capability only when its adapter has a key."""

        return self._openrouter if self._openrouter.catalog_available else None

    def model_for(self, model: str) -> Model:
        """Build a model through the first adapter that owns its route."""

        if not isinstance(model, str) or not model or model != model.strip():
            raise ModelConfigurationError(
                "chat model must be nonblank without surrounding whitespace"
            )
        adapter = self._adapter_for(model)
        try:
            return adapter.build_model(model)
        except ModelConfigurationError:
            raise
        except (UserError, ValueError) as exc:
            raise ModelConfigurationError(str(exc)) from exc
        except ImportError as exc:
            raise ModelConfigurationError(
                f"provider dependency is unavailable for {model!r}: {exc}"
            ) from exc

    def request_settings(
        self,
        resolution: ThreadModelResolution | None,
        thread_id: str,
    ) -> ModelSettings | None:
        if resolution is None:
            return None
        return self._adapter_for(resolution.model).request_settings(resolution, thread_id)

    async def aclose(self) -> None:
        await self._openrouter.aclose()

    def _adapter_for(self, model: str) -> CompletionAdapter:
        for adapter in self._adapters:
            if adapter.accepts(model):
                return adapter
        raise ModelConfigurationError(f"no completion adapter accepts {model!r}")


def model_settings_for(
    resolution: ThreadModelResolution | None,
    thread_id: str,
) -> ModelSettings | None:
    """Pure request-shape projection retained for golden and narrow callers."""

    if resolution is None:
        return None
    if resolution.uses_openrouter:
        # Request shaping uses no secret or network state.
        return OpenRouterCompletionAdapter(None).request_settings(resolution, thread_id)
    settings = _common_request_settings(resolution)
    return settings or None


def _common_request_settings(resolution: ThreadModelResolution) -> ModelSettings:
    parameters = resolution.request_parameters
    settings: ModelSettings = {}
    if parameters.temperature is not None:
        settings["temperature"] = parameters.temperature
    if parameters.top_p is not None:
        settings["top_p"] = parameters.top_p
    if parameters.top_k is not None:
        settings["top_k"] = parameters.top_k
    if parameters.max_tokens is not None:
        settings["max_tokens"] = parameters.max_tokens
    return settings


def _required_key(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ModelConfigurationError(f"{name} is required for the selected model provider")
    return value


def _required_secret(value: Any, name: str) -> str:
    if value is None or not value.get_secret_value().strip():
        raise ModelConfigurationError(f"{name} is required for the selected model provider")
    return value.get_secret_value()


__all__ = [
    "CompletionAdapter",
    "CompletionRouter",
    "DirectCompletionAdapter",
    "ModelConfigurationError",
    "OpenRouterCompletionAdapter",
    "model_settings_for",
]
