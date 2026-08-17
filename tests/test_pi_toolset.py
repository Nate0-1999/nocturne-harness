from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from harness.toolset import ToolsetProtocolError, open_standard_toolset

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
