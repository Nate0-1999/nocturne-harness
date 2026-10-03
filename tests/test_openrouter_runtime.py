import asyncio

import pytest
from httpx import Request
from openai import APIError, AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.providers.openrouter import OpenRouterProvider

from harness import model_router
from harness.openrouter_runtime import (
    ModelStalled,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["before the answer", "mid-answer"])
async def test_f169_a_silent_model_request_ends_at_the_bound_naming_the_model_and_the_wait(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """F169 is defended by verifying that a model request that goes silent, before or during its
    answer, ends at the harness's own bound with an error naming the model and the wait, where
    the client default had held the run for 10 minutes per attempt.
    """

    async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        if phase == "mid-answer":
            writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n\r\n")
            writer.write(
                b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m",'
                b'"choices":[{"index":0,"delta":{"role":"assistant","content":"Hel"}}]}\n\n'
            )
            await writer.drain()
        await asyncio.sleep(3600)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(
        model_router,
        "OpenRouterProvider",
        lambda api_key: OpenRouterProvider(
            openai_client=AsyncOpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key=api_key)
        ),
    )
    model = model_router.OpenRouterCompletionAdapter("test", 0.3).build_model(
        "openrouter:openai/gpt-4.1-mini"
    )
    try:
        with pytest.raises(ModelStalled) as stalled:
            async with asyncio.timeout(15):
                async with Agent(model).run_stream("hello") as run:
                    async for _ in run.stream_text():
                        pass
    finally:
        server.close()

    assert stalled.value.model_name == "openai/gpt-4.1-mini"
    assert stalled.value.message.startswith(
        "openai/gpt-4.1-mini stopped answering: nothing arrived for 0.3 s ("
    )
    assert stalled.value.waited_seconds < 15
