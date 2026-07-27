# H5 manual-gate Scout — 2026-07-27

Status: **SCOUT EXECUTED — FAIL; HUMAN USE HOLD REMAINS**

This is the first independent manual Scout pass against the real Harness UI,
real chat model, real embedding path, and deployed Spine. It is deliberately
not a rerun of the deterministic H5 builder fixture. The browser path was
driven through Nate's Chrome extension with visible clicks and typing. Shell
commands were used only to start or restart services and to establish the
isolated Spine-unreachable condition.

The gate is demoable, and several important mechanics work. It is not ready to
clear the human-use hold. The most serious finding is that a memory explicitly
removed in the first-turn gate still influenced that turn's answer. The Scout
also found no Wrong edit/expire flow, an unreachable third Never/quarantine
action, failed project scoping with an unwanted global fallback, a gate that
overflows horizontally at `390×844`, and a checklist/specification fork around
thread transcripts after a daemon restart.

## Session record

- Runner / session: `codex / 2026-07-27 / 86af`
- Harness base at the start of the record: `242c234`
- Garden Scout claim: `23b43f3`
- Harness daemon command:
  `MACHINE_ID=h5-sop-verification uv run --locked harness dev`
- UI: production SPA at `http://127.0.0.1:8765/`
- Browser: Nate's Chrome with the Codex Chrome extension
- Principal: `local`
- Verification machine ID: `h5-sop-verification`
- Evidence directory: [`scout-2026-07-27/`](scout-2026-07-27/)
- Entry state: the browser-local thread catalog was present and the daemon was
  live ([00](scout-2026-07-27/00-initial-state.png)).
- Ground before the Scout: Harness `243 passed, 2 deselected`; web lint and
  production build passed; Ruff, lock, pre-commit, and diff checks passed.
  Sibling Spine `160 passed`; Ruff, lock, pre-commit, and diff checks passed.
- Exit ground after the live Scout and evidence work: Harness `243 passed,
  2 deselected`; web lint and production build passed; Ruff, lock, pre-commit,
  and diff checks passed. Sibling Spine `160 passed`; Ruff, lock, pre-commit,
  and diff checks passed. The commands and environment notes are recorded in
  the closing report.

Verdicts below are for the complete checklist item, not for isolated controls.
`PASS` means the live behavior satisfied the item. `FAIL` means a required
behavior did not. `NEEDS-TASTE` means the browser evidence cannot substitute
for Nate's physical-device or subjective judgment.

## Verdict summary

| Tier | Item | Verdict | Short reason |
|---|---|---|---|
| 1 | 1. Other removal reasons | **FAIL** | Wrong opens no edit/expire flow, and a removed memory still influenced the same turn's answer. |
| 1 | 2. Quarantine at three kills | **FAIL** | Two Never hits lower the score until the memory becomes a near miss, where the third Never action is unavailable. |
| 1 | 3. Real-embedding dedup bands | **PASS** | Across fresh threads, a natural-language paraphrase surfaced the similar path and the agent edited the original UUID instead of duplicating it. |
| 1 | 4. Edit flow and lineage | **PASS** | One memory was edited in place under the same UUID; the read-only DB audit proves a contiguous revision chain. |
| 1 | 5. Snapshot pinning | **PASS** | An open thread retained the old value while a new thread received the revised value. |
| 2 | 6. Population stress | **NEEDS-TASTE** | The cardinality shell passed, while zero selected exact-tag fixtures and `f_kw=0` are strong M2 tuning evidence for Nate to judge. |
| 2 | 7. Token-cap enforcement | **PASS** | An over-limit save was rejected clearly with the measured token count and limit. |
| 2 | 8. Project scoping | **FAIL** | No project context was available, and the model then saved globally despite an explicit instruction not to do so. |
| 2 | 9. Cold open | **PASS** | Zero forced memories and exactly three near misses were presented; add-back worked. |
| 2 | 10. Latency feel | **NEEDS-TASTE** | Gate arrival was noticeable and post-Continue model latency was long enough for Nate to judge personally. |
| 3 | 11. Spine unreachable | **PASS** | Chat failed open, `/remember` failed clearly, and restoring Spine restored the gate. |
| 3 | 12. Restart persistence | **FAIL** | The browser-local title survived, but the selected thread transcript was empty after daemon restart and reload. |
| 3 | 13. Unicode / emoji | **PASS** | Storage, gate render, embedding, and model response preserved the test string byte-cleanly. |
| Cross-cutting | B.6 rule 5 responsive repeat | **FAIL** | At a real `390×844` emulated viewport, the gate retained a desktop-width inner layout and was horizontally clipped. |

