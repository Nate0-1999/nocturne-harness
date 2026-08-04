# H6 verification — live memory panel

H6 implements the principal-scoped memory panel and current-thread context
control required by SPEC C.4/C.6/C.7 and A-024. This package supplies the
deterministic feature trace required by SPEC B.6 rule 7 and the live-browser
walkthrough required by rule 8. It is builder evidence, not the independent M1
judge verdict.

## Executed result — 2026-07-28

The connected Chrome extension drove the production SPA and WebSocket path
against deployed Spine at 1440×900 and 390×844. The result is **PASS WITH
RECORDED FRICTION**; see [SOP.md](SOP.md) for the first-person record.

- Final implementation: Harness `1b2311e`
- Desktop trace: **PASS, 62 records**
- Mobile trace: **PASS, 72 records**
- Canonical cleanup: six desktop and six mobile fixture IDs tombstoned, with
  zero fixture IDs still ACTIVE after each run. Separate fresh desktop and
  phone conflict-image recaptures also exactly tombstoned their six fixture
  IDs apiece.
- Harness: **293 passed, 2 deselected**; Spine: **160 passed**
- Web lint/build, Ruff lint/format, both lock checks, repository scope fence,
  and diff checks: **PASS**
- Browser console: zero warnings and zero errors at both viewports
- Layout: no overflow at 390×844, every visible action at least 44×44px, and
  mobile focus trapped and returned correctly

The remaining friction is limited to correct-but-disorienting card reordering
after a mutation, the deliberately dense desktop rail, and mobile Escape
closing the whole Memory drawer when an editor is open. The draft is discarded
without a write and does not resurrect after reload. Earlier pre-final use
found a 32px composer textarea target; this fresh final-build pass measured
every visible action at 44px or larger. Decision 015 records that correction.

The fixture keeps the production SPA, `/ws` daemon route, `RunLoop`,
`MemoryGateTurnRunner`, `MemoryPanelController`, pydantic-ai history path, typed
C.4 client, and deployed Spine configured by the ignored `.env`. Only
the downstream chat model is replaced with a deterministic `FunctionModel`.
The trace records fixture roles, exact fixture IDs, and booleans or hashes at
privacy-sensitive seams; it never writes a credential or an unfiltered Spine
row.

## What the fixture proves

- The panel shows exactly the five ACTIVE units for its fresh configured
  principal. A sixth synthetic unit under another fresh principal is a
  negative isolation sentinel and must never render.
- Three pinned units are committed into the first thread context. Removing one
  uses the daemon-held injection ID and `mid_thread_removed`, leaves the unit
  ACTIVE and visible as **Stored**, and preserves the others as
  **In context**.
- The immediate next model call receives exactly one current memory block:
  the retained marker remains and the removed marker is absent.
- Body edit and pin toggle each make one successful CAS PATCH with
  daemon-derived `editor=user`, `reason=panel/*`, and machine identity. The
  edited current-context fragment stays frozen at its committed value, while a
  newly pinned Stored unit does not enter the already-open thread.
- A concurrent C.4 PATCH advances the conflict fixture. The stale browser save
  produces a real 409; the current unit reaches the browser, the draft remains
  available, and the daemon does not retry.
- Cleanup CAS-tombstones only the six exact seed IDs and verifies that none
  remain ACTIVE.

## Start and seed

From the Harness repository root:

```sh
npm run build --prefix web
PYTHONPATH=src:. uv run --locked python -m verification.run_fixture \
  verification.h6.scenario_app:create_scenario_app --port 8766
```

The command intentionally fails closed when `SPINE_TOKEN` is absent. It reads
`SPINE_URL` and `SPINE_TOKEN` from the ignored `.env`, then overrides only the
principal, machine, agent, and one-token verification context. Its machine ID
is `h6-sop-verification`, keeping the synthetic run identifiable as
verification traffic.

In another terminal:

```sh
curl -fsS -X POST http://127.0.0.1:8766/__scenario__/seed
curl -fsS http://127.0.0.1:8766/__scenario__/expectation
```

Seed before opening the browser. `force=true` guarantees fresh fixture rows;
there is no list-and-delete setup. The three context fixtures are patched to
`pin=true`, while the one-token context guarantees that the two ordinary
fixture rows are near misses. The isolation sentinel uses a different
synthetic principal.

## Canonical browser path

