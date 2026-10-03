from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from harness.progressive_prompt import render_workspace_context
from harness.pydantic_ai_adapter import adopted_skill_capabilities
from harness.pydantic_harness_adapter import adopted_skills, discover_skill_libraries
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
    location = AgentLocation(
        workspace_root=root,
        cwd=root,
        agent_id="agent",
        machine_id="machine",
        session_id="session",
        fence_reads=True,
    )
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
    """D.2 136 adopts the official filesystem battery for all six file tools. [ADR-013, ADR-015]"""

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


@pytest.mark.asyncio
async def test_shell_scratch_leaves_the_repo_and_a_fenced_agent_stays_inside(
    tmp_path: Path,
) -> None:
    """F137 / M3SF / M3EX-09, M3EX-10: tool scratch never lands in the repo; a fenced agent's
    shell cannot walk directories beyond its workspace root.
    """
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    root = tmp_path / "attempt"
    root.mkdir()
    toolset = await open_standard_toolset(cwd=root, workspace_root=root, fence_reads=True)
    try:
        scratch = await toolset.execute(
            "bash", {"command": 'printf x > "$TMPDIR/scratch.txt" && printf "%s" "$TMPDIR"'}
        )
        walk = await toolset.execute("bash", {"command": "find / -path '*/.venv/bin/python'"})
        home = await toolset.execute("bash", {"command": "ls ~"})
        inside = await toolset.execute("bash", {"command": "ls ."})
    finally:
        await toolset.close()

    scratch_dir = Path(re.search(r"/\S*nocturne-shell-[^\s/]+", scratch.content).group())
    assert scratch.success and list(root.iterdir()) == []
    assert not scratch_dir.exists()
    assert not walk.success and walk.boundary == "location"
    assert f"That command reaches outside this workspace: /. Stay inside {root.resolve()}." in (
        walk.content
    )
    assert not home.success and home.boundary == "location"
    assert inside.success


@pytest.mark.asyncio
async def test_git_on_the_enclosing_repository_works_from_a_subfolder(tmp_path: Path) -> None:
    """v2.125 (D.2 168), F134: git is the one exception to the bash subtree sandbox; other
    writes above the subtree stay refused and the refusal names the movement remedy."""
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    import subprocess

    repository = tmp_path / "repo"
    sub = repository / "docs"
    sub.mkdir(parents=True)
    for command in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"]):
        subprocess.run(["git", "-C", str(repository), *command], check=True)
    toolset = await open_standard_toolset(cwd=sub, workspace_root=repository)
    try:
        await toolset.execute("bash", {"command": "printf note > note.txt"})
        added = await toolset.execute("bash", {"command": "git add note.txt"})
        committed = await toolset.execute("bash", {"command": "git commit -q -m note"})
        above = await toolset.execute("bash", {"command": "printf x > ../above.txt"})
        trail = [(event.event, event.path) for event in toolset.presence_events()]
    finally:
        await toolset.close()

    log = subprocess.run(
        ["git", "-C", str(repository), "log", "--format=%s"], capture_output=True, text=True
    )
    assert added.success and "exit code" not in added.content.lower()
    assert committed.success and log.stdout.strip() == "note"
    assert not (repository / "above.txt").exists()
    assert "Move to the folder you need to change" in above.content
    assert trail.count(("write", sub.resolve())) == 4


@pytest.mark.asyncio
async def test_worktree_worker_creates_a_folder_and_commits_without_touching_parent(tmp_path):
    """F154 / M3SF2: a real worktree owns its index and can commit behind the shell fence."""
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.name", "t"),
        ("config", "user.email", "t@t"),
        ("commit", "--allow-empty", "-qm", "base"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"])
    attempt = tmp_path / "attempt"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(attempt)], check=True
    )
    toolset = await open_standard_toolset(cwd=attempt, workspace_root=attempt, fence_reads=True)
    try:
        namespace = "nocturne-worktrees/attempt"
        # F154: provision the namespace as the supervisor does before sandboxed tools start.
        subprocess.run(
            ["git", "-C", str(attempt), "checkout", "-qb", f"{namespace}/work"], check=True
        )
        named = await toolset.execute(
            "bash", {"command": f"git checkout -b {namespace}/named-result"}
        )
        assert named.success and "Operation not permitted" not in named.content, named.content
        made = await toolset.execute("bash", {"command": "mkdir scratch"})
        assert made.success and (attempt / "scratch").is_dir(), made.content
        await toolset.move(Path("scratch"))
        written = await toolset.execute("write", {"path": "note.txt", "content": "worker\n"})
        assert written.success, written.content
        added = await toolset.execute("bash", {"command": "git add note.txt"})
        committed = await toolset.execute("bash", {"command": "git commit -q -m worker"})
        owner_branch = subprocess.check_output(
            ["git", "-C", str(root), "symbolic-ref", "HEAD"], text=True
        ).strip()
        refused = await toolset.execute("bash", {"command": f"git update-ref {owner_branch} HEAD"})
        assert "Operation not permitted" in refused.content, refused.content
    finally:
        await toolset.close()
    log = subprocess.check_output(
        ["git", "-C", str(attempt), "log", "-1", "--format=%s"], text=True
    )
    assert log.strip() == "worker", (added.content, committed.content)
    assert subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"]) == base
    assert not (root / "scratch").exists()


