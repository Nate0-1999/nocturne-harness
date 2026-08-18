# M3S2 standard owner-core rescout

This is the frozen findings record for the standard owner core in the real
released app. I used a disposable local home and verification identity, but
the ordinary Rack, real browser controls, configured OpenRouter provider, and
released Palace 0.1.5. No fixture supplied an owner-facing verdict. No product
code was changed.

## 1 — PASS: real owner Rack and released Palace

**WHAT I DID:** I opened the ordinary Rack in the browser from a disposable
home and waited for its Palace status.

**WHAT I EXPECTED:** The real app would load without a fixture curtain and
connect to the released Palace.

**WHAT I SAW:** The Rack showed `PALACE READY`; authenticated health reported
0.1.5 / schema 0015 / API contract 0.1.4. Screenshot:
`01-real-owner-rack.png`.

**WHY IT MATTERS:** The rest of the walk is the owner's actual product path,
not a scenario fixture.

## 2 — PASS: first-turn gate precedes real OpenRouter chat

**WHAT I DID:** I started a new ordinary thread and sent one short chat prompt.

**WHAT I EXPECTED:** The one review gate would appear before model output, and
continuing unchanged would reach the configured provider.

**WHAT I SAW:** Gate `07fd28a6-9d6b-4004-8982-c8b3698771ef` showed zero
selected memories before the model started. The completed run resolved
`openrouter:minimax/minimax-m3`, used two requests, and terminated
`end_turn`. Screenshots: `03-first-turn-memory-gate.png` and
`04-real-openrouter-first-answer.png`.

**WHY IT MATTERS:** The first owner turn preserves memory consent without
substituting a fake model response.

## 3 — PASS: Unicode `/remember` writes a visible memory

**WHAT I DID:** I submitted `/remember` with the disposable phrase
`cobalt moth 🌙`.

**WHAT I EXPECTED:** The Rack would create one memory, preserve the Unicode,
and show the exact saved body in Memory.

**WHAT I SAW:** Memory `6d95565e-f94a-46c9-aaca-0d38c74c9ed9` appeared as
`M3S2 lantern phrase: cobalt moth` with the exact moon-bearing body.
Screenshots: `05-memory-written-and-visible.png` and
`15-switch-back-original-coherent.png`.

**WHY IT MATTERS:** The ordinary capture path can turn an owner instruction
into inspectable Palace state without losing its text.

## 4 — PASS: saved memory shapes the next real answer

**WHAT I DID:** I asked for the project-local lantern phrase in a second
ordinary turn.

**WHAT I EXPECTED:** Autonomous scoring would run without a second modal gate,
and the real answer would use the saved fact.

**WHAT I SAW:** The model answered exactly `cobalt moth 🌙`. The
terminal trace recorded one request, 3,065 input tokens, 40 output tokens, and
`end_turn`. Screenshots: `06-memory-shaped-answer.png` and
`15-switch-back-original-coherent.png`.

**WHY IT MATTERS:** Memory changes the next lived conversation rather than
only appearing in storage.

## 5 — PASS: Graph shows the written unit and its provenance

**WHAT I DID:** I opened Graph after the write and selected the new node.

**WHAT I EXPECTED:** The unit would appear with its relationship and complete
inspector text.

**WHAT I SAW:** Graph showed one memory and one relationship; the inspector
showed the exact label, body, fact kind, revision, and project provenance.
Screenshots: `07-current-graph-after-write.png` and
`08-graph-memory-inspector.png`.

**WHY IT MATTERS:** The owner can move from a remembered answer to the durable
unit that caused it.

## 6 — PASS: Injection Console explains why the memory surfaced

**WHAT I DID:** I opened Injection after the memory-backed turn.

**WHAT I EXPECTED:** The current scored event would name the active recipe and
show real score contributions.

**WHAT I SAW:** Injection named `m3f-location-v1`, ranked the memory `#1
injected` at 0.667, and displayed semantic, keyword, time, project, frequency,
history, location, and bias contributions. Screenshot:
`09-current-injection-console.png`.

**WHY IT MATTERS:** Memory influence is inspectable instead of being hidden
behind the answer.

## 7 — PASS: Vitals records the live provider work honestly

**WHAT I DID:** I refreshed Vitals immediately after the real turns.

**WHAT I EXPECTED:** Real chat, remember, and embedding work would appear as
priced receipt lanes without blocking the conversation.

**WHAT I SAW:** Vitals showed model lanes for `minimax/minimax-m3` and
`text-embedding-3-small`, purpose lanes for building, remember, and embedding,
and zero unpriced lines. Accounting was clear. It also honestly showed an
existing Palace-wide reconciliation drift of about -$0.22. Screenshot:
`10-vitals-after-live-turns.png`.

**WHY IT MATTERS:** The owner sees both the cost of this work and the current
accounting warning instead of a falsely green summary.

## 8 — PASS: Context Bars measures the selected turn

**WHAT I DID:** I read Context Bars on the same selected thread after the
memory-backed response.

**WHAT I EXPECTED:** Used capacity and the System, History, Memory, and Tools
breakdown would be visible and internally coherent at display precision.

**WHAT I SAW:** Context showed 3.1K / 1M with System 728, History 1.4K, Memory
100, and Tools 869. The module marked non-tool lanes as estimated and said
compaction was inactive. Screenshot: `11-context-bars-measured.png`.

**WHY IT MATTERS:** The owner can see where the request budget went without
pretending rounded estimates are exact counts.

## 9 — FAIL: the project control does not bind or isolate the thread

**WHAT I DID:** I entered `m3s2-core` on the original thread, then created a
sibling thread, entered `other-test`, and asked the sibling for the original
project-local phrase.

