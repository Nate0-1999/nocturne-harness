from __future__ import annotations

from pathlib import Path

import pytest

from harness.progressive_prompt import render_workspace_context
from harness.pydantic_ai_adapter import adopted_skill_capabilities
from harness.pydantic_harness_adapter import discover_skill_libraries
from harness.toolset import AgentLocation, ToolsetError, open_standard_toolset

ROOT = Path(__file__).resolve().parents[1]


def test_progressive_instructions_are_complete_but_cannot_read_outside_credentials(
    tmp_path: Path,
) -> None:
    """SPEC R16 removes silent 80-entry/12000-character cuts; ADR-015's instruction
    symlink fence still keeps an outside credential file out of paid model context.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    content = "owner instruction\n" * 1000
    (root / "AGENTS.md").write_text(content)
    for number in range(90):
        (root / f"entry-{number:03}").touch()
    location = AgentLocation(workspace_root=root, cwd=root, agent_id="agent", machine_id="machine",
                             session_id="session", fence_reads=True)
    rendered = render_workspace_context(location)
    assert content in rendered and "entry-089" in rendered
    outside = tmp_path / "credential"
    outside.write_text("outside-secret")
    (root / "AGENTS.override.md").symlink_to(outside)
    assert "outside-secret" not in render_workspace_context(location)


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
    """D.2 136 adopts the official filesystem battery for all six file tools. [ADR-013, ADR-015]
    """

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
    """The owned shim preserves PI's multi-edit all-or-none uniqueness contract. [ADR-013,
    ADR-015] M3GD / SPEC B.6 r14: exercised refusal: "oldText found {count} times; each
    replacement must be unique in the original file".
    """

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
    """P1 and D.2 141 require exact-directory presence while reads remain free. [ADR-013,
    ADR-015] M3GD / SPEC B.6 r14: exercised refusal: "Modification requires presence in the
    file's directory. Move to {target.parent} first.".
    """

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
    """ADR-013, ADR-015: strict reads and credentials remain walled. M3GD / SPEC B.6 r14:
    exercised refusals: "That path is outside this agent's location. Move to {target} first.";
    "That path may contain credentials. Ask the owner before reading it.".
    """
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
    """ADR-013, ADR-015: shell is one shot os fenced and remote state walled. M3GD / SPEC B.6
    r14: exercised refusal: "That command may leave this project or change remote state. Ask
    the owner to run it explicitly outside Nocturne.".
    """
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
    """D.2 136 closes M3PV's resource gap without patching the dependency. [ADR-013, ADR-015]
    """

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
    """ADR-013, ADR-015: skill discovery keeps project and legacy pi libraries.
    """
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


@pytest.mark.asyncio
async def test_presence_grant_cannot_be_widened_or_reused_after_close(tmp_path: Path) -> None:
    """ADR-015: 'cwd must be inside workspace_root', 'Cannot move outside', and 'The workspace
    toolset is closed.' prevent writes beyond an active presence grant. M3GD / SPEC B.6 r14:
    exercised refusal: "Cannot move outside the workspace {self._location.workspace_root}.".
    """
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError, match="cwd must be inside workspace_root"):
        await open_standard_toolset(cwd=tmp_path, workspace_root=root)
    toolset = await open_standard_toolset(cwd=root, workspace_root=root)
    with pytest.raises(ValueError, match="Cannot move outside the workspace"):
        await toolset.move(tmp_path)
    assert toolset.location().cwd == root.resolve()
    await toolset.close()
    with pytest.raises(ToolsetError, match="The workspace toolset is closed."):
        await toolset.execute("write", {"path": "after-close", "content": "bad"})
    assert not (root / "after-close").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("edits,message", [
    ([{"oldText": "", "newText": "bad"}],
     "each edit requires nonblank oldText and string newText"),
    ([{"oldText": "abc", "newText": "x"}, {"oldText": "bcd", "newText": "y"}],
     "edit replacements overlap in the original file"),
])
async def test_ambiguous_edits_preserve_original_bytes(tmp_path: Path, edits, message: str) -> None:
    """ADR-015: refuse edits whose requested spans cannot identify one unchanged source. M3GD /
    SPEC B.6 r14: exercised refusals: "each edit requires nonblank oldText and string
    newText"; "edit replacements overlap in the original file".
    """
    path = tmp_path / "note"
    path.write_text("abcdef")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        result = await toolset.execute("edit", {"path": "note", "edits": edits})
        assert not result.success and message in result.content
        assert path.read_text() == "abcdef"
    finally:
        await toolset.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("command,message", [
    ("cat .env", "That command may expose credentials. Ask the owner before reading them."),
    ("printf safe", "Secure shell is unavailable on this host; use read, edit, and write instead."),
])
async def test_shell_does_not_fall_through_a_wall(
    tmp_path: Path, monkeypatch, command: str, message: str,
) -> None:
    """ADR-015: credentials stay private, and a missing sandbox never starts a raw shell. M3GD /
    SPEC B.6 r14: exercised refusals: "Secure shell is unavailable on this host; use read,
    edit, and write instead."; "That command may expose credentials. Ask the owner before
    reading them.".
    """
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: False if str(p) == "/usr/bin/sandbox-exec"
                        else original(p))
    try:
        result = await toolset.execute("bash", {"command": command})
        assert not result.success and message in result.content
        assert list(tmp_path.iterdir()) == []
    finally:
        await toolset.close()
