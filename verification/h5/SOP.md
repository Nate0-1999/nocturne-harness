# H5 live agent walkthrough

Status: **EXECUTED — PASS WITH RECORDED FRICTION**

This is the human-style walkthrough required by SPEC B.6 rule 8. The browser
pass used the production SPA and WebSocket daemon against deployed Spine; only
the downstream chat model was deterministic. Observations below describe the
rendered pixels and interaction path, not just DOM assertions.

## Session record

- Runner / session: `codex / 2026-07-21 / a5e1`
- Date and local time: 2026-07-21, 12:33–12:51 CDT
- Built commit: H5 working tree based on `d65f945`; this record ships in the
  H5 relay commit.
- Deployed Spine health observed: HTTP 200 from
  `n8-memory-palace-spine-713925718873.us-central1.run.app` before seeding.
- Fixture principal: `h5-verification-15d26bcaf5b947a89e616ca7946ab0db`.
- Canonical desktop IDs: keep `736e3944-4740-41ee-b7c9-ddf75e18e02d`,
  not-relevant `9ebe2045-b0f9-418b-b1a0-96f16752a7c4`, wrong
  `c3eea422-2328-4c6f-9fae-33ee4370daaf`, never
  `e550236a-68db-4ea1-a45d-81bf715a3547`, add-back
  `7b67f3a4-c2ca-49d0-8d0b-d5d9ce0db7e4`.
- Canonical phone IDs: keep `db30974b-50fb-49ee-8cb7-cf7c512d6b70`,
  not-relevant `6202587f-dc30-4700-b6b1-1afc1f3d6a25`, wrong
  `93c0b933-b61e-4da9-881c-026715633e76`, never
  `8dfdd2f5-30a7-4586-bb29-ba169a369c42`, add-back
  `67669c26-33f1-486f-9bb5-ea7a412de22d`.
- Browser and viewports: in-app Chromium browser at 1440×900 and 390×844;
  unscripted checks also used 1024×700, 600×700, and 320×568.
- Console state before starting: no warning or error entries; the final recheck
  was also an empty list.

## Desktop walkthrough — 1440×900

### 1. Arrive as a new owner

- Action: Opened `http://127.0.0.1:8765` and created a fresh thread. I did not
  mutate browser storage: the old browser-local H4 catalog remained visible,
  while the new daemon thread began empty.
- Screenshot: the arrival hierarchy is visible after completion in
  `05-committed-run-desktop.jpg`.
- Observation: the local thread rail, current-thread heading, quiet empty
  canvas, bottom composer, and `Link live` status made the next action clear.
  Old local catalog entries add visual clutter but did not leak daemon state.
- Judgment: **FRICTION** — no clear-catalog control exists, though a fresh
  thread is unambiguous and snapshot authority remained intact.

### 2. Send the first prompt and stop touching the app

- Action: sent `Use the H5 verification memories to explain the handoff.`,
  left the gate open for more than five seconds, and called the pause endpoint.
- Screenshot: `01-gate-open-desktop.jpg`.
- Observation: the modal appeared before any model text. It showed four
  injected cards and one near miss with full bodies, overall scores, all six
  raw feature scores, UUIDs, injection UUID, scorer, and snapshot timestamp.
  The chat was dimmed and inert. The second-terminal check returned prepare
  1/result 1, commit 0/result 0, model 0.
- Judgment: **PASS**.

### 3. Take the ordinary one-tap path

- Action: plain-clicked × on `H5 proof — not relevant` once.
- Screenshot: `02-default-remove-desktop.jpg`.
- Observation: the row dimmed, gained `Removed · not relevant`, turned its ×
  into an explicit Restore control, and changed the sticky summary from four
  memories to three without opening another prompt.
- Judgment: **PASS**.

### 4. Use the exceptional reasons

- Action: Alt-clicked the wrong card, inspected the picker, chose Wrong, then
  repeated the path on the never card and chose Never.
- Screenshot: `03-modifier-menu-desktop.jpg`.
- Observation: the anchored picker clearly offered Wrong, Never, and Cancel;
  Escape closed the picker without closing the gate. Focus stayed on the ×.
  The status labels later distinguished all three reasons. The compact picker
  does not explain the downstream distinction between Wrong and Never.
- Judgment: **FRICTION**, not an invariant failure.

### 5. Recover a near-miss

- Action: clicked `+ Add` on `H5 proof — add back` and read through the modal.
- Screenshot: `04-decisions-desktop.jpg`.
- Observation: the dashed gray card became orange and said `Added ✓`; the
  summary read `3 removed · 1 added` and two memories to be used. The frame
  does not show all three reason labels at once; `03` proves the Wrong/Never
  chooser and the canonical trace proves the exact submitted reasons. All
  bodies stayed readable, and the sticky Stop/Continue footer never became
  stranded.
- Judgment: **PASS**.

### 6. Try to bypass the hard pause, then commit

- Action: pressed Escape, clicked the backdrop, then pressed Enter on Continue.
- Screenshot: `05-committed-run-desktop.jpg`.
- Observation: neither bypass attempt closed the gate. Enter submitted once;
  the gate remained while deployed Spine committed, then dismissed before the
  deterministic response rendered. The composer recovered focus and no second
  run appeared. This live pass also caught and fixed a singular-copy defect
  (`1 memories`) and a non-streaming verification-model wiring defect before
  the canonical rerun.
