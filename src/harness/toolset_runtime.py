"""Daemon-lifetime lazy ownership of the adopted standard toolset."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

from harness.toolset import (
    AgentLocation,
    PresenceEvent,
    StandardToolset,
    ToolExecutionResult,
    ToolName,
    ToolsetState,
    open_standard_toolset,
)


class LazyStandardToolset:
    """Start PI only when an owner turn first asks for a workspace tool."""

    def __init__(
        self,
        *,
        cwd: Path,
        workspace_root: Path,
        agent_id: str,
        machine_id: str,
        fence_reads: bool = False,
    ) -> None:
        self._cwd = cwd.resolve(strict=True)
        self._workspace_root = workspace_root.resolve(strict=True)
        if not self._cwd.is_relative_to(self._workspace_root):
            raise ValueError("toolset cwd must be inside workspace_root")
        self._agent_id = agent_id
        self._machine_id = machine_id
        self._fence_reads = fence_reads
        self._toolset: StandardToolset | None = None
        self._lock = asyncio.Lock()

    async def _owned(self) -> StandardToolset:
        if self._toolset is not None:
            return self._toolset
        async with self._lock:
            if self._toolset is None:
                self._toolset = await open_standard_toolset(
                    cwd=self._cwd,
                    workspace_root=self._workspace_root,
                    agent_id=self._agent_id,
                    machine_id=self._machine_id,
                    fence_reads=self._fence_reads,
                )
            return self._toolset

    async def state(self) -> ToolsetState:
        return await (await self._owned()).state()

    def location(self) -> AgentLocation:
        if self._toolset is not None:
            return self._toolset.location()
        return AgentLocation(
            agent_id=self._agent_id,
            machine_id=self._machine_id,
            session_id="not-started",
            workspace_root=self._workspace_root,
            cwd=self._cwd,
            fence_reads=self._fence_reads,
        )

    def presence_events(self) -> tuple[PresenceEvent, ...]:
        return () if self._toolset is None else self._toolset.presence_events()

    async def move(self, path: Path) -> AgentLocation:
        return await (await self._owned()).move(path)

    async def execute(
        self,
        tool_name: ToolName,
        arguments: Mapping[str, object],
    ) -> ToolExecutionResult:
        return await (await self._owned()).execute(tool_name, arguments)

    async def close(self) -> None:
        if self._toolset is not None:
            await self._toolset.close()
            self._toolset = None
