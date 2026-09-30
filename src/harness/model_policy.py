"""Compatibility imports for the model policy shared with the Palace curator."""

from spine.model_policy import (  # noqa: F401
    BenchmarkModel,
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
    lower_convex_hull,
    pareto_frontier,
    parse_model_policy,
    select_model,
)