def test_upstream_skills_gain_model_visible_bundled_resources(tmp_path: Path) -> None:
    """D.2 136 closes M3PV's resource gap without patching the dependency. [ADR-013, ADR-015]"""

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
    assert f"- `{(skill / 'references' / 'rules.md').resolve()}`" in instructions


def test_skill_discovery_keeps_project_and_legacy_pi_libraries(tmp_path: Path) -> None:
    """ADR-013, ADR-015: skill discovery keeps project and legacy pi libraries."""
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
    assert '"pydantic-ai==2.43.0"' in pyproject
    assert '"pydantic-ai-harness[skills]==0.31.0"' in pyproject


@pytest.mark.asyncio
async def test_presence_grant_cannot_be_widened_or_reused_after_close(tmp_path: Path) -> None:
    """ADR-015: 'cwd must be inside workspace_root', 'Cannot move outside', and 'The workspace
    toolset is closed.' prevent writes beyond an active presence grant. M3GD / SPEC B.6 r14:
    exercised refusal: "Cannot move outside the workspace {self._location.workspace_root}.".
    """
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "sibling").mkdir()
    with pytest.raises(ValueError, match="cwd must be inside workspace_root"):
        await open_standard_toolset(cwd=tmp_path, workspace_root=root)
    toolset = await open_standard_toolset(cwd=root, workspace_root=root)
    with pytest.raises(ValueError, match="Cannot move outside the workspace"):
        await toolset.move(tmp_path / "sibling")
    # M3W5B-05: a miscounted '..' above the root is refused plainly with the way back.
    with pytest.raises(ToolsetError) as above:
        await toolset.move(tmp_path)
    home = root.resolve()
    assert str(above.value) == (
        f"{tmp_path.resolve()} is above this thread's workspace. Its root is {home}; "
        f"move('{home}') goes there."
    )
    assert toolset.location().cwd == root.resolve()
    await toolset.close()
    with pytest.raises(ToolsetError, match="The workspace toolset is closed."):
        await toolset.execute("write", {"path": "after-close", "content": "bad"})
    assert not (root / "after-close").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edits,message",
    [
        (
            [{"oldText": "", "newText": "bad"}],
            "each edit requires nonblank oldText and string newText",
        ),
        (
            [{"oldText": "abc", "newText": "x"}, {"oldText": "bcd", "newText": "y"}],
            "edit replacements overlap in the original file",
        ),
    ],
)
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
@pytest.mark.parametrize(
    "command,message",
    [
        ("cat .env", "That command may expose credentials. Ask the owner before reading them."),
        (
            "printf safe",
            "Secure shell is unavailable on this host; use read, edit, and write instead.",
        ),
    ],
)
async def test_shell_does_not_fall_through_a_wall(
    tmp_path: Path,
    monkeypatch,
    command: str,
    message: str,
) -> None:
    """ADR-015: credentials stay private, and a missing sandbox never starts a raw shell. M3GD /
    SPEC B.6 r14: exercised refusals: "Secure shell is unavailable on this host; use read,
    edit, and write instead."; "That command may expose credentials. Ask the owner before
    reading them.".
    """
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    original = Path.is_file
    monkeypatch.setattr(
        Path, "is_file", lambda p: False if str(p) == "/usr/bin/sandbox-exec" else original(p)
    )
    try:
        result = await toolset.execute("bash", {"command": command})
        assert not result.success and message in result.content
        assert list(tmp_path.iterdir()) == []
    finally:
        await toolset.close()


