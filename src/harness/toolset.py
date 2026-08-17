"""Harness-owned boundary for the adopted standard coding toolset."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from harness.envelope import generate_ulid


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


@dataclass(frozen=True, slots=True)
class AgentLocation:
    """The one current place from which an agent's file tools may act."""

    agent_id: str
    machine_id: str
    session_id: str
    workspace_root: Path
    cwd: Path
    fence_reads: bool


@dataclass(frozen=True, slots=True)
class PresenceEvent:
    """One ADR-006-compatible observation emitted by the location adapter."""

    agent_id: str
    machine_id: str
    session_id: str
    event: Literal["spawn", "cwd_change", "read", "write", "idle", "exit"]
    path: Path
    ts: datetime


type PresenceSink = Callable[[PresenceEvent], None]


type ToolName = Literal["read", "edit", "write", "grep", "find", "ls", "bash", "move"]


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """One bounded result returned by the adopted tool implementation."""

    tool_name: ToolName
    content: str
    success: bool


class StandardToolset(Protocol):
    """Nocturne's current toolset seam; extend only when a packet first uses more."""

    async def state(self) -> ToolsetState: ...

    def location(self) -> AgentLocation: ...

    def presence_events(self) -> tuple[PresenceEvent, ...]: ...

    async def move(self, path: Path) -> AgentLocation: ...

    async def execute(
        self,
        tool_name: ToolName,
        arguments: Mapping[str, object],
    ) -> ToolExecutionResult: ...

    async def close(self) -> None: ...


async def open_standard_toolset(
    *,
    command: Sequence[str] | None = None,
    cwd: Path | None = None,
    workspace_root: Path | None = None,
    agent_id: str = "harness-agent",
    machine_id: str = "local-machine",
    session_id: str | None = None,
    fence_reads: bool = False,
    presence_sink: PresenceSink | None = None,
    timeout_seconds: float = 5.0,
) -> StandardToolset:
    """Open the selected standard toolset without leaking its protocol to callers."""

    from harness.pi_toolset_adapter import PiRpcToolset

    return await PiRpcToolset.open(
        command=command,
        cwd=cwd,
        workspace_root=workspace_root,
        agent_id=agent_id,
        machine_id=machine_id,
        session_id=session_id or generate_ulid(),
        fence_reads=fence_reads,
        presence_sink=presence_sink,
        timeout_seconds=timeout_seconds,
    )
