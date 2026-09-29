"""Tombstone the two seeded walk memories whose labels collide with M3EX-16's facts (TEST palace)."""
import asyncio
from harness.onboarding import load_config
from harness.spine_client import SpineClient, PatchMemoryRequest, MemoryStatus, ListMemoriesParams

async def main():
    config = load_config()
    assert config.palace_name == "test-m3exf"
    client = SpineClient(config.spine_url, config.spine_token, principal_id=config.principal_id)
    page = await client.list_memories(ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200, offset=0))
    for memory in page.items:
        if memory.label in {"Python test command", "Web UI test location"}:
            await client.patch_memory(memory.memory_id, PatchMemoryRequest(
                expected_revision=memory.revision, status=MemoryStatus.TOMBSTONED, editor="user",
                reason="panel/delete/no_longer_needed", machine_id=config.machine_id))
            print("tombstoned", memory.label)

asyncio.run(main())
