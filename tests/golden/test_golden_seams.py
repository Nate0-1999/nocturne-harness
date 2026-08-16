"""M3B zero-regression goldens for Harness-owned model and capability seams."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from harness.agent_runtime import _model_settings
from harness.config import HarnessSettings
from harness.model_policy import (
    BenchmarkModel,
    ModelCatalog,
    ModelPolicy,
    ModelPolicyResolver,
    ModelRequestParameters,
    ModelRoute,
    ThreadModelResolution,
    parse_model_policy,
    select_model,
)
from harness.pydantic_ai_adapter import MemoryCapability
from harness.tools_memory import MemoryToolContext

SNAPSHOT_DIR = Path(__file__).with_name("snapshots")
CATALOG_TIME = datetime(2026, 8, 15, 12, tzinfo=UTC)


def _row(
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


def test_model_policy_modes_keep_the_current_decision_matrix() -> None:
    """A-021 and P4 pin every current model-policy mode before its seam is rearranged."""

    rows = (
        _row("base", "10", "1"),
        _row("dup-z", "20", "2", ".1"),
        _row("dup-a", "20", "2", "9"),
        _row("same-intelligence-expensive", "20", "3"),
        _row("same-price-weaker", "15", "2"),
        _row("cross-dominated", "18", "2.5"),
        _row("good", "30", "4"),
        _row("apex", "40", "16"),
    )

    observed = {
        raw: select_model(parse_model_policy(raw), rows).permaslug
        for raw in (
            "max",
            "elbow",
            "floor:20",
            "slope:0.05",
            "slope:0.10",
            "slope:0.20",
            "slope:1.20",
        )
    }

    assert observed == {
        "max": "apex",
        "elbow": "good",
        "floor:20": "dup-z",
        "slope:0.05": "base",
        "slope:0.10": "dup-a",
        "slope:0.20": "good",
        "slope:1.20": "apex",
    }
    assert parse_model_policy("pinned:openrouter:vendor/model") == ModelPolicy(
        "pinned", "openrouter:vendor/model"
    )


def test_broker_request_shapes_keep_routing_stickiness_and_overrides() -> None:
    """A-020, A-021, and A-034 pin exact broker request settings across routing modes."""

    parameters = ModelRequestParameters(
        temperature=0.25,
        top_p=0.8,
        top_k=40,
        max_tokens=2048,
        effort="high",
    )
    observed = {
        "direct_default": _model_settings(
            ThreadModelResolution(
                model="anthropic:claude-sonnet-4-6",
                context_tokens=200_000,
                policy="pinned:anthropic:claude-sonnet-4-6",
            ),
            "thread-golden",
        ),
        "direct_overrides": _model_settings(
            ThreadModelResolution(
                model="anthropic:claude-sonnet-4-6",
                context_tokens=200_000,
                policy="pinned:anthropic:claude-sonnet-4-6",
                request_parameters=parameters,
            ),
            "thread-golden",
        ),
        "openrouter_pinned": _model_settings(
            ThreadModelResolution(
                model="openrouter:vendor/model",
                context_tokens=131_072,
                policy="pinned:openrouter:vendor/model",
            ),
            "thread-golden",
        ),
        "openrouter_policy_epoch": _model_settings(
            ThreadModelResolution(
                model="openrouter:vendor/model",
                context_tokens=131_072,
                policy="elbow",
                price_sorted=True,
                stickiness_epoch=2,
                request_parameters=parameters,
            ),
            "thread-golden",
        ),
    }

    assert observed == {
        "direct_default": None,
        "direct_overrides": {
            "temperature": 0.25,
            "top_p": 0.8,
            "top_k": 40,
            "max_tokens": 2048,
        },
        "openrouter_pinned": {
            "extra_body": {"session_id": "thread-golden"},
            "openrouter_usage": {"include": True},
        },
        "openrouter_policy_epoch": {
            "temperature": 0.25,
            "top_p": 0.8,
            "top_k": 40,
            "max_tokens": 2048,
            "extra_body": {"session_id": "thread-golden:epoch:2"},
            "openrouter_usage": {"include": True},
            "openrouter_reasoning": {"effort": "high"},
            "openrouter_provider": {"sort": "price"},
        },
    }


@pytest.mark.asyncio
async def test_policy_resolution_keeps_selected_route_stability_and_fail_open() -> None:
    """A-020 and A-021 pin selected, pinned, cached, and fail-open resolution outputs."""

    rows = (
        _row("vendor/base", "20", "1", "2"),
        _row("vendor/elbow", "55", "4", "8"),
        _row("vendor/apex", "60", "32", "64"),
    )
    catalog = ModelCatalog(
        rows=rows,
        model_routes={
            "vendor/base": ModelRoute("vendor/base", 64_000, frozenset({"text"})),
            "vendor/elbow": ModelRoute("vendor/elbow", 131_072, frozenset({"text", "image"})),
            "vendor/apex": ModelRoute("vendor/apex", 200_000, frozenset({"text"})),
        },
        fetched_at=CATALOG_TIME,
    )

    class FixedCatalog:
        async def load(self) -> ModelCatalog:
            return catalog

        async def load_named_route(self, model_id: str) -> tuple[ModelRoute, datetime]:
            return catalog.model_routes[model_id], CATALOG_TIME

    selected_resolver = ModelPolicyResolver(
        policy="elbow",
        static_model="openrouter:static/fallback",
        static_context_tokens=32_000,
        catalog=FixedCatalog(),
    )
    selected = await selected_resolver.resolve("thread-selected")
    selected_again = await selected_resolver.resolve("thread-selected")
    pinned = await ModelPolicyResolver(
        policy="pinned:anthropic:claude-sonnet-4-6",
        static_model="anthropic:claude-sonnet-4-6",
        static_context_tokens=200_000,
        catalog=None,
    ).resolve("thread-pinned")
    failed_open = await ModelPolicyResolver(
        policy="max",
        static_model="openrouter:static/fallback",
        static_context_tokens=32_000,
        catalog=None,
    ).resolve("thread-fail-open")

    assert selected_again is selected
    assert {
        "selected": {
            "model": selected.model,
            "context_tokens": selected.context_tokens,
            "policy": selected.policy,
            "price_sorted": selected.price_sorted,
            "input_modalities": sorted(selected.input_modalities or ()),
            "benchmark": selected.benchmark.permaslug if selected.benchmark else None,
            "catalog_fetched_at": selected.catalog_fetched_at.isoformat()
            if selected.catalog_fetched_at
            else None,
        },
        "pinned": {
            "model": pinned.model,
            "context_tokens": pinned.context_tokens,
            "policy": pinned.policy,
            "price_sorted": pinned.price_sorted,
            "input_modalities": pinned.input_modalities,
        },
        "failed_open": {
            "model": failed_open.model,
            "context_tokens": failed_open.context_tokens,
            "policy": failed_open.policy,
            "price_sorted": failed_open.price_sorted,
            "input_modalities": failed_open.input_modalities,
        },
    } == {
        "selected": {
            "model": "openrouter:vendor/elbow",
            "context_tokens": 131_072,
            "policy": "elbow",
            "price_sorted": True,
            "input_modalities": ["image", "text"],
            "benchmark": "vendor/elbow",
            "catalog_fetched_at": "2026-08-15T12:00:00+00:00",
        },
        "pinned": {
            "model": "anthropic:claude-sonnet-4-6",
            "context_tokens": 200_000,
            "policy": "pinned:anthropic:claude-sonnet-4-6",
            "price_sorted": False,
            "input_modalities": None,
        },
        "failed_open": {
            "model": "openrouter:static/fallback",
            "context_tokens": 32_000,
            "policy": "max",
            "price_sorted": True,
            "input_modalities": None,
        },
    }


def test_runtime_config_resolution_keeps_current_defaults_and_environment_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC C.5 and A-021 pin exact Harness config resolution before the seam moves."""

    for field in HarnessSettings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)

    defaults = HarnessSettings(_env_file=None)
    monkeypatch.setenv("CHAT_MODEL", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("MODEL_POLICY_CHAT", "slope:0.05")
    monkeypatch.setenv("MODEL_CONTEXT_TOKENS", "200000")
    overrides = HarnessSettings(_env_file=None)

    def projection(settings: HarnessSettings) -> dict[str, object]:
        return {
            "spine_url": settings.spine_url,
            "principal_id": settings.principal_id,
            "machine_id": settings.machine_id,
            "agent_id": settings.agent_id,
            "chat_model": settings.chat_model,
            "model_policy_chat": settings.model_policy_chat,
            "effective_model_policy_chat": settings.effective_model_policy_chat,
            "model_context_tokens": settings.model_context_tokens,
            "run_request_limit": settings.run_request_limit,
            "run_total_tokens_limit": settings.run_total_tokens_limit,
            "label_max": settings.label_max,
            "memory_max_tokens": settings.memory_max_tokens,
            "remember_split_timeout_seconds": settings.remember_split_timeout_seconds,
            "extraction_idle_hours": settings.extraction_idle_hours,
            "nocturne_transcript_backup": settings.nocturne_transcript_backup,
        }

    assert {"defaults": projection(defaults), "overrides": projection(overrides)} == {
        "defaults": {
            "spine_url": "http://localhost:8000",
            "principal_id": "local",
            "machine_id": "local-machine",
            "agent_id": "harness-agent",
            "chat_model": "openrouter:minimax/minimax-m3",
            "model_policy_chat": None,
            "effective_model_policy_chat": "pinned:openrouter:minimax/minimax-m3",
            "model_context_tokens": 1_000_000,
            "run_request_limit": 40,
            "run_total_tokens_limit": 500_000,
            "label_max": 64,
            "memory_max_tokens": 128,
            "remember_split_timeout_seconds": 30.0,
            "extraction_idle_hours": 24.0,
            "nocturne_transcript_backup": False,
        },
        "overrides": {
            "spine_url": "http://localhost:8000",
            "principal_id": "local",
            "machine_id": "local-machine",
            "agent_id": "harness-agent",
            "chat_model": "anthropic:claude-sonnet-4-6",
            "model_policy_chat": "slope:0.05",
            "effective_model_policy_chat": "slope:0.05",
            "model_context_tokens": 200_000,
            "run_request_limit": 40,
            "run_total_tokens_limit": 500_000,
            "label_max": 64,
            "memory_max_tokens": 128,
            "remember_split_timeout_seconds": 30.0,
            "extraction_idle_hours": 24.0,
            "nocturne_transcript_backup": False,
        },
    }


@pytest.mark.asyncio
async def test_memory_tool_invocation_surface_matches_the_checked_in_golden() -> None:
    """ADR-005 and ADR-013 pin the exact model-visible tool and instruction surface."""

    model = TestModel(call_tools=[], custom_output_text="ok")
    agent = Agent(model, deps_type=MemoryToolContext, capabilities=[MemoryCapability()])
    await agent.run("inspect the current tool surface", deps=object())
    parameters = model.last_model_request_parameters
    assert parameters is not None

    observed = {
        "instructions": [part.content for part in parameters.instruction_parts or []],
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "capability_id": tool.capability_id,
                "parameters_json_schema": tool.parameters_json_schema,
            }
            for tool in parameters.function_tools
        ],
    }
    expected = json.loads((SNAPSHOT_DIR / "memory_tool_surface.json").read_text())

    assert observed == expected
