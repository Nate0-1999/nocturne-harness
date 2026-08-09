# M2W verification — release lifecycle hardening

Session: `codex / 2026-08-08 / a7d2`

## Owner-visible journeys

Focused tests exercise the public command seams and assert the literal remedies:

- reverse schema skew refuses before any deploy prompt with
  `this app is older than your Palace — update the app first`;
- `nocturne doctor` consumes the same daemon preflight as `nocturne up` and
  reports web assets, port 8765, and the rung-specific startup toolchain;
- an existing Nocturne daemon on 8765 is adopted with exit status 0 and the
  plain `already running ... using it` notice;
- `nocturne open` on a down daemon returns
  `Nocturne isn't running — run nocturne up`;
- remote `nocturne backup` enters the human-owner gcloud credential check and
  the existing verified Cloud SQL `ON_DEMAND` receipt path, without deploy
  discovery or IAM-grant reconciliation.

The packet does not create a live owner-cloud backup: that operation is
explicitly owner hands and mutates external recovery state. The provider
request, completion wait, metadata verification, mode-0600 receipt, CLI
dispatch, and absence of deploy/grant machinery are covered at the subprocess
and command boundaries.

## Immutable release evidence

The exact packaged Spine build context is hashed by relative path, file mode,
and bytes. Buildx publishes the semantic version tag and a `source-<sha256>`
companion tag onto the same image. Artifact observation accepts an existing
version only when that row also owns the expected source tag; otherwise the
plan is blocked with:

```text
this version is already released; bump the spine version to ship changes
```

Tests alter source bytes and executable mode independently, prove the digest
changes, prove both tags are present in Buildx argv, and prove mismatched
source provenance cannot enter image build or deployment.

## Mechanical evidence

```text
Focused packaging/onboarding/deploy: 181 passed
Harness ground: 671 passed, 3 deselected
Spine ground: 223 passed
Harness test motivation check: 389 tests, 0 grandfathered
Changed-scope Ruff: PASS
git diff --check: PASS
```

The regenerated inverse law index lists the new defenders for SPEC D.2 and
the reverse-skew tests cite SPEC B.6 rule 12 directly.
