# M2U — live-contract real-provider expectations

M2U removes fixture identity from the assertions that are meant to prove the
live Harness–Spine contract. It does not add a mock product path or deploy
anything.

## Problem chain

1. The local contract fixture reports `h2-contract-embedding-1536`; the owner
   Palace correctly reports `openai/text-embedding-3-small`.
2. Two tests asserted the fixture model literally, so they rejected the real
   broker before reaching the contract behavior they exist to defend.
3. Once that blocker was removed, the first production run exposed the same
   mistake in the score layer: synthetic fixture phrases and exact fixture
   cosine values did not prove C.4's real hard/similar bands.
4. Each environment now declares its expected model identity explicitly. The
   tests use an exact duplicate for the hard band, a real-broker semantic pair
   measured at cosine `0.849219` for the similar band, and assert C.4's enacted
   intervals rather than fixture-only decimal values.

This keeps the deterministic fixture strict while making the production pass
real evidence under SPEC B.6 rule 10. Both modified tests carry motivation
docstrings citing SPEC B.6 rules 10 and 12.

## Evidence — 2026-08-08

Local isolated Spine + pgvector fixture:

```sh
sh tests/contract/run.sh
```

Result: `3 passed in 1.11s`. The runner declared
`SPINE_EXPECTED_EMBEDDING_MODEL=h2-contract-embedding-1536`, then removed its
containers, image, network, and database volume.

Deployed owner Palace, using the ignored mode-0600 `.env` for URL and bearer
token and stating only the non-secret expected provider identity:

```sh
set -a
source .env
set +a
SPINE_EXPECTED_EMBEDDING_MODEL=openai/text-embedding-3-small \
  PYTHONPATH=src uv run --locked pytest -q -m contract tests/contract
```

Result: `3 passed in 7.64s`. This exercised live memory create/conflict/dedup,
PATCH/CAS/tombstone/list, and spend-receipt behavior through the public HTTPS
Palace API. No infrastructure mutation or deploy command was performed.

Mechanical law check:

```sh
PYTHONPATH=src uv run --locked python scripts/check_test_motivations.py
```

Result: `test motivation check passed: 376 tests, 0 grandfathered`.
The deterministic inverse index was regenerated; B.6 now lists both modified
live tests and reports eight defenders.

Repository handoff checks:

```sh
uv lock --check
PYTHONPATH=src uv run --locked ruff check .
PYTHONPATH=src uv run --locked ruff format --check tests/contract
PYTHONPATH=src uv run --locked pytest -q -m 'not contract'
git diff --check
```

Results: lock resolved without change; lint and changed-scope formatting
passed; `658 passed, 3 deselected in 2.16s`; diff whitespace passed. A broad
`ruff format --check src tests` also identified six inherited, untouched files
that would be reformatted (`deploy.py`, `packaged.py`, `test_daemon.py`,
`test_deploy.py`, `test_onboarding.py`, and `test_packaging.py`). M2U does not
mix that unrelated formatting sweep into its contract repair.
