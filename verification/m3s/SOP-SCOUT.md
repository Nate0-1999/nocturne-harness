# M3S full pre-review scout

This is the frozen findings record for the real released owner app. I used a
disposable local home and verification identity, but the ordinary Rack, real
browser controls, configured OpenRouter provider, and released Palace 0.1.5.
No fixture supplied an owner-facing verdict. No product code was changed.

## 1 — PASS: real owner Rack and released Palace

**WHAT I DID:** I opened the ordinary owner Rack in the browser from a fresh
local home and waited for its Palace status.

**WHAT I EXPECTED:** The real app would load without a fixture curtain and
connect to released Palace 0.1.5.

**WHAT I SAW:** The Rack showed `PALACE READY`; authenticated health reported
0.1.5 / schema 0015 / API contract 0.1.4. Screenshot:
`01-real-owner-rack.png`.

**WHY IT MATTERS:** The rest of this walk tests what the owner would actually
use, not canned scenario data. [M3S; B.6 rules 8-9]

## 2 — PASS: escalation stays in chat

**WHAT I DID:** I typed `Take this to a symphony.` in a new conversation.

**WHAT I EXPECTED:** Deliberation would open inside that conversation with no
mode switch.

**WHAT I SAW:** The same thread immediately showed the full Symphony
deliberation form. Screenshot: `02-in-chat-deliberation.png`.

**WHY IT MATTERS:** Escalating hard work does not make the owner leave the
conversation where the work began. [SYM10; P3]

## 3 — PASS: the plan is owner-authored

**WHAT I DID:** I filled the objective, motivation, recipe step, observable
done condition, all three judge charters, and a performance metric, leaving the
search mark as a visible checked choice.

**WHAT I EXPECTED:** The app would require the real why, work, evidence, and
judging terms before launch.

**WHAT I SAW:** Every field remained visible and editable in the conversation;
the search-marked step remained explicit. Screenshot:
`03-signed-t2-authority.png`.

**WHY IT MATTERS:** The Symphony is bounded by the owner's stated outcome and
proof instead of inventing acceptance criteria later. [SYM10; P3]

## 4 — PASS: authority is plain before launch

**WHAT I DID:** I read and signed the displayed T2 line for 3 attempts, $10,
3 rounds, depth 2, 4 children per attempt, and 30 minutes.

**WHAT I EXPECTED:** Launch would stay unavailable until every numeric wall was
plainly signed.

**WHAT I SAW:** The complete sentence and all six walls were visible together
before launch became available. Screenshot: `03-signed-t2-authority.png`.

**WHY IT MATTERS:** The owner can see the worst case before authorizing the
work. [T2; R22]

## 5 — PASS: completion returns to the live conversation

**WHAT I DID:** I launched one toy Symphony without holding it for steering.

**WHAT I EXPECTED:** It would receive its own stack identity and return a
completed result card to the still-live conversation.

**WHAT I SAW:** Stack `01M0AY6GAPTCNNTS4RS3QFV15A` completed and its result,
signed wall, outcome, and search count appeared inline. Screenshot:
`04-result-returned-to-chat.png`.

**WHY IT MATTERS:** Parallel work remains distinct without breaking the
owner's conversational continuity. [SYM10; P3]

## 6 — PASS: all three steering controls are owner-visible

**WHAT I DID:** I launched a second held Symphony, clarified attempt 1,
cancelled attempt 2, and changed the signed motivation charter through visible
Deck controls.

**WHAT I EXPECTED:** Clarification, cooperative cancellation, and charter fork
would each be available without addressing workers directly.

**WHAT I SAW:** The Deck showed the running attempts, the clarification text,
the cancelled attempt, and the newly identified fork. Screenshots:
`05-live-deck-before-steering.png`, `06-clarified-and-cancelled.png`, and
`07-fork-lineage-owner-demand.png`.

**WHY IT MATTERS:** The owner can redirect the conductor while worker identity
and authority stay private. [SYM11; G19]

## 7 — PASS: interventions preserve truthful lineage