@pytest.mark.asyncio
async def test_a_cancelled_turn_stops_its_foreground_command(tmp_path: Path) -> None:
    """F135 (M3EX-13): Ctrl-C mid-turn must not wait on a stuck command, nor orphan it."""
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    import asyncio
    import subprocess

    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        running = asyncio.create_task(toolset.execute("bash", {"command": "sleep 97531"}))
        await asyncio.sleep(1.0)
        running.cancel()
        async with asyncio.timeout(5):
            await asyncio.gather(running, return_exceptions=True)
    finally:
        await toolset.close()

    listing = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    assert "sleep 97531" not in listing


@pytest.mark.asyncio
async def test_a_change_that_removes_most_of_a_file_needs_the_word_replace(tmp_path: Path) -> None:
    """INCIDENT M3W5B-01: a one-test request rewrote a 1,300-line file to 16 lines. M3GD /
    SPEC B.6 r14: exercised refusal: "Refused: this would remove {n}% of {name} ({lines}
    lines)."; small files and ordinary edits still just work."""

    body = "".join(f"def test_{number}():\n    assert {number}\n\n" for number in range(40))
    (tmp_path / "test_big.py").write_text(body)
    (tmp_path / ".nvmrc").write_text("18\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        rewrite = await toolset.execute(
            "write", {"path": "test_big.py", "content": "def test_new():\n    assert 1\n"}
        )
        gutted = await toolset.execute(
            "edit", {"path": "test_big.py", "edits": [{"oldText": body[20:], "newText": ""}]}
        )
        added = await toolset.execute(
            "edit",
            {"path": "test_big.py", "edits": [{"oldText": "assert 39\n", "newText": "assert 3\n"}]},
        )
        bumped = await toolset.execute("write", {"path": ".nvmrc", "content": "20\n"})
        replaced = await toolset.execute(
            "write", {"path": "test_big.py", "content": "# replaced\n", "replace": True}
        )
    finally:
        await toolset.close()

    assert not rewrite.success and "Refused: this would remove 9" in rewrite.content
    assert "test_big.py (120 lines)" in rewrite.content and "says replace" in rewrite.content
    assert "oldText set to its last lines, '    assert 39'," in rewrite.content
    assert not gutted.success and "Refused: this would remove" in gutted.content
    assert added.success and bumped.success and replaced.success
    assert (tmp_path / "test_big.py").read_text() == "# replaced\n"


@pytest.mark.asyncio
async def test_a_deep_glob_finds_files_directly_in_the_searched_folder(tmp_path: Path) -> None:
    """INCIDENT M3W5B-06: grep with glob '**/*' in web/src answered 'No matches found' for a
    word 17 files held; the upstream fnmatch needs a folder before '**/'. [ADR-013]"""

    source = tmp_path / "web" / "src"
    (source / "deep").mkdir(parents=True)
    (source / "App.tsx").write_text("data-tooltip-detail\n")
    (source / "deep" / "Tip.tsx").write_text("data-tooltip-detail\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        results = [
            await toolset.execute(
                "grep", {"pattern": "data-tooltip-detail", "path": "web/src", "glob": glob}
            )
            for glob in ("**/*", "**/*.tsx", "*.tsx")
        ]
    finally:
        await toolset.close()

    for result in results:
        assert result.success and "App.tsx" in result.content
        assert "deep/Tip.tsx" in result.content


@pytest.mark.asyncio
async def test_repository_commands_find_the_project_environment_from_a_subfolder(
    tmp_path: Path,
) -> None:
    """INCIDENT M3W5B-02: from tests/, '.venv/bin/python' was not found and the agent said
    pytest was missing; the project's .venv now comes first on PATH wherever the agent stands.
    [ADR-013, P3]"""
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    tests = tmp_path / "tests"
    tests.mkdir()
    binary = tmp_path / ".venv" / "bin"
    binary.mkdir(parents=True)
    (binary / "pytest").write_text("#!/bin/sh\necho project-pytest\n")
    (binary / "pytest").chmod(0o755)
    toolset = await open_standard_toolset(cwd=tests, workspace_root=tmp_path)
    try:
        ran = await toolset.execute("bash", {"command": 'pytest; printf "%s" "$VIRTUAL_ENV"'})
        context = render_workspace_context(toolset.location())
    finally:
        await toolset.close()

    assert ran.success and "project-pytest" in ran.content
    assert str((tmp_path / ".venv").resolve()) in ran.content
    assert f"Project environment: {(tmp_path / '.venv').resolve()} comes first" in context


