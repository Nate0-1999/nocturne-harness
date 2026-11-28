from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from harness.config import HarnessSettings
from harness.model_policy import (
    BenchmarkModel,
    ModelCatalog,
    ModelPolicyResolver,
    ModelRequestParameters,
    ModelRoute,
    NamedModelResolutionError,
    ThreadModelResolution,
)
from harness.model_router import (
    CompletionRouter,
    DirectCompletionAdapter,
    OpenRouterCompletionAdapter,
)


def settings(**overrides: object) -> HarnessSettings:
    values: dict[str, object] = {
        "spine_token": SecretStr("spine"),
        "anthropic_api_key": None,
        "openai_api_key": None,
        "openrouter_api_key": None,
        **overrides,
    }
    return HarnessSettings(_env_file=None, **values)


def test_pinned_direct_mode_uses_one_adapter_key_and_no_broker_catalog() -> None:
    """P4 is defended by keeping policy-off direct mode independent of broker catalog state;
    its only catalog is the source's own model list (FL-202).
    """

    configured = settings(
        chat_model="openai:gpt-4o-mini",
        openai_api_key=SecretStr("direct-key"),
    )
    router = CompletionRouter(configured)

    model = router.model_for(configured.chat_model)

    assert configured.effective_model_policy_chat == "pinned:openai:gpt-4o-mini"
    assert configured.model_policy_optimization_enabled is False
    assert router.remote_catalog is router._direct
    assert model.provider is not None
    assert model.provider.name == "openai"


def test_openrouter_is_adapter_one_with_optional_catalog_capability() -> None:
    """P4 is defended by keeping OpenRouter behind the same explicit completion seam."""

    configured = settings(openrouter_api_key=SecretStr("router-key"))
    router = CompletionRouter(configured)

    model = router.model_for("openrouter:vendor/model")

    assert isinstance(router._adapters[0], OpenRouterCompletionAdapter)
    assert isinstance(router._adapters[1], DirectCompletionAdapter)
    assert router.catalog is not None
    assert model.provider is not None
    assert model.provider.name == "openrouter"


def test_each_adapter_owns_its_request_shape_without_behavior_drift() -> None:
    """A-020 and A-034 are defended by adapter-local request shaping in both routing modes."""

    parameters = ModelRequestParameters(temperature=0.25, effort="high")
    router = CompletionRouter(settings())

    direct = router.request_settings(
        ThreadModelResolution(
            model="openai:gpt-4o-mini",
            context_tokens=128_000,
            policy="pinned:openai:gpt-4o-mini",
            request_parameters=parameters,
        ),
        "thread-one",
    )
    brokered = router.request_settings(
        ThreadModelResolution(
            model="openrouter:vendor/model",
            context_tokens=128_000,
            policy="elbow",
            price_sorted=True,
            request_parameters=parameters,
        ),
        "thread-one",
    )

    assert direct == {"temperature": 0.25}
    assert brokered == {
        "temperature": 0.25,
        "extra_body": {"session_id": "thread-one"},
        "openrouter_usage": {"include": True},
        "openrouter_cache_instructions": True,
        "openrouter_cache_messages": True,
        "openrouter_cache_tool_definitions": True,
        "openrouter_reasoning": {"effort": "high"},
        "openrouter_provider": {"sort": "price"},
    }


def test_top_k_reaches_openrouter_in_the_request_body() -> None:
    """A-034: model.top_k must ride the request; the OpenAI-compatible client drops a top_k
    setting, so OpenRouter receives it in the body beside the session id (FL-107's walk saw
    a journaled 40 sent as null)."""

    brokered = CompletionRouter(settings()).request_settings(
        ThreadModelResolution(
            model="openrouter:minimax/minimax-m3",
            context_tokens=1_000_000,
            policy="pinned:openrouter:minimax/minimax-m3",
            request_parameters=ModelRequestParameters(top_k=40),
        ),
        "thread-one",
    )

    assert brokered["extra_body"] == {"session_id": "thread-one", "top_k": 40}


def test_hidden_unsupported_parameters_do_not_reach_the_model() -> None:
    """F174: changing models may retain knobs, but cannot send unsupported ones."""
    request = CompletionRouter(settings()).request_settings(
        ThreadModelResolution(
            model="openrouter:openai/gpt-4o-mini",
            context_tokens=128_000,
            policy="pinned:openrouter:openai/gpt-4o-mini",
            supported_parameters=frozenset({"temperature", "max_tokens"}),
            request_parameters=ModelRequestParameters(
                temperature=0.4, top_k=40, top_p=0.5, effort="high"
            ),
        ),
        "thread-two",
    )
    assert request["temperature"] == 0.4
    assert request["extra_body"] == {"session_id": "thread-two"}
    assert "top_k" not in request
    assert "top_p" not in request
    assert "openrouter_reasoning" not in request


