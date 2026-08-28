from __future__ import annotations

from pathlib import Path

import pytest

from harness.pydantic_ai_adapter import adopted_skill_capabilities
from harness.pydantic_harness_adapter import discover_skill_libraries
from harness.toolset import open_standard_toolset

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_in_process_toolset_owns_location_and_presence(tmp_path: Path) -> None:
    """ADR-013 keeps the adopted implementation behind Nocturne's typed seam."""

    child = tmp_path / "child"
    child.mkdir()
    events = []
    toolset = await open_standard_toolset(
        cwd=tmp_path,
        workspace_root=tmp_path,
        agent_id="agent-location",
        machine_id="machine-location",
        session_id="session-location",
        presence_sink=events.append,
    )
    moved = await toolset.move(Path("child"))
    await toolset.close()

    assert moved.cwd == child.resolve()
    assert toolset.presence_events() == tuple(events)
    assert [(event.event, event.path) for event in events] == [
        ("spawn", tmp_path.resolve()),
        ("cwd_change", child.resolve()),
        ("exit", child.resolve()),
    ]


@pytest.mark.asyncio
async def test_six_file_tools_delegate_core_semantics_upstream(tmp_path: Path) -> None:
    """D.2 136 adopts the official filesystem battery for all six file tools."""

    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        written = await toolset.execute(
            "write", {"path": "note.txt", "content": "Alpha\nBeta\nGamma\n"}
        )
        read = await toolset.execute("read", {"path": "note.txt", "offset": 2, "limit": 1})
        edited = await toolset.execute(
            "edit",
            {
                "path": "note.txt",
                "edits": [
                    {"oldText": "Alpha", "newText": "A"},
                    {"oldText": "Gamma", "newText": "G"},
                ],
            },
        )
        grep = await toolset.execute(
            "grep",
            {
                "pattern": "beta",
                "path": ".",
                "glob": "*.txt",
                "ignoreCase": True,
                "literal": True,
                "context": 1,
                "limit": 10,
            },
        )
        found = await toolset.execute("find", {"pattern": "*.txt", "path": ".", "limit": 10})
        listed = await toolset.execute("ls", {"path": ".", "limit": 10})
    finally:
        await toolset.close()

    assert written.success and "Wrote 17 chars" in written.content
    assert read.success and "2\tBeta" in read.content
    assert edited.success and "Edited note.txt" in edited.content
    assert (tmp_path / "note.txt").read_text() == "A\nBeta\nG\n"
    assert grep.success and "1\tA" in grep.content and "2\tBeta" in grep.content
    assert found.success and found.content == "note.txt"
    assert listed.success and listed.content.startswith("note.txt  (")


@pytest.mark.asyncio
async def test_atomic_multi_edit_refuses_before_any_write(tmp_path: Path) -> None:
    """The owned shim preserves PI's multi-edit all-or-none uniqueness contract."""

    path = tmp_path / "duplicate.txt"
    path.write_text("same\nsame\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        result = await toolset.execute(
            "edit",
            {
                "path": "duplicate.txt",
                "edits": [{"oldText": "same", "newText": "new"}],
            },
        )
    finally:
        await toolset.close()

    assert not result.success
    assert "found 2 times" in result.content
    assert path.read_text() == "same\nsame\n"


@pytest.mark.asyncio
async def test_location_fence_precedes_act_and_move_precedes_next_act(tmp_path: Path) -> None:
    """P1 and D.2 141 require exact-directory presence while reads remain free."""

    current = tmp_path / "current"
    deep = current / "deep"
    sibling = tmp_path / "sibling"
    deep.mkdir(parents=True)
    sibling.mkdir()
    (deep / "editable.txt").write_text("before\n")
    (sibling / "readable.txt").write_text("reads are free\n")
    (current / "escape").symlink_to(sibling, target_is_directory=True)
    toolset = await open_standard_toolset(cwd=current, workspace_root=tmp_path)
    try:
        outside = await toolset.execute(
            "write", {"path": str(sibling / "blocked.txt"), "content": "no"}
        )
        nested_write = await toolset.execute("write", {"path": "deep/blocked.txt", "content": "no"})
        nested_edit = await toolset.execute(
            "edit",
            {
                "path": "deep/editable.txt",
                "edits": [{"oldText": "before", "newText": "after"}],
            },
        )
        read = await toolset.execute(
            "read", {"path": str(sibling / "readable.txt"), "offset": 1, "limit": 20}
        )
        symlink = await toolset.execute("write", {"path": "escape/symlink.txt", "content": "no"})
        moved = await toolset.execute("move", {"path": "deep"})
        edited = await toolset.execute(
            "edit",
            {
                "path": "editable.txt",
                "edits": [{"oldText": "before", "newText": "after"}],
            },
        )
        allowed = await toolset.execute("write", {"path": "allowed.txt", "content": "yes"})
    finally:
        await toolset.close()

    assert not outside.success and "Move to" in outside.content
    assert not nested_write.success and f"Move to {deep.resolve()} first" in nested_write.content
    assert not nested_edit.success and f"Move to {deep.resolve()} first" in nested_edit.content
    assert read.success and "reads are free" in read.content
    assert not symlink.success and "Move to" in symlink.content
    assert moved.success and edited.success and allowed.success
    assert not (sibling / "blocked.txt").exists()
    assert not (sibling / "symlink.txt").exists()
    assert not (deep / "blocked.txt").exists()
    assert (deep / "editable.txt").read_text() == "after\n"
    assert (deep / "allowed.txt").read_text() == "yes"
    assert [(event.event, event.path) for event in toolset.presence_events()] == [
        ("spawn", current.resolve()),
        ("read", (sibling / "readable.txt").resolve()),
        ("cwd_change", deep.resolve()),
        ("write", (deep / "editable.txt").resolve()),
        ("write", (deep / "allowed.txt").resolve()),
        ("exit", deep.resolve()),
    ]


@pytest.mark.asyncio
async def test_strict_reads_and_credentials_remain_walled(tmp_path: Path) -> None:
    current = tmp_path / "current"
    sibling = tmp_path / "sibling"
    current.mkdir()
    sibling.mkdir()
    (sibling / "note.txt").write_text("outside\n")
    (current / ".env").write_text("TOKEN=secret\n")
    toolset = await open_standard_toolset(cwd=current, workspace_root=tmp_path, fence_reads=True)
    try:
        outside = await toolset.execute("read", {"path": str(sibling / "note.txt")})
        credential = await toolset.execute("read", {"path": ".env"})
    finally:
        await toolset.close()

    assert not outside.success and "Move to" in outside.content
    assert not credential.success and "credentials" in credential.content


@pytest.mark.asyncio
async def test_shell_is_one_shot_os_fenced_and_remote_state_walled(tmp_path: Path) -> None:
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    current = tmp_path / "current"
    sibling = tmp_path / "sibling"
    child = current / "child"
    child.mkdir(parents=True)
    sibling.mkdir()
    toolset = await open_standard_toolset(cwd=current, workspace_root=tmp_path)
    try:
        pwd = await toolset.execute("bash", {"command": "pwd"})
        await toolset.execute("bash", {"command": "cd child"})
        pwd_again = await toolset.execute("bash", {"command": "pwd"})
        local = await toolset.execute("bash", {"command": "printf local > local.txt"})
        outside_path = sibling / "outside.txt"
        outside = await toolset.execute("bash", {"command": f"printf blocked > {outside_path}"})
        remote = await toolset.execute("bash", {"command": "git push origin main"})
    finally:
        await toolset.close()

    assert pwd.success and str(current) in pwd.content
    assert pwd_again.success and str(current) in pwd_again.content
    assert local.success and (current / "local.txt").read_text() == "local"
    assert outside.success and "exit code" in outside.content.lower()
    assert not outside_path.exists()
    assert not remote.success and "remote state" in remote.content


def test_upstream_skills_gain_model_visible_bundled_resources(tmp_path: Path) -> None:
    """D.2 136 closes M3PV's resource gap without patching the dependency."""

    library = tmp_path / ".agents" / "skills"
    skill = library / "review"
    (skill / "scripts").mkdir(parents=True)
    (skill / "references").mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review the current change.\n---\n\nFollow the checklist.\n"
    )
    (skill / "scripts" / "check.py").write_text("print('resource')\n")
    (skill / "references" / "rules.md").write_text("Keep the fence.\n")

    capabilities = adopted_skill_capabilities((library,))

    assert len(capabilities) == 1
    leaf = capabilities[0]
    instructions = "\n".join(leaf.get_instructions() or ())
    assert leaf.id == "review"
    assert leaf.description == "Review the current change."
    assert leaf.defer_loading is True
    assert "# Skill: review" in instructions
    assert str(skill.resolve()) in instructions
    assert "scripts/check.py" in instructions
    assert "references/rules.md" in instructions


def test_skill_discovery_keeps_project_and_legacy_pi_libraries(tmp_path: Path) -> None:
    for relative in (Path(".agents/skills"), Path(".pi/skills")):
        (tmp_path / relative).mkdir(parents=True)

    discovered = discover_skill_libraries(tmp_path)

    assert (tmp_path / ".agents/skills").resolve() in discovered
    assert (tmp_path / ".pi/skills").resolve() in discovered


def test_pydantic_harness_has_one_import_fence_and_exact_pin() -> None:
    """ADR-013 contains upstream churn in one implementation adapter."""

    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "harness").glob("*.py")):
        if path.name == "pydantic_harness_adapter.py":
            continue
        if "pydantic_ai_harness" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert offenders == []
    assert '"pydantic-ai==2.28.0"' in pyproject
    assert '"pydantic-ai-harness[skills]==0.24.0"' in pyproject
