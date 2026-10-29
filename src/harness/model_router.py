"""Swappable completion-router seam with OpenRouter as the first adapter."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import httpx
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModelSettings
from pydantic_ai.models.wrapper import WrapperModel
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
    parse_model_listing,
)
from harness.openrouter_runtime import PreservingOpenRouterModel
from harness.spend_walls import SpendWallModel


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

    def __init__(self, api_key: str | None, request_timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key.strip() if api_key is not None else None
        self._request_timeout_seconds = request_timeout_seconds
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
            # F169: OpenRouter sends a byte at least every few seconds while it works (2026-10-03
            # probe), so this many silent seconds means the request stalled.
            settings={"timeout": self._request_timeout_seconds},
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
        extra_body: dict[str, object] = {"session_id": session_id}
        if "top_k" in common:
            # The OpenAI-compatible client drops a top_k setting; OpenRouter reads it in the body.
            extra_body["top_k"] = common["top_k"]
        settings: OpenRouterModelSettings = {
            **common,
            "extra_body": extra_body,
            "openrouter_usage": {"include": True},
            "openrouter_cache_instructions": True,
            "openrouter_cache_messages": True,
            "openrouter_cache_tool_definitions": True,
        }
        if resolution.request_parameters.effort is not None and (
            resolution.supported_parameters is None
            or "reasoning" in resolution.supported_parameters
        ):
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
        self._listing: tuple[float, ModelCatalog] | None = None

    @property
    def catalog_available(self) -> bool:
        """M3G single-key mode: an OpenAI-compatible source lists its own models (FL-202)."""

        return (
            self._settings.chat_model.split(":", 1)[0] in _OPENAI_PROVIDERS
            and self._settings.openai_api_key is not None
        )

    def accepts(self, model: str) -> bool:
        return not model.startswith(("openrouter:", "local:"))

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
                api_key=_required_secret(self._settings.openai_api_key, "OPENAI_API_KEY"),
                base_url=self._settings.openai_base_url,
            )
        return infer_provider(name)

    async def load(self) -> ModelCatalog:
        """The source's own list; no benchmarks, so token-cost policies stay dormant."""

        # Fresh for a day, like the broker catalog: the chip and browser ask on every render.
        if self._listing is not None and time.monotonic() - self._listing[0] < 24 * 60 * 60:
            return self._listing[1]
        api_key = _required_secret(self._settings.openai_api_key, "OPENAI_API_KEY")
        base_url = (self._settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(
                    f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}
                )
            response.raise_for_status()
            # This adapter sends no reasoning effort, so no model here offers a thinking level.
            listing = tuple(
                replace(entry, reasoning=False) for entry in parse_model_listing(response.json())
            )
        except (httpx.HTTPError, ValueError, ModelCatalogUnavailable) as exc:
            raise ModelCatalogUnavailable("the model source's list is unavailable") from exc
        catalog = ModelCatalog(
            rows=(), model_routes={}, fetched_at=datetime.now(UTC), listing=listing
        )
        self._listing = (time.monotonic(), catalog)
        return catalog

    async def load_named_route(self, model_id: str) -> tuple[ModelRoute, datetime]:
        for _ in range(2):  # a miss refetches once, as the broker's /model lookup does
            catalog = await self.load()
            for entry in catalog.listing:
                if entry.model_id == model_id:
                    context = entry.context_tokens or self._settings.model_context_tokens
                    return ModelRoute(
                        model_id=model_id,
                        context_tokens=context,
                        supported_parameters=entry.supported_parameters,
                    ), catalog.fetched_at
            self._listing = None
        raise NamedModelResolutionError(f"unknown model: {model_id}")

    def qualify_model(self, model_id: str) -> str:
        return f"{self._settings.chat_model.split(':', 1)[0]}:{model_id}"

    def parse_named_model(self, model: str) -> str:
        provider = self._settings.chat_model.split(":", 1)[0]
        if not isinstance(model, str) or not model.startswith(f"{provider}:"):
            raise NamedModelResolutionError(f"model must be a {provider}:<model-id> string")
        return model.removeprefix(f"{provider}:")


_OPENAI_PROVIDERS = frozenset({"openai", "openai-chat", "openai-responses"})


class LocalProvider(OpenAIProvider):
    @property
    def name(self) -> str:
        return "local"


class LocalCompletionAdapter:
    """FL-188: discover an existing OpenAI-compatible server; never start or install one."""

    def __init__(self, settings: HarnessSettings) -> None:
        self.settings = settings
        self._listing: tuple[float, ModelCatalog] | None = None
        self._urls: dict[str, str] = {}

    def accepts(self, model: str) -> bool:
        return model.startswith("local:")

    async def load(self) -> ModelCatalog:
        if self._listing and time.monotonic() - self._listing[0] < 10:
            return self._listing[1]
        urls = (
            (self.settings.local_model_url,)
            if self.settings.local_model_url
            else ("http://127.0.0.1:11434/v1", "http://127.0.0.1:8080/v1")
        )
        listing = {}
        routes = {}
        async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
            for url in urls:
                base = url.rstrip("/")
                try:
                    response = await client.get(f"{base}/models")
                    response.raise_for_status()
                    entries = parse_model_listing(response.json())
                except (httpx.HTTPError, ValueError, ModelCatalogUnavailable):
                    continue
                for entry in entries:
                    name = f"local:{entry.model_id}"
                    if name in listing:
                        continue
                    self._urls[name] = base
                    context = entry.context_tokens or self.settings.local_model_context_tokens
                    listing[name] = replace(
                        entry,
                        model_id=name,
                        name=f"Local · {entry.name}",
                        context_tokens=context,
                        prompt_price=None,
                        completion_price=None,
                        intelligence_index=None,
                        reasoning=False,
                    )
                    routes[name] = ModelRoute(
                        name, context, supported_parameters=entry.supported_parameters
                    )
        catalog = ModelCatalog((), routes, datetime.now(UTC), tuple(listing.values()))
        self._listing = time.monotonic(), catalog
        return catalog

    async def load_named_route(self, model: str) -> tuple[ModelRoute, datetime]:
        catalog = await self.load()
        if model not in catalog.model_routes:
            raise NamedModelResolutionError(
                f"Local model {model} is unavailable; start its server."
            )
        return catalog.model_routes[model], catalog.fetched_at

    def build_model(self, model: str) -> Model:
        return LocalModel(self, model)

    def request_settings(self, resolution: ThreadModelResolution, thread_id: str) -> ModelSettings:
        return _common_request_settings(resolution)


