# H4 live chat-shell walkthrough

Status: **PARTIAL — CANONICAL WALKTHROUGH PASSED; RULE-8 EXPLORATION OPEN**

This is the current first-person canonical replay executed during I1. It is
builder evidence, not the independent M1 judge verdict. The canonical path
passed, but this file does not yet satisfy B.6 rule 8: the exploratory
Queue→Stop finding below lacks a dedicated screenshot and timed five-minute
unscripted segment.

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

The next I1 relay must execute and record that unscripted segment before H4's
SOP can be called re-executed.
