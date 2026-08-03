"""Create and tombstone the exact disposable memories used by the M2G live SOP."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from harness.config import HarnessSettings
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryRequest,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    PatchMemoryRequest,
    SpineClient,
)

MANIFEST = Path(__file__).with_name("live-seeds.json")
PRINCIPAL_ID = "m2g-sop-verification"
MACHINE_ID = "m2g-sop-verification"
EDITOR = "verification:m2g"

SEEDS = (
    (
        "confirmed",
        "M2G live confirmed lock",
        "A memory explicitly accepted at the first gate stays locked into later message context.",
        True,
    ),
    (
        "ambient",
        "M2G live amber-orchid rule",
        "The amber-orchid rule says every ordinary message is rescored without reopening the gate.",
        False,
    ),
)


async def seed() -> None:
    if MANIFEST.exists():
        raise RuntimeError("live seed manifest already exists; clean it before reseeding")
    settings = HarnessSettings()
    if settings.spine_token is None:
        raise RuntimeError("SPINE_TOKEN is required")
    client = SpineClient(settings.spine_url, settings.spine_token.get_secret_value())
    records: list[dict[str, object]] = []
    try:
        for role, label, body, pin in SEEDS:
            result = await client.create_memory(
                CreateMemoryRequest(
                    principal_id=PRINCIPAL_ID,
                    label=label,
                    body=body,
                    kind=MemoryKind.PROJECT_NOTE,
                    keywords=["M2G", "amber-orchid", role],
                    origin_path="verification/m2g",
                    editor=EDITOR,
                    machine_id=MACHINE_ID,
                    force=True,
                )
            )
            if not isinstance(result, CreatedMemoryResponse):
                raise RuntimeError("forced M2G seed was not created")
            memory = result.created
            if pin:
                memory = await client.patch_memory(
                    memory.memory_id,
                    PatchMemoryRequest(
                        expected_revision=memory.revision,
                        pin=True,
                        editor=EDITOR,
                        reason="M2G live SOP: guarantee the first accepted card",
                        machine_id=MACHINE_ID,
                    ),
                )
            records.append(
                {
                    "role": role,
                    "memory_id": str(memory.memory_id),
                    "revision": memory.revision,
                }
            )
        MANIFEST.write_text(
            json.dumps({"principal_id": PRINCIPAL_ID, "records": records}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, "created": len(records)}))
    finally:
        await client.aclose()


async def cleanup() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    settings = HarnessSettings()
    if settings.spine_token is None:
        raise RuntimeError("SPINE_TOKEN is required")
    client = SpineClient(settings.spine_url, settings.spine_token.get_secret_value())
    try:
        active = await client.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200)
        )
        revisions = {str(memory.memory_id): memory.revision for memory in active.items}
        for record in payload["records"]:
            memory_id = record["memory_id"]
            revision = revisions.get(memory_id)
            if revision is None:
                continue
            await client.patch_memory(
                memory_id,
                PatchMemoryRequest(
                    expected_revision=revision,
                    status=MemoryStatus.TOMBSTONED,
                    editor=EDITOR,
                    reason="M2G live SOP cleanup: tombstone exact fixture ID",
                    machine_id=MACHINE_ID,
                ),
            )
        MANIFEST.unlink()
        print(json.dumps({"ok": True, "tombstoned": len(payload["records"])}))
    finally:
        await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "cleanup"))
    action = parser.parse_args().action
    asyncio.run(seed() if action == "seed" else cleanup())


if __name__ == "__main__":
    main()
