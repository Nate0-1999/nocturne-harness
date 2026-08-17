"""Harness-owned boundary for the adopted standard coding toolset."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ToolsetError(RuntimeError):
    """The adopted toolset could not satisfy the Harness-owned contract."""


class ToolsetUnavailableError(ToolsetError):
    """The pinned external runtime is not installed or could not start."""


class ToolsetProtocolError(ToolsetError):
    """The external runtime violated the bounded wire contract."""


@dataclass(frozen=True, slots=True)
class ToolsetState:
    """The small process state Nocturne needs before exposing any file tools."""

    is_streaming: bool
    is_compacting: bool
    auto_compaction_enabled: bool
    message_count: int
    pending_message_count: int


class StandardToolset(Protocol):
    """Nocturne's current toolset seam; extend only when a packet first uses more."""

    async def state(self) -> ToolsetState: ...

    async def close(self) -> None: ...


async def open_standard_toolset(
    *,
    command: Sequence[str] | None = None,
    cwd: Path | None = None,
    timeout_seconds: float = 5.0,
) -> StandardToolset:
    """Open the selected standard toolset without leaking its protocol to callers."""

    from harness.pi_toolset_adapter import PiRpcToolset

    return await PiRpcToolset.open(
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )
