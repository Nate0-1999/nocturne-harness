from httpx import Request
from openai import APIError
from pydantic_ai.providers.openrouter import OpenRouterProvider

from harness.openrouter_runtime import (
    PreservingOpenRouterModel,
    PreservingOpenRouterStreamedResponse,
    _preserved_model_error,
)


def test_f034_openrouter_stream_adapter_preserves_canonical_error_type_metadata() -> None:
    """F034 and v2.52 are defended by verifying that Harness preserves OpenRouter's canonical
    streamed error_type before pydantic-ai can collapse it to a generic provider message.
    """
    body = {
        "code": 400,
        "message": "Provider returned error",
        "metadata": {
            "error_type": "invalid_request",
            "provider_code": "context_length_exceeded",
        },
    }
    source = APIError("provider failed", Request("POST", "https://openrouter.ai"), body=body)

    preserved = _preserved_model_error(source, "rekaai/reka-edge")

    assert preserved.status_code == 400
    assert preserved.body == body
    assert PreservingOpenRouterModel(
        "rekaai/reka-edge", provider=OpenRouterProvider(api_key="test")
    )._streamed_response_cls is (PreservingOpenRouterStreamedResponse)