Open `http://127.0.0.1:8766`, create a fresh browser-local thread, and send:

```text
Open the H6 verification thread context.
```

At the first-prompt memory gate, leave all three injected cards selected, leave
both near misses out, and choose **Continue**. The first deterministic answer
must report the retained, removed, and frozen-edit markers present and the
newly-pinned marker absent.

The desktop panel should now show five active units. `H6 thread context —
remove`, `H6 thread context — retain`, and `H6 panel edit` must say
**In context**; the conflict and pin fixtures must say **Stored**.
`H6 foreign-principal sentinel` must be absent.

Perform these product actions through visible controls:

1. On `H6 thread context — remove`, choose **Remove**. It remains listed as
   **Stored**, loses its Remove action, and the retained card stays
   **In context**.
2. On `H6 panel edit`, choose **Edit body**, replace the body with the exact
   text below, and choose **Save body**:

   ```text
   H6 edit saved through the memory panel with compare-and-swap.
   ```

3. On `H6 panel pin`, choose **Pin** and observe the **Pinned** badge.
4. On `H6 panel conflict`, choose **Edit body**, replace the draft with:

   ```text
   H6 draft that must survive a visible revision conflict.
   ```

   Leave that editor open. From another terminal, advance the same fixture:

   ```sh
   curl -fsS -X POST http://127.0.0.1:8766/__scenario__/stage-conflict
   ```

   Return to the browser and choose **Save body** once. Confirm the visible
   current body is `H6 concurrent editor won this revision before panel save.`,
   the draft remains in the textarea, and the button changes to
   **Retry save**. Do not retry during the canonical run.
5. Cancel the preserved conflict draft, return to chat, and send:

   ```text
   Report which H6 context markers are present now.
   ```

The second deterministic answer must report the retained and original
frozen-edit markers present, while the removed and newly-pinned markers are
absent. The new stored edit body must not appear in the model context. No new
memory gate should open.

## Trace assertion and exact cleanup

After capturing the completed product state, cleanup and assert:

```sh
curl -fsS -X POST http://127.0.0.1:8766/__scenario__/cleanup \
  | tee verification/h6/cleanup-result.json
uv run python verification/h6/assert_trace.py
```

`assert_trace.py` requires the exact active list, principal isolation,
prepare/commit membership, feedback identity and signal, post-removal panel
state, first/next-call context markers, one successful edit, one successful pin
toggle, one real conflict with no panel retry, and exact-ID cleanup.

For append-only evidence, copy the trace only after cleanup and assertion:

```sh
cp verification/h6/trace.jsonl verification/h6/trace-desktop.jsonl
uv run python verification/h6/assert_trace.py verification/h6/trace-desktop.jsonl
```

For the 390×844 pass, call seed again, create a fresh thread, repeat the
canonical path, cleanup, assert, and copy to `trace-mobile.jsonl`.

## Required visual evidence

Drive the built product through the connected Chrome extension, with real
clicking and typing rather than scripted DOM or HTTP product actions. Setup,
the deliberate concurrent edit, and cleanup remain fixture-control calls.

Capture append-only images under this directory:

- `01-active-list-desktop.png` — five current-principal units, exact
  In-context/Stored badges, and no sentinel.
- `02-removed-context-desktop.png` — removed unit still Stored and retained
  unit still In context.
- `03-edit-and-pin-desktop.png` — saved edited body remains In context and the
  separate Stored unit gains a persisted Pinned badge.
- `04-conflict-desktop.png` — current revision/body, preserved draft, and
  explicit Retry save.
- `05-next-call-desktop.png` — deterministic next-call answer says retain
  present/remove absent.
- `06-active-list-mobile-390x844.png` — opened Memory drawer at 390×844.
- `07-removed-context-mobile-390x844.png` — mobile removal state.
- `08-conflict-mobile-390x844.png` — mobile conflict and preserved draft.
- `09-next-call-mobile-390x844.png` — mobile next-call answer.
- `10-unscripted-exploration.png` — one representative state from the
  independent exploratory segment.

At both viewports verify document width equals client width, all actionable
controls are at least 44×44 CSS pixels, panel content can reach every unit,
the mobile drawer traps focus and returns it to the Memory trigger, the memory
gate remains modal, and the console has no warning or error.

The executed first-person record belongs in [SOP.md](SOP.md). Do not mark it
PASS from the scripted trace alone.