## Tier 1 — untested law

### 1. Other removal reasons — FAIL

**Action.** In a real first-turn gate, plain-clicked × on the chartreuse
memory, opened the Alt+× reason menu on the marmot memory, chose Wrong, and
used Never on the chartreuse fixture in separate threads. I also stopped one
run while the gate was open.

**Evidence.**

- [07 — injected alpha and beta](scout-2026-07-27/07-injected-gate-alpha-beta.png)
- [08 — Wrong/Never menu](scout-2026-07-27/08-wrong-never-menu.png)
- [09 — not-relevant and Wrong decisions](scout-2026-07-27/09-default-and-wrong-decisions.png)
- [10 — no Wrong edit flow](scout-2026-07-27/10-wrong-no-edit-flow-and-refetch.png)
- [11 — same-turn chartreuse answer and visible search reasoning](scout-2026-07-27/11-removed-memory-same-turn-answer-trace.png)
- [15 — Stop while the gate is open](scout-2026-07-27/15-stop-while-gate-open.png)

**Observation.** The visible interaction mechanics are good: plain × means
not relevant, Alt+× exposes Wrong and Never, statuses are distinct, Continue
stays disabled while commit is in flight, and Stop produces
`Stopped · partial kept`. Those successes do not rescue the item:

1. Choosing Wrong and committing the gate does not open an edit or expire
   flow.
2. More importantly, the model answered with the unique chartreuse fact after
   that record had been removed from the gate. Its visible reasoning said it
   would search memory, but the captured surface does not include the tool
   result, so this record does **not** claim which internal path supplied the
   fact or that both removed records were returned. The observable result is
   still sufficient: the removed chartreuse body crossed the first-turn
   boundary and influenced the answer.

The second behavior is a release-blocking contract failure, not UX polish.

### 2. Quarantine at three kills — FAIL

**Action.** Used Never against the exact chartreuse fixture across fresh
threads and attempted to repeat the action a third time.

**Evidence.**

- [12 — first Never](scout-2026-07-27/12-never-kill-1.png)
- [13 — second Never, score 0.571](scout-2026-07-27/13-never-kill-2-score-0571.png)
- [14 — third Never unreachable, score 0.421](scout-2026-07-27/14-third-never-unreachable-score-0421.png)

**Observation.** The visible score moved from approximately `0.721` to
`0.571` and then `0.421`. At `0.421` the record fell below the injection line
and appeared only as a near miss. A near miss has Add but no Wrong/Never
control, so the third kill required by the quarantine law cannot be issued
through the UI. No quarantine is claimed.

### 3. Dedup bands with real embeddings — PASS

**Action.** First probed the direct `/remember` similar and exact bands. Then,
in two fresh threads, told the agent a durable Saturday coffee preference and
restated it in different words with an instruction to update an existing
similar memory rather than duplicate it.

**Evidence.**

- [01 — first save succeeds](scout-2026-07-27/01-remember-alpha-success.png)
- [02 — real-embedding similar band](scout-2026-07-27/02-real-embedding-similar-band.png)
- [28 — exact duplicate refused](scout-2026-07-27/28-exact-duplicate-refused.png)
- [38 — agent creates the preference](scout-2026-07-27/38-dedup-agent-save-created.png)
- [39 — similar paraphrase edits it](scout-2026-07-27/39-dedup-agent-similar-edited.png)

