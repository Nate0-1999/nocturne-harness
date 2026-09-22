"""Truthful daemon-lifetime context observations for the Rack."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_core import to_jsonable_python
from spine.tokens import cl100k_token_count

from harness.memory_capability import DEFAULT_MEMORY_FEATURE
from harness.model_policy import ThreadModelResolution
from harness.pydantic_harness_adapter import truncate_head
from harness.spine_client import MemoryAllocation

_THRESHOLD_RATIO = 0.8
_HEAD_CHARS = 240


class ReturnShareBounds(BaseModel):
    """System parameters: the share of the compaction limit one return may take. [FL-198]"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    default_percent: float = Field(gt=0, le=100)
    min_percent: float = Field(gt=0, le=100)
    max_percent: float = Field(gt=0, le=100)

    def share(self, limit_tokens: int, percent: float | None = None) -> ReturnShare:
        """Clamp the sender's chosen percent into the bounds and size it against the limit."""
        chosen = self.default_percent if percent is None else percent
        chosen = min(max(chosen, self.min_percent), self.max_percent)
        return ReturnShare(
            percent=chosen,
            limit_tokens=limit_tokens,
            tokens=max(1, int(limit_tokens * chosen / 100)),
        )


class ReturnShare(BaseModel):
    """One return's allowance: a percent of this thread's compaction limit, in tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    percent: float = Field(gt=0, le=100)
    limit_tokens: int = Field(gt=0)
    tokens: int = Field(gt=0)

    @property
    def bytes(self) -> int:
        """The same allowance for byte-measured results (the library's ~4 chars per token)."""
        return self.tokens * 4


def bounds_from(settings: Any) -> ReturnShareBounds:
    """Read the three system parameters from HarnessSettings (duck-typed to avoid a cycle)."""
    return ReturnShareBounds(
        default_percent=settings.return_share_percent,
        min_percent=settings.return_share_min_percent,
        max_percent=settings.return_share_max_percent,
    )


class ContextCut(BaseModel):
    """A return that crossed its share: refused with a head, or sent back to shorten."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    thread_id: str
    agent_id: str
    at: datetime
    kind: Literal["query", "sub_agent"]
    source: str
    size_tokens: int = Field(ge=0)
    share: ReturnShare
    action: Literal["cut", "send_back"]
    shorten_by: int | None = None
    attempt: int = Field(ge=1, default=1)


class OverwhelmSnapshot(BaseModel):
    """The Security module's truthful daemon-lifetime view of shares, cuts and send-backs."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: Literal["GLOBAL", "CURRENT"]
    selected_thread_id: str | None
    bounds: ReturnShareBounds
    shares: dict[str, ReturnShare]
    cuts: list[ContextCut]


def cut_notice(cut: ContextCut, text: str, *, journaled: bool) -> str:
    """The error a sender receives instead of an oversized return: size, share, brief head."""
    what = "sub-agent return" if cut.kind == "sub_agent" else "result"
    return (
        f"Not delivered: this {what} is {cut.size_tokens:,} tokens; its share is "
        f"{cut.share.tokens:,} tokens ({cut.share.percent:g}% of the "
        f"{cut.share.limit_tokens:,}-token compaction limit)."
        + (" The full text is in the conversation journal." if journaled else "")
        + f"\nHead:\n{truncate_head(text, _HEAD_CHARS)}"
    )


def shorten_by(size_tokens: int, share: ReturnShare, *, thread_id: str, agent_id: str) -> int:
    """D = size − share + the cut notice's own overhead, so a compliant return fits with room."""
    probe = ContextCut(
        thread_id=thread_id,
        agent_id=agent_id,
        at=datetime.now(UTC),
        kind="sub_agent",
        source="",
        size_tokens=size_tokens,
        share=share,
        action="cut",
    )
    return size_tokens - share.tokens + cl100k_token_count(cut_notice(probe, "", journaled=True))


def send_back_instruction(cut: ContextCut) -> str:
    """The one instruction an oversized sub-agent receives: shorten by exactly D."""
    assert cut.shorten_by is not None
    return (
        f"Your return is {cut.size_tokens:,} tokens; its share is {cut.share.tokens:,} tokens "
        f"({cut.share.percent:g}% of the {cut.share.limit_tokens:,}-token compaction limit). "
        f"Return it again shortened by exactly {cut.shorten_by:,} tokens "
        f"(about {cut.shorten_by * 4:,} characters). Keep findings, evidence paths and open "
        "questions; move bulk to files."
    )


class OverwhelmTracker:
    """Retain every cut and send-back this daemon made, and the share in force per thread."""

    def __init__(self, bounds: ReturnShareBounds) -> None:
        self.bounds = bounds
        self._shares: dict[str, ReturnShare] = {}
        self._cuts: list[ContextCut] = []

    def share_for(
        self, thread_id: str, limit_tokens: int, percent: float | None = None
    ) -> ReturnShare:
        share = self.bounds.share(limit_tokens, percent)
        self._shares[thread_id] = share
        return share

    def record(self, cut: ContextCut) -> None:
        self._cuts.append(cut)

    def snapshot(self, thread_id: str | None) -> OverwhelmSnapshot:
        if thread_id is not None:
            return OverwhelmSnapshot(
                scope="CURRENT",
                selected_thread_id=thread_id,
                bounds=self.bounds,
                shares={key: value for key, value in self._shares.items() if key == thread_id},
                cuts=[cut for cut in self._cuts if cut.thread_id == thread_id],
            )
        return OverwhelmSnapshot(
            scope="GLOBAL",
            selected_thread_id=None,
            bounds=self.bounds,
            shares=dict(self._shares),
            cuts=list(self._cuts),
        )


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
    compaction_active: bool = True
    memory_allocation: ContextMemoryAllocation | None = None


class ContextMemoryAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    memory_context_share: float = Field(ge=0.01, le=0.50)
    share_tokens: int = Field(ge=0)
    regular_tokens: int = Field(ge=0)
    pinned_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    pinned_overflow_tokens: int = Field(ge=0)
    actual_block_tokens: int = Field(ge=0)
    unused_share_tokens: int = Field(ge=0)


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
        workspace_block: str | None = None,
        memory_allocation: MemoryAllocation | None = None,
        compaction_fraction: float = _THRESHOLD_RATIO,
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
            previous = self._observations.get(thread_id)
            if previous is not None:
                self._observations[thread_id] = previous.model_copy(
                    update={
                        "threshold_tokens": max(
                            1, int(previous.context_tokens * compaction_fraction)
                        )
                    }
                )
            return
        used = response.usage.input_tokens + response.usage.output_tokens
        self._observations[thread_id] = ContextObservation(
            thread_id=thread_id,
            model=resolution.model,
            observed_at=datetime.now(UTC),
            used_tokens=used,
            context_tokens=resolution.context_tokens,
            threshold_tokens=max(1, int(resolution.context_tokens * compaction_fraction)),
            categories=_estimated_categories(used, memory_block, workspace_block, captured),
            memory_allocation=_context_memory_allocation(memory_allocation, memory_block),
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


def _estimated_categories(
    used: int,
    memory_block: str | None,
    workspace_block: str | None,
    captured: Sequence[ModelMessage],
) -> ContextCategories:
    # The adapter imports this module's share models; keep its constants a call-time import.
    from harness.pydantic_ai_adapter import WORKSPACE_INSTRUCTIONS, WORKSPACE_TOOLS

    definition = DEFAULT_MEMORY_FEATURE.definition
    memory = cl100k_token_count(memory_block or "")
    system = sum(cl100k_token_count(item.text) for item in definition.instructions)
    system += cl100k_token_count(WORKSPACE_INSTRUCTIONS)
    system += cl100k_token_count(workspace_block or "")
    tools = sum(cl100k_token_count(f"{tool.name}\n{tool.description}") for tool in definition.tools)
    tools += sum(
        cl100k_token_count(f"{function.__name__}\n{function.__doc__ or ''}")
        for function in WORKSPACE_TOOLS
    )
    tools += _tool_traffic_tokens(captured)
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


def _tool_traffic_tokens(captured: Sequence[ModelMessage]) -> int:
    """Measure serialized call/return traffic present in the observed provider exchange."""

    total = 0
    for message in captured:
        if not isinstance(message, (ModelRequest, ModelResponse)):
            continue
        for part in message.parts:
            if isinstance(part, (ToolCallPart, ToolReturnPart)):
                total += cl100k_token_count(
                    json.dumps(to_jsonable_python(part), sort_keys=True, separators=(",", ":"))
                )
    return total


def _reduce(value: int, amount: int) -> tuple[int, int]:
    reduction = min(value, amount)
    return value - reduction, amount - reduction


def _context_memory_allocation(
    allocation: MemoryAllocation | None,
    memory_block: str | None,
) -> ContextMemoryAllocation | None:
    if allocation is None:
        return None
    actual = cl100k_token_count(memory_block or "")
    return ContextMemoryAllocation(
        **allocation.model_dump(),
        actual_block_tokens=actual,
        unused_share_tokens=max(0, allocation.share_tokens - allocation.regular_tokens),
    )


def _aggregate(observations: Sequence[ContextObservation]) -> ContextObservation | None:
    if not observations:
        return None
    categories = ContextCategories(
        system=sum(item.categories.system for item in observations),
        history=sum(item.categories.history for item in observations),
        memory=sum(item.categories.memory for item in observations),
        tools=sum(item.categories.tools for item in observations),
    )
    allocation_observations = [item for item in observations if item.memory_allocation]
    allocations = [item.memory_allocation for item in allocation_observations]
    memory_allocation = None
    if allocations:
        context_tokens = sum(item.context_tokens for item in allocation_observations)
        share_tokens = sum(item.share_tokens for item in allocations)
        memory_allocation = ContextMemoryAllocation(
            memory_context_share=share_tokens / context_tokens,
            share_tokens=share_tokens,
            regular_tokens=sum(item.regular_tokens for item in allocations),
            pinned_tokens=sum(item.pinned_tokens for item in allocations),
            total_tokens=sum(item.total_tokens for item in allocations),
            pinned_overflow_tokens=sum(item.pinned_overflow_tokens for item in allocations),
            actual_block_tokens=sum(item.actual_block_tokens for item in allocations),
            unused_share_tokens=sum(item.unused_share_tokens for item in allocations),
        )
    return ContextObservation(
        thread_id="GLOBAL",
        model=f"{len(observations)} observed thread{'s' if len(observations) != 1 else ''}",
        observed_at=max(item.observed_at for item in observations),
        used_tokens=sum(item.used_tokens for item in observations),
        context_tokens=sum(item.context_tokens for item in observations),
        threshold_tokens=sum(item.threshold_tokens for item in observations),
        categories=categories,
        memory_allocation=memory_allocation,
    )


__all__ = [
    "ContextCategories",
    "ContextCut",
    "ContextObservation",
    "ContextMemoryAllocation",
    "ContextWindowSnapshot",
    "ContextWindowTracker",
    "OverwhelmSnapshot",
    "OverwhelmTracker",
    "ReturnShare",
    "ReturnShareBounds",
    "bounds_from",
    "cut_notice",
    "send_back_instruction",
    "shorten_by",
]
