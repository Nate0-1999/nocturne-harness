"""M3EX-17: which delete reason did the Palace record for 'Commit style'? (TEST palace export)"""
import asyncio, json
import httpx
from harness.onboarding import load_config

async def main():
    config = load_config()
    assert config.palace_name == "test-m3exf", config.palace_name
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.get(f"{config.spine_url}/v1/memories/export", params={"principal_id": config.principal_id},
                                  headers={"Authorization": f"Bearer {config.spine_token}"})
    archive = response.json()
    head = next(m for m in archive["memories"] if m.get("label") == "Commit style")
    found = []
    def walk(value):
        if isinstance(value, dict):
            if value.get("memory_id") == head["id"] and "reason" in value:
                found.append({k: value.get(k) for k in ("revision", "reason", "status")})
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(archive)
    print(json.dumps({"label": head["label"], "status": head.get("status"), "revisions": found}, indent=1))

asyncio.run(main())
