"""Put 'Commit style' back (TEST palace) so the after walk deletes the same memory."""

import asyncio

from harness.onboarding import load_config
from harness.spine_client import ListMemoriesParams, MemoryStatus, PatchMemoryRequest, SpineClient


async def main():
    config = load_config()
    assert config.palace_name == "test-m3exf"
    client = SpineClient(config.spine_url, config.spine_token, principal_id=config.principal_id)
    page = await client.list_memories(ListMemoriesParams(status=None, limit=200, offset=0))
    target = next(m for m in page.items if m.label == "Commit style")
    if target.status != MemoryStatus.ACTIVE:
        restored = await client.patch_memory(
            target.memory_id,
            PatchMemoryRequest(
                expected_revision=target.revision,
                status=MemoryStatus.ACTIVE,
                editor="user",
                reason="panel/restore",
                machine_id=config.machine_id,
            ),
        )
        print("restored", restored.revision)


asyncio.run(main())
