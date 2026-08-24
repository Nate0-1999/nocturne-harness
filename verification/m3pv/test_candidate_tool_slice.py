"""Executable M3PV capability/fence slice for pydantic-ai-harness 0.24.0."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import pytest
from fenced_wrapper_prototype import (
    CandidateFencedWrapper,
    CoverageGap,
    FenceRefusal,
)
from pydantic_ai_harness import Skills


def test_six_file_tools_keep_the_required_core_semantics(tmp_path: Path) -> None:
    async def scenario() -> None:
        wrapper = CandidateFencedWrapper(workspace_root=tmp_path, cwd=tmp_path)
        await wrapper.execute("write", {"path": "note.txt", "content": "Alpha\nBeta\nGamma\n"})

        read = await wrapper.execute("read", {"path": "note.txt", "offset": 2, "limit": 1})
        assert "2\tBeta" in read

        await wrapper.execute(
            "edit",
            {
                "path": "note.txt",
                "edits": [
                    {"oldText": "Alpha", "newText": "A"},
                    {"oldText": "Gamma", "newText": "G"},
                ],
            },
        )
        assert (tmp_path / "note.txt").read_text() == "A\nBeta\nG\n"

        grep = await wrapper.execute(
            "grep",
            {
                "pattern": "beta",
                "path": ".",
                "glob": "*.txt",
                "ignoreCase": True,
                "literal": True,
                "context": 0,
                "limit": 10,
            },
        )
        assert ":2:Beta" in grep
        assert "note.txt" in await wrapper.execute(
            "find", {"pattern": "*.txt", "path": ".", "limit": 10}
        )
        assert "note.txt" in await wrapper.execute("ls", {"path": ".", "limit": 10})

    asyncio.run(scenario())


def test_edit_rejects_nonunique_input_before_any_write(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "duplicate.txt"
        path.write_text("same\nsame\n")
        wrapper = CandidateFencedWrapper(workspace_root=tmp_path, cwd=tmp_path)
        with pytest.raises(FenceRefusal, match="found 2 times"):
            await wrapper.execute(
                "edit",
                {"path": "duplicate.txt", "edits": [{"oldText": "same", "newText": "new"}]},
            )
        assert path.read_text() == "same\nsame\n"

    asyncio.run(scenario())


def test_location_fence_precedes_act_and_move_refresh_precedes_next_act(tmp_path: Path) -> None:
    async def scenario() -> None:
        current = tmp_path / "current"
        sibling = tmp_path / "sibling"
        current.mkdir()
        sibling.mkdir()
        (sibling / "readable.txt").write_text("reads are free\n")
        (current / "escape").symlink_to(sibling, target_is_directory=True)
        refreshes: list[Path] = []
        wrapper = CandidateFencedWrapper(
            workspace_root=tmp_path,
            cwd=current,
            movement_refresh=refreshes.append,
        )

        with pytest.raises(FenceRefusal, match="Move to"):
            await wrapper.execute("write", {"path": str(sibling / "blocked.txt"), "content": "no"})
        assert not (sibling / "blocked.txt").exists()
        assert "reads are free" in await wrapper.execute(
            "read",
            {"path": str(sibling / "readable.txt"), "offset": 1, "limit": 20},
        )
        with pytest.raises(FenceRefusal, match="Move to"):
            await wrapper.execute("write", {"path": "escape/symlink.txt", "content": "no"})
        assert not (sibling / "symlink.txt").exists()

        await wrapper.execute("move", {"path": str(sibling)})
        assert refreshes == [sibling.resolve()]
        await wrapper.execute("write", {"path": "allowed.txt", "content": "yes"})
        assert (sibling / "allowed.txt").read_text() == "yes"
        assert wrapper.events[-2:] == [
            ("cwd_change", sibling.resolve()),
            ("write", (sibling / "allowed.txt").resolve()),
        ]

    asyncio.run(scenario())


def test_bash_is_one_shot_and_os_fenced_to_the_current_location(tmp_path: Path) -> None:
    async def scenario() -> None:
        current = tmp_path / "current"
        sibling = tmp_path / "sibling"
        child = current / "child"
        child.mkdir(parents=True)
        sibling.mkdir()
        wrapper = CandidateFencedWrapper(workspace_root=tmp_path, cwd=current)

        assert str(current) in await wrapper.execute("bash", {"command": "pwd"})
        await wrapper.execute("bash", {"command": "cd child"})
        assert str(current) in await wrapper.execute("bash", {"command": "pwd"})

        await wrapper.execute("bash", {"command": "printf local > local.txt"})
        assert (current / "local.txt").read_text() == "local"
        outside = sibling / "outside.txt"
        denied = await wrapper.execute(
            "bash", {"command": f"printf blocked > {shlex.quote(str(outside))}"}
        )
        assert not outside.exists()
        assert "exit code" in denied.lower() or "not permitted" in denied.lower()
        with pytest.raises(FenceRefusal, match="remote state"):
            await wrapper.execute("bash", {"command": "git push origin main"})

    asyncio.run(scenario())


def test_known_grep_and_image_gaps_are_visible(tmp_path: Path) -> None:
    async def scenario() -> None:
        (tmp_path / "note.txt").write_text("one\nmatch\nthree\n")
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00payload")
        wrapper = CandidateFencedWrapper(workspace_root=tmp_path, cwd=tmp_path)
        with pytest.raises(CoverageGap, match="no context-line behavior"):
            await wrapper.execute(
                "grep", {"pattern": "match", "path": ".", "context": 1, "limit": 10}
            )
        image = await wrapper.execute("read", {"path": "image.png", "offset": 1, "limit": 20})
        assert "binary file" in image.lower()

    asyncio.run(scenario())


def test_skills_are_progressive_but_do_not_expose_bundled_resources(tmp_path: Path) -> None:
    library = tmp_path / "skills"
    skill = library / "review"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review the current change.\n---\n\nFollow the checklist.\n"
    )
    (skill / "scripts" / "check.py").write_text("print('resource')\n")

    leaves = []
    Skills(library).apply(leaves.append)
    assert len(leaves) == 1
    leaf = leaves[0]
    assert leaf.id == "review"
    assert leaf.description == "Review the current change."
    assert leaf.defer_loading is True
    assert leaf.get_instructions() == ["# Skill: review\n\nFollow the checklist."]
    assert "resource" not in "\n".join(leaf.get_instructions() or ())
