import asyncio
import json
import sys
import urllib.request
from pathlib import Path

from harness.onboarding import load_config
from harness.spine_client import SpineClient

home = Path("/Users/nateoswalt/relay/m8mf/walk/home")
c = load_config(home=home)


async def pin():
    async with SpineClient(base_url="http://127.0.0.1:8186", token=c.spine_token) as client:
        policy = await client.curator_model_policy(
            c.principal_id, "pinned:openrouter:openai/gpt-4.1-mini"
        )
        print(json.dumps({"curator_policy": policy}))


if len(sys.argv) > 1 and sys.argv[1] == "pin":
    asyncio.run(pin())
key = c.process_environment()["OPENROUTER_API_KEY"]
req = urllib.request.Request(
    "https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key}
)
d = json.load(urllib.request.urlopen(req))["data"]
values = {k: d.get(k) for k in ("usage", "usage_daily", "usage_monthly", "limit_remaining")}
p = home.parent / "spend-start.json"
if not p.exists():
    p.write_text(json.dumps(values, indent=2))
values["delta"] = values["usage"] - json.loads(p.read_text())["usage"]
print(json.dumps(values))
if values["delta"] >= 1:
    sys.exit(2)
