# M2X manual-gate Scout — 2026-08-08

Status: **SCOUT EXECUTED — FAIL; HUMAN USE HOLD REMAINS**

This was a first-person pass through the real owner application, remote Palace,
real embedding route, and real OpenRouter completion route. It was not the H5
scenario fixture: the app had no fixture banner, the first answer was produced
by `openrouter:minimax/minimax-m3`, and the broker usage counters advanced only
after the explicit first-turn Continue decision.

The assembled M2 product is useful and much of its center works. It is not ready
for the owner to clear M2X. The blocking pattern is narrower than “the app is
broken”: CURRENT/thread-scoped instruments work, while both GLOBAL Palace
instruments fail; seed and thread extraction can durably create work and then
report failure; queue decisions stamp the browser fixture identity instead of
the verification machine; and Vitals/Context overflow at the required phone
viewport. Those are mechanical failures, not taste calls.

## Session record

- Runner / session: `codex / 2026-08-08 / b4e9`
- Harness base: `3c89c495f354fa9875b6bb71ca8ad9c5520dfa01`
- Spine base: `63de81559fbee4dc0820e5a7b5a2ecf16e44c00c`
- Garden claim: `b7b3a11`; proposed checklist: `53cc686`
- Principal: `local`
- Verification identity: `machine_id=m2x-sop-verification`
- Owner daemon: `.venv/bin/nocturne up --no-open`, disposable
  `NOCTURNE_HOME`, one app at `127.0.0.1:8765`
- Browser: Codex in-app browser, desktop plus `390×844`
- Verification thread: `c59f6ada-b2df-47da-acee-8c4e0483ad36`
- Evidence manifest: [`trace-summary.json`](trace-summary.json)
- Input seed: [`seed-verification.md`](seed-verification.md)
- Browser console after the pass: no warning/error entries

`nocturne doctor` passed the remote Palace, packaged web, port, and schema
checks; deployed schema and expected schema were both `0009`. The local daemon
and disposable home were stopped and removed after evidence capture. No secret
or raw owner configuration is present in this directory.

Ground was green before and after the pass: Harness `671 passed, 3 deselected`
and Spine `223 passed`. The sandbox-only uv-cache denial on the first exit
attempt occurred before collection; rerunning the identical commands with
cache access produced those green results.

## Checklist verdicts

| # | Item | Verdict | First-person result |
|---:|---|---|---|
| 1 | Cold owner path and current contract | **PASS** | Doctor was green, the real owner shell opened, remote schema was `0009`, and no deterministic fixture surface was present. |
| 2 | Real first turn and one human gate | **PASS** | I saw one injection review before any model request, added a near miss, continued explicitly, and received a real OpenRouter answer; usage advanced from zero to one request. |
| 3 | Autonomous later-turn re-score | **PASS** | A second ordinary prompt completed without reopening the first-turn modal; CURRENT contribution bars refreshed and the model used both live memories. |
| 4 | Citation heuristic and reversible membership | **PASS** | The answer used the unique phrase “root of first principles”; the post-turn `hist` contribution was `0.012443570247023363` on that memory and `0` on the comparison. Remove changed it to Stored/Re-add and Re-add restored In context/r5. This is heuristic evidence, not semantic certainty. |
| 5 | Palace Vitals and spend strip | **PASS** | Live broker and embedding lanes, lifecycle/resource gauges, and compact ledger drift were visible without a modal. Drift was shown as `-$0.002278576000`, not hidden. |
| 6 | Context Bars | **PASS** | CURRENT showed `1.8K / 1M`; estimated System `145` + History `1.5K` + Memory `125` + Tools `58` matched the displayed total within formatting precision, with the estimate and inactive compaction stated plainly. |
| 7 | Memory Graph and Memory handoff | **FAIL** | CURRENT graph selection, inspector, relationship, and Graph-to-Memory edit handoff worked. GLOBAL returned “The live memory graph is unavailable” and its rack query returned 503. |
| 8 | Injection Console read/simulation | **FAIL** | CURRENT showed v0, all eleven documented controls, conserved `1.00` weight, score contributions, and a non-enacting simulation receipt; FORCE stayed untouched. GLOBAL returned “Memory tuning is temporarily unavailable” and both query/simulate returned 503. |
| 9 | `/model` device and resolution | **PASS** | The device showed the real resolved route and bound controls. I changed Temperature once to `0.05`, saw history, then restored Inherit; both writes returned 200 and the route did not drift. |
| 10 | Seed ingestion and review queue | **FAIL** | The first seed request created a durable pending batch but returned local 503 after a remote 422. A canonical retry succeeded as a second batch. I rejected both in the real queue and drained it, but the UI hard-coded `machine_id=harness-browser`, so the decisions are not verification-hygiene excluded. |
| 11 | Thread close and extraction queue | **FAIL** | Archive twice created one pending extraction candidate, then returned 503 both times. The UI swallowed the error, reopened no thread-end review surface, and left Archive available. I denied the exact candidate directly under the verification identity; baseline returned to three pending. |
| 12 | Responsive and unscripted pass | **FAIL** | Shell, Chat, Memory, CURRENT Graph, and CURRENT Injection were usable at `390×844`. Expanded Vitals measured `clientWidth=226`, `scrollWidth=320`; Context measured `clientWidth=163`, `scrollWidth=320`. The unscripted Archive retry reproduced partial-write/false-failure instead of recovering. |
| 13 | Cleanup and residue | **FAIL** | No candidate remained pending, no scorer version changed, the edited parameter was restored, and the disposable home was removed. But the two UI rejection events carry the wrong machine identity and the failed Archive path leaves the scout thread in the browser-local catalog, so hygiene/residue is not clean enough to claim PASS. |

