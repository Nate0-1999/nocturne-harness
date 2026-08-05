from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from harness.model_policy import (
    BenchmarkModel,
    ModelCatalog,
    ModelCatalogUnavailable,
    ModelPolicy,
    ModelPolicyConfigurationError,
    ModelPolicyResolver,
    ModelRoute,
    NamedModelResolutionError,
    OpenRouterCatalogClient,
    ThreadModelResolution,
    _parse_model_routes,
    lower_convex_hull,
    pareto_frontier,
    parse_model_policy,
    select_model,
)


def row(
    slug: str,
    intelligence: str,
    prompt_price: str,
    completion_price: str = "0",
) -> BenchmarkModel:
    return BenchmarkModel(
        permaslug=slug,
        intelligence_index=Decimal(intelligence),
        prompt_price=Decimal(prompt_price),
        completion_price=Decimal(completion_price),
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pinned:openrouter:vendor/model", ModelPolicy("pinned", "openrouter:vendor/model")),
        ("max", ModelPolicy("max")),
        ("elbow", ModelPolicy("elbow")),
        ("slope:0.05", ModelPolicy("slope", Decimal("0.05"))),
        ("floor:52", ModelPolicy("floor", Decimal(52))),
    ],
)
def test_policy_grammar_accepts_exact_five_forms(raw: str, expected: ModelPolicy) -> None:
    """A-021 is defended by verifying that policy grammar accepts exact five forms; this
    prevents drift in the deterministic model policy contract.
    """
    assert parse_model_policy(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " max",
        "MAX",
        "pinned:",
        "pinned:model-without-provider",
        "slope:0",
        "slope:-1",
        "slope:NaN",
        "floor:Infinity",
        "budget:10",
    ],
)
def test_policy_grammar_rejects_every_other_form(raw: str) -> None:
    """A-021 is defended by verifying that policy grammar rejects every other form; this
    prevents drift in the deterministic model policy contract.
    """
    with pytest.raises(ModelPolicyConfigurationError):
        parse_model_policy(raw)


def test_all_policy_algorithms_follow_one_golden_table() -> None:
    """A-021 is defended by verifying that all policy algorithms follow one golden table; this
    prevents drift in the deterministic model policy contract.
    """
    rows = (
        row("base", "10", "1"),
        row("dup-z", "20", "2", ".1"),
        row("dup-a", "20", "2", "9"),
        row("same-intelligence-expensive", "20", "3"),
        row("same-price-weaker", "15", "2"),
        row("cross-dominated", "18", "2.5"),
        row("good", "30", "4"),
        row("apex", "40", "16"),
    )

    assert [item.permaslug for item in pareto_frontier(rows)] == [
        "base",
        "dup-a",
        "good",
        "apex",
    ]
    assert select_model(ModelPolicy("max"), rows).permaslug == "apex"
    assert select_model(ModelPolicy("elbow"), rows).permaslug == "good"
    assert select_model(ModelPolicy("floor", Decimal(20)), rows).permaslug == "dup-z"
    assert select_model(ModelPolicy("slope", Decimal(".05")), rows).permaslug == "base"
    assert select_model(ModelPolicy("slope", Decimal(".10")), rows).permaslug == "dup-a"
    assert select_model(ModelPolicy("slope", Decimal(".20")), rows).permaslug == "good"
    assert select_model(ModelPolicy("slope", Decimal("1.20")), rows).permaslug == "apex"


def test_elbow_matches_the_a021_worked_example_and_small_frontier_max_rule() -> None:
    """A-021 is defended by verifying that elbow matches the a021 worked example and small
    frontier max rule; this prevents drift in the deterministic model policy contract.
    """
    worked = (
        row("A", "20", ".10"),
        row("B", "35", ".30"),
        row("C", "55", "1.00"),
        row("D", "60", "8.00"),
    )
    assert select_model(ModelPolicy("elbow"), worked).permaslug == "C"

    two_points = (row("cheap", "10", "1"), row("smart", "20", "2"))
    assert select_model(ModelPolicy("elbow"), two_points).permaslug == "smart"


