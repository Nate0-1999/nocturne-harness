from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from harness.agent_runtime import _model_settings
from harness.envelope import Envelope, EnvelopeFactory, StopReason
from harness.model_policy import ThreadModelResolution
from harness.parameter_registry import ParameterRegistry, ParameterWriteViolation
from harness.run_loop import RunLoop
from harness.run_protocol import TurnOutcome, UsageSnapshot


class _IdleRunner:
    async def run(self, **kwargs: object) -> TurnOutcome:
        return TurnOutcome(StopReason.END_TURN, (), UsageSnapshot())


class _Resolver:
    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        del thread_id
        return ThreadModelResolution(
            model="openrouter:vendor/base",
            context_tokens=32_000,
            policy="pinned:openrouter:vendor/base",
        )

    async def resolve_named(self, thread_id: str, model: str) -> ThreadModelResolution:
        del thread_id
        return ThreadModelResolution(
            model=model,
            context_tokens=64_000,
            policy="human_command",
        )


def test_registry_rejects_unknown_unbound_and_invalid_values() -> None:
    registry = ParameterRegistry()

    with pytest.raises(ParameterWriteViolation, match="unknown"):
        registry.validate_bound_write(
            module_id="model_device", parameter_id="model.unknown", value=1
        )
    with pytest.raises(ParameterWriteViolation, match="unbound"):
        registry.validate_bound_write(
            module_id="chat", parameter_id="model.temperature", value=1
        )
    with pytest.raises(ParameterWriteViolation, match="invalid"):
        registry.validate_bound_write(
            module_id="model_device", parameter_id="model.top_p", value=1.1
        )


@pytest.mark.asyncio
async def test_run_loop_applies_replays_and_publishes_bound_parameter_changes() -> None:
    now = datetime(2026, 8, 3, 16, 0, tzinfo=UTC)
    messages: list[Envelope] = []

    async def sink(message: Envelope) -> None:
        messages.append(message)

    loop = RunLoop(
        _IdleRunner(),
        EnvelopeFactory(machine_id="test"),
        model_resolver=_Resolver(),
        clock=lambda: now,
    )
    await loop.attach(sink)
    baseline = await loop.parameter_snapshot("thread-1", as_of=now - timedelta(seconds=1))
    await loop.request_snapshot("thread-1", sink)
    assert baseline.values["model.temperature"] is None

    changed = await loop.write_parameter(
        module_id="model_device",
        thread_id="thread-1",
        parameter_id="model.temperature",
        value=0.35,
    )
    assert changed.values["model.temperature"] == 0.35
    assert changed.changes[-1].old_value is None
    assert changed.changes[-1].new_value == 0.35
    await asyncio.sleep(0)
    assert any(message.type == "parameter.change" for message in messages)

    replay = await loop.parameter_snapshot("thread-1", as_of=now - timedelta(seconds=1))
    assert replay.values["model.temperature"] is None
    assert replay.changes == ()
    await loop.close()


@pytest.mark.asyncio
async def test_selector_uses_named_seam_preserves_overrides_and_journals_refusals() -> None:
    messages: list[Envelope] = []

    async def sink(message: Envelope) -> None:
        messages.append(message)

    loop = RunLoop(
        _IdleRunner(),
        EnvelopeFactory(machine_id="test"),
        model_resolver=_Resolver(),
    )
    await loop.attach(sink)
    await loop.parameter_snapshot("thread-2")
    await loop.request_snapshot("thread-2", sink)
    await loop.write_parameter(
        module_id="model_device",
        thread_id="thread-2",
        parameter_id="model.max_tokens",
        value=4096,
    )
    selected = await loop.write_parameter(
        module_id="model_device",
        thread_id="thread-2",
        parameter_id="model.slug",
        value="openrouter:vendor/next",
    )
    assert selected.resolved_model == "openrouter:vendor/next"
    assert selected.values["model.max_tokens"] == 4096
    await asyncio.sleep(0)
    assert any(message.type == "model.change" for message in messages)

    with pytest.raises(ParameterWriteViolation, match="unbound"):
        await loop.write_parameter(
            module_id="chat",
            thread_id="thread-2",
            parameter_id="model.temperature",
            value=1,
        )
    await asyncio.sleep(0)
    assert messages[-1].type == "parameter.refused"
    assert messages[-1].payload["reason"] == "unbound"
    await loop.close()


def test_model_settings_forward_every_real_request_parameter() -> None:
    from dataclasses import replace

    resolution = ThreadModelResolution(
        model="openrouter:vendor/model",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/model",
    )
    parameters = replace(
        resolution.request_parameters,
        temperature=0.4,
        top_p=0.8,
        top_k=40,
        max_tokens=2048,
        effort="high",
    )
    settings = _model_settings(replace(resolution, request_parameters=parameters), "thread-3")

    assert settings is not None
    assert settings["temperature"] == 0.4
    assert settings["top_p"] == 0.8
    assert settings["top_k"] == 40
    assert settings["max_tokens"] == 2048
    assert settings["openrouter_reasoning"] == {"effort": "high"}
