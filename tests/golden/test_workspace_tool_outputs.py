"""M3TS model-visible output goldens for the seven adopted coding tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.pydantic_ai_adapter import WORKSPACE_INSTRUCTIONS
from harness.toolset import open_standard_toolset


@pytest.mark.asyncio
async def test_seven_coding_tool_outputs_are_explicit(tmp_path: Path) -> None:
    """P1 and D.2 136/141 pin intentional model-visible tool output deltas."""

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("before\n")
    (tmp_path / "note.txt").write_text("zero\nmatch one\nnext\nmatch two\nend\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        read = await toolset.execute("read", {"path": "note.txt", "offset": 2, "limit": 2})
        grep = await toolset.execute(
            "grep", {"pattern": "match", "path": ".", "context": 1, "limit": 10}
        )
        found = await toolset.execute("find", {"pattern": "*.txt", "path": ".", "limit": 10})
        listed = await toolset.execute("ls", {"path": ".", "limit": 10})
        written = await toolset.execute("write", {"path": "new.txt", "content": "hello\n"})
        edited = await toolset.execute(
            "edit",
            {
                "path": "new.txt",
                "edits": [{"oldText": "hello", "newText": "world"}],
            },
        )
        refused_write = await toolset.execute(
            "write", {"path": "sub/new.txt", "content": "blocked\n"}
        )
        refused_edit = await toolset.execute(
            "edit",
            {
                "path": "sub/deep.txt",
                "edits": [{"oldText": "before", "newText": "after"}],
            },
        )
        shell = await toolset.execute("bash", {"command": "printf shell-output"})
    finally:
        await toolset.close()

    assert read.content == (
        "[note.txt | 5 lines | hash:b81908ceac96]\n"
        "     2\tmatch one\n"
        "     3\tnext\n"
        "... (2 more lines. Use offset=3 to continue reading.)\n"
    )
    assert grep.content == (
        "[note.txt | 5 lines | hash:b81908ceac96]\n"
        "     1\tzero\n"
        "     2\tmatch one\n"
        "     3\tnext\n"
        "     4\tmatch two\n"
        "     5\tend\n"
    )
    assert found.content == "note.txt"
    assert listed.content == "note.txt  (34 bytes)\nsub/"
    assert written.content == "Wrote 6 chars (1 lines) to new.txt. [hash:5891b5b522d5]"
    assert edited.content == "Edited new.txt. [hash:e258d248fda9]"
    exact_refusal = (
        f"Modification requires presence in the file's directory. Move to {sub.resolve()} first."
    )
    assert not refused_write.success and refused_write.content == exact_refusal
    assert not refused_edit.success and refused_edit.content == exact_refusal
    assert not (sub / "new.txt").exists()
    assert (sub / "deep.txt").read_text() == "before\n"
    if Path("/usr/bin/sandbox-exec").is_file():
        assert shell.success
        assert shell.content == "[stdout]\nshell-output"
    else:
        assert not shell.success
        assert shell.content == (
            "Secure shell is unavailable on this host; use read, edit, and write instead."
        )


def test_exact_movement_law_is_model_visible() -> None:
    """P1 and D.2 141 sharpen the prompt without giving bash the file-tool fence."""

    assert WORKSPACE_INSTRUCTIONS == (
        "To edit or write a file, you must use move in its own tool step to enter that file's "
        "directory first. Reads are free. Bash may modify files only within the current "
        "location's subtree. If a tool refuses a boundary crossing, explain the wall plainly; "
        "do not retry around it. Browser tools are headless and default to localhost or files "
        "beneath the current location. Never ask the owner for consent inside a tool call; a "
        "refused open-web request must wait for the owner's exact `/browser allow-web` command."
    )
