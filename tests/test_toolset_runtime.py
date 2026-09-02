from pathlib import Path

import pytest

from harness.toolset_runtime import LazyStandardToolset


@pytest.mark.asyncio
async def test_model_move_execution_notifies_thread_location(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    moved: list[Path] = []
    toolset = LazyStandardToolset(
        cwd=tmp_path,
        workspace_root=tmp_path,
        agent_id="agent",
        machine_id="machine",
        on_move=moved.append,
    )

    try:
        result = await toolset.execute("move", {"path": "nested"})
    finally:
        await toolset.close()

    assert result.success is True
    assert moved == [nested.resolve()]