**Observation.** Real embeddings were active. The paraphrase produced
similar-memory matches at approximately `0.844` and `0.802`, and the exact
repeat produced score `1.0`; no duplicate row was created. More importantly,
the required natural-language flow succeeded: the first agent turn created
`ca08cdc1-907c-407b-8c95-a05e1aacba2a` at revision 1, and the paraphrased
second turn reported a similar existing memory and edited that same UUID to
revision 2. A read-only API check found exactly one active `peaberry` memory
before cleanup, with the revised body. The direct exact-repeat response is
JSON-like and lacks v2.14 reinforcement polish, but the closing checklist
explicitly classifies that pre-v2.14 behavior as a known gap rather than a
defect.

The shared `H5SCOUT-86AF-0727` prefix also dominated the first semantic probe
enough to make an unrelated color, animal, and number look similar. That is a
fixture-design lesson and a useful warning about repeated boilerplate, not a
claim that the embedding service itself malfunctioned.

### 4. Edit flow and lineage — PASS

**Action.** Opened a second Chrome tab and asked the model to change the exact
`Scout86afGamma` record from a fictional library with `731 spiral staircases`
to `864 crystal staircases`.

**Evidence.**

- [22 — old body in tab A](scout-2026-07-27/22-snapshot-old-body-tab-a.png)
- [23 — same record edited to revision 4 in tab B](scout-2026-07-27/23-edit-in-place-revision-4-tab-b.png)
- [26 — revised value in a new thread](scout-2026-07-27/26-new-thread-revised-864.png)

**Observation.** The edit retained memory ID
`6c2ff7a9-bb9f-4bbe-acf4-4558ccea8e81`, advanced the visible revision to 4,
and a new thread retrieved the revised text. This passes the live edit
behavior. The closing read-only DB audit found revisions 1–8 in one contiguous
same-UUID chain and confirmed that revision 4 is the 731→864 edit. Later
inject/prepare activity and the exact cleanup tombstone advanced the head
without breaking its lineage.

### 5. Snapshot pinning — PASS

**Action.** Left tab A's first-turn gate open with the old `731 spiral`
snapshot, edited the same UUID to `864 crystal` in tab B, returned to tab A,
continued, and then opened a brand-new thread.

**Evidence.**

- [22 — old snapshot before edit](scout-2026-07-27/22-snapshot-old-body-tab-a.png)
- [23 — edit in second tab](scout-2026-07-27/23-edit-in-place-revision-4-tab-b.png)
- [24 — open gate still shows old body](scout-2026-07-27/24-snapshot-still-old-after-edit.png)
- [25 — open thread answers with frozen 731](scout-2026-07-27/25-open-thread-used-frozen-731.png)
- [26 — new thread receives 864](scout-2026-07-27/26-new-thread-revised-864.png)

**Observation.** The open thread did not drift when the underlying memory was
edited. Its model answer used 731. The fresh thread used 864. This is the
expected per-thread snapshot behavior.

## Tier 2 — scale and feel

### 6. Population stress — NEEDS-TASTE

**Action.** Seeded the local principal to roughly fifteen active memories,
then asked one first-turn prompt what it remembered about the exact fixture
tags `Orchid731`, `Tempo864`, `Gallery205`, `Cobalt418`, `Lamp593`,
`Export642`, `Soup357`, and `Rower918`.

**Evidence.**

- [27 — population fixtures seeded](scout-2026-07-27/27-population-fixtures-seeded.png)
- [29 — zero selected under exact-tag stress](scout-2026-07-27/29-population-stress-zero-selected.png)

**Observation.** The gate obeyed the cardinality shell—no more than eight
selected and exactly three near misses—but selected **zero** memories. Only
Orchid, Rower, and Cobalt appeared below the line even though the prompt named
eight exact fixture tokens. Visible keyword scores were `0.000` for exact tags
such as Orchid and Rower. The checklist explicitly asks whether relevance
*feels* right and calls the observations M2 scorer-tuning gold; hybrid
retrieval and the keyword mandate are also later work. The mechanical H5 shell
therefore passes, while this result remains strong negative evidence for
Nate's relevance judgment rather than a new H5 implementation flag.

### 7. Token-cap enforcement — PASS

**Action.** Sent `/remember` with a generated paragraph measuring well above
the 128-token cap.

**Evidence.**

- [17 — clear over-limit rejection](scout-2026-07-27/17-token-cap-clear-rejection.png)