@pytest.mark.asyncio
async def test_policy_resolver_uses_adapter_qualification_instead_of_openrouter_architecture() -> (
    None
):
    """Invariant 13 and P4 are defended by allowing policy selection over another adapter."""

    fetched_at = datetime(2026, 8, 17, tzinfo=UTC)

    class CustomCatalogAdapter:
        async def load(self) -> ModelCatalog:
            return ModelCatalog(
                rows=(
                    BenchmarkModel("low", Decimal(10), Decimal(1), Decimal(1)),
                    BenchmarkModel("middle", Decimal(20), Decimal(2), Decimal(2)),
                    BenchmarkModel("high", Decimal(30), Decimal(8), Decimal(8)),
                ),
                model_routes={
                    "low": ModelRoute("low-route", 32_000),
                    "middle": ModelRoute("middle-route", 64_000),
                    "high": ModelRoute("high-route", 128_000),
                },
                fetched_at=fetched_at,
            )

        async def load_named_route(self, model_id: str) -> tuple[ModelRoute, datetime]:
            return ModelRoute(model_id, 96_000), fetched_at

        def qualify_model(self, model_id: str) -> str:
            return f"custom:{model_id}"

        def parse_named_model(self, model: str) -> str:
            return model.removeprefix("custom:")

    resolver = ModelPolicyResolver(
        policy="max",
        static_model="custom:fallback",
        static_context_tokens=16_000,
        catalog=CustomCatalogAdapter(),
    )

    selected = await resolver.resolve("thread-custom")
    named = await resolver.resolve_named("thread-custom", "custom:owner-choice")

    assert selected.model == "custom:high-route"
    assert selected.context_tokens == 128_000
    assert named.model == "custom:owner-choice"
    assert named.context_tokens == 96_000


