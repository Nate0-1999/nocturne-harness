# H8 live Markdown and model-visibility walkthrough

Status: **PASS — SCREENSHOT-COMPLETE LIVE RERUN EXECUTED 2026-07-30**

This is the SPEC B.6 rule-8 first-person record for H8. I drove the built
production SPA and WebSocket daemon against deployed Spine through the
connected Chrome extension. The final rerun used Chrome's own explicit
viewport control, so navigation, every product click, and every product
keystroke—including the exact phone pass—stayed inside Chrome. No product step
used a direct HTTP/WebSocket call, DOM injection, scripted locator action, or
store mutation. Read-only DOM inspection followed the visible judgments.

An earlier live pass also succeeded, but its screenshots did not cover every
written SOP step. Its artifacts remain as historical evidence; this final
rerun is the rule-8 closure and records a screenshot for every step.

## Session record

- Runner / session: Codex relay `86af`
- Date and local time: 2026-07-30, approximately 11:24–11:32 CDT
- Built Harness commit: H8 pre-commit worktree; final commit is recorded in the
  Garden handoff
- Desktop fixture principal:
  `h8-verification-0bba5c7148344f67bcc1b75b71b8db2c`
- Phone fixture principal:
  `h8-verification-d7b5757509cf42ee8e0494dbba3c0fa1`
- Desktop thread IDs: `e28c7318-ba5f-45dc-8e4d-330535aec09a`,
  `be3274b4-4530-4b8a-ae3b-0cdd719a41c8`
- Phone thread IDs: `3728a769-2955-4153-af7e-43db190871e4`,
  `a6d5476a-aea7-4119-b04e-1046e5f8e5b4`
- Browser and viewports: Chrome at 1670×936; exact 390×844 phone viewport;
  320×844 exploration edge
- Evidence traces: `trace-live-desktop-rerun.jsonl`,
  `trace-live-mobile-rerun.jsonl`

## Desktop walkthrough — 1670×936

### 1. Arrive and identify the active model

- Action: I opened a fresh origin and waited for the authoritative snapshot.
- Screenshot: `05-arrival-desktop.png`
- Observation: `local:h8-verification` appeared in full on a dedicated Model
  row below the thread title. It read as status, not as a selectable control;
  there was no caret, button treatment, or ambiguous edit affordance.
- Judgment: **PASS**

### 2. Save one memory with `/remember`

- Action: I clicked the visible composer, typed
  `/remember H8 remembers that Markdown evidence needs readable tables and code.`,
  and clicked **Send**.
- Screenshot: `06-remember-desktop.png`
- Observation: The command finished with one concise
  `Remembered 'Readable Markdown evidence' (...)` response and never opened the
  memory gate. The header model did not flicker or change. The right rail moved
  to one active unit and showed the exact remembered body.
- Judgment: **PASS**

The matching trace shows one tools-free metadata completion, the generated
label, exactly `["markdown", "tables", "code"]`, the same keywords on the C.4
create request and result, and memory ID
`aa7c8d13-4aef-476b-b950-1fca06ebcda7`.

### 3. Send the plain-text user fixture in a fresh thread

- Action: I clicked **New thread**, typed, and sent:

  ```text
  Show the H8 Markdown proof. Keep **plain-user-text** literal in my message and treat <button data-h8-user-raw="true">unsafe</button> as text.
  ```

- Screenshot: `07-gate-desktop.png`
- Observation: My row visibly retained both asterisks and the full button tag.
  The first-chat gate opened with zero selected memories and one readable near
  miss at score `0.517`. The run showed `0 req · 0 in · 0 out`; the assistant
  remained at “Waiting for memory review,” so the model had not begun.
- Judgment: **PASS**

### 4. Continue through the real gate

- Action: I read the gate without adding or vetoing the fixture memory, then
  clicked **Continue**.
- Screenshot: `08-continued-desktop.png`
- Observation: The control changed to **Applying memory…** while the modal
  remained visibly authoritative. There was no Markdown behind it and no
  ambiguous double-submit state.
- Judgment: **PASS**

### 5. Read the rendered Markdown

- Action: I waited for dismissal, then read the complete response from heading
  through both raw-HTML sentinel lines.
- Screenshot: `09-markdown-desktop.png`
- Observation: The hierarchy was immediately legible: a clear H2, bold and
  italic text, two bullets, a bordered two-row table, and a fenced code
  surface. The button and script appeared as literal text, not controls.
  Nothing looked like unstyled provider output.
- Judgment: **PASS**

### 6. Confirm sanitization and plain-user behavior

- Action: After the visual read, I used read-only browser inspection.
- Screenshot: `10-inspection-desktop.png`
- Observation: The rendered pixels remained unchanged while inspection found
  zero raw button elements, zero content-created script elements,
  `typeof __h8RawHtmlExecuted === "undefined"`, zero rich descendants in the
  user row, the literal user markers intact, model
  `local:h8-verification`, and document `scrollWidth / clientWidth` of
  `1670 / 1670`.
- Judgment: **PASS**

## Phone walkthrough — exact 390×844

### 1. Arrive at the exact phone viewport

- Action: I set Chrome's explicit viewport to 390×844 and opened a fresh
  fixture origin.
