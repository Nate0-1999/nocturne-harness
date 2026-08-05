"""A-044 repeated-query memory bound for the real daemon HTTP path."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from vitals_fixture import vitals_payload  # noqa: E402

from harness.daemon import create_app  # noqa: E402
from harness.resources import ResourceWatch, current_rss_bytes  # noqa: E402
from harness.spine_client import VitalsSnapshot  # noqa: E402

WARM_UP_QUERIES = 500
SOAK_QUERIES = 10_000
SAMPLE_EVERY = 250
MAX_GROWTH_BYTES = 32 * 1024**2


def _required_rss() -> int:
    value = current_rss_bytes()
    if value is None:
        raise RuntimeError("current RSS is unavailable on this host")
    return value


def main() -> None:
    with TemporaryDirectory(prefix="nocturne-resource-soak-") as directory:
        home = Path(directory)
        base = VitalsSnapshot.model_validate(vitals_payload())
        watch = ResourceWatch(home)

        async def read_vitals() -> VitalsSnapshot:
            return base.model_copy(
                update={"resources": watch.snapshot(base.resources.database_bytes)}
            )

        with TestClient(create_app(vitals_snapshot_reader=read_vitals)) as client:
            for _ in range(WARM_UP_QUERIES):
                response = client.get("/v1/rack/query?resource=vitals&as_of=now")
                response.raise_for_status()

            baseline = _required_rss()
            samples = [baseline]
            for index in range(1, SOAK_QUERIES + 1):
                response = client.get("/v1/rack/query?resource=vitals&as_of=now")
                response.raise_for_status()
                if index % SAMPLE_EVERY == 0:
                    samples.append(_required_rss())
            final = _required_rss()

    peak_growth = max(samples) - baseline
    final_growth = final - baseline
    result = {
        "warm_up_queries": WARM_UP_QUERIES,
        "soak_queries": SOAK_QUERIES,
        "sample_every": SAMPLE_EVERY,
        "baseline_rss_bytes": baseline,
        "peak_rss_growth_bytes": peak_growth,
        "final_rss_growth_bytes": final_growth,
        "maximum_growth_bytes": MAX_GROWTH_BYTES,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if peak_growth > MAX_GROWTH_BYTES or final_growth > MAX_GROWTH_BYTES:
        raise SystemExit("resource soak exceeded the A-044 RSS growth bound")


if __name__ == "__main__":
    main()