@pytest.mark.asyncio
async def test_a_commit_message_keeps_its_dollar_signs(tmp_path: Path) -> None:
    """INCIDENT M3W5B-07: "$100" in a double-quoted commit message reached git as nothing.
    M3GD / SPEC B.6 r14: exercised refusal: "Refused: the shell would turn {parameter} in this
    commit message into nothing. Put the message in single quotes so it reaches git as typed."
    """
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    import subprocess

    for command in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"]):
        subprocess.run(["git", "-C", str(tmp_path), *command], check=True)
    (tmp_path / "note.txt").write_text("note\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        await toolset.execute("bash", {"command": "git add note.txt"})
        refused = await toolset.execute(
            "bash", {"command": 'git commit -q -m "a $100 monthly breaker"'}
        )
        committed = await toolset.execute(
            "bash", {"command": "git commit -q -m 'a $100 monthly breaker'"}
        )
    finally:
        await toolset.close()

    log = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--format=%s"], capture_output=True, text=True
    )
    assert not refused.success and "turn $100 in this commit message into nothing" in (
        refused.content
    )
    assert committed.success and log.stdout.strip() == "a $100 monthly breaker"


@pytest.mark.asyncio
async def test_a_folder_named_from_the_workspace_root_is_found_from_a_sibling(
    tmp_path: Path,
) -> None:
    """INCIDENT M3W5B-04, walked again in M3CL2: from docs/, move('web') found no docs/web and
    gpt-4.1-mini gave up twice in three runs; the folder named from the root is taken.
    [ADR-013, P3]"""

    (tmp_path / "docs").mkdir()
    (tmp_path / "web" / "src").mkdir(parents=True)
    (tmp_path / "docs" / "src").mkdir()
    toolset = await open_standard_toolset(cwd=tmp_path / "docs", workspace_root=tmp_path)
    try:
        sibling = await toolset.execute("move", {"path": "web"})
        await toolset.execute("move", {"path": str(tmp_path / "docs")})
        nearest = await toolset.execute("move", {"path": "src"})
        missing = await toolset.execute("move", {"path": "nowhere"})
    finally:
        await toolset.close()

    assert sibling.success and sibling.content == f"Moved to {(tmp_path / 'web').resolve()}."
    assert nearest.success
    assert nearest.content == f"Moved to {(tmp_path / 'docs' / 'src').resolve()}."
    assert not missing.success


def test_the_harness_repository_offers_its_own_skill_where_skills_are_found() -> None:
    """M3W5B FL-069/FL-190 FAIL (F158): asked for the nocturne-plugin-contributor skill in the
    harness repository, the agent could not load it; skills/ is not an upstream library path,
    so .agents/skills points at it (the adopted capability's path, whole)."""

    libraries = discover_skill_libraries(ROOT)
    assert (ROOT / "skills").resolve() in libraries
    assert "nocturne-plugin-contributor" in {skill.id for skill in adopted_skills(libraries)}


@pytest.mark.asyncio
async def test_paths_named_from_the_root_work_from_a_subfolder_and_misses_say_so(
    tmp_path: Path,
) -> None:
    """M3CL2 walk of M3W5B-01..04 on gpt-4.1-mini: standing in tests/, the agent named
    tests/test_onboarding.py from the root; grep answered 'No matches found.' and edits were
    sent to tests/tests/, so the new test never landed. Exercised refusals: "No file or folder
    {target}."; "oldText found {count} times ... (lines ...); include a neighboring line, or to
    add to the end use {ending!r}". [ADR-013, P3]"""

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_doctor.py").write_text("def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")
    toolset = await open_standard_toolset(cwd=tests, workspace_root=tmp_path)
    try:
        found = await toolset.execute(
            "grep", {"pattern": "def test_", "path": "tests/test_doctor.py"}
        )
        missing = await toolset.execute("grep", {"pattern": "x", "path": "tests/nowhere.py"})
        ambiguous = await toolset.execute(
            "edit",
            {"path": "tests/test_doctor.py", "edits": [{"oldText": "    pass\n", "newText": ""}]},
        )
        appended = await toolset.execute(
            "edit",
            {
                "path": "tests/test_doctor.py",
                "edits": [
                    {
                        "oldText": "def test_b():\n    pass\n",
                        "newText": "def test_b():\n    pass\n\n\ndef test_c():\n    pass\n",
                    }
                ],
            },
        )
        created = await toolset.execute(
            "write", {"path": "tests/test_new.py", "content": "def test_new():\n    pass\n"}
        )
    finally:
        await toolset.close()

    assert found.success and "def test_b" in found.content
    assert not missing.success
    assert missing.content == f"No file or folder {(tests / 'nowhere.py').resolve()}."
    assert not ambiguous.success and "found 2 times" in ambiguous.content
    assert (
        "(lines 2, 6); include a neighboring line, or to add to the end use "
        "'def test_b():\\n    pass'" in ambiguous.content
    )
    assert appended.success and "def test_c" in (tests / "test_doctor.py").read_text()
    assert created.success and (tests / "test_new.py").is_file()
    assert not (tests / "tests").exists()


