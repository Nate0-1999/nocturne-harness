# M2G live owner-app walkthrough

Executed 2026-08-03 CDT for SPEC B.6 rule 8. This is a first-person execution
log, not the deterministic fixture.

## Setup I actually used

I launched `harness.daemon:create_dev_app` on the product port
`127.0.0.1:8765`, a current local Spine/PostgreSQL stack, and a disposable
`NOCTURNE_HOME`. The isolated identity was
`principal_id=machine_id=m2g-sop-verification`. Chat and embeddings used the
owner's real OpenRouter credentials. The two exact seed IDs were tombstoned
afterward; both servers and the Compose services were stopped, the disposable
home was removed, and the browser tabs were finalized. No fixture banner was
present in this pass.

## Execution log

### 1. First message: stop at the human gate

Action: I created a new thread and typed `In one short sentence, what does a
confirmed lock do?`.

Screenshot: [`sop-01-owner-first-gate-desktop-1440x900.png`](sop-01-owner-first-gate-desktop-1440x900.png)

Observation: the first-turn review opened with one pinned proposed memory and
one near miss. The copy said the model had not started. I kept the pinned card
and pressed Continue.

### 2. Confirm the real model used the accepted lock

Observation: the active model resolved to `openrouter:minimax/minimax-m3` and
answered from the accepted text: `explicitly accepted at the first gate stays
locked into later message context.` This was a broker call, not the immediate
deterministic fixture response.

### 3. Send a later ordinary message

Action: I typed `What does the amber-orchid rule say? Answer in one short
sentence.`

Observation: no review modal appeared. Spine prepared autonomously and the
model answered. This first live score left the amber-orchid memory just below
threshold, while the confirmed memory remained in context. That was useful:
re-scoring did not manufacture a selection merely because the prompt named it.

### 4. Unscripted exploration: change a corpus pin, then send again

Action: rather than follow the happy-path script, I pinned the stored
amber-orchid memory in the live Memory panel, then sent `After that pin change,
repeat the amber-orchid rule in one short sentence.`

Screenshot: [`sop-02-owner-autonomous-entry-desktop-1440x900.png`](sop-02-owner-autonomous-entry-desktop-1440x900.png)

Observation: again there was no modal. On the next atomic re-score both memories
were visibly `In context`, and the real model repeated the exact amber-orchid
rule. This proved the post-first loop reads current corpus state while retaining
the earlier human lock.

### 5. Remove and re-add the autonomously entered member

Action: I clicked Remove on the amber-orchid card, inspected the excluded state,
then clicked Re-add.

Screenshots:

- [`sop-03-owner-excluded-desktop-1440x900.png`](sop-03-owner-excluded-desktop-1440x900.png)
- [`sop-04-owner-readded-desktop-1440x900.png`](sop-04-owner-readded-desktop-1440x900.png)

Observation: removal changed the card to Stored and exposed Re-add; re-add
returned it to `In context` with explicit lock copy. Both actions targeted the
same passive injection membership.

### 6. Repeat the user-facing criterion at 390×844

Action: I changed to the required phone viewport and opened Memory from the
header.

Screenshot: [`sop-05-owner-readded-mobile-390x844.png`](sop-05-owner-readded-mobile-390x844.png)

Observation: both context cards, badges, bodies, and full-width actions were
readable without horizontal page overflow. During the pass I found the
connection label crowding the phone header; the final build hides that redundant
label at this breakpoint, leaving Threads and Memory visible.

## Defects caught and burned down

The first real autonomous request exposed a pinned-plus-confirmed set bug:
Spine wrongly required the confirmed pin to also exist in the regular pool and
returned 500. The scorer now subtracts pins before validating regular locks,
with an exact regression test.

The exploratory Remove exposed a second 409: feedback accepted human outcomes
but not passive `auto_entered`. A-030 and the transition implementation now
permit that required removal, with an API regression. I reran the live actions
after both fixes. Browser console warnings/errors were zero.

Verdict: **PASS** after the two live-found defects were fixed and re-executed.

