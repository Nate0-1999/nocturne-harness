# M2X changed-ground re-scout

Session: `codex / 2026-08-08 / e6b1`

Identity: `principal_id=m2x-sop-verification`,
`machine_id=m2x-sop-verification`

Scope: re-run only the F020–F025 remedy slices and classify active F026.

I used the real owner app against the configured remote Palace, real
OpenRouter chat, and real broker-routed embeddings. The app was served from a
disposable local home on port 8786. No fixture server or fixture banner was
present.

## F021 + F023 — seed reconciliation and decision provenance: PASS

I submitted one Markdown seed through the owner API because the current page
still offers only the native file chooser; M2Y5 owns the missing in-page
drop/paste route and is not part of this re-scout. The first request took
8.704 seconds and returned HTTP 200 with one pending card. Replaying the exact
same batch UID, source name, and Markdown took 0.157 seconds and returned the
same item, memory, source digest, and timestamps with HTTP 200. It did not
split or create again.

I opened Palace queue in the rendered app. I saw one document and one semantic
child, then pressed **Reject batch**. The queue visibly changed to `Document
rejected` and `The queue is clear`. The real decision request returned 200.
The browser-facing API rejected an attempted `machine_id=harness-browser`
field with HTTP 422 `extra_forbidden`; configured daemon identity is the only
remaining identity source. The durable run journal independently stamps every
event `m2x-sop-verification`.

Screenshot: `01-seed-reconciled-before-deny.jpg`.

## F020 — Graph and Injection GLOBAL adapters: PASS

I opened Memory Graph and switched between CURRENT and GLOBAL. CURRENT showed
the selected fresh thread's honest empty state; GLOBAL loaded the verification
principal's real heads and relationships. Both rack queries returned 200 and
neither scope synthesized a thread.

I opened Injection Console in GLOBAL. It loaded active recipe `v0`, the eleven
controls, conserved influence `1.00 / 1.00`, and no availability alert. I ran
DEEP simulation without changing or forcing anything. The real response was
100% accuracy over one held-out disposition with digest prefix
`313e805f38f7`; FORCE remained untouched.

Screenshots: `02-global-injection-deep.jpg`, `06-global-graph.jpg`.

## Real turn used by the remaining slices

I created one fresh thread and sent a natural prompt. The first-turn gate
opened with zero selected and zero near misses; it explicitly said the model
had not started. I pressed **Continue**. The visible model route was
`openrouter:minimax/minimax-m3`; the completed turn recorded one request,
391 input tokens, and 66 output tokens. No verification memory was admitted.

## F024 + F025 — 390×844 responsive modules: PASS

At exactly 390×844, I expanded Vitals and inspected the populated Context
instrument. Measurements were:

- shell: 390 client / 390 scroll;
- Palace Vitals frame and document: 226 / 226;
- Context Bars frame and document: 163 / 163.

Vitals kept the exact `$0.000196500000` readout visible. Context displayed
measured `391 / 1M` plus the explicit estimated split System 145, History 155,
Memory 33, Tools 58; the four categories sum to 391. No page or module root
clipped horizontally.

Screenshot: `04-phone-context-vitals.jpg`.

## F022 — archive reconciliation and Thread Review: PASS

I pressed **Archive** once. The button visibly changed to `Extracting`; one
candidate was created, the request returned 200, and Thread Review opened in
the page with the final post and the exact candidate. I pressed **Deny** and
saw `Nothing pending`. After closing the review I pressed **Archive** again;
it returned 200 quickly, reopened the same resolved surface, and created no
second candidate. Final seed and thread queue reads both returned empty arrays.

Screenshot: `05-archive-thread-review.jpg`.

## F026 — CURRENT Vitals: FAIL

Unscripted exploration: after the populated turn, I switched Vitals from
GLOBAL to CURRENT instead of stopping after the layout proof. The exact
thread-scoped query returned HTTP 200 twice and contained real current spend
(`source_view=spend_event`, including the live turn's receipt lines). The UI
nevertheless rendered `Vitals couldn’t refresh. Chat is still available.` and
left the Palace-wide snapshot visible beneath it. Switching back to GLOBAL
cleared the alert.

The containing mismatch is concrete: `parseVitalsSnapshot` accepts only
`source_view=v_spend_rate`, while A-035 requires CURRENT Vitals to use
`source_view=spend_event`. F026 remains an active mechanical FAIL. A scout does
not repair an already-DONE adapter contract.

Screenshot: `03-current-vitals-f026.jpg`.

## Cleanup

Seed batch `63be3288-1f75-4c67-9b7b-20bfa3865411` and extraction item
`01KZJEBJMC2YYV81W7GNWG707Q` were denied through the real UI. Both approval
queue reads were empty afterward. The verification principal had zero active
memories throughout; no scorer configuration was changed; FORCE was not used;
browser warnings/errors were empty. The disposable local home was removed
after evidence capture.

M2X remains a HUMAN/TODO packet. This re-scout does not clear its hold.
