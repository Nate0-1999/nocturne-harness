"""Translate broker-native model responses into honest ADR-024 receipt lines."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from pydantic_ai.messages import ModelResponse
from pydantic_core import to_jsonable_python

from harness.envelope import generate_ulid
from harness.spine_client import SpendEvent, SpendEventsRequest, SpendEventsResponse

type SpendPurpose = Literal[
    "building",
    "extraction",
    "curation",
    "judge",
    "remember",
    "embedding",
    "scout",
]

_COST_QUANTUM = Decimal("0.000000000001")


class SpendGateway(Protocol):
    """The synchronous A-027 operation needed by a model adapter."""

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SpendLineage:
    principal_id: str
    machine_id: str
    origin_agent: str
    thread_id: UUID
    run_id: str
    prompt_id: str
    memory_id: UUID | None = None


def model_response_receipts(
    responses: Sequence[ModelResponse],
    *,
    lineage: SpendLineage,
    purpose: SpendPurpose,
) -> SpendEventsRequest | None:
    """Build one batch containing every nonzero price class in response order."""

    events: list[SpendEvent] = []
    for response in responses:
        events.extend(_response_receipts(response, lineage=lineage, purpose=purpose))
    if not events:
        return None
    return SpendEventsRequest(events=events)


def _response_receipts(
    response: ModelResponse,
    *,
    lineage: SpendLineage,
    purpose: SpendPurpose,
) -> list[SpendEvent]:
    usage = response.usage
    cache_read = usage.cache_read_tokens
    cache_write = usage.cache_write_tokens
    subtract_cache = response.provider_name != "anthropic"
    fresh = usage.input_tokens
    if subtract_cache:
        fresh = max(0, fresh - cache_read - cache_write)

    reasoning = usage.details.get("reasoning_tokens", 0)
    split_reasoning = 0 < reasoning <= usage.output_tokens
    ordinary_output = usage.output_tokens - reasoning if split_reasoning else usage.output_tokens
    quantities = [
        ("input_fresh", fresh),
        ("input_cached", cache_read),
        ("cache_write", cache_write),
        ("output", ordinary_output),
        ("reasoning", reasoning if split_reasoning else 0),
    ]
    quantities = [(kind, quantity) for kind, quantity in quantities if quantity > 0]
    if not quantities:
        return []

    event_ids = [generate_ulid(response.timestamp) for _ in quantities]
    details = _provider_details(response)
    ref, ref_source = _response_ref(response, details, event_ids[0])
    total_cost, cost_source = _native_cost(details)
    costs = _allocated_costs(total_cost, [quantity for _, quantity in quantities])
    basis: Literal["measured", "allocated"] = (
        "measured" if total_cost is None or len(quantities) == 1 else "allocated"
    )
    downstream = _optional_text(details.get("downstream_provider"))
    provider = downstream or response.provider_name
    quantization = _optional_text(details.get("quantization"))
    common_meta = {
        "broker_provider": response.provider_name,
        "cost_source": cost_source,
        "cost_allocation": "single_line" if len(quantities) == 1 else "token_pro_rata",
        "input_accounting": "fresh_excludes_cache" if subtract_cache else "provider_fresh",
        "ref_source": ref_source,
        "usage_details": dict(usage.details),
        "provider_details": details,
    }
    if reasoning > usage.output_tokens:
        common_meta["reasoning_split"] = "not_split_exceeds_output"

    return [
        SpendEvent(
            event_uid=event_uid,
            ts=response.timestamp,
            product_type="llm.request",
            quantity_type=quantity_type,
            unit_of_measure="tokens",
            quantity=Decimal(quantity),
            cost_usd=cost,
            basis=basis,
            behavior="variable",
            purpose=purpose,
            principal_id=lineage.principal_id,
            machine_id=lineage.machine_id,
            origin_agent=lineage.origin_agent,
            thread_id=lineage.thread_id,
            run_id=lineage.run_id,
            prompt_id=lineage.prompt_id,
            memory_id=lineage.memory_id,
            model=response.model_name,
            provider=provider,
            quantization=quantization,
            ref=ref,
            meta=cast(dict[str, Any], to_jsonable_python(common_meta)),
        )
        for (quantity_type, quantity), event_uid, cost in zip(
            quantities, event_ids, costs, strict=True
        )
    ]


def _provider_details(response: ModelResponse) -> dict[str, Any]:
    raw = response.provider_details or {}
    value = to_jsonable_python(raw)
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _response_ref(
    response: ModelResponse,
    details: dict[str, Any],
    fallback: str,
) -> tuple[str, str]:
    if value := _optional_text(response.provider_response_id):
        return value, "provider_response_id"
    for key in ("request_id", "x_request_id", "x-request-id"):
        if value := _optional_text(details.get(key)):
            return value, key
    return fallback, "event_uid"


def _native_cost(details: dict[str, Any]) -> tuple[Decimal | None, str]:
    for key in ("cost", "upstream_inference_cost"):
        value = _decimal(details.get(key))
        if value is not None:
            return value, key
    prompt = _decimal(details.get("upstream_inference_prompt_cost"))
    completion = _decimal(details.get("upstream_inference_completions_cost"))
    if prompt is not None or completion is not None:
        return (prompt or Decimal(0)) + (completion or Decimal(0)), "component_sum"
    return None, "unreported"


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result < 0:
        return None
    return result


def _allocated_costs(total: Decimal | None, quantities: Sequence[int]) -> list[Decimal | None]:
    if total is None:
        return [None] * len(quantities)
    normalized_total = total.quantize(_COST_QUANTUM)
    if len(quantities) == 1:
        return [normalized_total]
    quantity_total = sum(quantities)
    allocated: list[Decimal] = []
    remaining = normalized_total
    for quantity in quantities[:-1]:
        share = (normalized_total * quantity / quantity_total).quantize(
            _COST_QUANTUM,
            rounding=ROUND_DOWN,
        )
        allocated.append(share)
        remaining -= share
    allocated.append(remaining)
    return allocated


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "SpendGateway",
    "SpendLineage",
    "SpendPurpose",
    "model_response_receipts",
]
