"""OpenRouter adapter details that pydantic-ai's generic error wrapper drops."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

from openai import APIError
from pydantic_ai.exceptions import ModelHTTPError
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
        except APIError as exc:
            raise _preserved_model_error(exc, self._model_name) from exc


class PreservingOpenRouterModel(OpenRouterModel):
    """Use the metadata-preserving stream wrapper for every Harness OpenRouter route."""

    @property
    @override
    def _streamed_response_cls(self):  # type: ignore[no-untyped-def]
        return PreservingOpenRouterStreamedResponse


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
