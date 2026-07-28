# H5 FIXER affected-slice rerun — 2026-07-27

Status: **LOCAL PASS; DEPLOYED-RUNTIME VERIFICATION BLOCKED**

This append-only record covers only the F006–F010 slices inherited from the
H5 Scout. Chrome drove the production Harness SPA by visible clicking and
typing. The canonical desktop/mobile and quarantine runs used the fixture's
deterministic `FunctionModel`; separate F006 and F008 probes used the real
configured chat model. Every run used an isolated local Spine/Postgres stack so
the repaired Harness and Spine source could be tested together without mutating
owner memories or the deployed service.

This is builder evidence. It neither clears the `HUMAN USE HOLD` nor replaces
Nate's physical-use judgment.

## F006 — removals bind the current turn; Wrong opens a second hard pause

**PASS locally.**

- Both the 1440×900 and 390×844 canonical runs opened the review gate before
  any model call, committed `not_relevant`, `wrong`, and `never` removals plus
  one add-back, then opened the typed `wrong_resolution` gate.
- The Wrong editor submitted one CAS-guarded `gate/wrong:edit` PATCH. The
  canonical traces prove the PATCH result occurred before the first model
  invocation. The second prompt skipped both gates.
- A separate real-model run removed the unique pinned memory
  `5c97b2fb-5376-4a6a-b5c8-819cd67db24f` as `not_relevant`. The visible answer
  reported no matching memory and contained neither `ORBITAL-MARMOT-7319` nor
  the fixture body. An operator-read local DB query showed the injection event
  as `removed:not_relevant`; the fixture was then tombstoned. That query output
  was not retained as an artifact, so the committed screenshots prove the
  visible no-leak behavior, not the DB row.
- Search, save-similarity, duplicate/label-conflict, and edit-resolution paths
  now share the same per-run exclusion set. An ambiguous commit-response
  failure also carries the selected removals into the memoryless model run.

Evidence:

- [desktop review gate](01-review-gate-desktop.jpg)
- [desktop Wrong resolution](03-wrong-resolution-desktop.jpg)
- [desktop completed first turn](04-first-turn-complete-desktop.jpg)
- [desktop second turn](05-second-turn-no-gate-desktop.jpg)
- [removed before model](17-removed-memory-before-model.jpg)
- [removed memory not refetched](18-removed-memory-not-refetched.jpg)
- [desktop canonical trace](trace-desktop.jsonl)
- [mobile canonical trace](trace-mobile.jsonl)

Both canonical traces pass `verification/h5/assert_trace.py` with 11 records.

## F007 — near-miss Never can deliver the third kill

**PASS locally.**

The same non-pinned near-miss
`d762260a-c3a0-4df7-961d-4e269274794a` received three visible Never decisions
across fresh threads:

| Decision | Score shown | Revision | `never_kills` | Status |
|---|---:|---:|---:|---|
| first | 0.229 | 2 | 1 | active |
| second | 0.079 | 3 | 2 | active |
| third | -0.071 | 4 | 3 | quarantined |

The table and final bias of approximately `-0.45` are operator observations
from the isolated local API/DB during the run; their raw query output was not
retained. A fourth fresh gate visibly returned no such near miss. The committed
21-record trace proves three `removed:never` commits for that same ID, followed
by a fourth commit with no fixture membership.

Evidence:

- [first kill](11-near-miss-never-kill-1.jpg)
- [second kill](12-near-miss-never-kill-2.jpg)
- [third kill](13-near-miss-never-kill-3.jpg)
- [quarantined memory absent](14-quarantined-near-miss-absent.jpg)
- [quarantine trace](trace-near-miss-quarantine.jsonl)

## F008 — missing project context does not broaden to global

**PASS for the reported failure; policy boundary recorded.**

A real-model prompt requested a project-scoped save with no active project and
explicitly said not to save globally. The model surfaced the missing project
context, stated that global fallback requires explicit confirmation in a later
turn, and did not retry globally. A subsequent API/DB query for the unique
`H5FIXER-F008` marker returned zero memories. The zero-row query is an operator
observation whose raw output was not retained; the screenshot proves the
model-visible missing-context/no-retry result.

The no-global-fallback guard is deterministic for the current run. Requiring
confirmation in a later run is an agent instruction, not a machine-verifiable
cross-turn authorization store; this evidence does not claim otherwise.

Evidence: [missing-context result](16-project-scope-no-global-fallback.jpg).

## F009 — restart expectation aligned to M1 law

**PASS with no product mutation.**

After restarting the daemon while retaining the browser origin, the
browser-local thread catalog and message counts remained visible, while the
selected daemon transcript reopened empty. That is the C.7 M1 behavior: the
catalog is local UI state and daemon transcripts are not durable sessions.

Evidence:
[catalog survives; transcript does not](15-restart-catalog-survives-transcript-does-not.jpg).

## F010 — 390×844 gate containment

**PASS objectively; physical touch remains owner-only.**

At an actual 390×844 Chrome viewport:

- document `clientWidth/scrollWidth`: `390/390`;
- dialog x/right/width: `4/386/382`, with `380/380` client/scroll width;
- review content: `551/1909` client/scroll height;
- sticky footer remained inside the dialog;
- all eight review controls were at least 44×44 CSS pixels;
- the Wrong editor remained contained, with controls at least 44 pixels high
  and 133.5 pixels wide.

Every body and action was reachable by internal vertical scrolling without
page-level horizontal overflow. Chrome cannot certify physical long-press or
thumb feel; those remain part of Nate's `HUMAN USE HOLD`.

Evidence:

- [mobile review gate](06-review-gate-mobile-390x844.jpg)
- [mobile decisions](07-review-decisions-mobile-390x844.jpg)
- [mobile Wrong resolution](08-wrong-resolution-mobile-390x844.jpg)
- [mobile completed first turn](09-first-turn-complete-mobile-390x844.jpg)
- [mobile second turn](10-second-turn-no-gate-mobile-390x844.jpg)

## Verification and cleanup

Final source gates:

```text
Harness non-contract suite        258 passed, 2 deselected
Spine full integration suite      160 passed
Harness and Spine Ruff            passed
Harness and Spine uv lock checks  passed
Harness and Spine pre-commit      passed
Web ESLint                        passed
TypeScript + Vite build           passed
Canonical trace assertions        11 records each, passed
git diff --check                  passed
```

All deterministic seed sets were cleaned by exact ID. The F006 and F007
fixtures were tombstoned, and an operator-read final query found no active rows
for the isolated `h5-sop-verification` principal. Cleanup query output was not
retained as an artifact.

The `npm ci` dependency install used for this rerun reported one high-severity
advisory. Classification requires an npm audit request that sends local
dependency metadata to npm; that network action was not authorized in this
packet, so this record does not guess at affected package, reachability, or
remediation.

## Deployment boundary

The read-only Cloud Run audit found production service
`n8-memory-palace-spine` still serving revision
`n8-memory-palace-spine-00003-pjh` from immutable image tag
`e0cf50d50283cd2c4f800272b832b8166e299cab`, which predates the F007 Spine
repair.

Garden requires H5 and later Harness work to use deployed Spine, but PLAN §2
grants the named Cloud Run mutations only to D1. Therefore the repaired source
is locally proven but the live deployed-runtime rerun remains blocked pending a
narrow owner grant. No cloud service, IAM, secret, database, billing, traffic,
or breaker setting was changed by this H5 session.
