"""Truthful daemon-lifetime context observations for the Rack."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelMessage, ModelResponse
from spine.tokens import cl100k_token_count

from harness.memory_capability import DEFAULT_MEMORY_FEATURE
from harness.model_policy import ThreadModelResolution

_THRESHOLD_RATIO = 0.8


class ContextCategories(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    system: int = Field(ge=0)
    history: int = Field(ge=0)
    memory: int = Field(ge=0)
    tools: int = Field(ge=0)


class ContextObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    thread_id: str
    model: str
    observed_at: datetime
    used_tokens: int = Field(ge=0)
    context_tokens: int = Field(gt=0)
    threshold_tokens: int = Field(gt=0)
    categories: ContextCategories
    breakdown_basis: Literal["estimated"] = "estimated"
    compaction_active: Literal[False] = False


class ContextWindowSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: Literal["GLOBAL", "CURRENT"]
    selected_thread_id: str | None
    observations: list[ContextObservation]
    aggregate: ContextObservation | None


class ContextWindowTracker:
    """Retain only the latest completed provider request for each thread."""

    def __init__(self) -> None:
        self._observations: dict[str, ContextObservation] = {}

    def record(
        self,
        *,
        thread_id: str,
        captured: Sequence[ModelMessage],
        resolution: ThreadModelResolution | None,
        memory_block: str | None,
    ) -> None:
        if resolution is None:
            return
        response = next(
            (
                message
                for message in reversed(captured)
                if isinstance(message, ModelResponse) and message.usage.input_tokens > 0
            ),
            None,
        )
        if response is None:
            return
        used = response.usage.input_tokens
        self._observations[thread_id] = ContextObservation(
            thread_id=thread_id,
            model=resolution.model,
            observed_at=datetime.now(UTC),
            used_tokens=used,
            context_tokens=resolution.context_tokens,
            threshold_tokens=max(1, int(resolution.context_tokens * _THRESHOLD_RATIO)),
            categories=_estimated_categories(used, memory_block),
        )

    def snapshot(self, thread_id: str | None) -> ContextWindowSnapshot:
        if thread_id is not None:
            observation = self._observations.get(thread_id)
            observations = [] if observation is None else [observation]
            return ContextWindowSnapshot(
                scope="CURRENT",
                selected_thread_id=thread_id,
                observations=observations,
                aggregate=observation,
            )
        observations = [self._observations[key] for key in sorted(self._observations)]
        return ContextWindowSnapshot(
            scope="GLOBAL",
            selected_thread_id=None,
            observations=observations,
            aggregate=_aggregate(observations),
        )


def _estimated_categories(used: int, memory_block: str | None) -> ContextCategories:
    definition = DEFAULT_MEMORY_FEATURE.definition
    memory = cl100k_token_count(memory_block or "")
    system = sum(cl100k_token_count(item.text) for item in definition.instructions)
    tools = sum(cl100k_token_count(f"{tool.name}\n{tool.description}") for tool in definition.tools)
    overflow = max(0, memory + system + tools - used)
    tools, overflow = _reduce(tools, overflow)
    system, overflow = _reduce(system, overflow)
    memory, _ = _reduce(memory, overflow)
    return ContextCategories(
        system=system,
        history=used - memory - system - tools,
        memory=memory,
        tools=tools,
    )


def _reduce(value: int, amount: int) -> tuple[int, int]:
    reduction = min(value, amount)
    return value - reduction, amount - reduction


def _aggregate(observations: Sequence[ContextObservation]) -> ContextObservation | None:
    if not observations:
        return None
    categories = ContextCategories(
        system=sum(item.categories.system for item in observations),
        history=sum(item.categories.history for item in observations),
        memory=sum(item.categories.memory for item in observations),
        tools=sum(item.categories.tools for item in observations),
    )
    return ContextObservation(
        thread_id="GLOBAL",
        model=f"{len(observations)} observed thread{'s' if len(observations) != 1 else ''}",
        observed_at=max(item.observed_at for item in observations),
        used_tokens=sum(item.used_tokens for item in observations),
        context_tokens=sum(item.context_tokens for item in observations),
        threshold_tokens=sum(item.threshold_tokens for item in observations),
        categories=categories,
    )


__all__ = [
    "ContextCategories",
    "ContextObservation",
    "ContextWindowSnapshot",
    "ContextWindowTracker",
]
