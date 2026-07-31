# M1 independent judge verdict (superseding)

Judge session: `claude-code / 2026-07-31 / f648`

Date: 2026-07-31 America/Chicago

Overall verdict: **PASS**

This verdict supersedes the 2026-07-30 verdict (`codex / 2026-07-30 / 7f26`,
overall FAIL on J1/J2 proof coupling; retrievable in git history and still
summarized in report 028). Per that verdict's minimum repair charge and the
board's standing instruction, only the implicated J1/J2 slices were
re-executed; J0 was re-audited on the changed ground and J3–J8 were confirmed
standing. Independence: this judge is a fresh Claude Code session holding no
build context from this milestone; every builder including the I1 fixer was
Codex (B.6 rule 2 satisfied, different model).

The J1 failure's root cause was resolved lawfully rather than papered over:
F012 stopped the line, the owner enacted SPEC v2.26's journaled
resolution-point law (D.2 069), C.9's J1 was rewritten to test it, and the
I1 fixer implemented `/model` (Harness `66f1cc1`) and retained the repaired
evidence (report 030). This judgment verified that repaired evidence
independently and then re-executed both slices live on fresh clones.

## Checklist

| Item | Verdict | Tree node(s) | Evidence and reason |
|---|---|---|---|
| J0 | **PASS** (re-audited) | P4 | Re-run on current heads (Harness `b64cc82`, Spine `2eb85b9`): every DECISIONS.md entry in both repos cites a tree node (harness 019 cites P3/P4/P4.2); independent grep of both repos for forbidden families (weight updates, extraction, relay client, maintenance jobs, auth beyond static bearer) found zero real hits; both tracked `.githooks/pre-commit` scope fences pass in `--all` mode. |
| J1 | **PASS** | P3, P4 | Re-executed live per C.9 as rewritten (v2.26): fresh clones → isolated compose (authenticated `/healthz` 200) → `harness dev`. [`2026-07-31-jf648/01`](2026-07-31-jf648/01-j1-empty-state.png) empty state; [`02`](2026-07-31-jf648/02-j1-hello-default-model.png) hello on default `openrouter:minimax/minimax-m3` (hosted, 905 in/57 out); [`03`](2026-07-31-jf648/03-j1-model-change-event.png)/[`04`](2026-07-31-jf648/04-j1-post-switch-exchange.png) the `/model openrouter:x-ai/grok-4.5` command — zero-request run, journaled `model_change` (old→new slug, `reason=human_command`, `stickiness_epoch=1`, sacrificed prefix 962, context 500000) — and the exact post-switch hosted exchange; [`05`](2026-07-31-jf648/05-j1-reload-resolved-model.png) reload re-resolves the header from snapshot alone. Wire: [`wire-frames.jsonl`](2026-07-31-jf648/wire-frames.jsonl) retains the authoritative 6-message same-thread snapshot (`resolved_model=openrouter:x-ai/grok-4.5`, embedded model_change event) and a live C.7 `prompt.submit → run.started → run.delta → run.usage → run.done(end_turn)` chain on the switched thread. SQL: both threads stamped under the judge principal ([`sql-trace.txt`](2026-07-31-jf648/sql-trace.txt)). The builder's hello-specific live-delta record ([`../i1/2026-07-31-v226/wire-and-daemon.jsonl`](../i1/2026-07-31-v226/wire-and-daemon.jsonl), seqs 13–31/34–39/42–72) was verified claim-by-claim directly from the raw JSONL without using the builder's audit script; its deterministic audit also passes. Both records agree: same-thread hello → journaled resolution point → distinct hosted exchange, C.7 shapes throughout. |
| J2 | **PASS** | P1.4, P1.5 | Re-executed live: durable preference saved by exactly one `save_memory` in an ordinary chat turn — ack + panel unit `indentation-tabs-over-spaces` R1 with full body ([`06`](2026-07-31-jf648/06-j2-preference-saved.png)); fresh-word restatement ("when indenting source code, tabs are what I want, not spaces", new label) itself reached the Spine similar path and the agent surfaced the verbatim tool response with score `0.8366294031655829`, no force retry ([`07`](2026-07-31-jf648/07-j2-similar-result.png)). Trace: [`spine-access-log.txt`](2026-07-31-jf648/spine-access-log.txt) `201 Created` then `200 OK` (similar[]); [`sql-trace.txt`](2026-07-31-jf648/sql-trace.txt) one ACTIVE unit rev 1, embedding NOT NULL (1536), root `memory_revision` (parent_uid NULL, editor `agent:j-f648-agent`); snapshot retains both tool calls with distinct labels/bodies and A-015-default `force=false`. The builder's repaired fresh-word record (score 0.9075 naming the first memory, single call per prompt, no search/edit/retry) was independently confirmed from its raw trace and SQL. |
| J3 | **PASS** (stands) | P1.2.1a–c, P1.2.3 | Prior evidence (`2026-07-30-j7f26/` images 08–12, `j3-h5-trace.jsonl`, injection `bea3335c-…`) remains valid: git diff audit of `bce4b6e..b64cc82` shows the only product commit (`66f1cc1`) is keyed on `/model` prompts and `stickiness_epoch>0`, neither of which occurs in gate flows; gate/commit code untouched; Spine product code unchanged (docs freezes only). Both suites green on current heads. |
| J4 | **PASS** (stands) | P1.2.1b, P1.4 | Prior quarantine evidence (images 20–23, `j4-quarantine-trace.jsonl`: 3× never → `never_kills=3`, bias −0.45, quarantined, absent from fourth prepare) unaffected by the diff for the same reason. |
| J5 | **PASS** (stands) | P1.2.1d, P1.3, P1.5 | Prior `/remember`/panel-edit/CAS evidence (images 24–36, H6/H8 traces) stands; `remember_command_text` and panel UI files untouched in the range; web changes are backward-compatible protocol/store additions only. My live session also independently exercised the panel surface (live unit render, post-tombstone absence). |
| J6 | **PASS** (stands) | P1.2.1a | The replay test backing runs in the current green Spine suite (160 passed, including the prepare/commit replay proof); `RunDeltaEventPayload.resolved_model` is `exclude_if=None`, so journal/wire bytes of pre-existing event serialization are unchanged — the prior one-for-one gate reconstruction remains valid. |
| J7 | **PASS** (stands) | P1.1, P3 | Prior memory-death evidence (images 16–19, `j7-memory-death-trace.jsonl`) stands; error-degradation paths and spine-client handling untouched; `StopReason.ERROR` default preserved in the `66f1cc1` restructure. |
| J8 | **PASS** (stands) | P1.2.1c, P3 | Prior 390×844 evidence (images 13–15, `j8-h5-mobile-trace.jsonl`) stands; zero layout/component/CSS changes in the range. |

