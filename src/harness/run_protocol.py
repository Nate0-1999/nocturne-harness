"""Framework-neutral contracts between the run loop and a model adapter."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic_ai.messages import BinaryContent

from harness.envelope import GateCommitPayload, ProviderErrorPayload, StopReason
from harness.model_policy import ThreadModelResolution


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """Cumulative usage for one run."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __post_init__(self) -> None:
        values = (
            self.requests,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
        )
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
    cacheable_prefix_tokens: int = 0
    assistant_text: str | None = None
    model_visible: bool = True
    provider_error: ProviderErrorPayload | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stop_reason, StopReason):
            raise TypeError("stop_reason must be a StopReason")
        if not isinstance(self.message_history, tuple):
            raise TypeError("message_history must be a tuple")
        if not isinstance(self.usage, UsageSnapshot):
            raise TypeError("usage must be a UsageSnapshot")
        if type(self.cacheable_prefix_tokens) is not int:
            raise TypeError("cacheable_prefix_tokens must be an integer")
        if self.cacheable_prefix_tokens < 0:
            raise ValueError("cacheable_prefix_tokens must be non-negative")
        if self.assistant_text is not None and not isinstance(self.assistant_text, str):
            raise TypeError("assistant_text must be a string or None")
        if not isinstance(self.model_visible, bool):
            raise TypeError("model_visible must be a boolean")
        if self.provider_error is not None and not isinstance(
            self.provider_error, ProviderErrorPayload
        ):
            raise TypeError("provider_error must be a ProviderErrorPayload or None")
        if self.provider_error is not None and self.stop_reason is not StopReason.ERROR:
            raise ValueError("provider_error requires stop_reason=error")


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
        model_resolution: ThreadModelResolution | None = None,
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
        model_resolution: ThreadModelResolution | None = None,
        system_instructions: str | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome: ...


class ImageTurnRunner(Protocol):
    """Execute one image-bearing turn without changing the text-only seam. [A-052]"""

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        image: BinaryContent,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome: ...


class ImageSystemInstructionTurnRunner(Protocol):
    """Image-bearing form of the model adapter used behind the memory gate. [A-052]"""

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        image: BinaryContent,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
        system_instructions: str | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome: ...
