# H4 live chat-shell walkthrough

Status: **PASS WITH RECORDED FRICTION — I1 RULE-8 RE-EXECUTED**

This is the current first-person canonical replay executed during I1. It is
builder evidence, not the independent M1 judge verdict. The original canonical
path and the dated I1 closure addendum below together satisfy B.6 rule 8.

## Session record

- Runner: Codex relay using the connected Chrome extension
- Date: 2026-07-30
- Surface: production built SPA, production WebSocket/daemon/RunLoop, H4's
  deterministic model/release fixture
- Viewports: 1440×900 and exact 390×844
- Evidence: I1 screenshots 23–33 and the dated desktop/phone traces

## Desktop — 1440×900

1. I opened a fresh fixture and created a thread. The empty state, catalog,
   composer, and transcript hierarchy were immediately legible.
   [Screenshot 23](../i1/2026-07-30/23-h4-desktop-empty.jpg).
2. I typed `Map the release boundary and hold the queue open.` and clicked
   Send. Text, thinking, and usage appeared incrementally while the run stayed
   active. [Screenshot 24](../i1/2026-07-30/24-h4-desktop-streaming.jpg).
3. I typed the second fixture prompt during the active run and clicked Queue.
   It appeared once at the turn boundary, clearly distinguished from the
   active prompt. [Screenshot 25](../i1/2026-07-30/25-h4-desktop-queued.jpg).
4. I reloaded the actual page. The authoritative snapshot restored the same
   transcript, active run, and queued prompt without duplication.
   [Screenshot 26](../i1/2026-07-30/26-h4-desktop-hydrated.jpg).
5. After the fixture released the first turn, I observed its terminal event
   precede the queued run's start. After the second release, both turns were
   ordered and complete. [Screenshot 27](../i1/2026-07-30/27-h4-desktop-queue-complete.jpg).
6. I sent the cancellation prompt and clicked Stop while it streamed. Partial
   text remained and the terminal state read Cancelled.
   [Screenshot 28](../i1/2026-07-30/28-h4-desktop-cancelled-partial.jpg).
7. I sent the fixture budget and provider-error prompts. Their preserved
   partial text and distinct terminal labels remained visible together.
   [Screenshot 29](../i1/2026-07-30/29-h4-desktop-terminal-labels.jpg).

The matching [desktop trace](../i1/2026-07-30/h4-trace-desktop.jsonl) has 45
records and preserves the queue, snapshots, release order, cancellation, and
terminal reasons.

## Phone — 390×844

1. I reset to a fresh process, set Chrome to exactly 390×844, opened the
   drawer, selected a thread, and confirmed the empty chat surface remained
   usable. [Screenshot 30](../i1/2026-07-30/30-h4-mobile-empty.jpg).
2. I typed the same first prompt, then the second while the first was active.
   Queue remained reachable, and a real reload restored the active/queued
   state exactly once. [Screenshot 31](../i1/2026-07-30/31-h4-mobile-queued.jpg).
3. After ordered release, I sent the cancellation prompt and used Stop.
   Partial work stayed visible with the correct terminal state.
   [Screenshot 32](../i1/2026-07-30/32-h4-mobile-cancelled.jpg).
4. I sent the budget and provider-error prompts and read both distinct
   boundaries without horizontal overflow.
   [Screenshot 33](../i1/2026-07-30/33-h4-mobile-terminal-labels.jpg).

The browser reported `scrollWidth=clientWidth=390`. The matching
[phone trace](../i1/2026-07-30/h4-trace-mobile.jsonl) has 45 records.

## Friction

During exploratory phone use, the Queue control was stacked directly above
Stop. My first intended Queue tap hit Stop. I did not treat the resulting
state as canonical evidence: I restarted the fixture and repeated the full
mobile path cleanly. Both controls were readable and operable, but their
proximity deserves fresh attention in J.

## I1 closure addendum — unscripted phone exploration

