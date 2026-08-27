# M3BC — true build-cost evidence

Date: 2026-08-27  
Session: `codex / 2026-08-27 / bc27`

## Why this packet exists

M3BT1 proved that the ordinary owner agent could complete substantial builds,
but its OpenRouter requests reached the spend path without native dollars. The
remaining gap was narrower than a new accounting system: OpenRouter can put
native cost only on its terminal usage-only SSE chunk, while Pydantic AI 2.28
retains token usage from that chunk but skips provider-detail mapping when
`choices` is empty.

The Harness-owned OpenRouter stream wrapper now retains the typed provider
billing fields at validation time. Existing Pydantic AI token normalization,
Harness receipt batching, Spine `spend_event`, and Rack Vitals remain the sole
accounting path.

## Deterministic regression

`test_sd023_openrouter_usage_only_chunks_price_every_build_request` drives a
real `PreservingOpenRouterModel` and `PydanticAITurnRunner` through a two-request
tool turn over `httpx.MockTransport`. Both responses put usage and cost only in
an empty-choice terminal chunk. The test proves that:

- both request identities reach the existing receipt batch;
- every emitted line is priced;
- input-fresh, input-cached, output, and reasoning lanes survive;
- native downstream-provider and `purpose=building` lineage survive; and
- exact native cost sums to `$0.007000000000` without a catalog estimate.

## Real Rack build

The source Rack ran against the configured remote Palace with a disposable
principal and workspace. From a fresh Rack thread, the owner asked the real
OpenRouter-backed agent to build and test `note_stats.py`, a small Markdown
statistics CLI. The agent used its ordinary workspace and shell tools, wrote a
seven-test unittest suite, ran it green, and ended normally.

| Field | Observed value |
|---|---|
| Thread | `38649a11-fe5c-42c2-a9f0-e574c2c6fc18` |
| Run | `01M129QJ8RQ7MGVNBXPKCX5GM4` |
| Model | `minimax/minimax-m3` through OpenRouter |
| Stop | `end_turn`, `partial=false` |
| Requests | 10 |
| Input tokens | 61,044 |
| Cached input tokens | 46,805 |
| Output tokens | 7,865 |
| Independent project check | 7/7 tests passed in 0.143 s |
| Latest Vitals build point | `$0.009913320000`, 26 receipt lines |
| Unpriced build lines | 0 |

`vitals-priced-build.jpg` is the captured owner view of the completed chat and
the Stage Spend instrument. `trace-summary.json` preserves the bounded raw
identities, hashes, counts, and query result without prompts, credentials, or
streamed tool payloads.

## Honest exception and cleanup

Memory preparation returned `memory_unavailable`, so chat failed open and the
build continued without injected context. The same minute contains one priced
`text-embedding-3-small` line for `$0.000001300000`; it is not counted as build
spend. The prompt explicitly prohibited saving a memory, and the run did not
enter a memory-save flow.

The Vitals reconciliation view also showed inherited broker-versus-ledger
drift of `-$0.786847782000`. M3BC does not claim to repair historical drift; it
proves that every request in this new build reaches the existing ledger priced.

The local Rack process was stopped after capture. The disposable home and
scratch workspace were moved to Trash after their hashes and bounded trace
summary were recorded. Remote spend receipts remain append-only verification
truth.