def test_elbow_ties_fall_to_lower_prompt_price_and_zero_price_is_degenerate() -> None:
    """A-021 is defended by verifying that elbow ties fall to lower prompt price and zero price
    is degenerate; this prevents drift in the deterministic model policy contract.
    """
    tied = (
        row("start", "10", "1"),
        row("early", "60", "10"),
        row("late", "85", "100"),
        row("end", "110", "10000"),
    )
    assert select_model(ModelPolicy("elbow"), tied).permaslug == "early"

    zero_price = (
        row("free", "10", "0"),
        row("top", "30", "2"),
    )
    with pytest.raises(ModelCatalogUnavailable, match="non-positive"):
        select_model(ModelPolicy("elbow"), zero_price)


def test_lower_hull_retains_collinear_vertices_and_slope_equality_is_inclusive() -> None:
    """A-021 is defended by verifying that lower hull retains collinear vertices and slope
    equality is inclusive; this prevents drift in the deterministic model policy contract.
    """
    rows = (
        row("one", "10", "1"),
        row("two", "20", "2"),
        row("three", "30", "3"),
        row("four", "40", "5"),
    )
    assert [item.permaslug for item in lower_convex_hull(rows)] == [
        "one",
        "two",
        "three",
        "four",
    ]
    assert select_model(ModelPolicy("slope", Decimal(".1")), rows).permaslug == "three"


def test_slope_matches_a021_worked_example_and_one_point_is_degenerate() -> None:
    """A-021 is defended by verifying that slope matches a021 worked example and one point is
    degenerate; this prevents drift in the deterministic model policy contract.
    """
    worked = (
        row("a", "54", ".90"),
        row("b", "55", "1.00"),
        row("skipped", "55.3", "1.60"),
        row("c", "58", "1.70"),
        row("d", "65", "9.00"),
    )
    assert select_model(ModelPolicy("slope", Decimal(".5")), worked).permaslug == "c"

    with pytest.raises(ModelCatalogUnavailable, match="fewer than two"):
        select_model(ModelPolicy("slope", Decimal(".5")), (row("only", "1", "1"),))


def test_extreme_external_decimal_arithmetic_is_a_fail_open_condition() -> None:
    """A-021 is defended by verifying that extreme external decimal arithmetic is a fail open
    condition; this prevents drift in the deterministic model policy contract.
    """
    extreme = (
        row("cheap", "10", "1"),
        row("middle", "20", "2"),
        row("extreme", "30", "1e1000000"),
    )

    with pytest.raises(ModelCatalogUnavailable, match="arithmetic is degenerate"):
        select_model(ModelPolicy("slope", Decimal(".5")), extreme)


def benchmark_payload(*, prompt: str = "0.000001") -> dict[str, object]:
    return {
        "data": [
            {
                "source": "artificial-analysis",
                "model_permaslug": "vendor/model",
                "intelligence_index": 52,
                "pricing": {
                    "prompt": prompt,
                    "completion": "0.000002",
                },
            },
            {
                "source": "other-source",
                "model_permaslug": "ignored/model",
                "intelligence_index": 99,
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "source": "artificial-analysis",
                "model_permaslug": "incomplete/model",
                "intelligence_index": None,
                "pricing": {"prompt": "0", "completion": "0"},
            },
        ]
    }


def models_payload() -> dict[str, object]:
    return {
        "data": [
            {
                "id": "vendor/model",
                "canonical_slug": "vendor/model",
                "context_length": 131_072,
            },
            {
                "id": "vendor/model:free",
                "canonical_slug": "vendor/model",
                "context_length": 64_000,
            },
        ]
    }


