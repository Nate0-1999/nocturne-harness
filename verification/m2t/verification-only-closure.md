# M2T verification-only closure — 2026-08-06 / c811

Status: **PASS — M2T production verification is complete.**

The owner explicitly authorized one production execution of `nocturne deploy`
for the isolated memory create/dedup/injection/cleanup round trip, Vitals read,
and Cloud Run `nocturne-verified` label write. The authorization required every
infrastructure stage to remain NOOP and forbade a backup receipt.

## Fresh ground and preflight

All repositories were clean and synchronized before the run. Fresh inherited
ground passed:

- Spine: 222 passed; Ruff clean;
- Harness: 654 passed, 3 contract tests deselected; Ruff clean; and
- web: ESLint clean, 7 unit tests passed, TypeScript and Vite production build
  passed (287 modules).

The running Harness was commit `b617485`, which enforces D.2 098's receipt and
mutation-order boundary. A real pre-execution `nocturne deploy --dry-run`
reported stages 01–18 and 20 NOOP and only stage 19 `remote_verification`
UPDATE.

The private receipt baseline contained exactly four files; the newest was
`01KZD3K0CVGV29JMG7QAF9TPZ5`. Cloud SQL's latest on-demand backup was
`1786072630287`. Cloud Run served revision
`n8-memory-palace-spine-00005-t64` at 100% default traffic, with no
`nocturne-verified` label.

## Authorized execution

`uv run --locked nocturne deploy` ran once and exited 0. No retry or alternate
path was launched. Sanitized Cloud Run request metadata records the complete
typed path on revision `00005-t64`:

```text
GET    /health             401
GET    /health             200
POST   /v1/memories        201
POST   /v1/memories        409
POST   /v1/inject/prepare  200
POST   /v1/inject/commit   200
GET    /v1/memories        200
PATCH  /v1/memories/<id>   200
GET    /v1/vitals          200
```

Harness accepted the second create only as the expected typed hard-duplicate
conflict pointing to the first memory, required the fixture in prepare,
required a non-empty final block from commit, isolated exactly that fixture,
and required the cleanup PATCH result to be TOMBSTONED. Exit 0 therefore proves
those typed assertions as well as the status sequence above.

The final label is:

```text
nocturne-verified=6ad9613a455798d6d92e5f5f390ab4ba
```

## Independent postconditions

A post-execution `nocturne deploy --dry-run` exited 0 with all 20 stages NOOP.
The local receipt set remains the same four files with the same newest receipt.
Cloud SQL still lists `1786072630287` as its latest on-demand backup; no new
on-demand backup exists. Secret metadata remains version 2 enabled and version
1 disabled, with no version 3.

Cloud Run now serves revision `n8-memory-palace-spine-00006-b75` at 100%
default traffic. Cloud Run materialized that revision as a platform side effect
of `gcloud run services update --update-labels`, the specifically authorized
verification-label write. This was not hidden as a supposedly unchanged
revision:

- the complete old and new revision `spec` JSON compares equal;
- both resolve image digest
  `sha256:ec222889fb4af37b94c6b1d5382f91fed915dfce1a157ea3ec42939c27b59903`;
- service account, Cloud SQL attachment, scaling, execution environment,
  concurrency, timeout, environment, secret references, and container spec are
  unchanged; and
- the new revision passes the unauthenticated 401 and authenticated 200 health
  boundary.

The planner consequently observes `cloud_run_service` NOOP and
`remote_verification` NOOP. No credential reset, secret rewrite, image build or
push, migration, backup, or receipt occurred. No secret or credential value was
printed, retained in logs, or written to this evidence.
