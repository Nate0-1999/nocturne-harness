"""Run the real pinned PI package through Nocturne's owned toolset seam."""

from __future__ import annotations

import asyncio
from pathlib import Path

from harness.toolset import open_standard_toolset


async def _smoke() -> None:
    root = Path.cwd()
    events = []
    toolset = await open_standard_toolset(
        cwd=root,
        workspace_root=root,
        agent_id="pi-smoke-agent",
        machine_id="pi-smoke-machine",
        session_id="pi-smoke-session",
        presence_sink=events.append,
    )
    try:
        state = await toolset.state()
        moved = await toolset.move(Path("src/harness"))
    finally:
        await toolset.close()
    assert not state.is_streaming
    assert not state.is_compacting
    assert state.auto_compaction_enabled
    assert state.message_count == 0
    assert state.pending_message_count == 0
    assert moved.cwd == (root / "src/harness").resolve()
    assert [event.event for event in events[:2]] == ["spawn", "cwd_change"]


def main() -> None:
    asyncio.run(_smoke())
    print("pinned PI toolset RPC smoke passed")


if __name__ == "__main__":
    main()
