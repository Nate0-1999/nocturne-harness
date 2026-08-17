"""Run the real pinned PI package through Nocturne's owned toolset seam."""

from __future__ import annotations

import asyncio
from pathlib import Path

from harness.toolset import open_standard_toolset


async def _smoke() -> None:
    toolset = await open_standard_toolset(cwd=Path.cwd())
    try:
        state = await toolset.state()
    finally:
        await toolset.close()
    assert not state.is_streaming
    assert not state.is_compacting
    assert state.auto_compaction_enabled
    assert state.message_count == 0
    assert state.pending_message_count == 0


def main() -> None:
    asyncio.run(_smoke())
    print("pinned PI toolset RPC smoke passed")


if __name__ == "__main__":
    main()