@pytest.mark.asyncio
async def test_an_edit_that_stops_a_python_file_parsing_is_refused(tmp_path: Path) -> None:
    """M3CL2 walk on gpt-4.1-mini: an anchor ending inside a call put the new test in the middle
    of an existing one, and the agent then blamed "leftover code" for the break. [ADR-015]"""

    source = "def test_a():\n    assert run(\n        1,\n    ) == 2\n"
    (tmp_path / "test_a.py").write_text(source)
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        inside = await toolset.execute(
            "edit",
            {
                "path": "test_a.py",
                "edits": [
                    {"oldText": "        1,\n", "newText": "        1,\n\n\ndef test_b():\n"}
                ],
            },
        )
        written = await toolset.execute("write", {"path": "test_a.py", "content": source[:-9]})
    finally:
        await toolset.close()

    assert not inside.success and not written.success
    with pytest.raises(SyntaxError) as broken:
        ast.parse(source.replace("        1,\n", "        1,\n\n\ndef test_b():\n"))
    assert inside.content == (
        f"Refused: after this change test_a.py would not parse as Python ({broken.value.msg}, "
        f"line {broken.value.lineno}); the file is unchanged. Make oldText whole lines that end "
        "a statement, so newText does not land inside one."
    )
    assert (tmp_path / "test_a.py").read_text() == source


@pytest.mark.asyncio
async def test_a_file_search_ignores_its_glob_and_a_missed_anchor_names_the_closest_line(
    tmp_path: Path,
) -> None:
    """M3CL2 walk (gpt-4.1-mini): grep of one file with glob '*.py' answered 'No matches found.'
    and an anchor recalled with one word wrong answered 'found 0 times', after which the agent
    wrote a second test file and reported the edit made. Exercised refusal: "...; the closest
    line is {n}: {line!r}. Read the lines you mean to change and copy them exactly".
    [ADR-013, ADR-015]"""

    (tmp_path / "doctor.py").write_text("def test_doctor_reports_breaker():\n    pass\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        found = await toolset.execute(
            "grep", {"pattern": "def test_doctor", "path": "doctor.py", "glob": "*.py"}
        )
        missed = await toolset.execute(
            "edit",
            {
                "path": "doctor.py",
                "edits": [{"oldText": "def test_doctor_reports_breakers():", "newText": "x"}],
            },
        )
    finally:
        await toolset.close()

    assert found.success and "def test_doctor_reports_breaker" in found.content
    assert not missed.success
    assert "the closest line is 1: 'def test_doctor_reports_breaker():'" in missed.content
    assert missed.content.endswith("Read the lines you mean to change and copy them exactly")


@pytest.mark.asyncio
async def test_a_chained_git_commit_works_and_the_context_states_the_repository(
    tmp_path: Path,
) -> None:
    """M3CL2 walk: the default model ran `cd <repo> && git add … && git commit` from tests/ and
    the exception, which matched only commands starting with git, refused .git/index.lock; the
    workspace context now also states the last commit and what is uncommitted. [ADR-013, P3]"""
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    import subprocess

    repository = tmp_path / "repo"
    sub = repository / "tests"
    sub.mkdir(parents=True)
    for command in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t"]):
        subprocess.run(["git", "-C", str(repository), *command], check=True)
    (sub / "test_a.py").write_text("x = 1\n")
    toolset = await open_standard_toolset(cwd=sub, workspace_root=repository)
    try:
        chained = await toolset.execute(
            "bash", {"command": f"cd {repository} && git add tests/test_a.py && git commit -qm add"}
        )
        pathspec = await toolset.execute("bash", {"command": "git add tests/test_a.py"})
        (sub / "stray.py").write_text("y = 2\n")
        context = render_workspace_context(toolset.location())
    finally:
        await toolset.close()

    assert chained.success and "exit code" not in chained.content.lower()
    assert f"tests/test_a.py is in the repository root {repository.resolve()}" in pathspec.content
    assert "Repository now: last commit " in context
    assert " add (tests/test_a.py); uncommitted: ?? tests/stray.py." in context


