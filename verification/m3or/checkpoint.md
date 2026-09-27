# M3OR verification

The fifteen charged browser walks passed on public 0.1.36 and the installed
repair candidate, using a disposable home and real Palace/OpenRouter.
The earlier browser blocker and failed model attempts remain as before evidence.

Repairs: retain empty accepted commits; point judges at candidate directories
and require grounded feedback with no candidates; archive only the latest
snapshot per message ID. No other feature code changed.

`walk-observations.json` is the fifteen-row verdict table. `gallery.html` links
each capture. `browser-runtime-traces.tar.gz` contains the real worker contexts,
round plans, supervisor events and durable browser-thread transcripts.
`receipts/browser/` contains complete stack records and archive before/after counts.
`runtime-traces.tar.gz` retains the first discovery and candidate runs.

`ledger-report.json` accounts for the final diff: 17 required rows, one PASS
and 16 explicit context-only FAIL/F086. This coverage accounting does not erase
unrepeated gestures outside the fifteen-row charge.

The browser used the prior packets' Playwright pattern with persistent state.
`walk.mjs` packages the executed launch/result/archive gestures as a replay;
it requires an already running disposable app and a signed-launch JSON fixture.
The death watcher additionally checks the exact worker command before SIGKILL.

Validation: 1,798 Harness tests passed, 4 skipped, 3 live-contract tests deferred
to hosted CI; 322 Memory tests passed, 3 skipped; 158 web unit tests passed.
The first suite overlapped the version bump and failed only its metadata assertion;
the complete rerun against the fixed pair passed. UI canon and release receipts
are recorded separately when complete.
