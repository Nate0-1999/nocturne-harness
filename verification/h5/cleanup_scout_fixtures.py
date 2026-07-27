"""Tombstone only the exact H5 Scout fixtures created on 2026-07-27."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from harness.config import HarnessSettings
from harness.spine_client import (
    ListMemoriesParams,
    MemoryStatus,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
    SpineClient,
)

EXPECTED_MACHINE_ID = "h5-sop-verification"
EXPECTED_FIXTURES = {
    UUID("3454c5ef-b651-4576-8bac-23913ea1b903"): ("Scout-calibration-chartreuse-signal-alpha"),
    UUID("f475a273-28de-46dc-a989-4bd1a8622d67"): ("Scout calibration animal is a marmot"),
    UUID("6c2ff7a9-bb9f-4bbe-acf4-4558ccea8e81"): "Scout86afGamma",
    UUID("d36040b7-abee-4aca-99cd-df0199bffc8f"): ("Unicode round-trip fixture for Scout86af"),
    UUID("a0fd9cdd-c627-48c4-a5d4-c2cef8150711"): ("Project mascot: ibis (tag: Scout86afProject)"),
    UUID("ef8e37fc-8971-4a7d-82e8-71111eaee085"): "Orchid731BasilLocation",
    UUID("18b00cc0-6611-4a16-ab53-589a8184025e"): ("Cello practice tempo 92 BPM"),
    UUID("c59d5c5e-a67d-413f-aab7-a68e1b70bdc2"): "Gallery205 definition",
    UUID("a45f9e95-ad54-4365-8a4c-f72032a5e34f"): ("Cobalt theme for technical diagrams"),
    UUID("b4a67596-df67-40de-b611-b4991fb9909b"): ("Desk lighting color temperature"),
    UUID("de185afa-0cd0-43f5-87a9-1ef683730e07"): "Export642-CSV-Dates",
    UUID("b593a5ca-3ea9-417b-9f85-2839fac5bafc"): ("Soup357: Omit Cilantro"),
    UUID("c9117760-74c7-4d1d-9f67-cdde1cefc0cc"): "Rowing Tuesdays",
    UUID("ca08cdc1-907c-407b-8c95-a05e1aacba2a"): ("Saturday Kenyan peaberry coffee ritual"),
}


async def _inventory(client: SpineClient) -> dict[UUID, object]:
    found: dict[UUID, object] = {}
    offset = 0
    while True:
        page = await client.list_memories(ListMemoriesParams(limit=200, offset=offset))
        for item in page.items:
            if item.memory_id in EXPECTED_FIXTURES:
                found[item.memory_id] = item
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return found


async def main() -> None:
    settings = HarnessSettings()
    if settings.machine_id != EXPECTED_MACHINE_ID:
        raise SystemExit(
            f"refusing cleanup under machine_id={settings.machine_id!r}; "
            f"expected {EXPECTED_MACHINE_ID!r}"
        )
    if settings.spine_token is None:
        raise SystemExit("SPINE_TOKEN is not configured")

    results: list[dict[str, object]] = []
    async with SpineClient(
        settings.spine_url,
        settings.spine_token.get_secret_value(),
    ) as client:
        inventory = await _inventory(client)
        missing = sorted(
            str(memory_id) for memory_id in EXPECTED_FIXTURES.keys() - inventory.keys()
        )
        if missing:
            raise RuntimeError(f"cleanup allowlist is missing from Spine: {missing}")

        for memory_id, expected_label in EXPECTED_FIXTURES.items():
            original = inventory[memory_id]
            if original.principal_id != settings.principal_id:
                raise RuntimeError(f"principal mismatch for {memory_id}: {original.principal_id!r}")
            if original.label != expected_label:
                raise RuntimeError(f"label mismatch for {memory_id}: {original.label!r}")

            current = original
            for _ in range(3):
                if (
                    current.memory_id != memory_id
                    or current.principal_id != settings.principal_id
                    or current.label != expected_label
                ):
                    raise RuntimeError(f"cleanup target identity drifted: {memory_id}")
                if current.status == MemoryStatus.TOMBSTONED:
                    break
                try:
                    current = await client.patch_memory(
                        memory_id,
                        PatchMemoryRequest(
                            expected_revision=current.revision,
                            status=MemoryStatus.TOMBSTONED,
                            editor="verification:h5-scout",
                            reason=("H5 Scout cleanup: exact fixture ID from 2026-07-27 live SOP"),
                            machine_id=settings.machine_id,
                        ),
                    )
                    break
                except PatchMemoryConflictError as exc:
                    if not isinstance(exc.conflict, RevisionConflict):
                        raise
                    current = exc.conflict.conflict
            else:
                raise RuntimeError(f"CAS retries exhausted for {memory_id}")

            results.append(
                {
                    "memory_id": str(current.memory_id),
                    "label": current.label,
                    "principal_id": current.principal_id,
                    "revision": current.revision,
                    "status": current.status.value,
                }
            )

    print(
        json.dumps(
            {
                "machine_id": settings.machine_id,
                "principal_id": settings.principal_id,
                "fixture_count": len(results),
                "all_tombstoned": all(
                    result["status"] == MemoryStatus.TOMBSTONED.value for result in results
                ),
                "fixtures": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