- Judgment: **PASS after correction and rerun**.

### 7. Prove it is a first-prompt gate

- Action: sent `Confirm that the second prompt skips the memory gate.`.
- Screenshot: `06-second-prompt-desktop.jpg`.
- Observation: there was no gate flash or pause. The second user/assistant pair
  followed the first pair in order and rendered deterministic response 2.
- Judgment: **PASS**.

## Phone walkthrough — 390×844

After exact-ID cleanup and a fresh seed, I repeated the same path in a new
thread. Evidence is `07-gate-open-mobile.jpg` through
`12-second-prompt-mobile.jpg`.

The one-column cards kept every full body, score, six feature labels/bars, and
UUID readable without horizontal scrolling. The dialog measured 382×836 in a
390×844 viewport, document `scrollWidth` equaled `clientWidth` at 390, and the
smallest of all seven controls was 44×44 CSS pixels. The scroll area was
567/1860 pixels while the summary and two action buttons stayed fixed and
thumb-reachable. The reason picker stayed inside the card and viewport. The
controller has no pointer-hold primitive, so the allowed Alt-× path exercised
Wrong/Never rather than claiming a physical touch long-press. At phone width
the timestamp is intentionally hidden while injection UUID and scorer remain
visible; that saves height but is a minor auditability tradeoff. The composer
returned after commit and the second prompt ran with no gate flash.

Phone judgment: **PASS WITH FRICTION** — no layout or lifecycle invariant
failed; physical touch-hold remains for Nate's personal-use pass.

## Unscripted exploration — required

- Action: from 12:45:53 through 12:51:11 CDT (5m18s), I kept a real gate open
  and chose the next safe action from the rendered result: resized it through
  1024×700, 600×700, and 320×568; rapid-double-clicked an already decided ×;
  reopened a reason picker and escaped; attempted to scroll the backdrop;
  reloaded once mid-gate; then read to the bottom at the narrowest width.
- Screenshots: `14-exploration-resize.jpg` and
  `15-exploration-reconnect.jpg`.
- Observation: the rapid double-click ended in one coherent removal, not a
  duplicate state. Resize crossed the rail/mobile breakpoint without losing
  the open gate or sticky actions. Backdrop scroll changed neither page nor
  gate scroll. Escape dismissed only the picker. Reload reconstructed the
  same injection from the daemon and deliberately reset the unsubmitted local
  choice, matching the volatile-choice design. At 320 pixels the title wrapped
  and the content became dense, but width stayed 320/320 and the footer stayed
  visible at the bottom. The controller did not move browser focus under
  Shift+Tab, so I did not count reverse-tab order as verified product behavior;
  clicked native controls did retain visible/programmatic focus.
- Judgment: **PASS WITH RECORDED VERIFICATION FRICTION**.

## Trace and cleanup closure

- `assert_trace.py` desktop result: **PASS**, 8 records in
  `trace-desktop.jsonl`.
- `assert_trace.py` mobile result: **PASS**, 8 records in
  `trace-mobile.jsonl`.
- Prepare failure: `13-prepare-fail-open.jpg` shows no modal, the exact visible
  memory-unavailable warning, and a completed memoryless model response.
- Commit failure: `16-commit-fail-open.jpg` shows the gate dismissed, the same
  warning, and a completed response; the captured trace had no commit result
  and both fail-open model calls contained only static capability instructions.
- Browser console final state: `[]` for warning/error levels.
- Desktop layout: document 1440/1440, dialog 1120×832, scroll area 636/1189,
  smallest control 44×44.
- Phone layout: document 390/390, dialog 382×836, scroll area 567/1860,
  smallest control 44×44.
- Cleanup: all three exact seed sets were tombstoned. The final response named
  `cffab942-982f-4c9f-9b72-4b5df6c4db46`,
  `79876825-576d-48ee-84c3-1458226eda35`,
  `734ebb6b-2c98-4b16-bd79-21b7606f1f8b`,
  `93ecbd0c-2e15-4660-8cb9-c56278b91b4b`, and
  `ef86573d-e4e9-4fc4-886b-1c6f251120d5`; the fixture server then shut down.
- Remaining personal-use friction: stale local catalog cleanup, terse
  Wrong/Never semantics, hidden phone timestamp, physical long-press/tab
  traversal, Stop-from-gate feel, and rendered retry-after-rejection still
  need Nate's own feel rather than a builder claim. Backend tests cover cancel
  and rejection lifecycle, but this SOP did not browser-exercise those two
  controls.
- Overall H5 builder verdict: **PASS WITH RECORDED FRICTION**, followed by the
  plan-required day of Nate's personal use before H6.

## Contract note — 2026-07-27

This walkthrough remains the append-only record of the 2026-07-21 product. It
predates A-023 and does not claim that a Wrong decision opened the now-required
second gate. A current rerun must keep the model stopped after the review
commit, visibly open `wrong_resolution` for the returned current unit, submit
an Edit or Expire decision with that unit's revision, observe the corresponding
`gate/wrong:*` PATCH succeed, and only then observe the first model invocation.
