"""M3EX-18 live check on the TEST palace: delete one seeded memory, then restore it."""
import asyncio, json
from harness.onboarding import load_config
from harness.spine_client import SpineClient, PatchMemoryRequest, MemoryStatus, ListMemoriesParams

async def main():
    config = load_config()
    assert config.palace_name == "test-m3exf", config.palace_name
    client = SpineClient(config.spine_url, config.spine_token, principal_id=config.principal_id)
    page = await client.list_memories(ListMemoriesParams(status=None, limit=200, offset=0))
    target = next(m for m in page.items if m.label == "Release order")
    steps = [{"step": "start", "status": target.status.value, "revision": target.revision}]
    deleted = await client.patch_memory(target.memory_id, PatchMemoryRequest(
        expected_revision=target.revision, status=MemoryStatus.TOMBSTONED, editor="user",
        reason="panel/delete/should_never_have_been_saved", machine_id=config.machine_id))
    steps.append({"step": "delete", "status": deleted.status.value, "revision": deleted.revision})
    restored = await client.patch_memory(target.memory_id, PatchMemoryRequest(
        expected_revision=deleted.revision, status=MemoryStatus.ACTIVE, editor="user",
        reason="panel/restore", machine_id=config.machine_id))
    steps.append({"step": "restore", "status": restored.status.value, "revision": restored.revision})
    print(json.dumps({"memory_label": target.label, "steps": steps}, indent=1))

asyncio.run(main())