- Runner: Codex relay using the connected Chrome extension
- Date and local time: 2026-07-30, 13:51:10–13:56:57 CDT
- Duration: 5 minutes 47 seconds
- Surface: production SPA, `/ws`, daemon, and `RunLoop`; H4's deterministic
  model/release fixture
- Viewports: 390×844, 320×844, then 390×844
- Trace:
  [h4-exploration-trace.jsonl](../i1/2026-07-30-closure/h4-exploration-trace.jsonl)

I chose each next action from the rendered state rather than replaying the
canonical script:

1. **Action:** I opened the phone thread drawer and created a fresh thread.
   **Screenshot:** [08](../i1/2026-07-30-closure/08-h4-explore-arrival-390x844.jpg).
   **Observation:** The drawer closed onto a quiet, usable 390px composer. The
   browser-local catalog was long, but the selected daemon thread was clearly
   empty and authoritative.
2. **Action:** I typed the release-boundary prompt and clicked Send.
   **Screenshot:** [09](../i1/2026-07-30-closure/09-h4-explore-streaming-390x844.jpg).
   **Observation:** Partial model text and usage appeared while Stop stayed
   reachable. Queue was visibly present but disabled until I typed another
   prompt, which made the state understandable.
3. **Action:** While the first run was active, I typed a second prompt and
   clicked Queue.
   **Screenshot:** [10](../i1/2026-07-30-closure/10-h4-explore-queued-controls-390x844.jpg).
   **Observation:** The queued message appeared exactly once with `Queued 1`.
   Queue and Stop were both legible, though their vertical proximity remained
   the same friction noted in the canonical replay.
4. **Action:** I reloaded the real page with the active and queued turns still
   open.
   **Screenshot:** [11](../i1/2026-07-30-closure/11-h4-explore-reloaded-queue-390x844.jpg).
   **Observation:** Hydration restored the same partial answer and one queued
   prompt without duplication or loss.
5. **Action:** I opened the Threads drawer during that active queue.
   **Screenshot:** [12](../i1/2026-07-30-closure/12-h4-explore-thread-drawer-active.jpg).
   **Observation:** The selected thread read Live, while the obscured
   transcript retained the queued marker. The drawer felt like navigation,
   not a second source of run state.
6. **Action:** I pressed Escape from the drawer.
   **Screenshot:** [13](../i1/2026-07-30-closure/13-h4-explore-drawer-escape-return.jpg).
   **Observation:** Only the drawer closed; the active run and queue remained
   untouched, and focus returned to Threads.
7. **Action:** I narrowed the same live state to 320×844.
   **Screenshot:** [14](../i1/2026-07-30-closure/14-h4-explore-narrow-320x844.jpg).
   **Observation:** The transcript and both run controls still fit without
   horizontal clipping. At this width the Stop/Queue stack felt denser, but I
   could still distinguish the controls.
8. **Action:** I restored 390×844 after observing the narrow state.
   **Screenshot:** [15](../i1/2026-07-30-closure/15-h4-explore-restored-390x844.jpg).
   **Observation:** The queue and partial text survived the breakpoint round
   trip exactly.
9. **Action:** I clicked Stop on the first turn.
   **Screenshot:** [16](../i1/2026-07-30-closure/16-h4-explore-stop-promotes-queued.jpg).
   **Observation:** The first answer became `Stopped · partial kept`, and the
   queued prompt immediately promoted to the active run. That promotion was a
   useful surprise, but it was coherent and preserved both turns.
10. **Action:** After observing the promoted run, I clicked Stop again.
    **Screenshot:** [17](../i1/2026-07-30-closure/17-h4-explore-both-stopped.jpg).
    **Observation:** Both partial answers remained readable with distinct
    stopped boundaries; the composer returned to its idle state.

The trace records one `prompt.queued`, two authoritative reload snapshots, and
two `run.done(cancelled, partial=true)` events for the same visible journey.
No defect surfaced. Judgment: **PASS WITH RECORDED FRICTION**; Queue/Stop
proximity remains an owner-taste item for J, not a builder failure.
