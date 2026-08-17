from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness.toolset import ToolsetProtocolError, ToolsetUnavailableError, open_standard_toolset

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src" / "harness" / "_pi"
PACKAGE = "@earendil-works/pi-coding-agent"

_FAKE_RPC = r"""
import json
import sys

for line in sys.stdin.buffer:
    request = json.loads(line)
    if request.get("type") != "get_state":
        continue
    print(json.dumps({
        "id": request["id"],
        "type": "response",
        "command": "get_state",
        "success": True,
        "data": {
            "isStreaming": False,
            "isCompacting": False,
            "autoCompactionEnabled": True,
            "messageCount": 0,
            "pendingMessageCount": 0,
        },
    }), flush=True)
"""

_FAKE_LOCATION_RPC = r"""
import json
import os
import sys

identity = {
    "agent_id": os.environ["NOCTURNE_AGENT_ID"],
    "machine_id": os.environ["NOCTURNE_MACHINE_ID"],
    "session_id": os.environ["NOCTURNE_SESSION_ID"],
}

def presence(event, path):
    print(json.dumps({
        "type": "extension_ui_request",
        "id": f"presence-{event}",
        "method": "setStatus",
        "statusKey": "nocturne-presence",
        "statusText": json.dumps({
            **identity,
            "event": event,
            "path": path,
            "ts": "2026-08-17T12:00:00Z",
        }),
    }), flush=True)

presence("spawn", os.environ["NOCTURNE_INITIAL_LOCATION"])
for line in sys.stdin.buffer:
    request = json.loads(line)
    if request.get("type") == "get_state":
        print(json.dumps({
            "id": request["id"],
            "type": "response",
            "command": "get_state",
            "success": True,
            "data": {
                "isStreaming": False,
                "isCompacting": False,
                "autoCompactionEnabled": True,
                "messageCount": 0,
                "pendingMessageCount": 0,
            },
        }), flush=True)
    elif request.get("type") == "prompt":
        target = json.loads(request["message"].removeprefix("/nocturne-move "))
        presence("cwd_change", target)
        print(json.dumps({
            "id": request["id"],
            "type": "response",
            "command": "prompt",
            "success": True,
        }), flush=True)
"""


@pytest.mark.asyncio
async def test_standard_toolset_state_crosses_only_the_owned_seam(tmp_path: Path) -> None:
    """ADR-013 keeps PI's process protocol behind Nocturne's typed toolset seam."""
    toolset = await open_standard_toolset(
        command=(sys.executable, "-c", _FAKE_RPC),
        cwd=tmp_path,
    )
    try:
        state = await toolset.state()
    finally:
        await toolset.close()

    assert not state.is_streaming
    assert not state.is_compacting
    assert state.auto_compaction_enabled
    assert state.message_count == 0
    assert state.pending_message_count == 0


@pytest.mark.asyncio
async def test_standard_toolset_rejects_malformed_upstream_state(tmp_path: Path) -> None:
    """Invariant 14 makes a malformed adopted-tool response a wall, never a guess."""
    bad_rpc = _FAKE_RPC.replace('"messageCount": 0', '"messageCount": "zero"')
    toolset = await open_standard_toolset(
        command=(sys.executable, "-c", bad_rpc),
        cwd=tmp_path,
    )
    try:
        with pytest.raises(ToolsetProtocolError, match="invalid get_state"):
            await toolset.state()
    finally:
        await toolset.close()


@pytest.mark.asyncio
async def test_standard_toolset_rejects_clean_eof_while_request_is_pending(
    tmp_path: Path,
) -> None:
    """Invariant 14 makes a vanished PI process unavailable, never a guessed timeout."""
    toolset = await open_standard_toolset(
        command=(sys.executable, "-c", "pass"),
        cwd=tmp_path,
        timeout_seconds=1.0,
    )
    try:
        with pytest.raises(ToolsetUnavailableError, match="ended unexpectedly"):
            await toolset.state()
    finally:
        await toolset.close()


@pytest.mark.asyncio
async def test_location_state_is_defined_and_moves_only_inside_workspace(tmp_path: Path) -> None:
    """ADR-010 and ADR-006 make movement an explicit, identity-bearing event."""
    child = tmp_path / "child"
    child.mkdir()
    events = []
    toolset = await open_standard_toolset(
        command=(sys.executable, "-c", _FAKE_LOCATION_RPC),
        cwd=tmp_path,
        workspace_root=tmp_path,
        agent_id="agent-location",
        machine_id="machine-location",
        session_id="session-location",
        presence_sink=events.append,
    )
    try:
        await toolset.state()
        assert toolset.location().cwd == tmp_path.resolve()
        moved = await toolset.move(Path("child"))
        journal = toolset.presence_events()
    finally:
        await toolset.close()

    assert moved.cwd == child.resolve()
    assert journal == tuple(events)
    assert [(event.event, event.path) for event in events] == [
        ("spawn", tmp_path.resolve()),
        ("cwd_change", child.resolve()),
    ]
    assert all(event.agent_id == "agent-location" for event in events)


