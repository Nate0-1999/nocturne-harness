"""Compatibility imports for the model policy shared with the Palace curator, and the
model browser's read path (FL-202), which only the Harness serves."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

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
    _parse_model_routes,
    _parse_named_model,
    _qualify_model,
    elbow_price_floor,
    lower_convex_hull,
    pareto_frontier,
    parse_model_listing,
    parse_model_policy,
    select_model,
)


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
) -> tuple[StandardConfiguration, ...]:
    """Pinned, max, elbow and floor, each resolved now; single-key catalogs have none.

    Pinned keeps the conversation's model. Floor uses the configured floor, else the score of
    the current model (as smart as this, cheapest), else of the configured model, else the
    elbow's. A policy the table cannot resolve shows the static model it fails open to
    (A-020(f)); elbow names the price floor it gave a free model (SPEC C.5, v2.129).
    """

    if not catalog.rows:
        return ()
    configured = parse_model_policy(chat_policy)
    scores = {entry.model_id: entry.intelligence_index for entry in catalog.listing}

    def pick(policy: ModelPolicy) -> tuple[str, str, Decimal | None]:
        try:
            selected = select_model(policy, catalog.rows)
            route = catalog.model_routes.get(selected.permaslug)
            if route is None:
                raise ModelCatalogUnavailable("the selected model has no unambiguous route")
        except ModelCatalogUnavailable as exc:
            return fallback_model, f"falls back to the configured model: {exc}", None
        return (
            qualify(route.model_id),
            f"score {selected.intelligence_index}",
            (selected.intelligence_index),
        )

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
    return tuple(configurations)


async def browse_models(
    loader: ModelCatalogLoader,
    *,
    chat_policy: str,
    current_model: str | None,
    fallback_model: str,
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
            )
        ],
    }
