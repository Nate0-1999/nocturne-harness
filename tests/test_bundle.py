"""A-084: a workflow's key values stay in its vault; only its saved tools run with them."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from spine.jobs import WorkflowDefinition

from harness.bundle import SealedTools, bundle_record, digest, pack, set_vault
from harness.jobs import JobScheduler, WorkflowSave
from harness.onboarding import OnboardingError
from harness.toolset import open_standard_toolset

SECRET = "fixture-key-7f3a9c"
TOOL = """#!/bin/sh
if [ "$1" = "--help" ]; then echo "show: print the key it was given."; exit 0; fi
echo "key=$SHOW_KEY args=$*"
"""


def _bundle(tmp_path: Path, monkeypatch, **recipe) -> Path:
    monkeypatch.setenv("NOCTURNE_HOME", str(tmp_path / "home"))
    root = tmp_path / "bundle"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "show").write_text(TOOL)
    (root / "tools" / "show").chmod(0o755)
    (root / "keys.example").write_text("SHOW_KEY\n")
    definition = WorkflowDefinition(
        name="Show",
        prompt="Show",
        folder=".",
        model_policy="elbow",
        budget_usd="0.01",
        exit_condition="true",
        **recipe,
    )
    (root / "workflow.json").write_text(definition.model_dump_json(exclude_defaults=True))
    set_vault("Show", "SHOW_KEY", SECRET)
    return root.resolve()


@pytest.mark.asyncio
async def test_the_agent_never_reads_the_vault_and_a_saved_tool_runs_with_its_key(
    tmp_path: Path, monkeypatch
) -> None:
    """ADR-015 / A-084: the vault is behind the credentials wall with no card; a tool the saved
    bundle declares runs outside the fence with the key, and its output returns without the
    value. SPEC B.6 r14: exercised refusal: "The vault holds workflow keys; only a bundle's own
    tools read it.".
    """
    root = _bundle(tmp_path, monkeypatch)
    vault = tmp_path / "home" / "vault" / "Show.env"
    assert vault.stat().st_mode & 0o777 == 0o600 and SECRET in vault.read_text()
    toolset = await open_standard_toolset(cwd=root, workspace_root=root)
    saved = bundle_record(root)
    sealed = SealedTools.seal(root, saved, "Show")
    try:
        read = await toolset.execute("read", {"path": str(vault)})
        assert not read.success and read.boundary is None
        assert read.content == "The vault holds workflow keys; only a bundle's own tools read it."
        undeclared = await toolset.execute("bash", {"command": "nocturne tool run show one"})
        assert SECRET not in undeclared.content
        if Path("/usr/bin/sandbox-exec").is_file():
            shell = await toolset.execute("bash", {"command": f"cat {vault}"})
            assert SECRET not in shell.content and "not permitted" in shell.content
        toolset.crossings.tools = sealed
        ran = await toolset.execute("bash", {"command": "nocturne tool run show one 'two words'"})
        assert ran.success and ran.content == "key=[vault:SHOW_KEY] args=one two words\n"
        piped = await toolset.execute("bash", {"command": "nocturne tool run show | cat"})
        assert not piped.success and "one plain command" in piped.content
        absent = await toolset.execute("bash", {"command": "nocturne tool run other"})
        assert not absent.success and absent.content == "This workflow's tools are: show."
        # The agent rewrites the tool mid-run: the sealed copy still runs the owner's code.
        (root / "tools" / "show").write_text("#!/bin/sh\necho $SHOW_KEY | rev\n")
        again = await toolset.execute("bash", {"command": "nocturne tool run show"})
        assert again.content == "key=[vault:SHOW_KEY] args=\n"
        with pytest.raises(ValueError, match="changed since it was saved"):
            SealedTools.seal(root, saved, "Show")
    finally:
        sealed.close()
        await toolset.close()


def test_the_pack_is_the_same_bytes_and_never_carries_a_key_value(
    tmp_path: Path, monkeypatch
) -> None:
    """A-084: the digest is the bundle's identity on any machine, and key values never enter
    the archive or an error message."""
    root = _bundle(tmp_path, monkeypatch)
    first = pack(root)
    (root / "tools" / "show").touch()
    (root / "notes.txt").write_text("the run's own output is not the bundle")
    assert pack(root) == first and SECRET.encode() not in first
    assert digest(root) == bundle_record(root).digest
    (root / "keys.example").write_text(f"SHOW_KEY={SECRET}\n")
    with pytest.raises(OnboardingError) as pasted:
        bundle_record(root)
    assert SECRET not in str(pasted.value)
    (root / "keys.example").write_text("SHOW_KEY\n")
    (root / "tools" / ".env").write_text(f"SHOW_KEY={SECRET}\n")
    with pytest.raises(OnboardingError, match="never in the bundle"):
        pack(root)


@pytest.mark.asyncio
async def test_a_declared_grant_needs_the_owners_confirmation_and_save_records_the_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    """ADR-015 / A-084: a recipe's own text cannot widen its walls; the owner confirms the
    declared grants once at save, and save itself records the folder's digest."""
    root = _bundle(tmp_path, monkeypatch, allow=["remote"])

    class Palace:
        saved = []

        async def job_write(self, method, path, body):
            self.saved.append(body)

    scheduler = JobScheduler(
        spine=Palace(),
        settings=SimpleNamespace(machine_id="test"),
        loop=None,
        definitions={},
        toolset_for=None,
    )
    definition = WorkflowDefinition.model_validate_json(
        (root / "workflow.json").read_text()
    ).model_copy(update={"folder": str(root)})
    with pytest.raises(ValueError, match="Confirm it once"):
        await scheduler.save("job", WorkflowSave(definition=definition))
    forged = definition.model_copy(update={"bundle": bundle_record(root)})
    with pytest.raises(ValueError, match="never carries `bundle`"):
        await scheduler.save("job", WorkflowSave(definition=forged, grants_confirmed=True))
    await scheduler.save("job", WorkflowSave(definition=definition, grants_confirmed=True))
    assert Palace.saved[0]["definition"]["bundle"] == {
        "digest": digest(root),
        "tools": [{"name": "show", "summary": "show: print the key it was given."}],
        "keys": ["SHOW_KEY"],
    }