**Observation.** The UI reported that the body had `298 cl100k_base tokens`
and that the maximum was `128`. It did not silently truncate, create a record,
or return a generic 500.

### 8. Project scoping — FAIL

**Action.** Asked the model to save the `Scout86afProject` ibis fixture as
project-scoped and explicitly said not to save it globally.

**Evidence.**

- [18 — project save falls back globally](scout-2026-07-27/18-project-scoped-save-fell-back-global.png)
- [19 — global save event trace](scout-2026-07-27/19-project-global-save-event-trace.png)

**Observation.** The project-scoped attempt failed because there was no active
project context. Instead of stopping and explaining the limitation, the model
retried globally and created
`a0fd9cdd-c627-48c4-a5d4-c2cef8150711`, directly contradicting the person's
instruction. Cross-project ranking could not be tested because the initial
scope boundary was not available. This is both a missing M1 context path and
an unsafe fallback.

### 9. Cold open — PASS

**Action.** Started a thread on an unrelated topic, reviewed an empty selected
set with exactly three near misses, added one near miss, and continued.

**Evidence.**

- [03 — cold open with three near misses](scout-2026-07-27/03-cold-open-three-near-misses.png)
- [04 — near miss added](scout-2026-07-27/04-near-miss-added.png)
- [05 — commit in flight](scout-2026-07-27/05-gate-commit-in-flight.png)
- [06 — add-back reaches model](scout-2026-07-27/06-add-back-model-response.png)

**Observation.** The gate did not force irrelevant context. The empty state
was understandable, add-back was reversible and visible, and the model used
the added record after commit.

### 10. Latency feel — NEEDS-TASTE

**Action.** Watched the visible `Working…` state on first prompts and the
transition from Continue through answer rendering throughout the session.

**Observation.** Informal observation was roughly 4.5–5 seconds from Send to
gate arrival and often 15–22 seconds from Continue to the completed provider
answer. Gate commit itself appeared quick; provider time dominated the latter
wait. No instrumented timing trace was collected, so those values are ranges,
not benchmark claims. Nate should decide whether the pacing feels acceptable.

## Tier 3 — resilience

### 11. Spine unreachable — PASS

**Action.** Restarted the Harness daemon with an intentionally unreachable
Spine base while leaving the chat provider available. Through the UI, sent an
ordinary chat prompt and then `/remember`. Restored the normal Spine
configuration and started another first-turn prompt.

**Evidence.**

- [35 — chat survives isolated Spine outage](scout-2026-07-27/35-spine-offline-chat-survives.png)
- [36 — remember fails clearly](scout-2026-07-27/36-spine-offline-remember-fails-cleanly.png)
- [37 — recovery restores the gate](scout-2026-07-27/37-spine-recovery-gate-restored.png)

**Observation.** Memory preparation failed open without crashing the chat;
the model still answered. `/remember` failed with a comprehensible
memory-unavailable error and did not pretend to save. After Spine was restored,
the first-turn memory gate returned with live candidates. This isolates Spine
from the model provider more cleanly than dropping all network connectivity.

### 12. Restart persistence — FAIL

**Action.** Created a two-message thread, captured it, stopped and restarted
the daemon, selected the same browser-local thread, and then reloaded Chrome.

**Evidence.**

- [32 — two-message thread before restart](scout-2026-07-27/32-before-daemon-restart-two-message-thread.png)
- [33 — selected thread empty after restart](scout-2026-07-27/33-after-daemon-restart-selected-thread-empty.png)
- [34 — reload retains catalog but not transcript](scout-2026-07-27/34-browser-reload-catalog-with-empty-selected.png)

**Observation.** The local catalog retained the title, which creates the
appearance of persistence, but the authoritative daemon transcript was empty
after restart and remained empty after browser reload. Thread history is
therefore not intact across daemon restarts, contrary to the checklist's
source-of-truth expectation.

### 13. Unicode and emoji — PASS

**Action.** Saved and recalled:
`café 🌶️🧪 — 日本語 — naïve résumé stays byte-clean`.

**Evidence.**

