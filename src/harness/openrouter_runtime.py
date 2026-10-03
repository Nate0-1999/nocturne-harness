"""OpenRouter adapter details that pydantic-ai's generic error wrapper drops."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, override

from openai import APIError, APITimeoutError
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT
from pydantic_ai.models.openrouter import (
    OpenRouterModel,
    OpenRouterStreamedResponse,
    _OpenRouterChatCompletionChunk,
)


class PreservingOpenRouterStreamedResponse(OpenRouterStreamedResponse):
    """Keep OpenRouter's canonical error_type metadata on streamed failures. [A-054]"""

    @override
    async def _validate_response(self):  # type: ignore[no-untyped-def]
        try:
            async for chunk in self._response:
                validated = _OpenRouterChatCompletionChunk.model_validate(chunk.model_dump())
                if details := _usage_only_provider_details(validated):
                    self.provider_details = {**(self.provider_details or {}), **details}
                yield validated
        except APITimeoutError:
            raise  # F169: a silent stream is a stall, not an HTTP 500.
        except APIError as exc:
            raise _preserved_model_error(exc, self._model_name) from exc


class ModelStalled(ModelAPIError):
    """A model request that sent nothing for its quiet bound. [F169]"""

    def __init__(self, model_name: str, *, quiet_seconds: float, waited_seconds: float) -> None:
        self.quiet_seconds = quiet_seconds
        self.waited_seconds = waited_seconds
        super().__init__(
            model_name,
            f"{model_name} stopped answering: nothing arrived for {_duration(quiet_seconds)} "
            f"({_duration(waited_seconds)} since the request began)",
        )


class PreservingOpenRouterModel(OpenRouterModel):
    """Use the metadata-preserving stream wrapper for every Harness OpenRouter route."""

    @property
    @override
    def _streamed_response_cls(self):  # type: ignore[no-untyped-def]
        return PreservingOpenRouterStreamedResponse

    @override
    async def request(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        started = time.monotonic()
        try:
            return await super().request(*args, **kwargs)
        except ModelAPIError as exc:
            if not isinstance(exc.__cause__, APITimeoutError):
                raise
            raise self._stalled(started) from exc

    @override
    @asynccontextmanager
    async def request_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        started = time.monotonic()
        try:
            async with super().request_stream(*args, **kwargs) as response:
                yield response
        except (APITimeoutError, ModelAPIError) as exc:
            if not isinstance(exc, APITimeoutError) and not isinstance(
                exc.__cause__, APITimeoutError
            ):
                raise
            raise self._stalled(started) from exc

    def _stalled(self, started: float) -> ModelStalled:
        quiet = (self.settings or {}).get("timeout", DEFAULT_HTTP_TIMEOUT)
        return ModelStalled(
            self.model_name,
            quiet_seconds=quiet if isinstance(quiet, int | float) else DEFAULT_HTTP_TIMEOUT,
            waited_seconds=time.monotonic() - started,
        )


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.3g} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest} s" if rest else f"{minutes} min"


def _preserved_model_error(exc: APIError, model_name: str) -> ModelHTTPError:
    body = exc.body
    status_code = _error_status(body)
    return ModelHTTPError(status_code=status_code, model_name=model_name, body=body)


def _usage_only_provider_details(chunk: _OpenRouterChatCompletionChunk) -> dict[str, Any]:
    """Retain OpenRouter billing metadata from its terminal usage-only chunk. [SD-023]"""

    usage = chunk.usage
    if chunk.choices or usage is None:
        return {}
    details: dict[str, Any] = {}
    if chunk.provider is not None:
        details["downstream_provider"] = chunk.provider
    if usage.cost is not None:
        details["cost"] = usage.cost
    if cost_details := usage.cost_details:
        details["upstream_inference_cost"] = cost_details.upstream_inference_cost
        details["upstream_inference_prompt_cost"] = cost_details.upstream_inference_prompt_cost
        details["upstream_inference_completions_cost"] = (
            cost_details.upstream_inference_completions_cost
        )
    if usage.is_byok is not None:
        details["is_byok"] = usage.is_byok
    if server_tool_use := usage.server_tool_use_details:
        details["server_tool_use"] = {
            "tool_calls_requested": server_tool_use.tool_calls_requested,
            "tool_calls_executed": server_tool_use.tool_calls_executed,
        }
    return details


def _error_status(body: object | None) -> int:
    if isinstance(body, Mapping):
        code: Any = body.get("code")
        if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
            return code
        error = body.get("error")
        if isinstance(error, Mapping):
            nested: Any = error.get("code")
            if isinstance(nested, int) and not isinstance(nested, bool) and 100 <= nested <= 599:
                return nested
    return 500


__all__ = ["PreservingOpenRouterModel"]