def test_model_routes_prefer_standard_use_sole_variant_and_drop_real_ambiguity() -> None:
    """A-021 is defended by verifying that model routes prefer standard use sole variant and
    drop real ambiguity; this prevents drift in the deterministic model policy contract.
    """
    routes = _parse_model_routes(
        {
            "data": [
                {
                    "id": "vendor/standard",
                    "canonical_slug": "vendor/standard-v1",
                    "context_length": 100_000,
                },
                {
                    "id": "vendor/standard:free",
                    "canonical_slug": "vendor/standard-v1",
                    "context_length": 50_000,
                },
                {
                    "id": "vendor/only:free",
                    "canonical_slug": "vendor/only-v1",
                    "context_length": 25_000,
                },
                {
                    "id": "vendor/ambiguous:free",
                    "canonical_slug": "vendor/ambiguous-v1",
                    "context_length": 20_000,
                },
                {
                    "id": "vendor/ambiguous:batch",
                    "canonical_slug": "vendor/ambiguous-v1",
                    "context_length": 10_000,
                },
                {
                    "id": "vendor/alias-one",
                    "canonical_slug": "vendor/two-standard-v1",
                    "context_length": 30_000,
                },
                {
                    "id": "vendor/alias-two",
                    "canonical_slug": "vendor/two-standard-v1",
                    "context_length": 30_000,
                },
                {
                    "id": "vendor/invalid-standard",
                    "canonical_slug": "vendor/invalid-standard-v1",
                    "context_length": 0,
                },
                {
                    "id": "vendor/invalid-standard:free",
                    "canonical_slug": "vendor/invalid-standard-v1",
                    "context_length": 20_000,
                },
                {
                    "id": "vendor/mixed-variants:free",
                    "canonical_slug": "vendor/mixed-variants-v1",
                    "context_length": 20_000,
                },
                {
                    "id": "vendor/mixed-variants:batch",
                    "canonical_slug": "vendor/mixed-variants-v1",
                    "context_length": None,
                },
            ]
        }
    )

    assert routes == {
        "vendor/standard-v1": ModelRoute("vendor/standard", 100_000),
        "vendor/only-v1": ModelRoute("vendor/only:free", 25_000),
    }