- [16 — Unicode save](scout-2026-07-27/16-unicode-save-byte-clean.png)
- [20 — Unicode in the gate](scout-2026-07-27/20-unicode-gate-roundtrip.png)
- [21 — Unicode in the model response](scout-2026-07-27/21-unicode-model-response.png)

**Observation.** Accents, emoji, Japanese characters, and em dashes survived
save, embedding/retrieval, gate rendering, and the downstream response without
replacement characters or visible corruption.

## Responsive repeat — FAIL; physical touch — NEEDS-TASTE

**Action.** In Chrome DevTools device emulation, set Responsive to `390×844`
at `100%`, opened a live first-turn gate, and inspected the rendered result
without zooming.

**Evidence.**

- [30 — visible 390×844 controls and overflowing gate](scout-2026-07-27/30-mobile-390x844-gate-overflow.png)
- [31 — clipped gate detail](scout-2026-07-27/31-mobile-390x844-gate-overflow-detail.png)

**Observation.** The shell entered its narrow layout, but the gate did not.
Its inner content retained desktop width and overflowed horizontally, leaving
only a narrow left slice readable. Full memory bodies and actions were not
phone-readable, so this fails B.6 rule 5 and C.9 J8 even if programmatic
controls remain addressable. This is F010.

The Chrome extension still cannot prove authentic touch-hold discoverability.
Physical long-press, thumb reach, and real-device feel therefore remain
`NEEDS-TASTE`; that separate limitation does not soften the rendering failure.

## Unscripted exploration

The useful findings came from following what the product rendered rather than
staying on a happy-path script:

- A shared test prefix unexpectedly drove unrelated facts into the
  similar-memory band.
- After choosing not relevant and Wrong, I read the visible run-event trace
  instead of stopping at the final answer. That exposed a same-turn removal
  boundary failure; the visible reasoning named memory search, while the
  captured surface did not expose the actual tool result.
- I followed the falling Never score into a third thread and discovered that
  quarantine becomes unreachable exactly when the candidate crosses into the
  near-miss band.
- I stopped a run from inside the gate; the partial transcript remained
  coherent.
- I used two tabs to separate edit behavior from snapshot behavior instead of
  assuming one implied the other.
- I obeyed the rendered project error far enough to see the agent ignore the
  “do not save globally” instruction.
- I tested a byte-identical duplicate after the population seed rather than
  inferring exact-band behavior from the paraphrase conflict.
- I returned to the checklist's actual natural-language dedup path and watched
  a second thread edit the original UUID instead of treating the direct
  `/remember` response as the whole feature.
- I used DevTools' visible `390×844` controls at `100%` and found that the
  responsive shell concealed a desktop-width, horizontally clipped gate.
- I restarted the real daemon and reloaded the browser, which separated a
  persistent-looking local catalog from missing authoritative history.
- I isolated Spine failure from the chat provider, then recovered it, so a
  surviving answer was meaningful evidence rather than a cached screen.

No separate five-minute exploration timer was maintained, so this record does
not invent one. The branch points above occurred throughout the manual session.

## Exact verification records

These are the only memories created by this Scout and therefore the only
records authorized for exact-ID cleanup:

| Purpose | Memory ID |
|---|---|
| Chartreuse signal alpha / Never feedback | `3454c5ef-b651-4576-8bac-23913ea1b903` |
| Marmot signal beta / Wrong | `f475a273-28de-46dc-a989-4bd1a8622d67` |
| `Scout86afGamma` snapshot/edit | `6c2ff7a9-bb9f-4bbe-acf4-4558ccea8e81` |
| Unicode round trip | `d36040b7-abee-4aca-99cd-df0199bffc8f` |
| Ibis project-scope fallback | `a0fd9cdd-c627-48c4-a5d4-c2cef8150711` |
| `Orchid731` | `ef8e37fc-8971-4a7d-82e8-71111eaee085` |
| `Tempo864` / cello practice | `18b00cc0-6611-4a16-ab53-589a8184025e` |
| `Gallery205` | `c59d5c5e-a67d-413f-aab7-a68e1b70bdc2` |
| `Cobalt418` diagram theme | `a45f9e95-ad54-4365-8a4c-f72032a5e34f` |
| `Lamp593` desk lighting | `b4a67596-df67-40de-b611-b4991fb9909b` |
| `Export642` CSV dates | `de185afa-0cd0-43f5-87a9-1ef683730e07` |
| `Soup357` omit cilantro | `b593a5ca-3ea9-417b-9f85-2839fac5bafc` |
| `Rower918` Tuesdays | `c9117760-74c7-4d1d-9f67-cdde1cefc0cc` |
| Natural-language dedup / Saturday coffee | `ca08cdc1-907c-407b-8c95-a05e1aacba2a` |

