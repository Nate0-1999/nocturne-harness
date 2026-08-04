# H4 verification — responsive Web shell and chat

H4 implements the browser side of C.7, Garden A-017/A-018, and ADR-009's
phone requirement. This is builder evidence, not the independent M1 judge
verdict reserved by SPEC B.6. The deterministic fixture mounts the production
FastAPI app, production `/ws` route, and production `RunLoop`; only its model
runner and out-of-band turn-release controls are test doubles.

## Reproduce the browser fixture

Build the app, then run the fixture from the Harness repository root:

```sh
npm run build --prefix web
PYTHONPATH=src:. uv run --locked python -m verification.run_fixture \
  verification.h4.scenario_app:create_scenario_app --port 8764
```

The scenario controls used by the browser pass are:

```sh
curl -X POST http://127.0.0.1:8764/__scenario__/reset
curl -X POST http://127.0.0.1:8764/__scenario__/release/primary
curl -X POST http://127.0.0.1:8764/__scenario__/release/secondary
```

The first deterministic prompt streams and waits at `primary`; the second is
queued and waits at `secondary`; the third streams until Stop cancels it.
Budget and provider-error prompts terminate with distinct partial states.

## Experiential evidence

The real built SPA was driven through the real WebSocket in the in-app browser
at both required viewports. Every image below is verified JPEG/JFIF with an
extension that matches its bytes.

| State | 1440×900 | 390×844 | Result |
|---|---|---|---|
| Local catalog / empty thread | [01](01-empty-desktop.jpg) | [09](09-threads-mobile.jpg), [10](10-empty-mobile.jpg) | PASS |
| Incremental text, thinking, and usage | [02](02-streaming-desktop.jpg) | [11](11-streaming-mobile.jpg) | PASS |
| Prompt queued at the turn boundary | [03](03-queued-desktop.jpg) | [12](12-queued-mobile.jpg) | PASS |
| Reload hydrates once from snapshot | [04](04-rehydrated-desktop.jpg) | [13](13-rehydrated-mobile.jpg) | PASS |
| Prior done precedes queued start | [05](05-turn-boundary-desktop.jpg) | exercised in the same mobile run | PASS |
| Stop preserves and labels partial work | [06](06-cancelled-desktop.jpg) | [14](14-cancelled-mobile.jpg) | PASS |
| Budget and provider-error boundaries stay distinct | [07](07-terminal-boundaries-desktop.jpg) | [08](08-terminal-boundaries-mobile.jpg) | PASS |

At 390×844 the document reported `scrollWidth=clientWidth=390`; at 1440×900
it reported `scrollWidth=clientWidth=1440`. The composer stayed visible, its
Send/Queue control measured 88×44 CSS pixels, and the browser console contained
no warning or error. Opening the phone thread view focused Back, made the
obscured chat inert, closed on Escape, and restored focus to Threads.

Reload assertions counted three visible message rows before and after the
active-plus-queued desktop and mobile reloads, proving snapshot replacement did
not duplicate the transcript. A separate read-only integration audit exercised
A-018's attach-snapshot/request-snapshot race and found the volatile outbound
overlay preserves pre-ack prompt text without weakening snapshot authority or
resubmitting after reload.

## Traced and adversarial evidence

[`trace.jsonl`](trace.jsonl) is the daemon-side trace for the same final desktop
queue, reload, boundary, and cancellation run:

- `prompt.queued` reserves the second run once;
- the two reload snapshots contain the same three ordered rows and the same
  active/queued IDs;
- the first `run.done(end_turn)` is immediately followed by the reserved
  second `run.started`;
- cancellation records the preserved text, runner cancellation, and exactly
  one `run.done(cancelled, partial=true)`; no later delta or usage follows.

The backpressure path is covered by `tests/test_run_loop.py` and
`tests/test_daemon.py`: subscriber or connection-outbox overflow detaches only
that client, closes it with 1013 `snapshot resync required`, and retains
authoritative daemon state for snapshot recovery. Final focused asyncio-debug
execution completed 43 tests with RuntimeWarnings fatal.

## Repository gates — 2026-07-20

```text
Harness non-contract suite        220 passed, 2 deselected
Loop/daemon asyncio-debug suite    43 passed
Live migrated Spine contract       2 passed
Sibling Spine inherited ground   158 passed
Web ESLint                          passed
TypeScript + Vite production build passed (24 modules)
Ruff lint / format                  passed (26 files formatted)
uv lock / M1 scope / diff checks    passed
```

The live contract teardown left no H2 container, network, or image. Three
independent read-only audits covered wire overflow/races, browser state and
snapshot ordering, and visual/mobile accessibility. Their concrete findings
were fixed and re-audited; no blocker remained.
