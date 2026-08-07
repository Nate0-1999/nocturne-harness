# M2T post-alignment completion attempt — 2026-08-06 / c809

Status: **BLOCKED after receipt; the owner's F018 single-use grant is consumed.**

The owner expressly authorized one literal `nocturne up --no-open` → `y`
post-alignment completion attempt. The command presented exactly one update
sentence and one `[y/N]` choice. Accepting it forwarded consent into the same
deploy run; no credential-alignment question appeared.

## Stage result

| stage | result | safe evidence |
|---|---|---|
| fresh verified backup | PASS | receipt `01KZD3K0CVGV29JMG7QAF9TPZ5`; backup `1786072630287`; operation `485b0b6f-b814-4b1f-a1e6-47ed00000032` |
| database credential reset | NOOP | the only Cloud SQL admin operation in the attempt window was the backup |
| `spine-database-url` rewrite | NOOP | v2 remains ENABLED, v1 DISABLED, and no v3 exists; custody is unchanged |
| image build/push | PASS | tag `0.1.0`; OCI index digest `sha256:5b3dc8cb86f83bd60b21bb56573c41dba18277739575279717a46755c320caa7` |
| Cloud Run rollout | PASS | revision `n8-memory-palace-spine-00005-t64`; Ready; 100% default traffic; database secret `spine-database-url:latest` |
| migrations 0002→0009 | PASS | post-failure read-only deploy observation reports the packaged Alembic head exact |
| authenticated health boundary | PASS | unauthenticated `/health` 401, authenticated `/health` 200 |
| typed round trip | **PARTIAL / FAIL** | create 201; second create 409, but the verifier demanded the wrong conflict variant |
| fixture cleanup | PASS | isolated list 200 and tombstone PATCH 200 |
| inject prepare/commit | NOT RUN | verifier stopped at duplicate classification |
| `/v1/vitals` | NOT RUN | no request reached the service |
| final verification label | NOT WRITTEN | `nocturne-verified` remains absent |

Minting the fresh receipt consumed the grant. No production mutation was
retried after the verification failure.

## Receipt and alignment proof

The private receipt is mode 0600 inside a mode-0700 directory. Cloud SQL
independently re-described backup `1786072630287` as `SUCCESSFUL`, `ON_DEMAND`,
PostgreSQL 16, in `us-central1`; it ran from `2026-08-07T03:17:10.288Z` to
`2026-08-07T03:18:01.103Z`. Operation
`485b0b6f-b814-4b1f-a1e6-47ed00000032` is `DONE` and names the same backup.

No second credential reset or secret rewrite occurred. The attempt window has
only the backup Cloud SQL operation. Secret metadata remains v2 ENABLED and v1
DISABLED with no v3. The mode-0600 custody receipt retains its earlier
alignment time, version 2, and prior receipt link. No credential or secret
payload was read or recorded.

## Deployed state

Artifact Registry tag `0.1.0` maps to OCI index digest
`sha256:5b3dc8cb86f83bd60b21bb56573c41dba18277739575279717a46755c320caa7`.
Cloud Run resolved its linux/amd64 image as
`sha256:ec222889fb4af37b94c6b1d5382f91fed915dfce1a157ea3ec42939c27b59903`.
Revision `n8-memory-palace-spine-00005-t64` is the latest ready revision,
serves 100% of default traffic, carries the expected Cloud SQL attachment,
and resolves `SPINE_DATABASE_URL` from `spine-database-url:latest` (v2).

After the failure, a real read-only `nocturne deploy --dry-run` exited 0 and
reported project, database, secret, image, service, and migrations all NOOP;
the packaged migration head is exact at 0009. Only `remote_verification`
remains UPDATE.

## Verification failure and correction

The sanitized request sequence was:

```text
GET   /health                       401
GET   /health                       200
POST  /v1/memories                  201
POST  /v1/memories                  409
GET   /v1/memories                  200
PATCH /v1/memories/<fixture-id>     200
```

Harness posted the exact same create request twice and required the second 409
to decode as a hard duplicate. SPEC C.4 deliberately checks an active-label
collision before embedding or semantic deduplication, so Spine correctly
returned a typed label conflict. The verifier then ran its `finally` cleanup,
isolated the created fixture, and tombstoned it. It never reached injection
prepare/commit, Vitals, or the final `nocturne-verified` label.

The local correction preserves the principal and body but gives the second
probe a distinct valid label, allowing C.4's hard-duplicate band to be tested.
No new decision is required because this restores existing contract law.
Regression proof deliberately models label-first conflict precedence and
asserts the different-label duplicate plus tombstone cleanup.

Local proof after the correction:

- focused verifier regression: 1 passed;
- deployment module: 142 passed;
- full non-live Harness suite: 650 passed, 3 live contracts deselected;
- full Harness Ruff: clean;
- `git diff --check`: clean.

One unfiltered test invocation first ran all 650 local tests successfully and
then reported three setup errors because the live-contract environment was not
provided. The corrected marker-qualified command above is the authoritative
non-live result; the setup error was not a product failure and made no remote
request.

F019 must be resolved before another production write. Because the Palace is
already current, `nocturne up` cannot honestly offer another update prompt.
The minimum safe authority is one fresh receipt-first, single-use
**post-deploy verification** attempt through `nocturne deploy`; credential,
secret, image, rollout, and migration stages remain NOOP, and only the
corrected typed round trip, cleanup, Vitals probe, and final verification label
remain.
