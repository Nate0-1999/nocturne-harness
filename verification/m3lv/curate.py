"""M3LV walk: start one manual curator pass on the scratch home's selected test Palace and print
its receipt counts.

Runs with the harness's own config loader (NOCTURNE_HOME must name the scratch home); no
credential is printed.
"""

import json
import sys
import urllib.error
import urllib.request

from harness.onboarding import load_config

config = load_config()
assert config.principal_id and "test-m3lv" in str(config.home), config.home
request = urllib.request.Request(
    f"{config.spine_url.rstrip('/')}/v1/curation/runs",
    data=json.dumps(
        {"principal_id": config.principal_id, "machine_id": config.machine_id}
    ).encode(),
    headers={"Authorization": f"Bearer {config.spine_token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=600) as response:
        receipt = json.loads(response.read())
except urllib.error.HTTPError as error:
    print(json.dumps({"status": error.code, "detail": error.read().decode()[:300]}))
    sys.exit(1)
print(
    json.dumps(
        {
            key: receipt.get(key)
            for key in (
                "run_uid",
                "status",
                "verdict_count",
                "queued_count",
                "executed_count",
                "admitted_writes_snapshot",
            )
        }
    )
)
