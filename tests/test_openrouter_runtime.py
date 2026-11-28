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


@pytest.mark.asyncio
async def test_filtered_request_keeps_only_providers_with_eligible_locations(tmp_path):
    """SPEC C.5 / SD-100: a restricted model turn cannot escape through another provider
    or a provider whose other datacenter would violate the owner's country rule."""
    import httpx
    from pydantic_ai.exceptions import ModelAPIError
    from pydantic_ai.models import ModelRequestParameters
    from spine.model_countries import CountryFilters
    from spine.model_policy import HomeModelChoices

    countries = HomeModelChoices(tmp_path).countries
    providers = [
        {"slug": "one", "headquarters": "US", "datacenters": ["US"]},
        {"slug": "mixed", "headquarters": "US", "datacenters": ["US", "FR"]},
        {"slug": "unknown", "headquarters": "US", "datacenters": []},
    ]

    def catalog(request):
        if request.url.path.endswith("/providers"):
            return httpx.Response(200, json={"data": providers})
        endpoints = [{"tag": p["slug"] + "/fast", "status": 0} for p in providers]
        return httpx.Response(200, json={"data": {"endpoints": endpoints}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(catalog)) as client:
        await countries.refresh(["mistralai/example"], client, "https://broker.test")
    model = model_router.OpenRouterCompletionAdapter("test", countries=countries).build_model(
        "openrouter:mistralai/example"
    )

    def routing():
        settings, _ = model.prepare_request(
            {"openrouter_provider": {"sort": "price"}}, ModelRequestParameters()
        )
        return settings["extra_body"]["provider"]

    assert routing() == {"sort": "price"}
    countries.save(CountryFilters.model_validate({"maker": {"countries": ["CN"]}}))
    assert routing() == {"sort": "price"}
    filters = CountryFilters.model_validate({"serving": {"mode": "allow", "countries": ["US"]}})
    countries.save(filters)
    assert routing() == {"sort": "price", "only": ["one"]}
    countries.save(
        CountryFilters.model_validate(
            {"serving": {"mode": "allow", "countries": ["US"], "keep_unknown": True}}
        )
    )
    assert routing()["only"] == ["one", "unknown"]
    countries.save(
        CountryFilters.model_validate({"serving": {"mode": "allow", "countries": ["FR"]}})
    )
    with pytest.raises(ModelAPIError, match="No allowed provider serves this model"):
        routing()


@pytest.mark.asyncio
async def test_resolved_conversation_refreshes_expired_provider_locations(tmp_path, monkeypatch):
    """SPEC C.5 / SD-100: a retained conversation refreshes aged fleet data before dispatch;
    a failed refresh must not send a completion or masquerade as an empty provider list."""
    import json
    import sqlite3

    import httpx
    from pydantic import SecretStr
    from pydantic_ai.exceptions import ModelAPIError
    from spine.model_countries import CountryFilters
    from spine.model_policy import ModelPolicyResolver, OpenRouterCatalogClient

    from harness.config import HarnessSettings

    settings = HarnessSettings(
        _env_file=None,
        nocturne_home=tmp_path,
        openrouter_api_key=SecretStr("example"),
        spine_token=SecretStr("example"),
    )
    router = model_router.CompletionRouter(settings)
    choices = settings.model_choices
    choices.countries.save(
        CountryFilters.model_validate({"serving": {"mode": "allow", "countries": ["FR"]}})
    )
    slug = "mistralai/example"
    provider = "first"
    destinations = []

    def broker(request):
        if request.url.path.endswith("/providers"):
            if not provider:
                return httpx.Response(503)
            data = [{"slug": provider, "headquarters": "FR", "datacenters": ["FR"]}]
        elif request.url.path.endswith(f"/models/{slug}/endpoints"):
            data = {"endpoints": [{"tag": provider, "status": 0}]}
        elif request.url.path.endswith("/models"):
            data = [{"id": slug, "context_length": 4096}]
        else:
            assert request.url.path.endswith("/chat/completions")
            destinations.append(json.loads(request.content)["provider"]["only"])
            return httpx.Response(
                200,
                json={
                    "id": "example",
                    "model": slug,
                    "created": 1,
                    "object": "chat.completion",
                    "provider": provider,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "ok"},
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"data": data})

    def expire():
        with sqlite3.connect(choices.countries.path) as db:
            db.execute("UPDATE country_catalog SET checked=checked-86401")

    async with httpx.AsyncClient(transport=httpx.MockTransport(broker)) as client:
        router._openrouter._catalog = OpenRouterCatalogClient("example", http_client=client)
        await router.load_countries([f"openrouter:{slug}"])
        assert choices.countries.catalog().models == {slug: ["first"]}
        monkeypatch.setattr(
            model_router,
            "OpenRouterProvider",
            lambda api_key: OpenRouterProvider(api_key=api_key, http_client=client),
        )
        resolver = ModelPolicyResolver(
            policy=f"pinned:openrouter:{slug}",
            static_model=None,
            static_context_tokens=None,
            catalog=router,
            choices=choices,
        )
        pick = await resolver.resolve("same-thread")
        agent = Agent(router.model_for(pick.model))
        first = await agent.run("First turn.")
        expire()
        provider = "second"
        assert await resolver.resolve("same-thread") is pick
        second = await agent.run("Next turn.", message_history=first.all_messages())
        assert second.output == "ok"
        expire()
        agent = Agent(router.model_for(pick.model))
        provider = ""
        with pytest.raises(ModelAPIError, match="Provider locations could not be refreshed"):
            async with agent.run_stream("Again.", message_history=second.all_messages()):
                pytest.fail("Refresh failure must precede streaming")
        assert destinations == [["first"], ["second"]]
