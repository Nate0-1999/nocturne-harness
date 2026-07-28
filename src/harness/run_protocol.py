"""Framework-neutral contracts between the run loop and a model adapter."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from harness.envelope import GateCommitPayload, StopReason


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """Cumulative usage for one run."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        values = (self.requests, self.input_tokens, self.output_tokens)
        if any(type(value) is not int for value in values):
            raise TypeError("usage values must be integers")
        if min(values) < 0:
            raise ValueError("usage values must be non-negative")


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """A terminal model turn with its well-formed opaque provider history."""

    stop_reason: StopReason
    message_history: tuple[object, ...]
    usage: UsageSnapshot = UsageSnapshot()

    def __post_init__(self) -> None:
        if not isinstance(self.stop_reason, StopReason):
            raise TypeError("stop_reason must be a StopReason")
        if not isinstance(self.message_history, tuple):
            raise TypeError("message_history must be a tuple")
        if not isinstance(self.usage, UsageSnapshot):
            raise TypeError("usage must be a UsageSnapshot")


class RunEmitter(Protocol):
    """Events a model adapter may publish while its run is live."""

    async def text(self, value: str) -> None: ...

    async def thinking(self, value: str) -> None: ...

    async def event(self, value: Mapping[str, object]) -> None: ...

    async def usage(self, value: UsageSnapshot) -> None: ...

    async def open_gate(self, value: Mapping[str, object]) -> GateCommitPayload: ...

    async def dismiss_gate(self) -> None: ...

    async def error(self, value: Mapping[str, object]) -> None: ...


class TurnRunner(Protocol):
    """Execute one complete prompt while the loop owns scheduling/cancellation."""

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
    ) -> TurnOutcome: ...


class SystemInstructionTurnRunner(Protocol):
    """Execute a turn with optional system-adjacent per-run instructions."""

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        system_instructions: str | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome: ...
