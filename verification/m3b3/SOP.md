# M3B3 — build test, round three

I ran this as a continuing build experiment, not as a product-change packet.
The point was to finally put both dials on the same honest scale: true build
cost against round two, and memory carryover against the same principal.

## Protocol

I restored the four exact round lessons that M3BT1 had tombstoned. That cleanup
was incompatible with this owner-fired continuity experiment. I then cloned
fresh Harness and Spine sources, created an empty scratch Git repository, and
froze an eight-test external acceptance before the build.

The real owner prompt asked `openrouter:minimax/minimax-m3` to build `inireport`,
a standard-library CLI that parses strict INI and writes a deterministic,
escaped, redacted HTML audit atomically. The task was similar enough to test
carryover but materially different from the prior Markdown/JSONL builds.

The initial gate automatically injected nothing. It surfaced three near
misses. I added back the two relevant CLI lessons and left the static-site link
lesson out. Those two memories were then injected and kept on later turns.
That is genuine carryover participation after an informed owner choice, but it
is not a natural initial threshold crossing.

The ordinary agent's first run built the project and found a real parser bug,
then hit its budget. One ordinary continuation fixed the parser and several
self-authored test mistakes. The agent's suite passed 52/52. At the fixed
checkpoint I ran that suite and the frozen acceptance concurrently; the later
completion was the acceptance pass at 2026-08-31T19:09:20.856821Z.

Both build runs ended `budget_exceeded`; neither was relabeled as a clean agent
finish. The externally observed artifact nevertheless reached the complete
exit contract. The agent began emitting three `save_memory` tool calls before
the second budget stop, but they were not executed. After the pass I used one
ordinary `/remember` owner command to persist the two genuinely reusable
configparser lessons as a single atomic fact. Its $0.000292920000 remember cost
and $0.000001520000 embedding cost are recorded separately after the metric
boundary.

## Four metrics

| Metric | M3B2 | M3B3 | Delta |
|---|---:|---:|---:|
| Time to first full pass | 337.776s | 645.723s | +91.169% |
| True building cost | $0.071068620000 | $0.178117200000 | +150.627% |
| Churn | 1,170 lines | 1,038 lines | -11.282% |
| Final pass rate | 100% | 100% (60/60) | 0 points |

The building cost contains 159 priced receipt lines and zero unpriced lines.
The full thread at close, including embedding and the post-pass remember
completion, cost $0.178435520000 across 172 priced lines. Accounting was clear
with zero pending lines.

Honest tagline: **third build: +91.2% time, +150.6% true build cost, -11.3%
churn; final pass rate stayed 100%. Carryover began as 0 automatic injections,
3 near misses, and 2 owner add-backs.**

## Observations only

- Active scorer: `m3ms-share-v1`; tau 0.55; memory-context share 0.10.
- Learning remained below floor at 3/25; share tuning remained inactive.
- No scorer, share, threshold, law, Palace, or product value was changed.
- The final Memory Palace showed five active units: all four carried lessons
  plus the new configparser fact. No experiment memory was tombstoned.
- The live Stage composer invalidated its newly selected thread snapshot before
  submit and displayed “The prompt was not sent.” I did not fix that product
  regression under findings freeze. I used the released owner WebSocket
  contract instead; it retained the same daemon, gate, journal, provider, and
  spend ledger.
- My first exit Spine invocation omitted the host Testcontainers socket
  override and produced 126 setup errors when Ryuk tried to mount the Colima
  socket path. I reran the same suite with the documented host-ground override;
  291 tests passed. Harness passed 1,688 tests with 3 live contracts deselected.

## Evidence boundary

The screenshots show continuity before the build, the first real gate, the
agent at work, and the final live Rack. `trace-summary.json`, the two test
summaries, scorer and spend summaries, and `memory-final.txt` carry the bounded
machine-readable facts. The disposable project remains under
`/tmp/nocturne-m3b3-b331-dfqWrY` until local cleanup; no source from that
scratch repository is promoted into Harness.

The local verification daemon was stopped after the final captures.

