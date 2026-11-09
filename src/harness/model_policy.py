"""Compatibility imports for the model policy shared with the Palace curator, and the
model browser's read path (FL-202), which only the Harness serves."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from spine.model_policy import (  # noqa: F401
    BenchmarkModel,
    ListedModel,
    ModelCatalog,
    ModelCatalogLoader,
    ModelCatalogUnavailable,
    ModelPolicy,
    ModelPolicyConfigurationError,
    ModelPolicyResolver,
    ModelRequestParameters,
    ModelRoute,
    NamedModelResolutionError,
    OpenRouterCatalogClient,
    ThreadModelResolution,
    ThreadModelResolver,
    TokenBurn,
    _parse_model_routes,
    _parse_named_model,
    _qualify_model,
    elbow_price_floor,
    explain_choice,
    lower_convex_hull,
    pareto_frontier,
    parse_model_listing,
    parse_model_policy,
    select_model,
)

from harness.spine_client import SpineClient, SpineClientError


@dataclass(frozen=True, slots=True)
class StandardConfiguration:
    """FL-202 / FL-154: one token-cost policy and the model it selects from this snapshot."""

    policy: str
    model: str | None
    reason: str


def standard_configurations(
    catalog: ModelCatalog,
    *,
    chat_policy: str,
    current_model_id: str | None,
    fallback_model: str,
    qualify: Callable[[str], str],
    burn: TokenBurn | None = None,
) -> tuple[StandardConfiguration, ...]:
    """Pinned, max, elbow, floor and budget, each resolved now; single-key catalogs have none.

    Pinned keeps the conversation's model. Floor uses the configured floor, else the score of
    the current model (as smart as this, cheapest), else of the configured model, else the
    elbow's. Budget (FL-152) uses the configured dollars per hour, else what the current or
    configured model costs an hour at the measured burn (as costly as this, smartest); with no
    measured burn and none configured it is not offered. A policy the table cannot resolve shows
    the static model it fails open to (A-020(f)); elbow names the price floor it gave a free
    model (SPEC C.5, v2.129).
    """

    if not catalog.rows:
        return ()
    configured = parse_model_policy(chat_policy)
    scores = {entry.model_id: entry.intelligence_index for entry in catalog.listing}

    def pick(policy: ModelPolicy) -> tuple[str, str, Decimal | None]:
        try:
            selected = select_model(policy, catalog.rows, burn)
            route = catalog.model_routes.get(selected.permaslug)
            if route is None:
                raise ModelCatalogUnavailable("the selected model has no unambiguous route")
        except ModelCatalogUnavailable as exc:
            return fallback_model, f"falls back to the configured model: {exc}", None
        reason = f"score {selected.intelligence_index}"
        if policy.kind in {"elbow", "budget"}:
            reason = explain_choice(policy, catalog.rows, selected, burn)
        return qualify(route.model_id), reason, selected.intelligence_index

    elbow_model, elbow_reason, elbow_score = pick(ModelPolicy("elbow"))
    price_floor = elbow_price_floor(pareto_frontier(catalog.rows), catalog.rows)
    if elbow_score is not None and price_floor is not None:
        elbow_reason += (
            f"; free models count at the ${format(price_floor.normalize(), 'f')}/M price floor"
        )
    floor = configured.value if configured.kind == "floor" else None
    if floor is None and current_model_id is not None:
        floor = scores.get(current_model_id)
    if floor is None:
        floor = scores.get(fallback_model.split(":", 1)[1])
    if floor is None:
        floor = elbow_score
    pinned = qualify(current_model_id) if current_model_id is not None else None
    if pinned is None and configured.kind == "pinned":
        assert isinstance(configured.value, str)
        pinned = configured.value
    pinned = pinned or fallback_model
    configurations = [
        StandardConfiguration(f"pinned:{pinned}", pinned, "keeps this model"),
        StandardConfiguration("max", *pick(ModelPolicy("max"))[:2]),
        StandardConfiguration("elbow", elbow_model, elbow_reason),
    ]
    if isinstance(floor, Decimal):
        configurations.append(
            StandardConfiguration(f"floor:{floor}", *pick(ModelPolicy("floor", floor))[:2])
        )
    budget = configured.value if configured.kind == "budget" else None
    if budget is None and burn is not None:
        prices = {entry.model_id: entry for entry in catalog.listing}
        here = prices.get(current_model_id or "") or prices.get(fallback_model.split(":", 1)[1])
        if here is not None and None not in (here.prompt_price, here.completion_price):
            hourly = burn.hourly_cost(
                BenchmarkModel(here.model_id, Decimal(0), here.prompt_price, here.completion_price)
            )
            budget = max(Decimal("0.01"), (hourly * 100).to_integral_value(ROUND_CEILING) / 100)
    if isinstance(budget, Decimal):
        label = format(budget.normalize(), "f")
        configurations.append(
            StandardConfiguration(f"budget:{label}", *pick(ModelPolicy("budget", budget))[:2])
        )
    return tuple(configurations)


async def measured_token_burn(spine: SpineClient) -> TokenBurn | None:
    """FL-152 / A-082: the agents' tokens per working hour over the last day of the ledger.

    Building receipts only (agents and sub-agents, not memory upkeep); a working hour is a clock
    hour with at least one receipt. None when the Palace has no such receipts or cannot answer.
    """
    try:
        table = await spine.spend_table()
    except SpineClientError:
        return None
    if table is None:
        return None
    since = table.as_of - timedelta(hours=24)
    sums = {"input": Decimal(0), "output": Decimal(0)}
    sides = {"input_fresh": "input", "input_cached": "input", "cache_write": "input"}
    sides |= {"output": "output", "reasoning": "output"}
    hours = set()
    for receipt in table.receipts:
        side = sides.get(receipt.quantity_type)
        if receipt.ts < since or receipt.purpose != "building" or side is None:
            continue
        sums[side] += Decimal(receipt.quantity)
        hours.add(receipt.ts.replace(minute=0, second=0, microsecond=0))
    if not hours:
        return None
    return TokenBurn(sums["input"] / len(hours), sums["output"] / len(hours), len(hours))


async def browse_models(
    loader: ModelCatalogLoader,
    *,
    chat_policy: str,
    current_model: str | None,
    fallback_model: str,
    burn: TokenBurn | None = None,
) -> dict[str, object]:
    """FL-202's read path: the listing in qualified ids plus the configurations now."""

    catalog = await loader.load()
    current_id = None
    if current_model is not None:
        try:
            current_id = _parse_named_model(loader, current_model)
        except NamedModelResolutionError:
            pass

    def qualify(model_id: str) -> str:
        return _qualify_model(loader, model_id)

    def number(value: Decimal | None) -> str | None:
        return None if value is None else format(value.normalize(), "f")

    return {
        "fetched_at": catalog.fetched_at.isoformat(),
        "models": [
            {
                "model": qualify(entry.model_id),
                "name": entry.name,
                "context_tokens": entry.context_tokens,
                "prompt_price": number(entry.prompt_price),
                "completion_price": number(entry.completion_price),
                "score": number(entry.intelligence_index),
                "reasoning": entry.reasoning,
                "parameters": None
                if entry.supported_parameters is None
                else sorted(entry.supported_parameters),
            }
            for entry in catalog.listing
        ],
        "configurations": [
            {"policy": item.policy, "model": item.model, "reason": item.reason}
            for item in standard_configurations(
                catalog,
                chat_policy=chat_policy,
                current_model_id=current_id,
                fallback_model=fallback_model,
                qualify=qualify,
                burn=burn,
            )
        ],
    }