**WHAT I EXPECTED:** Each visible project selection would become the durable
thread project, and the sibling gate and answer would exclude the original
project's memory.

**WHAT I SAW:** The UI temporarily displayed both entered values, but both
transcript journals persisted `build-test`. The saved memory's Graph inspector
also said `Project · build-test`. In the `other-test` UI, the gate ranked that
memory `#1 injected` with raw Project 1.000, and the real model answered
`cobalt moth 🌙`. Screenshots: `02-project-bound-thread.png`,
`08-graph-memory-inspector.png`, `12-sibling-project-bound.png`,
`13-sibling-isolation-failure-gate.png`, and
`14-sibling-isolation-failure-answer.png`.

**WHY IT MATTERS:** The owner can believe a conversation moved to a different
project while its durable scope stays on the old project, allowing a
project-local memory to cross the boundary.

## 10 — PASS: switching back restores the original selected surfaces

**WHAT I DID:** I selected the original thread again after the sibling probe.

**WHAT I EXPECTED:** The original transcript, memory-shaped answer, Memory
state, Vitals, and Context would return together.

**WHAT I SAW:** Thread `83DC9574` returned with all six messages, the exact
saved memory, the `cobalt moth 🌙` answer, 3.1K Context state, and the
live spend lanes. Screenshot: `15-switch-back-original-coherent.png`.

**WHY IT MATTERS:** Selection changes do not scramble the rest of the Rack,
even though the project-binding defect remains.

## 11 — PASS: durable state survives a real daemon restart

**WHAT I DID:** I stopped the daemon, restarted it against the same disposable
home, reloaded the browser, and reopened the original thread.

**WHAT I EXPECTED:** Durable thread catalog, transcript, actual project key,
memory, and answer would return. Daemon-lifetime Context observation was not
expected to persist.

**WHAT I SAW:** Both thread IDs returned; the original six-message transcript,
actual `build-test` binding, exact Unicode memory, and memory-backed answer
were restored. The transcript journal had grown to 122 records / 69,172
bytes. Screenshot: `16-restart-persistence.png`.

**WHY IT MATTERS:** Restart does not erase the owner's durable story, and it
does not disguise the actual persisted project key.

## 12 — PASS: every shipped theme switches and persists

**WHAT I DID:** I selected NEO-NOIR, SERAPH DRESSED, and GOLD LINES through the
ordinary settings control, reloaded with GOLD LINES active, then returned to
NEO-NOIR.

**WHAT I EXPECTED:** Each named theme would visibly change the Rack, the
selection would survive reload, and the default could be restored.

**WHAT I SAW:** All three themes rendered distinct Rack treatments; GOLD LINES
remained selected after reload; final state returned to NEO-NOIR. Screenshots:
`17-theme-seraph-dressed.png`, `18-theme-gold-lines.png`,
`19-theme-return-neo-noir.png`, and `22-theme-persists-reload.png`.

**WHY IT MATTERS:** Appearance choice is a real persistent owner control. Its
visual quality remains an owner taste call.

## 13 — PASS: an unscripted Graph control is reversible

**WHAT I DID:** I opened Memory Graph settings, switched from Everything to
This thread, observed the scoped view, and restored Everything.

**WHAT I EXPECTED:** The module scope would change without destroying the
layer or durable memory.

**WHAT I SAW:** The pressed scope changed to This thread and then back to
Everything. Screenshot: `20-unscripted-graph-scope.png`.

**WHY IT MATTERS:** Ordinary wandering remains recoverable rather than turning
one exploratory click into state loss.

## 14 — PASS: browser state agrees with durable trace

**WHAT I DID:** I traced the two browser threads through their disposable
transcript journals, gate events, provider usage, Palace reads, and released
health.

**WHAT I EXPECTED:** IDs, project keys, model, injected unit, token totals,
terminal state, and receipts would agree with the visible Rack.

**WHAT I SAW:** Both thread IDs, both gate IDs, memory ID, real model, answers,
terminal `end_turn` events, and receipt lanes matched. Most importantly, both
`thread_context` records independently prove durable `build-test` despite the
two different visible project entries. Sanitized facts:
`trace-summary.json`.

**WHY IT MATTERS:** The isolation finding is a durable data fact, not an
interpretation of labels in a screenshot.

## 15 — PASS: cleanup and exit ground are clean

**WHAT I DID:** I tombstoned the exact verification memory, refreshed the
Rack, scanned committed text evidence for credential-shaped material, hashed
every screenshot, and reran both ordinary product suites.

**WHAT I EXPECTED:** The disposable unit would no longer be active or
injectable, no secret would enter evidence, and both repos would stay green.

**WHAT I SAW:** The memory moved from active revision 3 to tombstoned revision
4; the exact active-match count became zero and the Rack showed zero active
units. Spine passed 278 tests. Harness passed 1,664 tests with 3 live contracts
deselected. Screenshot: `21-cleanup-no-active-memory.png`; hashes:
`SHA256SUMS`.

**WHY IT MATTERS:** The scout leaves reproducible proof without polluting the
owner's memory or weakening the product.

## Frozen finding

The project field acknowledges a new visible value without changing the
durable thread context. Because both threads remain `build-test`, a fact that
appears project-local is scored as a perfect project match and injected into
the supposed sibling project. This is one finding: project binding and sibling
isolation share the same observed cause. No fix was attempted and no fix
packet was created.

## Reserved owner judgment

Whether the standard core feels calm, legible, and genuinely Nocturne remains
owner-only. I switched themes mechanically and made no authentic keep, remove,
wrong, never, scorer activation, FORCE action, or real-project judgment.