**WHAT I DID:** I compared the visible Deck states with the durable stack
record after each intervention.

**WHAT I EXPECTED:** Clarification would stay on the same stack, cancellation
would drain before cancelling, and a charter change would block the signed
parent and continue in a child.

**WHAT I SAW:** The parent timeline contains clarification, requested,
draining, cancelled, forked, and blocked in order; partial evidence remained,
no attempt admitted memory, and the Deck showed `Owner demand` beside the
child identity. Screenshots: `06-clarified-and-cancelled.png` and
`07-fork-lineage-owner-demand.png`.

**WHY IT MATTERS:** Steering changes the future without rewriting what was
already signed or discarding inconvenient evidence. [SYM11; G19-G20]

## 8 — PASS: reload restores the full story

**WHAT I DID:** I finished the child, reloaded the Rack, and reopened the same
conversation and Deck.

**WHAT I EXPECTED:** Completed child, blocked parent, cancelled attempt, fork
ancestry, and returned chat result would all reappear.

**WHAT I SAW:** Child `01M0AY8GXJHP06KRHAD632V4MC` remained completed above
its blocked parent, while the chat retained the completed result card.
Screenshot: `08-completed-fork-lineage.png`.

**WHY IT MATTERS:** The owner can trust the story after refresh rather than
only during one fragile browser session. [SYM11; ADR-006]

## 9 — FAIL: the real Recipe graph is unavailable

**WHAT I DID:** I switched to Graph and added Recipe from the Stage Library in
the real owner app.

**WHAT I EXPECTED:** Recipe would show the live packet graph, dependency
direction, search nodes, judge gates, state, frontier, and selected why.

**WHAT I SAW:** Recipe showed only `The live recipe is unavailable.` while the
real `recipe_graph` request repeatedly returned 503. Screenshot:
`09-real-recipe-unavailable.png`.

**WHY IT MATTERS:** The owner cannot inspect what can run now, what is blocked,
or why from the released app. [SYM12; P2.3]

## 10 — FAIL: the completion grid cannot be read

**WHAT I DID:** I looked for the left-to-right completion grid in the same real
Recipe module.

**WHAT I EXPECTED:** Completed cells would dim, the current frontier would
glow, shared dependencies would merge, and one final cell would show the served
milestone.

**WHAT I SAW:** No grid rendered because Recipe stopped at `The live recipe is
unavailable.` Screenshot: `09-real-recipe-unavailable.png`.

**WHY IT MATTERS:** The owner has no released visual answer to “where are we?”
for the current plan. [SYM13; P2.3]

## 11 — FAIL: phone recovery returns clipped modules

**WHAT I DID:** I repeated the Graph and Deck checks at 390 by 844 and used the
visible off-screen recovery buttons for Recipe and The Deck.

**WHAT I EXPECTED:** One obvious action would bring each module back into a
readable and operable phone view.

**WHAT I SAW:** The page itself did not overflow, but recovered Recipe appeared
as a tiny clipped sliver and recovered Deck remained mostly beyond the left
edge. Screenshots: `11-phone-recipe-recovered-390x844.png` and
`12-phone-deck-recovered-390x844.png`.

**WHY IT MATTERS:** A phone owner can find the escape control but still cannot
use the module it promises to recover. [B.6 rule 8; R21]

## 12 — PASS: ordinary Recipe manipulation remains reversible

**WHAT I DID:** I switched layers, moved and resized Recipe with its visible
keyboard controls, inspected its settings control, removed it, reopened the
Stage Library, and added it back.

**WHAT I EXPECTED:** These normal Rack actions would preserve the layer and put
Recipe back without hidden state loss.

**WHAT I SAW:** Recipe disappeared after Remove, returned after the visible
Library Add action, and remained on the selected Graph layer. The pre-removal
state is in `09-real-recipe-unavailable.png`; the control sequence is recorded
in the browser trace.

**WHY IT MATTERS:** A bad layout choice remains reversible even though the
module's real data request currently fails. [B.6 rule 8; R21]

## 13 — PASS: browser actions match durable records

