from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr

from harness.config import HarnessSettings
from harness.model_policy import (
    BenchmarkModel,
    ModelCatalog,
    ModelPolicyResolver,
    ModelRequestParameters,
    ModelRoute,
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


def test_pinned_direct_mode_uses_one_adapter_key_and_no_catalog() -> None:
    """P4 is defended by keeping policy-off direct mode independent of broker catalog state."""

    configured = settings(
        chat_model="openai:gpt-4o-mini",
        openai_api_key=SecretStr("direct-key"),
    )
    router = CompletionRouter(configured)

    model = router.model_for(configured.chat_model)

    assert configured.effective_model_policy_chat == "pinned:openai:gpt-4o-mini"
    assert configured.model_policy_optimization_enabled is False
    assert router.catalog is None
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
        "openrouter_reasoning": {"effort": "high"},
        "openrouter_provider": {"sort": "price"},
    }


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
