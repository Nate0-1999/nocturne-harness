# M2T verification-only readiness — 2026-08-06 / c810

Status: **READY LOCALLY; production apply not started.**

SPEC v2.55 / D.2 098 classifies the corrected typed round trip, Vitals read,
fixture cleanup, and final verification label as ordinary data-plane operation.
Every infrastructure stage is already exact, so this run must mint no Cloud SQL
backup receipt.

## Local correction

The deploy orchestrator now:

- excludes a verification-only run from infrastructure receipt creation;
- mints a receipt for every real infrastructure CREATE/UPDATE, including a
  secret-only change;
- materializes packaged source before the receipt when credential alignment can
  make a blocked migration runnable;
- builds and pushes the image before credential alignment; and
- re-observes the image and stops before any service-affecting mutation unless
  the pushed image is exact.

Regression coverage fixes both sides of the scope boundary and the
mutation-last failure path. The authoritative local lane passed with `654
passed, 3 deselected`; Harness Ruff and `git diff --check` are clean. The fresh
boot ground also passed before this correction: Spine `222 passed`, Harness
`650 passed, 3 deselected`, web ESLint, seven unit tests, TypeScript, and the
Vite production build.

## Read-only production preflight

`uv run --locked nocturne deploy --dry-run` exited 0 and reported:

- stages 01–18: NOOP;
- stage 19 `remote_verification`: UPDATE; and
- stage 20 `billing_breaker`: NOOP.

The local private-receipt baseline remains four files. The newest is
`01KZD3K0CVGV29JMG7QAF9TPZ5`, timestamped 2026-08-06T22:18:05-0500. Cloud SQL
still reports backup `1786072630287` as the latest on-demand backup;
the newer `1786071600000` entry is an automated backup.

Cloud Run remains on ready revision `n8-memory-palace-spine-00005-t64`, serving
100% of default traffic from image tag `0.1.0`. Its labels contain the expected
`nocturne-image=6ad9613a455798d6d92e5f5f390ab4ba` marker and no
`nocturne-verified` marker yet.

## Execution boundary

At 2026-08-06T23:11-0500 the execution environment rejected the live
`nocturne deploy` command before creating its process. It requires fresh,
explicit owner authorization for the isolated memory create/dedup/injection/
cleanup round trip and Cloud Run verification-label write. No endpoint request,
label write, receipt, backup, or other production mutation occurred.

After that authorization, the remaining literal path is:

1. run `uv run --locked nocturne deploy` once;
2. require the corrected typed round trip, cleanup, Vitals, and label write to
   succeed;
3. run a second dry-run and require all 20 stages NOOP; and
4. prove the local receipt set and latest on-demand Cloud SQL backup are
   unchanged.

No secret or credential value was read, printed, or recorded in this evidence.
