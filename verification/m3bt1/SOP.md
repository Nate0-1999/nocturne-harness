# M3BT1 iterative build test

This is the frozen findings record for two real CLI builds performed by the
ordinary NOCTURNE owner agent. The agent ran from fresh `origin/main` wheels in
a disposable home, worked in one scratch root outside every repository, used
the released Palace 0.1.5 and real `openrouter:minimax/minimax-m3`, and changed
no product code.

## Protocol

- Fresh Harness source: `0574535b316bcc073d4a805bf33bcc5c6616a72a`.
- Fresh Spine source: `165a3ba2b9744be6514638a7b85ab194694adf8b`.
- Installed distributions: `nocturne-ai==0.1.5` and
  `nocturne-spine==0.1.5`.
- Released Palace health: version 0.1.5, schema 0015, API contract 0.1.4.
- Verification principal: `m3bt1-verification-20260821-bt21`; machine:
  `m3bt1-sop-verification`.
- The two eight-test acceptance scripts were frozen at 20:20:28Z, before the
  first prompt at 20:23:08Z. Their SHA-256 values are recorded in `SHA256SUMS`.
- Build time is wall clock from browser transmission of the first prompt to
  the first external run in which both the project suite and frozen acceptance
  suite passed.
- Cost is the sum of priced, thread-filtered ledger receipt lines. Churn is
  final lines added plus deleted from each round's committed empty baseline,
  including any temporary files the agent left behind.

## Raw result

| Metric | Round 1: Markdown notes to HTML | Round 2: CSV to report |
|---|---:|---:|
| Build time | 608.438 s (10m 8.4s) | 765.036 s (12m 45.0s) |
| Ledger cost | $0.00001882 (6 priced lines) | $0.00001582 (4 priced lines) |
| Churn | 828 added + 0 deleted = 828 | 719 added + 0 deleted = 719 |
| Own tests, final | 41/41 (100%) | 31/31 (100%) |
| Frozen acceptance, first external run | 6/8 (75%) | 7/8 functional, 30/31 own; overall 7/8 (87.5%) |
| Frozen acceptance, final | 8/8 (100%) | 8/8 (100%) |
| Owner correction turns | 1 | 1 |

**Tagline:** second build: **+25.7% time, -15.9% ledger cost, -13.2%
churn**.

The requested all-negative tagline is not supported: round 2 was cheaper and
smaller, but slower. Its first run also ended `partial=true` with
`budget_exceeded` immediately after an unverified edit, requiring the owner to
return the failing test. That interruption is part of the lived result, not a
measurement to subtract.

Ledger cost is deliberately narrow. All ten receipt lines were priced
embedding work with zero unpriced lines; the installed PI adapter emitted
request counts but zero token/cost fields for the OpenRouter build stream.
Therefore these figures satisfy the packet's ledger-receipt metric but are not
claimed as the complete provider bill.

## Round 1 finding

The real agent built and tested `notes2site`, then saved three memories. Its
own first suite passed 37/37, but the frozen contract found that the first H1
was removed from the note body and a note's nav omitted its self-link. One
ordinary owner correction produced 41/41 own tests and 8/8 frozen checks.
Screenshots: `01-round1-agent-working.png`, `02-round1-complete.png`,
`03-round1-memories.png`, and `04-round1-vitals.png`.

This matters because the agent's first green suite encoded two reasonable but
wrong assumptions. Fixed acceptance exposed the confidence gap and proved the
ordinary chat recovery path.

## What Palace offered and what the owner used in round 2

Automatic injection selected zero memories. The first-turn gate exposed all
three round-1 memories as near misses under `m3f-location-v1`:

| Rank | Memory | Score | Owner decision |
|---:|---|---:|---|
| 1 | Single `_error` helper for clean CLI exits | 0.375608 | add |
| 2 | Escape once, then layer inline transforms | 0.352833 | add |
| 3 | Deterministic input order + link rewriting | 0.343914 | leave out |

The owner added only the first two because clean CLI failure and HTML escaping
transfer to the CSV report, while static-site link rewriting does not. The
gate and exact decisions are visible in `05-round2-memory-gate.png`.

## Round 2 finding

The real agent used the reviewed error and escaping patterns while building
`csvreport`; it also used Decimal aggregation and atomic output replacement.
Its first run exhausted its turn budget after editing the last failing unit
test without rerunning. External checks showed 30/31 own tests and 7/8 frozen
checks. One ordinary owner correction produced 31/31 and 8/8. The agent then
saved one genuinely new lesson about defensive `sys.argv[0]` handling.
Screenshots: `06-round2-agent-working.png`, `07-round2-complete.png`,
`08-round2-memories.png`, and `09-round2-vitals.png`.

The Palace reduced repeated design work in two local seams, but this single
paired run does not prove the second build is cheaper overall: wall time got
worse, and the tasks were intentionally similar-but-varied rather than
identical. The honest next default is to keep this metric harness and collect
more paired runs; do not build product changes from one mixed result.

## Cleanup and durable proof

The four exact experiment memory IDs were tombstoned with optimistic revision
checks. After refresh, the disposable principal showed zero active memories;
see `10-cleanup-no-active-memory.png`. Raw journals were not committed because
they contain full prompts and large streamed tool payloads. `trace-summary.json`
preserves IDs, counts, hashes, provider state, gate scores, metrics, and cleanup
revisions without credentials or raw payloads. The bounded credential scan was
clean. Settled-ground exit was Spine 281/281 and Harness 1677 passed with the
three explicitly live contract tests deselected. The initial environment-only
setup failures and bounded retry commands are retained in `CHECKLIST.md`.
