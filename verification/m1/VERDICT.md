# M1 independent judge verdict

Judge session: `codex / 2026-07-30 / 7f26`

Date: 2026-07-30 America/Chicago

Overall verdict: **FAIL**

The judge packet completed, but M1 does not pass. J0 and J3–J8 pass. J1 and J2
fail because the independent record does not satisfy their explicitly named
trace/action coupling. These are proof failures; this judgment did not
establish a product implementation defect.

## Checklist

| Item | Verdict | Tree node(s) | Evidence and reason |
|---|---|---|---|
| J0 | **PASS** | P4 | [`2026-07-30-j7f26/j0-scope-journal-audit.md`](2026-07-30-j7f26/j0-scope-journal-audit.md): all substantive decision entries cite valid nodes; strict forbidden-code audit has zero hits; both pre-commit hooks pass. |
| J1 | **FAIL** | P3, P4 | Images `2026-07-30-j4d73/01`–`04` prove cold browser use and a hosted reply; SQL proves the thread row. The residue has no hello-specific daemon/wire trace and no distinct default-to-OpenRouter switch/exchange. J2 deltas cannot substitute for J1's named trace. |
| J2 | **FAIL** | P1.4, P1.5 | Image `05`, create wire, and SQL prove the atomic revision-1 memory, non-null embedding, root lineage, and agent editor. The fresh-word run in image `06` never calls `save_memory` or Spine. The separate exact `/remember` in image `07` hits the duplicate path, but does not trace the fresh-word action required by C.9. |
| J3 | **PASS** | P1.2.1a–c, P1.2.3 | Images `08`–`12`, [`j3-h5-trace.jsonl`](2026-07-30-j7f26/j3-h5-trace.jsonl), injection `bea3335c-76f3-4e28-9f6f-506a7dd8688f`: on-screen identity, scores, outcomes, wrong-resolution pause, and final block all cross-check. |
| J4 | **PASS** | P1.2.1b, P1.4 | Images `20`–`23` and [`j4-quarantine-trace.jsonl`](2026-07-30-j7f26/j4-quarantine-trace.jsonl): same UUID receives three Never decisions; `never_kills=3`, bias `-0.45`, status quarantined; absent from fourth prepare/gate. |
| J5 | **PASS** | P1.2.1d, P1.3, P1.5 | Images `24`–`36`; H6 desktop/mobile and H8 traces. `/remember` confirms and renders in panel; user edit creates a child revision; stale CAS returns current state and preserves draft with no retry. |
| J6 | **PASS** | P1.2.1a | [`j6-replay.md`](2026-07-30-j7f26/j6-replay.md): focused replay test passes; J3's five persisted rows reconstruct the visible gate one-for-one. |
| J7 | **PASS** | P1.1, P3 | Images `16`–`19` and [`j7-memory-death-trace.jsonl`](2026-07-30-j7f26/j7-memory-death-trace.jsonl): clear mid-thread error, chat continuity, new-thread memoryless warning, and recovered next-thread gate; no daemon crash. |
| J8 | **PASS** | P1.2.1c, P3 | Images `13`–`15` and [`j8-h5-mobile-trace.jsonl`](2026-07-30-j7f26/j8-h5-mobile-trace.jsonl): exact 390×844 gate readability, full bodies, one-tap remove/add, no overflow, usable chat. |

Detailed first-person record:
[`2026-07-30-j7f26/SOP.md`](2026-07-30-j7f26/SOP.md).

## Packet implication

The failure is diffuse integration/judge-proof ground rather than a localized
implementation defect. Per PLAN C.9, set **I1** to `FAILED_JUDGMENT`. A FIXER
inherits this verdict.

The minimum repair charge is evidence, not new product work:

1. execute J1's two named model stages and retain the hello-specific daemon
   trace with C.7-shaped `run.delta` envelopes;
2. execute J2 so the fresh-word restatement itself reaches the Spine
   duplicate/similar path, retaining the action-correlated server trace;
3. rerun only the implicated J1/J2 slices, then issue a fresh independent
   verdict. Do not relabel the existing separate exact `/remember` as the
   fresh-word trace.

## ADR status normalization proposal for the human gate

Append a new immutable D.2 normalization decision rather than rewriting
historical rows.

- **ADR-002:** accept the M1 HTTP/SpineClient/MemoryCapability
  prepare–gate–commit boundary and system-adjacent block. Keep later
  SSE/compaction/third-party adapter extensions milestone-scoped.
- **ADR-004:** accept the shipped M1 unit/CAS/revision/tombstone/quarantine/pin
  law after the J1/J2 fixer closes the overall verdict.
- **ADR-005:** keep **PARTIALLY ACCEPTED**; clarify that M1 scorer v0, full
  gate logging, removal/add-back, and quarantine are verified while M2 online
  learning remains future.
- **ADR-008:** accept the M1 React/TypeScript/Vite command-center and
  browser-to-local-daemon path. Keep relay/deck clauses later-milestone.
- **ADR-009:** retain its mixed status; annotate the M1 responsive-mobile
  clause as verified.
- **ADR-006:** remain proposed; presence behavior is not M1.
- Accept the M1 scope of the system-adjacent block placement, M1 vertical
  slice, and decision 013's phased accumulation boundary. Keep durable
  execution proposed.

Because the overall verdict is FAIL, this is a proposal for the later human
gate, not an enacted status change.

## Verification and hygiene

- Harness mandatory suite: `356 passed, 2 deselected`
- Spine mandatory suite: `160 passed`
- J6 focused replay: `1 passed`
- H6 desktop trace assertion: `58 records`, PASS
- H6 mobile trace assertion: `62 records`, PASS
- H8 trace assertion: `18 records`, PASS
- Exact-ID fixture cleanup: zero ACTIVE rows across all J verification
  principals
- Browser viewport override: reset