class LocalModel(WrapperModel):
    """Resolve the server before calling it, including saved pins after an app restart."""

    def __init__(self, adapter: LocalCompletionAdapter, model: str) -> None:
        self.adapter, self.local_name = adapter, model
        super().__init__(
            self._build(adapter.settings.local_model_url or "http://127.0.0.1:11434/v1")
        )

    def _build(self, url: str) -> Model:
        return OpenAIChatModel(
            self.local_name.removeprefix("local:"),
            provider=LocalProvider(base_url=url, api_key="local"),
            settings={"timeout": self.adapter.settings.model_request_timeout_seconds},
        )

    async def _resolve(self) -> None:
        await self.adapter.load_named_route(self.local_name)
        self.wrapped = self._build(self.adapter._urls[self.local_name])

    async def request(self, *args: Any, **kwargs: Any):
        await self._resolve()
        return await self.wrapped.request(*args, **kwargs)

    @asynccontextmanager
    async def request_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        await self._resolve()
        async with self.wrapped.request_stream(*args, **kwargs) as response:
            yield response


class CompletionRouter:
    """Own adapter selection while callers depend on one stable internal interface."""

    def __init__(self, settings: HarnessSettings) -> None:
        self.settings = settings
        openrouter_key = (
            settings.openrouter_api_key.get_secret_value()
            if settings.openrouter_api_key is not None
            else None
        )
        self._openrouter = OpenRouterCompletionAdapter(
            openrouter_key, settings.model_request_timeout_seconds
        )
        self._direct = DirectCompletionAdapter(settings)
        self.local = LocalCompletionAdapter(settings)
        self._adapters: tuple[CompletionAdapter, ...] = (self._openrouter, self._direct, self.local)

    @property
    def catalog(self) -> ModelCatalogLoader | None:
        return self

    @property
    def remote_catalog(self):
        if self._openrouter.catalog_available:
            return self._openrouter
        return self._direct if self._direct.catalog_available else None

    async def load(self) -> ModelCatalog:
        local = await self.local.load()
        remote = self.remote_catalog
        if remote is None:
            return local
        try:
            catalog = await remote.load()
        except ModelCatalogUnavailable:
            if local.listing:
                return local
            raise
        return replace(catalog, listing=catalog.listing + local.listing)

    def qualify_model(self, model: str) -> str:
        if model.startswith("local:"):
            return model
        remote = self.remote_catalog
        return remote.qualify_model(model) if remote else model

    def parse_named_model(self, model: str) -> str:
        if model.startswith("local:") and model.removeprefix("local:"):
            return model
        remote = self.remote_catalog
        if remote is None:
            raise NamedModelResolutionError("No remote model source is configured.")
        return remote.parse_named_model(model)

    async def load_named_route(self, model: str) -> tuple[ModelRoute, datetime]:
        if model.startswith("local:"):
            return await self.local.load_named_route(model)
        remote = self.remote_catalog
        if remote is None:
            raise ModelCatalogUnavailable("No remote model source is configured.")
        return await remote.load_named_route(model)

    async def offline_resolution(self, resolution: ThreadModelResolution) -> ThreadModelResolution:
        """Switch at a turn boundary only when the opted-in broker cannot be reached."""
        if not self.settings.local_when_offline or not resolution.uses_openrouter:
            return resolution
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get("https://openrouter.ai/api/v1/models")
            # An HTTP refusal (including a spent key) is reachable, never an offline signal.
            return resolution
        except httpx.TransportError:
            catalog = await self.local.load()
            model = self.settings.local_model
            if model and not model.startswith("local:"):
                model = f"local:{model}"
            if not model and catalog.listing:
                model = catalog.listing[0].model_id
            if model is None:
                raise ModelConfigurationError(
                    "OpenRouter is unreachable and no local model is running."
                )
            route, fetched_at = await self.local.load_named_route(model)
            return ThreadModelResolution(
                model=model,
                context_tokens=route.context_tokens,
                policy="local_when_offline",
                stickiness_epoch=resolution.stickiness_epoch + 1,
                supported_parameters=route.supported_parameters,
                catalog_fetched_at=fetched_at,
                request_parameters=resolution.request_parameters,
            )

    def model_for(self, model: str) -> Model:
        """Build a model through the first adapter that owns its route."""

        if not isinstance(model, str) or not model or model != model.strip():
            raise ModelConfigurationError(
                "chat model must be nonblank without surrounding whitespace"
            )
        adapter = self._adapter_for(model)
        try:
            return SpendWallModel(adapter.build_model(model))
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
    if resolution.supported_parameters is not None:
        settings = {
            key: value for key, value in settings.items() if key in resolution.supported_parameters
        }
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
