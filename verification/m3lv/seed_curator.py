"""M3LV walk: give a real curator pass work on the test Palace (M3VL's palace_seed.py precedent) — memories filed
under a single keyword and one fact filed twice under different subjects. Written through the Palace API with
force=True (the save door refuses near-duplicates); receipts go to stdout. No credential is printed.

usage: NOCTURNE_HOME=<scratch home> python seed_curator.py <tag>
"""

import asyncio
import json
import sys

from harness.onboarding import load_config
from harness.spine_client import CreateMemoryConflictError, CreateMemoryRequest, SpineClient

TAG = sys.argv[1]
config = load_config()
assert "test-m3lv" in str(config.home), config.home
FACTS = [
    (["lighthouse"], f"{TAG}: the M3LV lighthouse lamp is trimmed every Thursday"),
    (["orchard"], f"{TAG}: the M3LV orchard ladder is stored in the north shed"),
    (["harbour", "tides"], f"{TAG}: the M3LV harbour gate closes two hours before high tide"),
    (["tides", "harbour"], f"{TAG}: two hours before high tide the M3LV harbour gate is closed"),
]


async def main() -> None:
    async with SpineClient(config.spine_url, config.spine_token, principal_id=config.principal_id) as palace:
        for keywords, fact in FACTS:
            try:
                response = await palace.create_memory(CreateMemoryRequest(
                    principal_id=config.principal_id, label=fact[:60], body=f"{fact}.", kind="fact",
                    keywords=keywords, project_key=None, editor="m3lv-verification",
                    machine_id=config.machine_id, force=True))
                print(json.dumps(response.model_dump(mode="json"))[:160])
            except CreateMemoryConflictError:  # the Palace reinforces a hard duplicate instead
                print(json.dumps({"conflict": fact}))


asyncio.run(main())
