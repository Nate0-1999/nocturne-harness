# H8 verification — Markdown, resolved model, and memory keywords

Status: **PASS — SCRIPTED REGRESSION AND SCREENSHOT-COMPLETE LIVE SOP EXECUTED
2026-07-30**

H8 adds three gate-day improvements:

1. sanitized Markdown for assistant messages while user messages remain plain;
2. the thread's daemon-resolved model in the header; and
3. 2–5 generated keywords on every `/remember` save.

This package keeps SPEC B.6 rules 7 and 8 separate. `browser_check.mjs` is the
repeatable browser regression: it drives the built production SPA with real
browser clicks and sequential keystrokes, asserts rendered outcomes, captures
screenshots, traces the exact memory save, and performs exact-ID cleanup.
`SOP.md` is the independently executed first-person Chrome walkthrough. The
live SOP was not discharged by the script.

The fixture mounts the production SPA, `/ws` daemon route, `RunLoop`,
`MemoryGateTurnRunner`, direct `/remember` path, and configured deployed Spine.
Only the downstream model is a deterministic `FunctionModel`. Its resolved slug
is `local:h8-verification`. A fixture process refuses a second memory before
the first exact ID is cleaned.

## Proven outcomes

- Before a dynamically resolved H9 thread starts, `thread.snapshot` carries
  `resolved_model: null` and the UI truthfully shows its waiting state. Both
  `run.started` frames, and every later hydrated snapshot, carry the exact
  `resolved_model` shown by the UI.
- `/remember` makes one tools-free metadata completion containing one label and
  exactly `["markdown", "tables", "code"]`.
- The same keywords land in the C.4 create request and returned ACTIVE unit.
- Assistant headings, emphasis, lists, GFM table, and fenced code render with
  the theme's typography.
- Literal raw `<button>` and `<script>` input creates no matching DOM and
  executes no script.
- User asterisks and raw tags remain literal plain text.
- The complete model slug remains visible at 390×844.
- The 390px document has no page-level horizontal overflow; visible actions are
  at least 44px high; table and code surfaces remain reachable.
- Desktop and mobile browser consoles are clean.
- All six created verification IDs were CAS-tombstoned by exact UUID and no
  exact fixture ID remained ACTIVE.

## Repeat the scripted check

From the Harness repository root, first build the production SPA:

```sh
npm run build --prefix web
```

Start one fresh fixture process per viewport. The command fails closed when
`SPINE_TOKEN` is absent and otherwise reads the ignored local `.env`:

```sh
PYTHONPATH=src uv run --locked uvicorn \
  scenario_app:create_scenario_app --factory \
  --app-dir verification/h8 --host 127.0.0.1 --port 8770
```

In another terminal:

```sh
npm run verify:h8:browser --prefix web -- \
  --base-url http://127.0.0.1:8770 --mode desktop
uv run --locked python verification/h8/assert_trace.py \
  verification/h8/trace-scripted-desktop.jsonl
```

Stop that fixture, start a fresh one on another origin, and repeat with
`--mode mobile`. Mobile mode creates a real 390×844 Chrome context. The script
always checks fixture health in `finally`, exact-ID tombstones any created
memory, preserves the trace, and closes Chrome even when an assertion fails.

## Scripted evidence — B.6 rule 7

- `browser_check.mjs`
- `assert_trace.py`
- `rendered-scripted-desktop.json`
- `rendered-scripted-mobile.json`
- `scripted-desktop-01-remember-1440x900.png`
- `scripted-desktop-02-markdown-1440x900.png`
- `scripted-mobile-01-remember-390x844.png`
- `scripted-mobile-02-markdown-390x844.png`
- `trace-scripted-desktop.jsonl`
- `trace-scripted-mobile.jsonl`
- `cleanup-result-scripted-desktop.json`
- `cleanup-result-scripted-mobile.json`

Both scripted traces pass `assert_trace.py` with 18 records each.

## Live evidence — B.6 rule 8

The final live rerun used the connected Chrome extension for navigation, every
product click and keystroke, screenshots, and read-only rendered inspection.
Chrome's explicit viewport control produced true 390×844 and 320×844 evidence
without DevTools or a second input mechanism. No product action used HTTP,
WebSocket calls, DOM injection, scripted locator actions, or direct state
mutation.

- `SOP.md`
- `05-arrival-desktop.png`
- `06-remember-desktop.png`
- `07-gate-desktop.png`
- `08-continued-desktop.png`
- `09-markdown-desktop.png`
- `10-inspection-desktop.png`
- `11-arrival-mobile-390x844.png`
- `12-remember-mobile-390x844.png`
- `13-gate-mobile-390x844.png`
- `14-continued-mobile-390x844.png`
- `15-markdown-mobile-390x844.png`
- `16-inspection-mobile-390x844.png`
- `17-explore-reload-mobile-390x844.png`
- `18-explore-thread-switch-mobile-390x844.png`
- `19-explore-thread-return-mobile-390x844.png`
- `20-explore-narrow-320x844.png`
- `21-explore-memory-drawer-320x844.png`
- `22-explore-unsent-input-320x844.png`
- `23-explore-restored-mobile-390x844.png`
- `rendered-live-desktop-rerun.json`
- `rendered-live-mobile-rerun.json`
- `trace-live-desktop-rerun.jsonl` — 18 records, assertion PASS.
- `trace-live-mobile-rerun.jsonl` — 22 records including reload/thread
  hydration, assertion PASS.
- `cleanup-result-live-desktop-rerun.json`
- `cleanup-result-live-mobile-rerun.json`

Final desktop fixture:

- principal `h8-verification-0bba5c7148344f67bcc1b75b71b8db2c`
- threads `e28c7318-ba5f-45dc-8e4d-330535aec09a` and
  `be3274b4-4530-4b8a-ae3b-0cdd719a41c8`
- cleaned memory `aa7c8d13-4aef-476b-b950-1fca06ebcda7`

Final mobile fixture:

- principal `h8-verification-d7b5757509cf42ee8e0494dbba3c0fa1`
- threads `3728a769-2955-4153-af7e-43db190871e4` and
  `a6d5476a-aea7-4119-b04e-1046e5f8e5b4`
- cleaned memory `57992b12-cc26-44a9-bcf0-73c5b518b9b1`

The earlier `01`–`04` screenshots, `rendered-live-{desktop,mobile}.json`,
`trace-live-{desktop,mobile}.jsonl`, and matching cleanup receipts remain as
historical successful-use evidence. They are not relied on to satisfy the
per-step screenshot requirement.

## Cleanup boundary

The fixture never deletes, bulk-mutates, or cleans by principal. It retains the
exact UUID returned by the product's `/remember` save, refuses a second save
until that ID is closed, retries a cleanup CAS only for the same UUID, patches
it to `TOMBSTONED`, and lists only to confirm that exact UUID is absent from
ACTIVE results.
