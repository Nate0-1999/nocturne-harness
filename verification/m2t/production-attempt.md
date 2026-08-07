# M2T production attempt — 2026-08-06 / c808

Status: **BLOCKED after receipt; single-use D.2 097 grant consumed.**

The owner expressly approved the literal `nocturne up --no-open` → `y` path.
An initial process became stranded at the consent prompt on an inaccessible
PTY. Read-only proof showed no fresh receipt, no custody receipt, and no cloud
child operation, so that pre-receipt process was interrupted and the same path
was relaunched in-session with a monitored `y`.

## Stage result

| stage | result | safe evidence |
|---|---|---|
| fresh verified backup | PASS | receipt `01KZD1HVSZXWXJGPNEN58PY6XC`; backup `1786070495876`; operation `17e0291f-3034-4992-81db-cbe400000032` |
| database credential reset | PASS | the alignment call advanced to secret rewrite and custody publication |
| `spine-database-url` rewrite | PASS | version 2 ENABLED; version 1 DISABLED; no payload read |
| durable custody | PASS | receipt links version 2 to the fresh backup; file mode 0600 |
| image build/push | **FAIL** | sanitized CLI error: `subprocess failed without changing scope: docker buildx build` |
| Cloud Run rollout | NOT RUN | revision and traffic unchanged |
| migrations 0002→0009 | NOT RUN | read-only deploy observation still reports the allowed migration update |
| authenticated M2 verification | NOT RUN | typed round trip and `/v1/vitals` proof did not execute |

Minting the receipt consumed D.2 097. No production mutation was retried after
the image-build failure.

## Backup and custody proof

Cloud SQL independently re-described backup `1786070495876` as
`SUCCESSFUL`, `ON_DEMAND`, PostgreSQL 16, in `us-central1`, ending
`2026-08-07T02:42:26.790Z`. The private backup directory is mode 0700; both the
receipt and `cloud-credential-custody.json` are mode 0600. The custody document
names project `n8-memory-palace`, instance `n8-memory-palace-db`, user `spine`,
secret `spine-database-url`, version `2`, and the fresh receipt. No credential
or secret value was printed, read into evidence, or committed.

## Failure diagnosis and local correction

The build path created an empty `DOCKER_CONFIG` for short-lived registry auth.
That also hid the configured Homebrew Buildx plugin and Colima context. The
failure is reproduced without building or pushing anything:

- normal `docker buildx version`: Homebrew Buildx v0.35.0;
- the empty-config version check: `docker: unknown command: docker buildx`.

Decision 042 now keeps only Docker's non-secret routing facts
(`currentContext`, `cliPluginsExtraDirs`, and linked Buildx/plugin/context
state) in the 0600 temporary config. Persistent registry auth and credential
helpers remain excluded. Preflight proves Buildx and daemon access in that
exact isolated environment before any future receipt. The deploy planner also
now guarantees that a post-custody continuation mints its own fresh receipt and
runs image → service → migration → verification; custody prevents another
reset or secret rewrite.

Local proof after the correction:

- deployment tests: 141 passed;
- full non-live Harness suite: 649 passed, 3 live-contract tests deselected;
- full Harness Ruff: clean;
- read-only real `nocturne deploy --dry-run`: exit 0 through the corrected
  isolated preflight; database/user/secret exact, migration UPDATE, image
  CREATE, service UPDATE, remote verification UPDATE.

The dry-run also proves the newly managed version-2 database credential can
read Alembic state at 0002. It did not mutate the cloud.

## Read-only production state after failure

- Artifact Registry has no `0.1.0` tag.
- Cloud Run remains `n8-memory-palace-spine-00004-vs2`, old digest
  `dfe9fd5465038e9ac82ca61a49fd93f872afd041dae60b992a5b625fcb694cbb`,
  with 100% latest-revision traffic.
- That revision explicitly references database-secret version 1, now disabled
  and carrying the pre-reset credential. Platform Ready metadata therefore is
  not database-health proof.
- Status-only authenticated reads returned `/health` 200,
  `/v1/memories?limit=1` 500, and `/v1/vitals` 404. The old health route is
  static; the DB-backed 500 confirms owner-service disruption, while 404
  confirms the M2 Vitals rollout never happened. No response body was retained.

F018 must be resolved before any retry. The minimum safe authority is one fresh
single-use **post-alignment completion** attempt: fresh verified receipt first;
reset and secret rewrite remain NOOP; then image build/push → rollout →
migrations 0002→0009 → authenticated health, typed round trip, and Vitals
verification.
