# M2FX6 — bounded split-planning verification

Status: **EXECUTED / PASS** on 2026-08-13.

- Harness: `d360895` (`8f68f63` contains the M2FX6 implementation)
- Owner app: `harness.daemon:create_dev_app` on an isolated port and home
- Identity: principal and machine `m2fx6-sop-verification`
- Provider: real OpenRouter through the configured `openrouter:minimax/minimax-m3` route
- Palace: authenticated production Palace
- Source: the exact `LIVE_SPLIT_SOURCE` from `tests/test_agent.py`, submitted through the production WebSocket as one `/remember` turn

The tools-free split planner reached its 30-second server wall. At
`20:14:35.429Z` the daemon emitted the existing lossless no-write guidance once,
then emitted one `run.done` with `stop_reason=end_turn` and `partial=false` at
`20:14:35.432Z`. The turn took approximately 30.06 seconds from `run.started`.
The durable transcript ended with the same terminal state and contained no
provider-refusal or partial-save event.

Production Palace queries for the source and all three distinctive child facts
returned only the already-tombstoned M2XS verification family created on
2026-08-10. No M2FX6 source or child was written, so this run created no cleanup
debt. The isolated daemon was stopped and its disposable home was moved to Trash.

The in-app browser controller reported no available browser backend, so no
visual capture was possible. The reproduction used the real composed daemon,
production WebSocket, real OpenRouter route, durable journal, and authenticated
Palace rather than a fixture.