@pytest.mark.asyncio
async def test_a_command_written_from_the_root_names_where_its_path_is(tmp_path: Path) -> None:
    """INCIDENT M3W5B-02, walked again in M3CL2: from tests/, the user's
    `.venv/bin/python -m pytest tests/...` answered 'no such file', and gpt-4.1-mini built a venv
    in tests/ and reported pytest missing; the result now names the root and the command.
    [ADR-013, P3]"""
    if not Path("/usr/bin/sandbox-exec").is_file():
        pytest.skip("the standing hard shell fence is macOS sandbox-exec")
    binary = tmp_path / ".venv" / "bin"
    binary.mkdir(parents=True)
    (binary / "python").write_text("#!/bin/sh\necho project-python\n")
    (binary / "python").chmod(0o755)
    (tmp_path / "tests").mkdir()
    toolset = await open_standard_toolset(cwd=tmp_path / "tests", workspace_root=tmp_path)
    try:
        missed = await toolset.execute("bash", {"command": ".venv/bin/python -m pytest"})
        probed = await toolset.execute("bash", {"command": "ls -d .venv"})
        rerun = await toolset.execute(
            "bash", {"command": f"cd {tmp_path.resolve()} && .venv/bin/python -m pytest"}
        )
    finally:
        await toolset.close()

    assert f".venv/bin/python is in the repository root {tmp_path.resolve()}" in missed.content
    assert f"cd {tmp_path.resolve()} && .venv/bin/python -m pytest" in missed.content
    assert rerun.success and "project-python" in rerun.content
    # The M3CL2 move re-walk: `ls -d web` from docs/ prints the path before the error.
    assert f".venv is in the repository root {tmp_path.resolve()}" in probed.content


@pytest.mark.asyncio
async def test_a_read_from_offset_zero_starts_at_the_first_line(tmp_path: Path) -> None:
    """M3CL2 walk: offset 0 became upstream offset -1 and returned only the file's last line
    with 'Use offset=-1 to continue', and gpt-4.1-mini read one file 27 times. [ADR-013]"""

    (tmp_path / "note.txt").write_text("first\nsecond\nthird\n")
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        read = await toolset.execute("read", {"path": "note.txt", "offset": 0, "limit": 2})
    finally:
        await toolset.close()

    assert read.success and "1\tfirst" in read.content and "2\tsecond" in read.content
    assert "offset=-1" not in read.content


@pytest.mark.asyncio
async def test_the_refusal_names_a_unique_ending_to_add_after(tmp_path: Path) -> None:
    """M3CL2 walk: the refusal named the last line, "    )", which appeared 94 times in the
    test file, and the next edit was refused as ambiguous; the anchor is now unique. [ADR-015]"""

    body = "".join(f"def test_{n}():\n    call(\n        {n},\n    )\n\n\n" for n in range(30))
    (tmp_path / "test_many.py").write_text(body)
    toolset = await open_standard_toolset(cwd=tmp_path, workspace_root=tmp_path)
    try:
        refused = await toolset.execute("write", {"path": "test_many.py", "content": "x = 1\n"})
        anchor = "        29,\n    )"
        appended = await toolset.execute(
            "edit",
            {
                "path": "test_many.py",
                "edits": [
                    {"oldText": anchor, "newText": anchor + "\n\n\ndef test_new():\n    pass"}
                ],
            },
        )
    finally:
        await toolset.close()

    assert refused.content.endswith(
        f"% of test_many.py ({body.count(chr(10))} lines). Change only what the request needs "
        "with edit; the whole file is replaced only when the user's request says replace. To add "
        f"to the end, edit with oldText set to its last lines, {anchor!r}, and newText set to "
        "those lines followed by what you add."
    )
    assert appended.success and (tmp_path / "test_many.py").read_text().count("def test_") == 31
