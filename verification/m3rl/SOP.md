# Clean conversation rendering and recovery

PRECEDENT: PLAN M3RL; F070/F071 and the duplicated F073/F074 entries;
SPEC B.6/C.7; ancestors M3RS, M3B2, M3CP. The answer should be readable,
temporary Palace failures should recover, and names should survive restart.

## Walk procedure

Use the real packaged app with the initialized `/tmp/m3rl-verification/home`
and its distinct verification principal. Confirm `/v1/identity` first.
Use a fresh browser origin; do not capture old browser-local catalogs.

1. Create a thread in the disposable project. Ask minimax to solve a small
   reasoning problem. Continue the gate; inspect the answer and collapsed tools.
2. Ask it to create a tiny page, open it with its browser and take a screenshot.
   Inspect the image, then deliberately expand the event panel: no binary text.
3. Rename the project in the Conversation header. Reload and verify the label.
4. Create an empty thread, stop and restart the app, and inspect its name.
5. Inspect the screenshot at phone width; try an unsent draft and mode switch.
6. Separately, under a labeled regression fixture, provoke HTTP 429 and an
   ordinary read failure, then recover. Verify retry and source-matched clearing.

## Execution

2026-09-08, rl08. Packaged factory and built assets; real Palace and
`openrouter:minimax/minimax-m3`; principal
`nocturne-verification-cb49eb66-85cf-474c-b337-ca8fd4326c7f`.
The two real turns ended cleanly in `045f8f85-e829-4f65-b3d2-8d74169af9ab`.
The model used native thinking on this run; the permanent heartbeat and every
split-point unit regression supply literal tags. Do not claim the live provider
emitted literal tags on these two turns.

| Check | Result | Capture |
|---|---|---|
| Reasoning answer | PASS: no thinking delimiter in visible answer | [01](01-minimax-answer-no-thinking-tags.png) |
| Browser image | PASS: real write → navigate → screenshot; 1280×720 decoded image, Tools collapsed | [02](02-browser-image-collapsed-tools.png) |
| Expanded JSON | PASS: `image/png, 23 KB`, no raw PNG text | [03](03-expanded-tools-binary-elided.png) |
| Header rename | PASS: `Render proof` survives reload | [04](04-header-project-rename-persists.png) |
| Empty-thread restart | PASS: `69741227-9c42-4603-908e-8618913729c3` stays `New thread`, zero messages | [before](05-empty-thread-before-restart.png), [after](06-empty-thread-after-ctrl-c-up.png) |
| Temporary refusal | PASS under the labeled heartbeat fixture: busy, retry, recovered banner clears; unrelated success does not clear it | [07](07-busy-palace-retrying.png), [08](08-palace-recovered-banner-cleared.png), [trace](recovery.json) |
| Phone width | PASS for image/collapsed Tools at 390×844, using the existing Stage zoom/pan controls | [09](09-phone-browser-image-collapsed-tools.png) |
| Extra exploration | FAIL: `Unsent M3RL draft` is lost across Focused → Stack → Focused; no prompt sent | [before](10-draft-before-mode-switch.png), [after](11-draft-after-mode-switch.png) |

The first browser-image attempt revealed broken URL-safe base64 and placement in
the label column. Both were repaired before capture 02. Default-port browser
storage contained older catalogs; the main walk used the fresh 51942 origin.
Two setup-only empty IDs were persisted in this disposable home, without prompts.
The restart used ordinary `nocturne up --no-open`, SIGINT (Ctrl-C), then
`nocturne up --no-open` again;
the second startup succeeded after the previous listener released port 8765.
Capture 06 is explicitly cropped to the tested row/header to exclude old
browser-local catalog entries. No other screenshots use that mixed origin.
Port 8883 was briefly inspected read-only, identified as the peer's M3VI home,
and left alone. No verification prompts or captures came from it.

The recovery fixture reuses M3FP's visible curtain and deterministic dependencies.
Run `NOCTURNE_HOME=/tmp/m3rl-recovery .venv/bin/python -m uvicorn
verification.m3rl.recovery_app:create_scenario_app --factory --port 51943`, then
`node verification/m3rl/recovery_check.mjs http://127.0.0.1:51943 verification/m3rl`.
The backend test separately proves a real typed non-JSON Palace 429 preserves its
status/header. No artificial load was sent to the real Palace to force throttling.

Both full suites, web tests/lint/build and the full UI canon pass; logs are adjacent.
The motivation checker retains 31 inherited findings. [Journal summary](journal-summary.json)
keeps only each message's final revision. [Cleanup](cleanup.json) confirms zero
active memories, pending cards, admitted writes, pressure events or curator runs
for this principal. Contract tests clean their own disposable writes.
The verification tabs and daemons were closed, both disposable homes and the
generated project were removed, and no pending receipts remained. The credential
scan passed. No owner-home cleanup was attempted.
