# M2RR resurrection agent test

Authority: PLAN M2RR, P4, Garden A-057. This is a fixture-only mechanical proof;
it does not touch an owner's home, Palace, credentials, or Cloud resources.

## Tier 1 — code is disposable

DO: run

```sh
UV_CACHE_DIR=/tmp/n8-harness-uv uv run --locked --extra dev pytest -q \
  tests/test_transcript_sync.py::test_a057_exact_rows_restore_and_derive_the_catalog
```

EXPECT: PASS. The test creates a disposable journal, exports its exact lines,
reconstructs them under a separate fresh path, validates ordinary hydration,
and proves the restored catalog title comes from the journal.

## Tier 2 — fresh home reconnect

DO: run

```sh
UV_CACHE_DIR=/tmp/n8-harness-uv uv run --locked --extra dev pytest -q \
  tests/test_onboarding.py::test_a057_discovery_accepts_only_one_spine_service \
  tests/test_onboarding.py::test_a057_fresh_home_restores_palace_transcripts_before_daemon
```

EXPECT: 2 passed. The first test supplies fixture gcloud reads and accepts only
one `-spine` Cloud Run origin with project and region. The second supplies a
fixture Palace response, restores into an empty disposable home, proves byte
identity, and proves a second startup does not fetch or overwrite local rows.

## Spine append authority

DO: run

```sh
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock \
UV_CACHE_DIR=/tmp/n8-spine-uv uv run --locked pytest -q tests/test_transcripts.py
```

EXPECT: 3 passed against disposable PostgreSQL. Exact replay is idempotent;
changed replay and gaps are atomic conflicts; corrupt wire data is rejected;
and direct UPDATE is database-refused.
