# M2XH final delta re-scout

Status: **EXECUTED / PASS** on 2026-08-13.

This was a real owner-app pass against the released Palace, not an H5 fixture.
The checked-in `harness.daemon:create_dev_app` factory served the current SPA
from an isolated port and disposable Nocturne home. The run used principal and
machine `m2x-sop-verification` and the configured real
`openrouter:minimax/minimax-m3` route.

Only owner-checklist items 17 and 22 were re-run, as charged.

## Verdict

- **17 PASS — oversized durable capture.** The exact `LIVE_SPLIT_SOURCE` from
  `tests/test_agent.py` produced the existing bounded, lossless no-write
  guidance once after approximately 30 seconds. The terminal journal state was
  `run.done(partial=false, stop_reason=end_turn)`, the ordinary composer
  recovered, and production Palace listings found no active, quarantined, or
  tombstoned M2XH split source/child residue. No partial memory was written.
- **22 PASS — authoritative project binding.** A human-paced Project submit
  created thread `c6548879-2f44-420f-8968-048bac0417ca` with authoritative
  project `m2xh-project-xh1b`. The next save stored the same project in
  `project_key` and `origin_path`; the next ordinary turn selected that exact
  memory with raw Project feature `1.000` and answered the stored fact. CURRENT
  Graph showed exactly that memory under the same project. A fresh sibling
  thread bound to `m2xh-other-xh1a` selected zero memories, both model-issued
  `search_memory` calls returned `no matching memories`, the answer denied
  knowledge of the fact, and CURRENT Graph was empty.

## Owner journey and evidence

The retained screenshots are deliberately small:

- `07-scoped-answer.png` — same-project answer after the real gate.
- `08-current-graph.png` — CURRENT Graph inspector naming
  `m2xh-project-xh1b`.
- `09-sibling-empty-gate.png` — sibling gate with zero selected and zero near
  misses.
- `11-sibling-graph-empty.png` — sibling CURRENT Graph empty.
- `12-bounded-split-guidance.png` — one bounded guidance message and recovered
  composer.

The browser compositor did not include the gate overlay in the earlier
same-project screenshot, so that capture was discarded. The gate's exact
injection ID, selected memory ID, score, and feature vector are preserved in
`trace-summary.json` from the durable journal instead.

During setup, submitting a visually hidden control without a human pacing beat
left the Project value as a draft. That first thread therefore remained
authoritatively `build-test`; it was automation-invalid, not counted as owner
evidence, and was re-run through the visible Enter path. Its one exact memory
and the valid scoped memory were both CAS-tombstoned during cleanup. Because
the screenshots predate cleanup, the discarded setup memory is still visible
in some Memory sidebars; no claim depends on it.

The unscripted segment was the recovery from that draft-only Project state and
the Work to CURRENT Graph to sibling-project roundtrip. It exposed no product
failure. Browser warnings and errors were empty.

## Cleanup

Only the two exact verification IDs were touched. Both are tombstoned at
revision 3 with editor `verification:m2xh`; a final active listing returned
zero matches. Append-only gate, model, spend, and tombstone evidence remains.
The daemon was stopped, port 8797 was confirmed closed, and the disposable home
was moved to Trash after evidence was frozen.

No product code or owner memories were changed. M2X is ready for owner review;
the existing HUMAN use hold is unchanged.
