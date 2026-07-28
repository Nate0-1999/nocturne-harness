# H6 live memory-panel walkthrough

Status: **PASS WITH RECORDED FRICTION**

This is the first-person record for SPEC B.6 rule 8. It must be completed only
after a runner drives the production SPA and WebSocket daemon through the
connected Chrome extension against deployed Spine. The deterministic trace is
rule-7 evidence; it cannot substitute for this rendered, human-style pass.

## Session record

- Runner / session: Codex relay, driving the connected Chrome extension
- Date and local time: 2026-07-28, 16:27–16:41 CDT
- Built commit: final implementation `1b2311e`; both canonical browser paths
  ran on a fresh build of that exact commit.
- Deployed Spine health: authenticated typed C.4 seed, list, prepare, commit,
  feedback, PATCH/conflict, and exact cleanup calls all succeeded against the
  configured Cloud Run Spine.
- Fixture principal: `h6-verification-a2098db9693247ee9677e7cb0c6c155b`
- Desktop thread ID: `82ca2138-737a-4e1f-a339-c987c71f9dad`
- Mobile thread ID: `cd422290-c9bf-463c-a8d9-7f67672701b1`
- Browser and viewports: Chrome at 1440×900 and 390×844
- Browser console: zero warnings and zero errors at both viewports
- Evidence trace paths: `trace-desktop.jsonl` and `trace-mobile.jsonl`

## Desktop walkthrough — 1440×900

### 1. Arrive and identify the panel

- Action: I opened `http://127.0.0.1:8766`, created a fresh thread, and read
  the visible shell before acting.
- Screenshot: `01-active-list-desktop.png` after the first gate commit.
- Observe: Is Memory clearly a live product surface rather than an admin dump?
  Is the relationship between the thread and the right-hand panel legible?
- First-person observation: I read the panel as a product rail, not a database
  dump. “Current principal,” the active count, and the In context / Stored
  states made its relationship to the open thread legible. The rail is dense
  by design, but its hierarchy stayed restrained beside the transcript.
- Judgment: **PASS**

### 2. Establish a frozen thread context

- Action: I typed `Open the H6 verification thread context.`, reviewed the real
  first-turn memory gate, changed no card decisions, and clicked Continue.
- Observe: Before Continue, does the model remain stopped? After Continue, does
  the deterministic answer say retain/remove/frozen-edit are present and the
  newly-pinned marker is absent? Does the panel then show exactly five units,
  with remove/retain/edit marked In context and conflict/pin Stored? Is the
  foreign sentinel absent?
- First-person observation: The model remained stopped until I clicked
  Continue. The first answer reported retained, removed, and frozen-edit
  markers present and the newly pinned marker absent. The panel then contained
  exactly the five fixture units: remove, retain, and edit were In context;
  conflict and pin were Stored; the foreign-principal sentinel was absent.
- Judgment: **PASS**

### 3. Remove from this conversation, not storage

- Action: I clicked Remove once on `H6 thread context — remove`.
- Screenshot: `02-removed-context-desktop.png`.
- Observe: Does that card remain visible as Stored, lose only its current
  context action, and leave `H6 thread context — retain` In context? Is the
  result copy understandable without knowing `mid_thread_removed`?
- First-person observation: The action copy said it removed the memory from
  this thread’s next model context. The card stayed visible as Stored and lost
  its Remove action; the retained card stayed In context. I did not have to
  know the protocol signal name to understand the result.
- Judgment: **PASS**

### 4. Edit one body and pin one stored unit

- Action: I opened `H6 panel edit`, replaced its body with
  `H6 edit saved through the memory panel with compare-and-swap.`, clicked Save
  body, closed the editor, and clicked Pin on `H6 panel pin`.
- Screenshot: `03-edit-and-pin-desktop.png`.
- Observe: Is editing direct and recoverable? Are saved body, revision change,
  and Pinned badge visible? Does the edited unit remain In context while the
  newly pinned unit remains Stored?
- First-person observation: The edited body was visible at revision 4 after
  revision 3, and the separate pin card gained a Pinned badge at revision 2.
  The edit card remained In context while the newly pinned card remained
  Stored. The success copy explicitly said both mutations apply to future
  injections and do not rewrite this thread’s committed copy.
- Judgment: **PASS**

### 5. Encounter a real concurrent edit

- Action: I opened `H6 panel conflict`, typed
  `H6 draft that must survive a visible revision conflict.`, left the editor
  open, called the fixture's `/__scenario__/stage-conflict` control, returned,
  and clicked Save body exactly once.
- Screenshot: `04-conflict-desktop.png`.
- Observe: Does the panel name a revision conflict, show the current revision
  and current body, preserve my draft, and require an explicit Retry save? Is
  it clear that no silent merge or automatic retry occurred?
- First-person observation: The real 409 named a revision conflict, showed the
  server’s current revision and winning body, preserved my draft, and changed
  the action to Retry save. Nothing retried or merged without another click.
- Judgment: **PASS**

### 6. Prove immediate next-call context

- Action: I canceled the preserved conflict draft and typed
  `Report which H6 context markers are present now.`.
- Screenshot: `05-next-call-desktop.png`.
- Observe: Does the model report retained and frozen-edit present, but removed
  and newly-pinned absent, with no new gate? That combination proves the stored
  edit and new pin did not rewrite the frozen thread block. Does the transcript
  remain coherent while the desktop panel stays visible?
