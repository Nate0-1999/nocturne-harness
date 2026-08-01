"""Unit proof for broker-response to receipt-line normalization."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage

from harness.spend import SpendLineage, model_response_receipts


def _lineage() -> SpendLineage:
    return SpendLineage(
        principal_id="owner",
        machine_id="workstation",
        origin_agent="harness-chat",
        thread_id=UUID("11111111-1111-4111-8111-111111111111"),
        run_id="01K1M2A0000000000000000001",
        prompt_id="01K1M2A0000000000000000002",
    )


def test_openrouter_receipts_split_price_classes_and_preserve_exact_native_cost() -> None:
    response = ModelResponse(
        parts=[TextPart("answer")],
        usage=RequestUsage(
            input_tokens=100,
            cache_read_tokens=20,
            cache_write_tokens=10,
            output_tokens=50,
            details={"reasoning_tokens": 10},
        ),
        model_name="anthropic/claude-sonnet-4.6",
        timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        provider_name="openrouter",
        provider_response_id="gen-123",
        provider_details={
            "cost": 0.01,
            "downstream_provider": "anthropic",
            "upstream_inference_prompt_cost": 0.004,
            "upstream_inference_completions_cost": 0.006,
        },
    )

    request = model_response_receipts([response], lineage=_lineage(), purpose="building")

    assert request is not None
    assert [(event.quantity_type, event.quantity) for event in request.events] == [
        ("input_fresh", Decimal(70)),
        ("input_cached", Decimal(20)),
        ("cache_write", Decimal(10)),
        ("output", Decimal(40)),
        ("reasoning", Decimal(10)),
    ]
    assert {event.ref for event in request.events} == {"gen-123"}
    assert {event.provider for event in request.events} == {"anthropic"}
    assert {event.basis for event in request.events} == {"allocated"}
    assert sum((event.cost_usd or Decimal(0)) for event in request.events) == Decimal(
        "0.010000000000"
    )
    assert all(event.meta["cost_source"] == "cost" for event in request.events)
    assert all(event.run_id == _lineage().run_id for event in request.events)


def test_direct_anthropic_fresh_semantics_missing_cost_and_ref_fallback_stay_honest() -> None:
    response = ModelResponse(
        parts=[TextPart("answer")],
        usage=RequestUsage(input_tokens=30, cache_read_tokens=20, output_tokens=5),
        model_name="claude-test",
        timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        provider_name="anthropic",
    )

    request = model_response_receipts([response], lineage=_lineage(), purpose="remember")

    assert request is not None
    assert [(event.quantity_type, event.quantity) for event in request.events] == [
        ("input_fresh", Decimal(30)),
        ("input_cached", Decimal(20)),
        ("output", Decimal(5)),
    ]
    assert all(event.cost_usd is None for event in request.events)
    assert all(event.basis == "measured" for event in request.events)
    assert all(event.ref == request.events[0].event_uid for event in request.events)
    assert all(event.meta["ref_source"] == "event_uid" for event in request.events)
    assert all(event.meta["input_accounting"] == "provider_fresh" for event in request.events)