## Primary evidence

### Owner path, gate, and real model

- [01 — real owner shell](sop-01-owner-shell-desktop-1440x900.jpg)
- [02 — first gate before model](sop-02-first-gate-before-model-desktop-1440x900.jpg)
- [03 — real answer and Context Bars](sop-03-real-answer-context-desktop-1440x900.jpg)
- [04 — autonomous second turn](sop-04-autonomous-second-turn-desktop-1440x900.jpg)

The first gate injection was
`55d06364-abfc-42a0-8578-c7898f32e0ab`. The added memory was
`9cdaa36b-aa77-4089-a37f-dd508c503116`. The two live model requests reported
`1024/449` and `3340/494` input/output tokens respectively.

### Instruments

- [05 — CURRENT Injection](sop-05-injection-current-desktop-1440x900.jpg)
- [06 — GLOBAL Injection 503](sop-06-injection-global-fail-desktop-1440x900.jpg)
- [07 — CURRENT Graph](sop-07-graph-current-desktop-1280x720.jpg)
- [08 — Graph-to-Memory edit handoff](sop-08-graph-to-memory-edit-desktop-1280x720.jpg)
- [09 — model device before change](sop-09-model-device-before-desktop-1280x720.jpg)
- [10 — model device restored](sop-10-model-device-restored-desktop-1280x720.jpg)
- [18 — memory removed](sop-18-memory-removed-desktop-1440x900.jpg)
- [19 — same memory re-added](sop-19-memory-readded-desktop-1440x900.jpg)

The graph edit was canceled rather than changing owner content. The only live
parameter mutation was the low-impact thread-local Temperature probe, and its
starting Inherit state was restored.

### Seed, extraction, and cleanup

- [11 — both seed batches after partial write](sop-11-seed-partial-write-desktop-1280x720.jpg)
- [12 — seed queue drained](sop-12-seed-queue-clean-desktop-1280x720.jpg)
- [20 — final candidate baseline](sop-20-cleanup-baseline-desktop-1440x900.jpg)

Seed batch IDs were `b4e90000-0000-4000-8000-000000000001` and
`b4e90000-0000-4000-8000-000000000002`. The canonical child was item
`01KZJ15KBFT18YS469T5QMNF8C`, candidate memory
`5e4c6168-45fc-41d6-bbf5-8a1f57aa074a`. The thread-close candidate was item
`01KZJ1B19462FP7J7HWE4DS8TE`, candidate memory
`63c1d178-cd51-4d59-9e91-5520a72ff24e`, merge-targeting the existing owner
memory above. It was denied with `machine_id=m2x-sop-verification`; Vitals then
returned to the pre-scout baseline of three pending candidates. Nothing was
accepted.

### Phone viewport

- [13 — shell](sop-13-owner-shell-mobile-390x844.jpg)
- [14 — Memory](sop-14-memory-mobile-390x844.jpg)
- [15 — CURRENT Graph](sop-15-graph-current-mobile-390x844.jpg)
- [16 — CURRENT Injection](sop-16-injection-current-mobile-390x844.jpg)
- [17 — Vitals and Context overflow](sop-17-vitals-context-mobile-390x844.jpg)

The top-level shell stayed `390/390`; the overflow was local to the two bottom
rack modules and materially clipped their information.

## Owner-only outcomes — NEEDS-TASTE

The following were deliberately not converted into agent PASSes:

1. Whether the NEO-NOIR shell, density, copy, latency, and intervention cadence
   feel like one useful owner instrument.
2. Authentic owner keep/reject/edit/removal decisions toward the 25-signal
   floor. The scout's mis-stamped UI decisions must not count.
3. Any scorer FORCE/activation decision. The scout only simulated.
4. A live owner Cloud SQL backup. `nocturne backup --help` exists; no backup was
   taken by agent hands.
5. Any restore drill or target. `nocturne restore BACKUP_ID --help` exists; no
   owner data was mutated.
6. M2X clearance itself. The board hold remains until Nate says otherwise.

## Handoff

Route the mechanical failures through the Blight Protocol before asking the
owner to spend authentic signal. Re-run only the affected GLOBAL, queue,
archive, and `390×844` slices after repair, then return M2X to Nate for taste,
backup/restore authorization, real dispositions, and the only valid clearance.