- First-person observation: The second answer reported retained and the
  original frozen-edit marker present, with removed and newly pinned absent.
  The saved replacement body was also absent. No second gate opened, and the
  transcript remained coherent beside the live panel.
- Judgment: **PASS**

## Phone walkthrough — 390×844

After exact-ID cleanup and a fresh seed, I repeat the same canonical path in a
fresh thread at 390×844. I use the visible Memory trigger to open the drawer;
I do not call hidden DOM methods.

- Active list screenshot: `06-active-list-mobile-390x844.png`
- Removed-state screenshot: `07-removed-context-mobile-390x844.png`
- Conflict screenshot: `08-conflict-mobile-390x844.png`
- Next-call screenshot: `09-next-call-mobile-390x844.png`
- Document `scrollWidth/clientWidth`: `390 / 390`
- Panel scroll dimensions: `1031 / 655` (`scrollHeight / clientHeight`);
  I reached every one of the five units by scrolling.
- Smallest actionable control: `44px`; no visible actionable control measured
  below 44×44 CSS pixels after the composer correction.
- Focus trap and return behavior: Opening focused Back; Shift-Tab wrapped to
  the last visible Remove control; Tab wrapped to Back; closing and Escape
  returned focus to the Memory trigger with `aria-expanded=false`.
- First-person observation: The drawer felt like a full-screen phone
  workspace rather than a clipped desktop rail. All five units and the saved,
  removed, conflict, and next-call states remained reachable. There was no
  horizontal overflow and no console warning or error.
- Phone judgment: **PASS**

## Unscripted exploration — required

Start and end time: 16:35:43–16:40:53 CDT (five minutes, ten seconds) on the
final mobile build.

- Actions I chose without following the canonical script: After the successful
  edit, I used Refresh and watched the pending state settle to the unchanged
  revision-4 authoritative body and context split. I opened an editor on the
  Stored removed unit, typed an unsaved draft, and pressed Escape. I reloaded
  the page, confirmed the four-message thread snapshot returned with no Memory
  body editor and the canonical stored body intact, created a fresh local
  thread and saw all five units marked Stored, then returned to the original
  thread and saw its exact In context / Stored split restored. I also traversed
  both ends of the drawer focus loop and audited the actual control rectangles.
- Screenshot: `10-unscripted-exploration.png`
- What surprised me: Mutations update `updated_at`, so the stable C.4 ordering
  can move a card after a refresh. That is correct, but the movement is mildly
  disorienting. On phone, Escape from an open editor closes the whole Memory
  drawer as it discards the draft; that is safe and recoverable, but broader
  than I expected from the editor itself.
- What recovered cleanly: The unsaved draft never wrote or resurrected;
  reload preserved the transcript and thread context; the mobile drawer
  trapped and returned focus; and local thread switching restored the
  server-authoritative relationship state. The final build measured 44px or
  larger for every visible action, with no short controls.
- What felt awkward or ambiguous: The desktop rail is intentionally dense and
  requires scrolling, and cards can reorder after mutation. Neither obscured
  an action or state.
- Judgment: **PASS WITH RECORDED FRICTION**

Useful safe seams to explore include resizing with an editor open, Escape and
backdrop behavior in the mobile drawer, tab and reverse-tab traversal, a
refresh after a successful mutation, closing/reopening a preserved editor,
switching between local threads, attempting Remove on a Stored unit, and
reconnecting after a drawer is open. Do not mutate non-fixture rows, retry the
canonical conflict, or turn the unscripted segment into scripted DOM calls.

## Trace and cleanup closure

- Desktop trace assertion:
  `uv run --locked python verification/h6/assert_trace.py verification/h6/trace-desktop.jsonl`
  — **PASS, 62 records**
- Mobile trace assertion:
  `uv run --locked python verification/h6/assert_trace.py verification/h6/trace-mobile.jsonl`
  — **PASS, 72 records**
- `trace.jsonl` is an exact byte-for-byte copy of the final mobile trace.
- Browser console final state: zero warnings and zero errors at both viewports
- Desktop layout: 1440×900 with a persistent, independently scrollable memory
  rail and no page overflow
- Phone layout: 390×844, document width exactly 390px, scrollable focus-trapped
  drawer with `1031 / 655` scroll dimensions, and 44px minimum visible controls
- Exact-ID cleanup response:
  [desktop](cleanup-result-desktop.json) and
  [mobile](cleanup-result-mobile.json) each tombstoned only their six fixture
  IDs and reported `remaining_active_ids: []`.
- Visual-evidence note: the first fresh conflict images clipped the server
  body and Retry action below the desktop rail and phone drawer folds. I
  replaced only those images from separate fresh browser runs, scrolled each
  visible surface, then exactly tombstoned each run's six fixture IDs. The
  durable receipts are
  [desktop recapture](cleanup-result-desktop-conflict-recapture.json) and
  [phone recapture](cleanup-result-mobile-conflict-recapture.json).
  `04-conflict-desktop.png` and `08-conflict-mobile-390x844.png` now show the
  preserved draft, current body, and explicit Retry save.
- Fixture process stopped: yes, cleanly after every exact cleanup
- Remaining product friction: Correct C.4 reordering after a mutation can move
  the card the user just acted on; the desktop rail is dense enough to require
  deliberate scrolling. The 32px composer target found during exploration was
  fixed and recorded in Decision 015 before handoff.
- Overall H6 builder verdict: **PASS WITH RECORDED FRICTION**
