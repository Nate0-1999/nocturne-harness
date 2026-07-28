# H5 F011 deployed-runtime verification — 2026-07-28

Status: **REMOTE PASS**

The single-use F011 grant was consumed successfully. Cloud Run revision
`n8-memory-palace-spine-00004-vs2` now serves 100% of default traffic from the
immutable image index
`sha256:dfe9fd5465038e9ac82ca61a49fd93f872afd041dae60b992a5b625fcb694cbb`,
built from Spine commit
`d41b2862d1e824fafb29fada955756304e48e7f5`.

This is FIXER/builder evidence. It closes the deployed-runtime defect recorded
as F011; it does not clear the `HUMAN USE HOLD`, which remains an owner decision
and gates J only.

## Remote F007 result

The verification used the typed
`harness.spine_client.SpineClient`, authenticated `/health`, and a randomized
principal/project fixture against the live service. Three `never` decisions
produced the required score descent and quarantine transition:

| Decision | Lane | Score | Revision | `never_kills` | Status |
|---|---|---:|---:|---:|---|
| first | injected | 0.7966666222 | 3 | 1 | active |
| second | injected | 0.6466666460 | 5 | 2 | active |
| third | near_miss | 0.4966666400 | 6 | 3 | quarantined |

The per-memory bias descended by approximately `-0.15` each time, reaching
approximately `-0.45`. A fourth prepare returned zero injected memories, zero
near misses, and zero search results for the fixture. Exact-ID cleanup found
the fixture and tombstoned it at revision 7. The fail-closed cleanup journal was
not needed and no journal remains.

Evidence:

- [`remote-verification.json`](remote-verification.json) — redacted typed-client
  result, deployment binding, scores, stats, absence check, and cleanup.
- [`transport-summary.json`](transport-summary.json) — redacted Cloud Logging
  transport summary: startup succeeded, every verification request returned
  its expected 2xx status, and the revision emitted zero error-severity entries
  in the verification window.
- Spine
  `verification/h5/f011-2026-07-28/deployment.json` — the image build,
  one-mutation record, before/after service state, and protected-state
  comparison. Its SHA-256,
  `77f29a7715a3266a6007e90af7cadb0c11cdfc6f5508b35414fe814c9cbf6761`,
  is recorded in `remote-verification.json`.

Raw query values, fixture identifiers, and credentials are not retained.
Committed fixture references are one-way truncated hashes.

## F011 constraints

The only service mutation was one image update. Project, region, service,
runtime identity, Cloud SQL attachment and safety settings, secret references,
IAM, max scale, ingress/application-bearer posture, traffic posture and `d1v`
tag, Artifact Registry immutability, and billing-breaker state all matched the
preflight snapshot. The canonical protected-state SHA-256 remained
`c5006f2141490ac10ebb4c319dcefbcf4d47ee80fe0413039dc34ff2f196a2aa`.
No migration, delete, IAM change, secret rotation, billing change, or new cloud
resource occurred.

The deployed digest is immutable and bound to the source commit by its image
label and BuildKit provenance. The historical Dockerfile nevertheless uses an
unpinned base name and unlocked pip dependency ranges, so a future rebuild from
Git alone is not guaranteed to be bit-for-bit identical; the deployment
artifact records the base, runtime, attestation, and index digests needed to
identify this exact build.

## Final source gates

```text
Harness non-contract suite        258 passed, 2 deselected
Spine full integration suite      160 passed
Harness and Spine Ruff            passed
Harness and Spine uv lock checks  passed
Harness and Spine repository hook passed
Web ESLint                        passed
TypeScript + Vite build           passed
git diff --check                  passed
```
