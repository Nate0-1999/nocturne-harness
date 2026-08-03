# M2C live owner-app walkthrough

Executed 2026-08-02 CDT (ledger timestamps 2026-08-03 UTC) for SPEC B.6
rule 8. This is a first-person execution log, not the deterministic rule-7
fixture.

## Setup I actually used

I launched the real `harness.daemon:create_dev_app` owner surface on the
product port (`127.0.0.1:8765`) against a current source checkout, a disposable
`NOCTURNE_HOME`, and a disposable current Spine/PostgreSQL stack. The Harness
identity was `principal_id=m2c-sop-verification` and
`machine_id=m2c-sop-verification`. Chat and embedding both used the real
broker credentials already configured for the owner app. I used a browser
profile isolated from the owner's browser data.

There was no `M2C REGRESSION FIXTURE` banner anywhere in the surface. The
fixture server and its deterministic model were not involved in this pass.

## Execution log

### 1. Open the owner app and establish the empty baseline

Action: I opened the rack at 1440x900, created a new thread, and looked across
the whole surface before transmitting anything.

Screenshot: [`sop-01-owner-empty-desktop-1440x900.png`](sop-01-owner-empty-desktop-1440x900.png)

Observation: the Header, Channel Stack, Active Channel, Memory Palace, and
Palace Vitals were visibly separate residents. Chat was ready; Vitals showed
zero active/pinned units, `Created 0/hr`, honest `Not recorded yet` copy for
unavailable lifecycle signals, and `No spend recorded in this window.` The
strip did not invent zeroes for signals it cannot measure.

### 2. Send one real turn

Action: in the new thread I typed `Reply with exactly: M2C LIVE OWNER PATH`,
clicked Transmit, inspected the first-turn memory review, and continued with
its empty proposed-context set.

Screenshot: [`sop-02-owner-live-spend-desktop-1440x900.png`](sop-02-owner-live-spend-desktop-1440x900.png)

Observation: the active-model line resolved to
`openrouter:minimax/minimax-m3`; the model streamed and then rendered exactly
`M2C LIVE OWNER PATH`. The finished run showed `1 req · 915 in · 184 out`.
Chat stayed responsive while Vitals was still on its previous derived-view
snapshot. This was a real call, not an instant fixture response.

### 3. Follow that same turn into the spend strip

Action: I waited for Spine's minute-cadence materialized-view refresh, then
clicked the Vitals Refresh button.

Screenshots:

- [`sop-02-owner-live-spend-desktop-1440x900.png`](sop-02-owner-live-spend-desktop-1440x900.png)
- [`sop-07-owner-reopened-desktop-1440x900.png`](sop-07-owner-reopened-desktop-1440x900.png)

Observation: at 10:40 PM the Total, `purpose:building`, and
`model:minimax/minimax-m3` lanes all showed the same exact
`$0.000464580000` and `4 receipts`. The equality is visible rather than
recomputed into a rounded display. The model label on the surface agrees with
the four real ledger receipts. The request log and SQL trace are preserved in
[`live-trace.txt`](live-trace.txt).

### 4. Scrub to the preceding embedding minute and focus its lane

Action: I pressed Left Arrow on the `text-embedding-3-small spend timeline`,
then selected the `embedding` lane.

Screenshot: the retained 10:39 state after changing to the phone viewport is
visible in
[`sop-05-owner-expanded-mobile-390x844.png`](sop-05-owner-expanded-mobile-390x844.png).

Observation: every lane moved together to 10:39 PM. Total, embedding, and
`text-embedding-3-small` agreed on `$0.000000200000` and one receipt; the
building and Minimax lanes honestly showed `$0` and `No spend in this lane`
for that minute. The focused embedding lane stayed full-emphasis while the
sibling lanes remained readable.

### 5. Collapse and reopen without losing the working context

Action: I collapsed and reopened Palace Vitals twice, once after focusing the
embedding lane and again after focusing Building.

Screenshot: [`sop-07-owner-reopened-desktop-1440x900.png`](sop-07-owner-reopened-desktop-1440x900.png)

Observation: `aria-expanded` changed from `true` to `false` and back to
`true`. The selected lane survived both cycles, as did the shared scrub
minute. Chat and its completed response never disappeared or became inert.

### 6. Repeat the experiential pass at 390x844

Action: I changed to the required phone viewport, observed the default
collapsed strip, expanded it, focused Building, moved the shared timeline
right to 10:40 PM, and collapsed/reopened again.

Screenshots:

- [`sop-04-owner-collapsed-mobile-390x844.png`](sop-04-owner-collapsed-mobile-390x844.png)
- [`sop-05-owner-expanded-mobile-390x844.png`](sop-05-owner-expanded-mobile-390x844.png)
- [`sop-06-owner-building-focus-mobile-390x844.png`](sop-06-owner-building-focus-mobile-390x844.png)

Observation: the phone layout arrived collapsed with the exact
`$0.000464580000` summary still visible. Expanded, all five real lanes fit
without horizontal page overflow. Building became visibly selected; Total,
Building, and Minimax again agreed on `$0.000464580000`, while the zero-spend
siblings remained legible. Building was still selected after collapse and
reopen.

## Unscripted exploration

I deliberately wandered rather than replaying the scripted driver: I moved
back and forth between two non-contiguous spend minutes, focused a purpose
lane and a model-purpose sibling, collapsed the strip from both desktop and
phone layouts, reopened it, and watched the rest of the rack for collateral
movement. I also checked the live browser console after the exploration.

What I judged:

- The strip makes the causal story unusually clear: the embedding penny-line
  lives at 10:39, while the model turn lives at 10:40. Shared scrubbing makes
  the absence in the sibling lanes explicit instead of drawing a misleading
  connected trend.
- Long model identities are visually ellipsized at 390px. Their full text
  remains the accessible control name and the exact identity survives the
  trace, so this is density/taste friction rather than an accounting defect.
  It should be revisited during visual refinement instead of widened ad hoc in
  this packet.
- The isolated browser profile was not empty: it retained older
  verification-only thread cards. The disposable backend home contained only
  this M2C transcript, so owner data was not touched, but a fresh isolated
  profile per SOP would make future screenshots less noisy.
- The browser console contained zero warnings and zero errors.

## Same-action trace and verdict

The surface and trace agree on one thread (`5def1a04-...`), one run
(`01KZ2V9SGY02HRWTQR0R83Q4PN`), one OpenRouter-resolved Minimax turn, 915
input tokens, and 184 output-plus-reasoning tokens. Spine received one real
embedding receipt followed by four real chat receipts. After the scheduled
view refresh, `v_spend_rate` contained exactly the two minute rows rendered by
the scrubber. See [`live-trace.txt`](live-trace.txt) for the bounded evidence.

Verdict: **PASS**, with the two non-blocking friction notes above carried into
the packet handoff. I found no defect requiring the Blight Protocol.
