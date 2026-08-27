# M3B2 iterative build test, round two

This is the frozen findings record for one real CLI build performed by the
ordinary NOCTURNE owner agent. The agent ran from fresh `origin/main` sources
installed in a disposable environment, worked in one scratch Git repository
outside every product repository, used the released Palace and the real
`openrouter:minimax/minimax-m3` route, and changed no product code.

## Protocol

- Fresh Harness source: `fb11867865d7cbded968aefda6a3ad4e3a2b1b98`.
- Fresh Spine source: `2309aa37033205e6e4d5ab0223dd802124868d06`.
- Installed distributions reported `nocturne-ai==0.1.5` and
  `nocturne-spine==0.1.6`.
- Released Palace health reported product `0.1.5`, schema `0015`, and API
  contract `0.1.4`.
- Verification principal continued M3BT1 exactly:
  `m3bt1-verification-20260821-bt21`. This run used machine
  `m3b2-sop-verification` and agent `m3b2-owner-agent`.
- The eight-test acceptance script was frozen at `2026-08-27T19:19:24Z`,
  before the first prompt at `2026-08-27T19:21:03.224Z`. Its SHA-256 is
  `435a15cd0d28ce9dd2622b0805be8d96b065219c61979939d3706c5a4f8fdbe5`.
- Build time is wall clock from browser transmission of the first prompt to
  the first external run in which both the project suite and frozen acceptance
  suite passed.
- Cost is the sum of thread-filtered, `purpose=building` ledger receipt lines
  through that pass. The later summary-only turn is disclosed separately.
- Churn is the staged Git diff against the committed empty baseline, including
  demo files the agent left behind; bytecode is binary and contributes no line
  count.

The varied task was a standard-library Python JSONL build-event to deterministic
HTML report CLI. The contract required exact JSON schema validation, sorted and
escaped per-task summaries, overall totals, atomic output, clean failures, and
an executable unittest suite.

## What I saw and did

1. I opened the real Rack against the remote Palace. Chrome carried an old
   local thread-catalog entry, so I created a fresh thread rather than touching
   or clearing browser data. The new thread kept the M3BT1 `build-test` project
   key. The Memory module visibly showed zero active memories.
   Screenshot: `01-preflight-zero-active.png`.
2. I transmitted the frozen task through the ordinary composer. The real model
   resolved as `openrouter:minimax/minimax-m3`. Prepare failed open with the
   exact visible message `Memory is unavailable; continuing without injected
   context.` The agent independently called `search_memory` twice; both calls
   returned `no matching memories`.
3. I watched the agent inspect the empty location, write the package and tests,
   and run them. Its first suite exposed two defects: a missing `__slots__`
   member and a test helper emitting JSON arrays rather than objects. It fixed
   both and reached 47/47. Screenshot: `02-agent-working.png`.
4. Its optional manual demo then consumed attention on several incorrect demo
   assertions and two location-fence refusals. I did not erase that time or
   spend. While the first turn was still narrating the demo, I ran the project
   suite and the already-frozen acceptance externally. Both passed at
   `2026-08-27T19:26:41Z`; that is the metric stop.
5. The first turn ended eight seconds later with
   `partial=true, stop_reason=budget_exceeded`. I sent one bounded owner
   follow-up: no edits, no tools, summarize only. It ended normally and
   reported that no Palace memory was saved. Screenshot:
   `03-build-complete.png`.

Unscripted exploration: I tried a unique loopback hostname to isolate browser
storage completely. The top-level shell loaded but its `rack.localhost` frames
initially rendered connection refusals, so I abandoned that route without a
prompt and used `localhost` plus an explicit fresh thread. This changed no
product, Palace, or owner browser data.

## Raw result

| Metric | M3BT1 round-one baseline | M3B2 round two |
|---|---:|---:|
| Build time | 608.438 s | 337.776 s |
| True building cost | not recorded by the old build stream | $0.071068620000 |
| Churn | 828 | 1,170 |
| Own tests, final | 41/41 | 47/47 |
| Frozen acceptance, final | 8/8 | 8/8 |

The current build used 86 priced building receipt lines with zero unpriced
through the passing checkpoint. The summary-only turn raised full-thread
building spend to `$0.074193600000` across 90 priced lines. The failed memory
prepare/search path produced one separate embedding line for `$0.000004480000`;
it is not in build spend.

**True tagline:** second build: **-44.5% time, cost delta unavailable
(`$0.07106862` honestly measured now), +41.3% churn; final pass rate stayed
100%.**

An honest cost percentage cannot be computed. M3BT1 round one recorded only
`$0.00001882` of embedding receipts because its model lanes had no dollars;
comparing that partial number to M3B2's now-complete build cost would be false.

## Did round-one lessons inject?

No. M3BT1's own cleanup tombstoned all four experiment memories, and this exact
principal had zero active units before and after M3B2. Automatic prepare then
failed with `memory_unavailable`; the agent's two explicit searches both found
no matching memories. No lesson was injected, manually added, or newly saved.

There was no tuning. The deployed active scorer remained `m3f-location-v1`
with `tau=0.55`; the released Palace reported 3/25 authentic dispositions and
`floor_met=false` before and after. The deployed 0.1.5 Palace predates M3MS's
`memory_context_share`, so the share field was absent rather than moved. M3B2
observes this version boundary; findings freeze forbids compensating for it.

## Cleanup and scope

No experiment memory existed to tombstone. The verification principal still
had zero active memories after the run. The local Rack process stopped cleanly.
The disposable source, environment, journal, and scratch repository were moved
to the recoverable Trash location
`~/.Trash/nocturne-m3b2-b227-20260827T1929`. Remote spend receipts remain
append-only evidence. The bounded credential scan over committed evidence and
the scratch text was clean. Settled exit ground passed with Spine 285/285 and
Harness 1680 passed with the three explicitly live contract tests deselected.

This packet ends at findings. It makes no product, scorer, share, threshold, or
Palace change.