**WHAT I DID:** I traced the browser walk through the same thread journal and
the three Symphony stack records.

**WHAT I EXPECTED:** Draft, signed authority, three charter digests, search
mark, interventions, cancellation phases, fork, completion, and real-provider
turn would agree with what the Rack showed.

**WHAT I SAW:** The 110-record journal and stack snapshots match each visible
transition. The final ordinary turn records resolved model
`openrouter:minimax/minimax-m3`, provider `openrouter`, one request, 2,278 input
tokens, 76 output tokens, and terminal `end_turn`. Screenshots:
`13-real-gate-before-openrouter.png` and `14-real-openrouter-answer.png`;
sanitized facts: `trace-summary.json`.

**WHY IT MATTERS:** The evidence proves real provider and durable lineage, not
just labels painted in the browser. [M3S; B.6 rule 9]

## 14 — PASS: released memory bridge preserves consent

**WHAT I DID:** Against production 0.1.5, I staged one disposable result from
each of two sibling attempts, queried both scopes, resolved one unanimous
winner, inspected the ordinary Palace Queue, and explicitly rejected the
verification batch.

**WHAT I EXPECTED:** Each sibling would see only its own staged result; the
winner would become one consent-gated Symphony candidate; the loser would
tombstone with lineage; cleanup would leave no active or injectable result.

**WHAT I SAW:** Both own-scope checks passed and both sibling checks were
invisible; one unanimously judged queue card appeared; the loser was
`tombstoned` at its `root.2` origin; rejection left zero pending cards and zero
visible target memories. Sanitized facts: `trace-summary.json`.

**WHY IT MATTERS:** Symphony can learn from a winner without bypassing the
owner's Palace consent boundary or leaking losing work. [A-059; P1.6]

## 15 — PASS: exit ground and evidence hygiene

**WHAT I DID:** I reran both ordinary product suites, hashed every screenshot,
and scanned the committed text evidence for credential-shaped material.

**WHAT I EXPECTED:** Both repos would remain green and the scout artifact would
contain no secret.

**WHAT I SAW:** Spine passed 278 tests; Harness passed 1,664 tests with 3 live
contracts deselected. Screenshot hashes are in `SHA256SUMS`; the bounded scan
found no credential value.

**WHY IT MATTERS:** The scout leaves reproducible evidence without weakening
the product or exposing its keys. [PLAN section 3; Evidence Capture Law]

## 16 — NEEDS-TASTE: calm and legible enough

**WHAT I DID:** I exercised deliberation, the Deck, the failed Recipe surface,
and the completion path as far as the released app allowed.

**WHAT I EXPECTED:** The owner would decide whether the whole experience feels
calm, legible, and genuinely Nocturne.

**WHAT I SAW:** Mechanical evidence exists, but Recipe and its completion grid
cannot yet be tasted in real data, and an agent cannot supply the owner's
visual judgment. Screenshots: `03-signed-t2-authority.png`,
`08-completed-fork-lineage.png`, and `09-real-recipe-unavailable.png`.

**WHY IT MATTERS:** Passing controls cannot substitute for the owner's felt
experience of the instrument. [B.6 rules 9-10]

## 17 — NEEDS-TASTE: authentic owner signals stay owner-only

**WHAT I DID:** I stopped at verification actions and denied the disposable
memory candidate instead of admitting it, activating a scorer, using FORCE, or
making a real project judgment.

**WHAT I EXPECTED:** No scout action would impersonate the owner's disposition
or broaden the packet's authority.

**WHAT I SAW:** No owner memory was written, no proposal was activated, no
cloud state was mutated, no FORCE action occurred, and no fix packet was
minted. Sanitized cleanup facts: `trace-summary.json`.

**WHY IT MATTERS:** The review remains genuinely the owner's rather than a
verification script voting on the owner's behalf. [M3S authority; B.6 rule 10]

## Frozen findings

The released Recipe data path is unavailable, so its live graph and completion
grid cannot be reviewed. Phone recovery also leaves Recipe and The Deck clipped
and unusable. These are findings only. This scout made no product repair and
minted no fix packet.
