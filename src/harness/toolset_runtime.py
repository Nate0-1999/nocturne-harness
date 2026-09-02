"""Daemon-lifetime lazy ownership of the adopted standard toolset."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path

from harness.browser_toolset import BrowserToolset
from harness.toolset import (
    AgentLocation,
    PresenceEvent,
    StandardToolset,
    ToolExecutionResult,
    ToolName,
    open_standard_toolset,
)


class LazyStandardToolset:
    """Construct the adopted tool layer only when an owner turn first needs it."""

    def __init__(
        self,
        *,
        cwd: Path,
        workspace_root: Path,
        agent_id: str,
        machine_id: str,
        fence_reads: bool = False,
        on_move: Callable[[Path], None] | None = None,
    ) -> None:
        self._cwd = cwd.resolve(strict=True)
        self._workspace_root = workspace_root.resolve(strict=True)
        if not self._cwd.is_relative_to(self._workspace_root):
            raise ValueError("toolset cwd must be inside workspace_root")
        self._agent_id = agent_id
        self._machine_id = machine_id
        self._fence_reads = fence_reads
        self._on_move = on_move
        self._toolset: StandardToolset | None = None
        self._browser = BrowserToolset(location=self.location)
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
        location = await (await self._owned()).move(path)
        if self._on_move is not None:
            self._on_move(location.cwd)
        return location

    async def execute(
        self,
        tool_name: ToolName,
        arguments: Mapping[str, object],
    ) -> ToolExecutionResult:
        if self._browser.owns(tool_name):
            return await self._browser.execute(tool_name, arguments)
        return await (await self._owned()).execute(tool_name, arguments)

    def grant_open_web(self, thread_id: str) -> None:
        self._browser.grant_open_web(thread_id)

    def set_browser_consent_check(self, consent_check: Callable[[str], bool]) -> None:
        self._browser.set_consent_check(consent_check)

    async def close(self) -> None:
        await self._browser.close()
        if self._toolset is not None:
            await self._toolset.close()
            self._toolset = None
