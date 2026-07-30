"""Print a credential-safe receipt for the live OpenRouter H9 catalog contract."""

from __future__ import annotations

import asyncio
import json

from harness.config import HarnessSettings
from harness.model_policy import (
    ModelCatalogUnavailable,
    OpenRouterCatalogClient,
    pareto_frontier,
    parse_model_policy,
    select_model,
)

POLICIES = ("max", "elbow", "slope:0.05", "floor:52")


async def main() -> None:
    settings = HarnessSettings()
    if settings.openrouter_api_key is None:
        raise SystemExit("OPENROUTER_API_KEY is required")
    client = OpenRouterCatalogClient(
        settings.openrouter_api_key.get_secret_value(),
    )
    try:
        catalog = await client.load()
    finally:
        await client.aclose()

    frontier = pareto_frontier(catalog.rows)
    decisions: dict[str, object] = {}
    for raw_policy in POLICIES:
        try:
            selected = select_model(parse_model_policy(raw_policy), catalog.rows)
        except ModelCatalogUnavailable as exc:
            decisions[raw_policy] = {
                "result": "degenerate",
                "reason": str(exc),
            }
            continue
        decisions[raw_policy] = {
            "result": "selected",
            "benchmark_model": selected.permaslug,
            "intelligence_index": str(selected.intelligence_index),
            "prompt_usd_per_m": str(selected.prompt_price),
            "completion_usd_per_m": str(selected.completion_price),
            "route": (
                catalog.model_routes[selected.permaslug].model_id
                if selected.permaslug in catalog.model_routes
                else None
            ),
            "context_tokens": (
                catalog.model_routes[selected.permaslug].context_tokens
                if selected.permaslug in catalog.model_routes
                else None
            ),
        }

    print(
        json.dumps(
            {
                "source": "openrouter/artificial-analysis",
                "fetched_at": catalog.fetched_at.isoformat(),
                "complete_benchmark_rows": len(catalog.rows),
                "unambiguous_model_routes": len(catalog.model_routes),
                "frontier_rows": len(frontier),
                "zero_price_frontier_models": [
                    item.permaslug for item in frontier if item.prompt_price == 0
                ],
                "decisions": decisions,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