First-person record of the re-executed slices:
[`2026-07-31-jf648/SOP.md`](2026-07-31-jf648/SOP.md) — including method
disclosure, an unscripted segment, one small friction note for the human
gate (in-message JSON block scroll behavior), and one lawful observation
(live events deliver only to the originating socket).

## Packet implication

None. All nine items pass. The board's `FAILED_JUDGMENT` on I1 was already
resolved by the fixer (report 030); with this superseding verdict M1's judge
gate is satisfied. Per PLAN §7 the milestone completes when the owner reads
this verdict beside its screenshots; M2 planning (and the M3 re-plan) opens
there, and D3 becomes claimable.

## ADR status normalization proposal for the human gate

Propose one new immutable D.2 normalization decision rather than rewriting
historical rows (carrying forward the prior judge's proposals, now
actionable because the overall verdict is PASS; current status lines
verified against the v2.27 master, whose product-repo copies are
byte-identical):

- **ADR-002 (PROPOSED):** accept the M1 scope — HTTP service boundary,
  typed SpineClient, MemoryCapability prepare–gate–commit flow,
  system-adjacent final block. Later SSE/compaction/third-party adapter
  clauses stay milestone-scoped.
- **ADR-004 (PROPOSED):** accept the shipped M1 unit/CAS/revision/
  tombstone/quarantine/pin law — the S-packets built it, J1–J8 now verify
  it end to end (this session's fixture tombstone once again exercised the
  CAS/append-only revision chain).
- **ADR-005 (PARTIALLY ACCEPTED):** keep; annotate that M1 scorer v0, full
  gate logging, removal/add-back/never (incl. A-022 near-miss veto), and
  quarantine are verified while M2 online learning remains future.
- **ADR-008 (ACCEPTED, stack details PROPOSED):** accept the M1 stack
  details — React/TypeScript/Vite command center over the browser→local
  daemon path, snapshot-authoritative state. Relay/deck clauses stay
  later-milestone.
- **ADR-009 (mixed):** retain; annotate the M1 responsive-mobile clause as
  verified (J8).
- **ADR-006 (PROPOSED):** remain proposed; presence is not M1.
- Accept the M1 scope of the system-adjacent block placement, the M1
  vertical slice, and decision 013's phased accumulation boundary; durable
  execution remains proposed.
- New since the prior verdict: A-020/A-021 model-policy law now has its
  first built-and-verified surface (the v2.26 resolution-point command,
  epoch-scoped cache stickiness). No status line exists to normalize —
  policy law lives in AMENDMENTS pending the pre-M2 fold — so this is
  recorded as verification context only.

## Verification and hygiene

- Harness mandatory suite (current head `b64cc82`): `381 passed, 2 deselected`
- Spine mandatory suite (current head `2eb85b9`, documented Colima
  Testcontainers environment): `160 passed`
- Builder evidence deterministic audit (`assert_trace.py`): PASS; plus an
  independent claim-by-claim verification of the raw trace that did not use
  that script (all seven claims CONFIRMED, no secrets present in the trace)
- J0 re-audit: both repos' DECISIONS.md fully cited; zero forbidden hits;
  both scope-fence hooks pass
- Diff audit `bce4b6e..b64cc82` (harness) and 2026-07-29→`2eb85b9` (spine):
  NO_INVALIDATION of J3–J8 ground
- Live-slice hygiene: single fixture exact-ID tombstoned (revision 2,
  parented to root, zero active units — [`sql-after-cleanup.txt`](2026-07-31-jf648/sql-after-cleanup.txt));
  isolated Compose project `n8jf648` down with volume and network removed;
  fresh clones, dedicated Chrome profile, and the clone's mode-0600 `.env`
  deleted; no persistent product or cloud data touched; no secret value
  printed or committed
