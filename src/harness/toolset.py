"""Harness-owned boundary for the adopted standard coding toolset."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from harness.envelope import generate_ulid


class ToolsetError(RuntimeError):
    """The adopted toolset could not satisfy the Harness-owned contract."""


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


type ToolName = Literal[
    "read",
    "edit",
    "write",
    "grep",
    "find",
    "ls",
    "bash",
    "move",
    "navigate",
    "click",
    "type",
    "read_page",
    "screenshot",
]


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """One bounded result returned by the adopted tool implementation."""

    tool_name: ToolName
    content: str
    success: bool
    image: bytes | None = None
    media_type: str | None = None


class StandardToolset(Protocol):
    """Nocturne's current toolset seam; extend only when a packet first uses more."""

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
    cwd: Path | None = None,
    workspace_root: Path | None = None,
    agent_id: str = "harness-agent",
    machine_id: str = "local-machine",
    session_id: str | None = None,
    fence_reads: bool = False,
    presence_sink: PresenceSink | None = None,
) -> StandardToolset:
    """Open the selected standard toolset without leaking its protocol to callers."""

    from harness.pydantic_harness_adapter import PydanticHarnessToolset

    return await PydanticHarnessToolset.open(
        cwd=cwd,
        workspace_root=workspace_root,
        agent_id=agent_id,
        machine_id=machine_id,
        session_id=session_id or generate_ulid(),
        fence_reads=fence_reads,
        presence_sink=presence_sink,
    )