def test_location_fence_blocks_outside_writes_and_symlink_escapes(tmp_path: Path) -> None:
    """SPEC D.2 103 makes the location subtree a deterministic tool-layer fence."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the adopted PI location adapter")
    current = tmp_path / "current"
    sibling = tmp_path / "sibling"
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    current.mkdir()
    sibling.mkdir()
    outside.mkdir()
    (current / "escape").symlink_to(outside, target_is_directory=True)
    module_uri = (RUNTIME / "location_fence.mjs").as_uri()
    script = f"""
import {{ LocationFence }} from {json.dumps(module_uri)};
const root = {json.dumps(str(tmp_path))};
const current = {json.dumps(str(current))};
const sibling = {json.dumps(str(sibling))};
const fence = new LocationFence({{ workspaceRoot: root, initialLocation: current }});
await fence.initialize();
const local = {{ path: "nested/file.txt" }};
const localResult = await fence.preflight("write", local);
if (localResult.block || !local.path.endsWith("nested/file.txt")) process.exit(10);
const outsideWrite = await fence.preflight("write", {{ path: sibling + "/file.txt" }});
if (!outsideWrite.block || !outsideWrite.reason.includes("Move to")) process.exit(11);
const symlinkWrite = await fence.preflight("write", {{ path: "escape/file.txt" }});
if (!symlinkWrite.block) process.exit(12);
const outsideRead = await fence.preflight("read", {{ path: sibling + "/note.txt" }});
if (outsideRead.block) process.exit(13);
await fence.move(sibling);
const afterMove = await fence.preflight("edit", {{ path: "file.txt" }});
if (afterMove.block) process.exit(14);
const strict = new LocationFence({{
  workspaceRoot: root,
  initialLocation: current,
  fenceReads: true,
}});
const strictRead = await strict.preflight("read", {{ path: sibling + "/note.txt" }});
if (!strictRead.block) process.exit(15);
"""
    subprocess.run([node, "--input-type=module", "-e", script], check=True)


def test_pi_dependency_receipt_and_lock_are_exact() -> None:
    """P4 and ADR-013 pin the adopted whole toolset, provenance, and MIT notice."""
    package = json.loads((RUNTIME / "package.json").read_text(encoding="utf-8"))
    receipt = json.loads((RUNTIME / "dependency.json").read_text(encoding="utf-8"))
    lock = json.loads((RUNTIME / "package-lock.json").read_text(encoding="utf-8"))
    notice = (RUNTIME / "LICENSE.upstream").read_bytes()

    assert package["dependencies"] == {PACKAGE: "0.84.2"}
    assert receipt["version"] == "0.84.2"
    assert receipt["source_repository"] == "https://github.com/earendil-works/pi"
    assert receipt["source_commit"] == receipt["npm_git_head"]
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    pinned = lock["packages"][f"node_modules/{PACKAGE}"]
    assert pinned["version"] == receipt["version"]
    assert pinned["integrity"] == receipt["artifact_integrity"]
    assert hashlib.sha256(notice).hexdigest() == receipt["license_sha256"]
    assert b"MIT License" in notice


def test_pi_protocol_has_one_import_fence() -> None:
    """ADR-013 keeps all PI protocol knowledge inside exactly one adapter module."""
    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "harness").glob("*.py")):
        if path.name in {"pi_toolset_adapter.py", "toolset.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "pi_toolset_adapter" in text or '"--mode", "rpc"' in text:
            offenders.append(path.name)
    assert offenders == []


def test_pi_activation_has_no_unfenced_shell_escape() -> None:
    """SPEC D.2 103 keeps unfenced shell mutation outside the active PI tool set."""
    extension = (RUNTIME / "nocturne_location.mjs").read_text(encoding="utf-8")
    active_tools = extension.split("const ACTIVE_TOOLS =", 1)[1].split(";", 1)[0]

    assert '"bash"' not in active_tools
    assert all(f'"{name}"' in active_tools for name in ("read", "edit", "write", "move"))
