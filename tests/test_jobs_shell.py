"""SD-059 / PLAN M3SJ background shell lifetime and inherited fences."""

import asyncio
from pathlib import Path

import pytest

from harness.toolset_runtime import LazyStandardToolset


@pytest.mark.asyncio
async def test_background_shell_survives_other_calls_and_stops(tmp_path):
    """PLAN M3SJ / ADR-015: one thread retains its fenced shell across turns."""
    tools = LazyStandardToolset(
        cwd=tmp_path, workspace_root=tmp_path, agent_id="shell-test", machine_id="test"
    )
    try:
        started = await tools.execute("start_shell", {"command": "echo ready; sleep 30"})
        if not Path("/usr/bin/sandbox-exec").is_file():
            assert not started.success
            assert started.content == (
                "Secure shell is unavailable on this host; use read, edit, and write instead."
            )
            return
        assert started.success, started.content
        command_id = started.content.split("ID: ", 1)[1].split(".", 1)[0]
        await asyncio.sleep(0.1)
        for _ in range(3):
            assert (await tools.execute("ls", {"path": "."})).success
            read = await tools.execute("read_shell", {"command_id": command_id})
            assert "ready" in read.content and "running" in read.content
        stopped = await tools.execute("stop_shell", {"command_id": command_id})
        assert stopped.success and "ready" in stopped.content
        refused = await tools.execute("start_shell", {"command": "git push"})
        assert not refused.success and refused.boundary == "remote"
        for name in ("read_shell", "stop_shell"):
            missing = await tools.execute(name, {"command_id": "other-thread"})
            assert not missing.success
            assert "No background shell with that ID in this thread." in missing.content
        empty = await tools.execute("start_shell", {"command": ""})
        assert not empty.success and "A shell command is required." in empty.content
    finally:
        await tools.close()
