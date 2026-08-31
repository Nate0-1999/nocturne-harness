#!/usr/bin/env python3
"""Restore the four exact build-test lessons tombstoned after round one."""

from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID

from harness.spine_client import (
    ListMemoriesParams,
    MemoryStatus,
    PatchMemoryRequest,
    SpineClient,
)


PRINCIPAL_ID = "m3bt1-verification-20260821-bt21"
MACHINE_ID = "m3b3-sop-verification"
MEMORY_IDS = (
    UUID("d4695150-9fcb-40e4-80c1-c6a687e7f11d"),
    UUID("9ba18ac1-98e9-445a-9e2f-83044ac1741f"),
    UUID("e2a57cdd-adae-448f-aa47-483725f5643e"),
    UUID("ea5536d7-b502-4c8c-8f99-c15de23bb8f3"),
)


async def _all_by_status(client: SpineClient, status: MemoryStatus):
    items = []
    offset = 0
    while True:
        page = await client.list_memories(
            ListMemoriesParams(status=status, limit=200, offset=offset)
        )
        items.extend(page.items)
        offset += len(page.items)
        if offset >= page.total or not page.items:
            return items


async def main() -> None:
    spine_url = os.environ["SPINE_URL"]
    spine_token = os.environ["SPINE_TOKEN"]
    async with SpineClient(spine_url, spine_token) as client:
        tombstoned = {
            item.memory_id: item
            for item in await _all_by_status(client, MemoryStatus.TOMBSTONED)
        }
        active = {
            item.memory_id: item
            for item in await _all_by_status(client, MemoryStatus.ACTIVE)
        }
        result = []
        for memory_id in MEMORY_IDS:
            current = tombstoned.get(memory_id) or active.get(memory_id)
            if current is None:
                raise RuntimeError(f"experiment memory missing: {memory_id}")
            if current.principal_id != PRINCIPAL_ID:
                raise RuntimeError(f"principal mismatch for {memory_id}")
            before_status = current.status
            before_revision = current.revision
            if current.status is MemoryStatus.TOMBSTONED:
                current = await client.patch_memory(
                    memory_id,
                    PatchMemoryRequest(
                        expected_revision=current.revision,
                        status=MemoryStatus.ACTIVE,
                        editor="verification:m3b3",
                        reason=(
                            "M3B3 owner-fired continuity restoration: reverse the "
                            "round-one experiment cleanup mistake"
                        ),
                        machine_id=MACHINE_ID,
                    ),
                )
            result.append(
                {
                    "memory_id": str(memory_id),
                    "label": current.label,
                    "before_status": before_status.value,
                    "before_revision": before_revision,
                    "after_status": current.status.value,
                    "after_revision": current.revision,
                }
            )
    print(json.dumps({"principal_id": PRINCIPAL_ID, "memories": result}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
