# J6 — replay integrity

Result: **PASS**

Tree node: **P1.2.1a**.

## Automated replay

Command:

```sh
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock \
TESTCONTAINERS_RYUK_DISABLED=true \
PYTHONPATH=src \
uv run --locked pytest -q \
  tests/test_inject_api.py::test_prepare_commit_replays_gate_and_prepare_updates_only_injected
```

Result: `1 passed in 1.96s`.

The focused test makes real prepare/commit calls, rereads persisted
`injection_event` rows, reconstructs each card from rank, score, feature
vector, prompt, scorer version, frozen `_memory` snapshot, and `shown_as`,
then verifies committed membership and outcomes.

## Manual reconstruction of J3

Injection: `bea3335c-76f3-4e28-9f6f-506a7dd8688f`

Thread: `3ec5bb39-b539-48c8-8b6c-339ca9441422`

Prompt: `Use the H5 verification memories to explain the handoff.`

Scorer: `v0`

| Rank | Label | Shown as | Persisted outcome | Score | Screenshot match |
|---:|---|---|---|---:|---|
| 1 | H5 proof — never | pinned | removed:never | 0.316526 | yes |
| 2 | H5 proof — keep | pinned | kept | 0.421001 | yes |
| 3 | H5 proof — not relevant | pinned | removed:not_relevant | 0.250297 | yes |
| 4 | H5 proof — wrong | pinned | removed:wrong | 0.373464 | yes |
| 5 | H5 proof — add back | near_miss | added_back | 0.229229 | yes |

Every row had the six raw features `sem`, `kw`, `time`, `proj`, `freq`, and
`hist`, plus the frozen `_memory` snapshot. The five labels, bodies, ranks,
scores, shown-as values, and outcomes matched images `08`–`10` one-for-one.

The traced commit block contains exactly `H5 proof — keep` and
`H5 proof — add back`. Both deterministic model calls received that exact
block as the system-adjacent suffix. Removed units do not appear in it.