The two pre-existing owner memories below are explicit cleanup exclusions:

- `9cdaa36b-aa77-4089-a37f-dd508c503116`
- `b67bd79a-8911-4c41-8376-c9a11e3f4a08`

Observed injection IDs:

| Scenario | Injection ID |
|---|---|
| Cold open and add-back | `d673d222-cd6c-4094-a6e8-d346da2c326f` |
| Not-relevant plus Wrong | `83fb128a-ad89-45b6-8d0b-566143edb467` |
| First Never | `5a8d7d47-c101-45c2-aa68-a977cc9d6232` |
| Second Never | `3362bf01-4b05-4d6e-a782-b01f87270e41` |
| Third-Never attempt and Stop | `e1f7db3b-0b8b-4bbd-99f4-c1c280709f66` |
| Unicode round trip | `7bf243a3-98a0-4f58-99ad-fd5e470c22b2` |
| Open snapshot with old Gamma | `87ba19ad-0549-4ccd-a9eb-f5738db4da0e` |
| New-thread revised Gamma | `d9d5db89-b4dd-473b-a299-fab823faf610` |
| Population stress | `40f52ad3-c645-4001-a671-d4b835661826` |
| Alternate-input gate (desktop control path) | `193b1e5e-6079-4700-9c44-d6cb82b0f8d0` |
| Post-outage recovery | `8063d4c0-4e9e-420f-828f-49a85ff0deca` |
| Natural-language dedup initial save / responsive finding | `c2350e88-c428-4c85-ba08-c634813f4528` |
| Natural-language dedup paraphrase | `9d4f073a-dc55-4330-9ab5-3d391f790206` |

## Trace and cleanup closure

**DB trace audit: PASS.** The credential-free
[`db-trace-redacted.json`](scout-2026-07-27/db-trace-redacted.json) was
captured in a Cloud SQL transaction that explicitly reported read-only, after
the exact cleanup had completed. It found all 14 exact fixture IDs, all 13
injection IDs, and 50 event rows. Every fixture belonged to principal `local`;
every event used `h5-sop-verification` and scorer `v0`. Persisted outcomes
were:

- `added_back`: 1
- `kept`: 4
- `removed:not_relevant`: 1
- `removed:wrong`: 1
- `removed:never`: 2
- no outcome yet: 41 prepare-only rows

Before explicit cleanup, the alpha head was active with `never_kills=2`,
`bias=-0.3`, and three total removals. The refreshed trace shows its deliberate
cleanup tombstone; no third Never or quarantine transition was fabricated. The
Gamma lineage is contiguous across revisions 1–8, with the 731→864 edit at
revision 4. The dedup fixture is one contiguous three-revision chain: create,
same-UUID agent edit, then cleanup tombstone. Exact-label, body-revision, and
chain checks each found only `ca08cdc1-907c-407b-8c95-a05e1aacba2a`, proving
no duplicate head. Prompt text, bodies, snapshot labels, and revision reasons
are represented only by hashes/byte counts in the artifact.

**Exact-ID cleanup: PASS.** The allowlisted
[`cleanup_scout_fixtures.py`](cleanup_scout_fixtures.py) helper asserted the
verification machine, configured principal, exact UUID, and exact label before
each CAS PATCH. It tombstoned all 14 Scout fixtures; the result is
[`cleanup-result.json`](scout-2026-07-27/cleanup-result.json). The two
pre-existing owner memories were not in the allowlist and were not mutated.

The complete trace and cleanup do not soften the live verdict. The H5
human-use hold remains because the manual product behavior contains multiple
failures, including one that defeats the purpose of the gate.
