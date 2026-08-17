"""Run the real pinned PI package through Nocturne's owned toolset seam."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from harness.toolset import open_standard_toolset


async def _smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="nocturne-pi-smoke-") as temporary:
        root = Path(temporary)
        project = root / "project"
        sibling = root / "sibling"
        project.mkdir()
        sibling.mkdir()
        events = []
        os.environ["NOCTURNE_M3H_SMOKE_SECRET"] = "must-not-cross"
        command = os.environ.get("NOCTURNE_PI_COMMAND")
        toolset = await open_standard_toolset(
            command=None if command is None else (command,),
            cwd=project,
            workspace_root=root,
            agent_id="pi-smoke-agent",
            machine_id="pi-smoke-machine",
            session_id="pi-smoke-session",
            presence_sink=events.append,
        )
        try:
            state = await toolset.state()
            wrote = await toolset.execute("write", {"path": "note.txt", "content": "first\n"})
            edited = await toolset.execute(
                "edit",
                {
                    "path": "note.txt",
                    "edits": [{"oldText": "first", "newText": "second"}],
                },
            )
            shelled = await toolset.execute("bash", {"command": "printf 'third\\n' >> note.txt"})
            scrubbed = await toolset.execute(
                "bash", {"command": 'test -z "$NOCTURNE_M3H_SMOKE_SECRET"'}
            )
            read = await toolset.execute("read", {"path": "note.txt"})
            escaped = await toolset.execute("bash", {"command": "printf escaped > ../escape.txt"})
            moved = await toolset.move(Path("../sibling"))
        finally:
            await toolset.close()
            os.environ.pop("NOCTURNE_M3H_SMOKE_SECRET", None)
        assert wrote.success
        assert edited.success
        assert shelled.success
        assert scrubbed.success
        assert read.success and "second\nthird" in read.content
        assert not escaped.success
        assert not (root / "escape.txt").exists()
        assert moved.cwd == sibling.resolve()
    assert not state.is_streaming
    assert not state.is_compacting
    assert state.auto_compaction_enabled
    assert state.message_count == 0
    assert state.pending_message_count == 0
    event_names = [event.event for event in events]
    assert event_names[0] == "spawn"
    assert event_names.count("write") == 4
    assert "read" in event_names
    assert "cwd_change" in event_names


def main() -> None:
    asyncio.run(_smoke())
    print("pinned PI toolset RPC smoke passed")


if __name__ == "__main__":
    main()