@pytest.mark.asyncio
async def test_single_key_mode_lists_its_sources_own_models_and_switches_among_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P4 is defended by giving M3G's one-key OFF mode the source's own model list (FL-202):
    no benchmarks, so policies stay dormant, but /model and the browser switch within it.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "127.0.0.1":
            raise httpx.ConnectError("No local server", request=request)
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "gpt-4.1-mini", "object": "model"},
                    {"id": "gpt-4.1", "object": "model", "supported_parameters": ["reasoning"]},
                ],
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "harness.model_router.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    configured = settings(
        chat_model="openai:gpt-4.1-mini",
        openai_api_key=SecretStr("direct-key"),
        openai_base_url="https://compatible.example/v1/",
        model_context_tokens=64_000,
    )
    router = CompletionRouter(configured)
    resolver = ModelPolicyResolver(
        policy=configured.effective_model_policy_chat,
        static_model=configured.chat_model,
        static_context_tokens=configured.model_context_tokens,
        catalog=router.catalog,
    )

    catalog = await router.catalog.load()  # type: ignore[union-attr]
    switched = await resolver.resolve_named("thread", "openai:gpt-4.1")
    await router.catalog.load()  # type: ignore[union-attr]

    assert catalog.rows == ()
    assert [entry.model_id for entry in catalog.listing] == ["gpt-4.1-mini", "gpt-4.1"]
    assert not any(entry.reasoning for entry in catalog.listing)
    assert (switched.model, switched.context_tokens) == ("openai:gpt-4.1", 64_000)
    assert len(seen) == 1  # one fetch serves the list, the switch and a later read
    assert str(seen[0].url) == "https://compatible.example/v1/models"
    assert seen[0].headers["Authorization"] == "Bearer direct-key"
    with pytest.raises(NamedModelResolutionError):
        await resolver.resolve_named("thread", "openai:not-listed")
    assert len(seen) == 2  # the miss refetched once


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,plan", [("codex", "chatgpt"), ("claudeAgent", "pro")])
async def test_stock_subscription_choice_uses_the_offered_models_window(
    tmp_path, monkeypatch, tool, plan
):
    """A-095: a stock verification home must resolve a listed native model before its first turn."""
    import asyncio
    import json
    import secrets
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from harness import onboarding

    monkeypatch.delenv("MODEL_CONTEXT_TOKENS", raising=False)
    monkeypatch.setattr(onboarding, "_discover_cloud_palace", lambda *_: None)
    monkeypatch.setattr(onboarding, "_ensure_tool_runtimes", lambda *_args, **_kwargs: None)
    onboarding.init_nocturne(
        home=tmp_path,
        verification=True,
        environ={"OPENROUTER_API_KEY": "fixture"},
        prompt=lambda _: "n",
    )
    environment = onboarding.load_config(home=tmp_path).process_environment({})
    assert "MODEL_CONTEXT_TOKENS" not in environment
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    router = CompletionRouter(HarnessSettings(_env_file=None))
    slug = uuid4().hex
    window = secrets.randbits(20) + 1
    provider = {
        "instanceId": tool,
        "status": "ready",
        "models": [{"slug": slug}],
        "auth": {"status": "authenticated", "type": plan, "profileId": "fixture"},
    }
    client = SimpleNamespace(
        call=AsyncMock(return_value={"providers": [provider]}), native_env={"TMPDIR": str(tmp_path)}
    )
    server = Mock()
    server.client = AsyncMock(return_value=client)
    server._settings.return_value = {"providerInstances": {tool: {"config": {"binaryPath": tool}}}}
    router.subscription_server = server

    def native(args, **kwargs):
        if tool == "codex":
            assert args[1:] == ["debug", "models"]
            output = {
                "models": [
                    {
                        "slug": slug,
                        "context_window": window * 2,
                        "effective_context_window_percent": 50,
                    }
                ]
            }
        else:
            assert args[args.index("--model") + 1] == slug
            request = json.loads(kwargs["input"])
            assert request["request"] == {"subtype": "get_context_usage"}
            output = {
                "type": "control_response",
                "response": {
                    "request_id": request["request_id"],
                    "subtype": "success",
                    "response": {"model": slug, "maxTokens": window},
                },
            }
        return SimpleNamespace(stdout=json.dumps(output))

    query = Mock(side_effect=native)
    monkeypatch.setattr("subprocess.run", query)
    resolver = ModelPolicyResolver(
        policy=router.settings.effective_model_policy_chat,
        static_model=router.settings.chat_model,
        static_context_tokens=router.settings.model_context_tokens,
        catalog=router.catalog,
    )
    requested = f"subscription:{tool}/{slug}"
    selected, repeated = await asyncio.gather(
        resolver.resolve_named("thread", requested), resolver.resolve_named("thread", requested)
    )
    assert repeated.context_tokens == window
    assert selected.context_tokens == window
    assert selected.model.endswith(f"/{slug}")
    query.assert_called_once()
    provider["models"].clear()
    with pytest.raises(NamedModelResolutionError, match="unavailable"):
        await resolver.resolve_named("thread", requested)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "native,measured,configured",
    [(True, True, True), (False, True, True), (False, False, True), (False, False, False)],
)
async def test_subscription_window_survives_native_catalog_changes(
    native, measured, configured, monkeypatch, tmp_path
):
    """A-112: a catalog format change must not strand a previously measured conversation."""
    import asyncio
    import hashlib
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from harness.transcript import TranscriptJournal

    slug = uuid4().hex
    sizes = range(len(slug), len(slug) + 3)
    key = f"subscription:codex/account/{slug}"
    router = CompletionRouter(settings(model_context_tokens=sizes[2] if configured else None))
    journal = TranscriptJournal(tmp_path)
    router.subscription_binding = journal.subscription_binding
    journal.bind_subscription(
        "thread",
        {
            "source": key,
            "environment": hashlib.sha256(b"local").hexdigest(),
            "native_thread": "bound",
        },
    )
    client = SimpleNamespace(environment_id="local", native_env={"TMPDIR": str(tmp_path)})
    server = Mock()
    server.client = AsyncMock(return_value=client)
    server._settings.return_value = {
        "providerInstances": {"codex": {"config": {"binaryPath": "codex"}}}
    }
    router.subscription_server = server
    monkeypatch.setattr(
        "harness.model_router.resolve_offer",
        AsyncMock(return_value=(key, {"tool": "codex"}, {"id": slug})),
    )
    run = {"ordinal": 1, "activeAttemptId": "a", "providerThreadId": "p", "status": "completed"}
    turn = {
        "ordinal": 1,
        "runAttemptId": "a",
        "providerThreadId": "p",
        "status": "completed",
        "tokenUsage": {"maxTokens": sizes[1]},
    }
    client.call = AsyncMock(
        return_value={"runs": [run], "providerTurns": [turn] if measured else []}
    )
    catalog = {
        "models": [
            {"slug": slug, "context_window": sizes[0], "effective_context_window_percent": 100}
        ]
    }
    query = Mock(return_value=SimpleNamespace(stdout=json.dumps(catalog if native else {})))
    monkeypatch.setattr("subprocess.run", query)
    resolver = ModelPolicyResolver(
        policy="elbow",
        static_model=None,
        static_context_tokens=router.settings.model_context_tokens,
        catalog=router,
    )
    if native or measured or configured:
        expected = sizes[0] if native else sizes[1] if measured else sizes[2]
        assert (await resolver.resolve_hydrated("thread", key)).context_tokens == expected
        if measured and not native:
            assert (await resolver.resolve_named("other", key)).context_tokens == sizes[2]
    else:

        async def first_choice():
            with pytest.raises(
                NamedModelResolutionError, match="The tool did not report a context size"
            ):
                await resolver.resolve_hydrated("thread", key)

        await asyncio.gather(first_choice(), first_choice())
        query.assert_called_once()
        query.return_value = SimpleNamespace(stdout=json.dumps(catalog))
        for _ in range(3):
            assert (await resolver.resolve_hydrated("thread", key)).context_tokens == sizes[0]
        assert query.call_count == 2