- Screenshot: `11-arrival-mobile-390x844.png`
- Observation: The responsive shell replaced the side rails with 44px Threads
  and Memory actions. The complete model slug remained visible beneath the
  thread title, and the composer stayed reachable at the bottom.
- Judgment: **PASS**

### 2. Save the fixture memory

- Action: I clicked the phone composer, typed the same `/remember` command,
  and clicked **Send**.
- Screenshot: `12-remember-mobile-390x844.png`
- Observation: The user command and one-line confirmation wrapped cleanly.
  The Memory badge advanced to `1`; the model row stayed stable.
- Judgment: **PASS**

### 3. Open the first-chat memory gate

- Action: I opened Threads, created a fresh thread, typed the same Markdown
  fixture, and clicked **Send**.
- Screenshot: `13-gate-mobile-390x844.png`
- Observation: The gate fit the exact viewport with readable feature scores,
  an untouched `0.517` near miss, and visible 44px **Stop run** and
  **Continue** actions. The model still showed zero requests and tokens.
- Judgment: **PASS**

### 4. Continue and watch the boundary

- Action: I clicked **Continue** once.
- Screenshot: `14-continued-mobile-390x844.png`
- Observation: The gate dismissed into a visible streaming state. The user row
  remained plain text, the model slug stayed complete, and the composer
  truthfully changed to Queue/Stop while the run was active.
- Judgment: **PASS**

### 5. Read the phone Markdown result

- Action: I waited for completion and read the heading, emphasis, list, table,
  code, and literal raw-tag lines.
- Screenshot: `15-markdown-mobile-390x844.png`
- Observation: The table and code remained distinct and reachable, the raw
  tags wrapped instead of widening the page, and the composer remained usable.
- Judgment: **PASS**

### 6. Inspect the phone safety and layout boundary

- Action: I used read-only browser inspection after the visual judgment.
- Screenshot: `16-inspection-mobile-390x844.png`
- Observation: The viewport was exactly `390×844`; document
  `scrollWidth / clientWidth` was `390 / 390`; model
  `clientWidth / scrollWidth` was `135 / 135`; Threads, Memory, textarea, and
  Send were all 44px high; raw button and script counts were zero; the script
  sentinel was undefined; and the user row had zero rich descendants.
- Judgment: **PASS**

## Unscripted exploration

### 1. Reload the completed Markdown thread

- Action: I reloaded the page and waited for authoritative hydration.
- Screenshot: `17-explore-reload-mobile-390x844.png`
- Observation: The rich assistant hierarchy and both literal raw strings
  returned without a visible reconstruction flash or model-name change.

### 2. Switch away and back

- Action: I opened Threads, selected the `/remember` thread, read its restored
  confirmation, then returned to the Markdown thread.
- Screenshots: `18-explore-thread-switch-mobile-390x844.png`,
  `19-explore-thread-return-mobile-390x844.png`
- Observation: The unloaded thread hydrated on demand, and returning restored
  the rich Markdown DOM rather than flattening it into text.

### 3. Narrow beyond the required breakpoint

- Action: I changed Chrome from 390×844 to 320×844.
- Screenshot: `20-explore-narrow-320x844.png`
- Observation: The wordmark deliberately collapsed to `H`, but the full model
  slug remained visible. The document measured `320 / 320` with no
  page-level overflow; table, code, raw-tag lines, and composer remained
  reachable.

### 4. Open the memory drawer at 320px

- Action: I clicked Memory, read the stored unit, then clicked Back.
- Screenshot: `21-explore-memory-drawer-320x844.png`
- Observation: The drawer occupied the narrow canvas cleanly, kept the body and
  Edit/Pin actions readable, and closed without disturbing the chat thread.

### 5. Try an odd unsent input

- Action: I clicked the composer and typed
  `# unsent **draft** <img src=x onerror=alert(1)>`, left it unsent for the
  screenshot, then selected all and cleared it with Chrome keystrokes.
- Screenshot: `22-explore-unsent-input-320x844.png`
- Observation: The draft remained editable plain input, auto-grew within its
  ceiling, and cleared without sending, rendering, or changing the transcript.

### 6. Restore the required phone viewport

- Action: I restored Chrome to 390×844.
- Screenshot: `23-explore-restored-mobile-390x844.png`
- Observation: The stable Markdown thread returned to `390 / 390`, the empty
  composer shrank back, and no stale drawer or draft remained.

- Exploration judgment:
  **PASS — NO PRODUCT DEFECT; THE EARLIER DEVTOOLS INPUT FRICTION IS AVOIDED BY
  CHROME'S EXPLICIT VIEWPORT CONTROL**

## Trace and cleanup closure

- Desktop rerun trace assertion: **PASS**, 18 records
- Phone rerun trace assertion: **PASS**, 22 records including reload and thread
  hydration
- Desktop exact-ID cleanup:
  `aa7c8d13-4aef-476b-b950-1fca06ebcda7` → TOMBSTONED, remaining exact ACTIVE
  IDs `[]`
- Phone exact-ID cleanup:
  `57992b12-cc26-44a9-bcf0-73c5b518b9b1` → TOMBSTONED, remaining exact ACTIVE
  IDs `[]`
- Fixture ports: stopped after cleanup
- Chrome viewport override: reset after the walkthrough
- No rerun fixture ID remains ACTIVE: **confirmed**