@pytest.mark.asyncio
async def test_catalog_normalizes_per_token_prices_and_caches_for_strictly_under_24h() -> None:
    """A-021 is defended by verifying that catalog normalizes per token prices and caches for
    strictly under 24h; this prevents drift in the deterministic model policy contract.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/benchmarks"):
            assert dict(request.url.params) == {"source": "artificial-analysis"}
            return httpx.Response(200, json=benchmark_payload())
        return httpx.Response(200, json=models_payload())

    monotonic = [100.0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterCatalogClient(
            "test-key",
            http_client=http_client,
            monotonic=lambda: monotonic[0],
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
        )
        first = await client.load()
        assert first.rows == (row("vendor/model", "52", "1", "2"),)
        assert first.model_routes == {
            "vendor/model": ModelRoute(
                model_id="vendor/model",
                context_tokens=131_072,
            )
        }
        monotonic[0] += 86_399
        assert await client.load() is first
        assert len(requests) == 2

        monotonic[0] += 1
        refreshed = await client.load()
        assert refreshed is not first
        assert len(requests) == 4


@pytest.mark.asyncio
async def test_catalog_refresh_is_single_flight_and_expired_failure_never_reuses_stale() -> None:
    """A-021 is defended by verifying that catalog refresh is single flight and expired failure
    never reuses stale; this prevents drift in the deterministic model policy contract.
    """
    request_count = 0
    fail = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if fail:
            return httpx.Response(503)
        payload = (
            benchmark_payload() if request.url.path.endswith("/benchmarks") else models_payload()
        )
        return httpx.Response(200, json=payload)

    monotonic = [0.0]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterCatalogClient(
            "test-key",
            http_client=http_client,
            monotonic=lambda: monotonic[0],
        )
        first, second = await asyncio.gather(client.load(), client.load())
        assert first is second
        assert request_count == 2

        monotonic[0] = 86_400
        fail = True
        with pytest.raises(ModelCatalogUnavailable, match="HTTP 503"):
            await client.load()
        assert request_count == 4


@dataclass
class FakeCatalog:
    value: ModelCatalog
    calls: int = 0
    named_routes: dict[str, ModelRoute] | None = None
    named_calls: list[str] | None = None

    async def load(self) -> ModelCatalog:
        self.calls += 1
        return self.value

    async def load_named_route(self, model_id: str) -> tuple[ModelRoute, datetime]:
        if self.named_calls is None:
            self.named_calls = []
        self.named_calls.append(model_id)
        routes = self.value.model_routes if self.named_routes is None else self.named_routes
        route = routes.get(model_id)
        if route is None:
            raise NamedModelResolutionError(f"unknown OpenRouter model: {model_id}")
        return route, self.value.fetched_at


def catalog(
    rows: tuple[BenchmarkModel, ...],
    contexts: dict[str, int],
) -> ModelCatalog:
    return ModelCatalog(
        rows=rows,
        model_routes={
            slug: ModelRoute(model_id=slug, context_tokens=context)
            for slug, context in contexts.items()
        },
        fetched_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_pinned_resolution_bypasses_catalog_and_is_stable_per_thread() -> None:
    """A-021 is defended by verifying that pinned resolution bypasses catalog and is stable per
    thread; this prevents drift in the deterministic model policy contract.
    """
    table = FakeCatalog(catalog((row("vendor/model", "52", "1"),), {"vendor/model": 10}))
    resolver = ModelPolicyResolver(
        policy="pinned:anthropic:claude-sonnet-4-6",
        static_model="openrouter:static/model",
        static_context_tokens=99,
        catalog=table,
    )

    first = await resolver.resolve("thread-1")
    second = await resolver.resolve("thread-1")

    assert first is second
    assert first.model == "anthropic:claude-sonnet-4-6"
    assert first.context_tokens == 99
    assert first.price_sorted is False
    assert table.calls == 0


@pytest.mark.asyncio
async def test_nonpinned_resolution_joins_context_and_remains_stable_per_thread() -> None:
    """A-021 is defended by verifying that nonpinned resolution joins context and remains
    stable per thread; this prevents drift in the deterministic model policy contract.
    """
    table = FakeCatalog(
        ModelCatalog(
            rows=(row("vendor/model-v1", "52", "1", "2"),),
            model_routes={
                "vendor/model-v1": ModelRoute(
                    model_id="vendor/model",
                    context_tokens=131_072,
                )
            },
            fetched_at=datetime(2026, 7, 30, tzinfo=UTC),
        )
    )
    resolver = ModelPolicyResolver(
        policy="max",
        static_model="openrouter:static/model",
        static_context_tokens=99,
        catalog=table,
    )

    first = await resolver.resolve("thread-1")
    second = await resolver.resolve("thread-1")

    assert first is second
    assert first.model == "openrouter:vendor/model"
    assert first.context_tokens == 131_072
    assert first.price_sorted is True
    assert first.benchmark == row("vendor/model-v1", "52", "1", "2")
    assert table.calls == 1


@pytest.mark.asyncio
async def test_named_resolution_validates_exact_openrouter_route_without_mutating_thread() -> None:
    """A-021 is defended by verifying that named resolution validates exact openrouter route
    without mutating thread; this prevents drift in the deterministic model policy contract.
    """
    initial = ThreadModelResolution(
        model="openrouter:vendor/initial",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/initial",
    )
    table = FakeCatalog(
        ModelCatalog(
            rows=(),
            model_routes={},
            fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
        ),
        named_routes={
            "vendor/next:free": ModelRoute("vendor/next:free", 131_072),
        },
    )
    resolver = ModelPolicyResolver(
        policy="pinned:openrouter:vendor/initial",
        static_model=initial.model,
        static_context_tokens=initial.context_tokens,
        catalog=table,
    )

    assert await resolver.resolve("thread-1") == initial
    named = await resolver.resolve_named("thread-1", "openrouter:vendor/next:free")

    assert named == ThreadModelResolution(
        model="openrouter:vendor/next:free",
        context_tokens=131_072,
        policy="human_command",
        catalog_fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
    )
    assert await resolver.resolve("thread-1") == initial
    assert table.named_calls == ["vendor/next:free"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    ["vendor/next", "anthropic:claude-sonnet-4-6", "openrouter:", " openrouter:x/y"],
)
async def test_named_resolution_rejects_non_openrouter_model_strings(target: str) -> None:
    """A-021 is defended by verifying that named resolution rejects non openrouter model
    strings; this prevents drift in the deterministic model policy contract.
    """
    resolver = ModelPolicyResolver(
        policy="pinned:openrouter:vendor/initial",
        static_model="openrouter:vendor/initial",
        static_context_tokens=64_000,
        catalog=FakeCatalog(catalog((), {"vendor/next": 100_000})),
    )

    with pytest.raises(NamedModelResolutionError):
        await resolver.resolve_named("thread-1", target)


@pytest.mark.asyncio
async def test_named_resolution_rejects_unknown_broker_model() -> None:
    """A-021 is defended by verifying that named resolution rejects unknown broker model; this
    prevents drift in the deterministic model policy contract.
    """
    resolver = ModelPolicyResolver(
        policy="pinned:openrouter:vendor/initial",
        static_model="openrouter:vendor/initial",
        static_context_tokens=64_000,
        catalog=FakeCatalog(catalog((), {"vendor/known": 100_000})),
    )

    with pytest.raises(NamedModelResolutionError, match="unknown OpenRouter model"):
        await resolver.resolve_named("thread-1", "openrouter:vendor/unknown")


@pytest.mark.asyncio
async def test_named_resolution_refetches_models_without_benchmark_dependency() -> None:
    """A-021 is defended by verifying that named resolution refetches models without benchmark
    dependency; this prevents drift in the deterministic model policy contract.
    """
    requests: list[str] = []
    context_tokens = [64_000]
    benchmark_available = [True]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/benchmarks"):
            if not benchmark_available[0]:
                return httpx.Response(503)
            return httpx.Response(200, json=benchmark_payload())
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/model",
                        "canonical_slug": "vendor/model-v1",
                        "context_length": context_tokens[0],
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterCatalogClient("test-key", http_client=http_client)
        await client.load()
        context_tokens[0] = 262_144
        benchmark_available[0] = False
        resolver = ModelPolicyResolver(
            policy="pinned:openrouter:vendor/initial",
            static_model="openrouter:vendor/initial",
            static_context_tokens=64_000,
            catalog=client,
        )

        named = await resolver.resolve_named("thread-1", "openrouter:vendor/model")

    assert named.context_tokens == 262_144
    assert requests == [
        "/api/v1/benchmarks",
        "/api/v1/models",
        "/api/v1/models",
    ]


@pytest.mark.asyncio
async def test_named_resolution_requires_exact_broker_id_not_canonical_alias() -> None:
    """A-021 is defended by verifying that named resolution requires exact broker id not
    canonical alias; this prevents drift in the deterministic model policy contract.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/model",
                        "canonical_slug": "vendor/model-v1",
                        "context_length": 100_000,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        resolver = ModelPolicyResolver(
            policy="pinned:openrouter:vendor/initial",
            static_model="openrouter:vendor/initial",
            static_context_tokens=64_000,
            catalog=OpenRouterCatalogClient("test-key", http_client=http_client),
        )
        with pytest.raises(NamedModelResolutionError, match="unknown OpenRouter model"):
            await resolver.resolve_named("thread-1", "openrouter:vendor/model-v1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "rows", "contexts"),
    [
        ("max", (row("vendor/model", "52", "1"),), {}),
        ("floor:60", (row("vendor/model", "52", "1"),), {"vendor/model": 10}),
        (
            "elbow",
            (
                row("free", "10", "0"),
                row("middle", "20", "1"),
                row("top", "30", "2"),
            ),
            {"free": 10, "middle": 10, "top": 10},
        ),
    ],
)
async def test_every_degenerate_nonpinned_resolution_fails_open_to_static_pair(
    policy: str,
    rows: tuple[BenchmarkModel, ...],
    contexts: dict[str, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A-021 is defended by verifying that every degenerate nonpinned resolution fails open to
    static pair; this prevents drift in the deterministic model policy contract.
    """
    resolver = ModelPolicyResolver(
        policy=policy,
        static_model="openrouter:static/model",
        static_context_tokens=99,
        catalog=FakeCatalog(catalog(rows, contexts)),
    )

    resolved = await resolver.resolve("thread-1")

    assert resolved.model == "openrouter:static/model"
    assert resolved.context_tokens == 99
    assert resolved.price_sorted is True
    assert "model policy failed open" in caplog.text
