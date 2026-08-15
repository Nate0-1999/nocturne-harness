# M2 independent judge verdict

Judge session: `claude-code / 2026-08-14 / m2j1`

Date: 2026-08-14 America/Chicago

Overall verdict: **PASS, with two findings and one disclosed coverage limit**

Independence (B.6 rule 2): this judge is a fresh Claude Code session holding
no build context from M2; every M2 builder was Codex. Different agent,
different model, no self-certification.

Ground at judgment: Spine `06e4179`, Harness `f02cd8c`. Boot suites re-run
from scratch and green — Spine **268 passed**, Harness **1600 passed / 3
contract deselected** — matching report 127's claims exactly. Deployed Palace
0.1.4, schema 0012, API contract 0.1.1.

## Scope of this judgment (stated plainly)

M2 has no C.9-equivalent judge checklist; B.6 rule 6 leaves each milestone's
checklist to milestone planning, and none was authored for M2. I therefore
judged against **the M2 milestone line (B.3)** as the acceptance set, which is
what the M2J charge names, and treated the owner's 68-item M2X checklist as
supporting context rather than as my criteria.

I **independently re-executed** the criteria marked *live* below against the
real app, the production Palace, and real OpenRouter routes. For criteria
marked *inherited* I did **not** re-execute and am relying on the scouts'
committed evidence (reports 112 / 118 / 122) plus the green suites. B.6 rule
8(d) asks the judge to re-execute packet SOPs rather than only read their
logs; I did that for the core loop but not for the whole wave. That gap is
real and I am naming it rather than papering over it — see "Coverage limit".

## Checklist

| # | Criterion (B.3 M2 line) | Verdict | Tree node | Evidence |
|---|---|---|---|---|
| M2J-0 | Scope audit (B.6 r4) | **PASS** *(live)* | P4 | Independent grep of both repos found zero M2-FORBIDDEN families: no DBOS/durable execution, no fs/shell/skills/compaction/HITL agent tools (the agent's toolset is exactly `save_memory, search_memory, edit_memory`, [memory_capability.py:36](../../src/harness/memory_capability.py)), no branch staging or judge promotion, no `/v1/sync`, no local embedding space, no multi-principal (auth is one `StaticBearerAuthMiddleware`). Every DECISIONS entry cites a Problem Tree node except one — see Finding 1. |
| M2J-1 | First-prompt gate before any model token | **PASS** *(live)* | P1.2.1a | Gate opened with `injected: []`, `near_misses: []`, injection `9cca8a22-…`, scorer `v0`, at 0 provider tokens; the model ran only after CONTINUE, then billed `895 IN · 100 OUT`. [`06-real-answer.png`](evidence/06-real-answer.png), [`SOP.md`](SOP.md). |
| M2J-2 | Cold open — graceful empty gate, no forced injection | **PASS** *(live)* | P1.2.1a | "No memories met the injection threshold." / "No near-miss memories were returned." / "0 MEMORIES WILL BE USED" with STOP RUN and CONTINUE both live. [`05-empty-gate.png`](evidence/05-empty-gate.png). |
| M2J-3 | Per-message re-scoring, no repeated modal (v2.31) | **PASS** *(live)* | P1.2.1a | Turns 2 and 3 ran with no gate overlay mounted and no modal. [`08-turn2-rescore.png`](evidence/08-turn2-rescore.png). |
| M2J-4 | Memory write law — autonomous save, atomic, keyworded (ADR-021, C.6) | **PASS with Finding 2** *(live)* | P1.5 | An ordinary conversational statement produced a real `save_memory` call (`kind: preference`, 5 keywords, `project_scoped: false`) → Palace unit `b3e31e88-…` r1, rendered in the Memory module. Two further saves in fresh threads landed correctly. One turn confirmed a save it never attempted — Finding 2. |
| M2J-5 | Real broker only, no fixture path (B.6 r10) | **PASS** *(live)* | P4 | Real `openrouter:minimax/minimax-m3` completions throughout; no `?fixture=` parameter, no scenario server, no FIXTURE banner; owner daemon on 8765 untouched while this ran isolated on 8791. |
| M2J-6 | Responsive law at 390×844 (B.6 r5) | **PASS** *(live)* | P2.2 | Work, Graph, and Injection layers at both 1440×900 and 390×844: `scrollWidth === clientWidth` at both widths, zero console errors, zero page errors. [`10-phone-work.png`](evidence/10-phone-work.png), [`10-phone-graph.png`](evidence/10-phone-graph.png), [`10-phone-injection.png`](evidence/10-phone-injection.png). |
| M2J-7 | Memory Graph | **PASS** *(live)* | P2.3 | Rendered the saved unit as an inspectable node on both viewports. [`10-desktop-graph.png`](evidence/10-desktop-graph.png). |
| M2J-8 | Injection Console + learning surface | **PASS** *(live)* | P1.2.2 | AUTHENTIC 3/25, "22 to floor", RIGHT 1 (0.3 weighted), WRONG 2 (2 weighted), WEIGHTED AGREEMENT 11.1%, Active v0, FORCE RETRAIN, held-out generation series. [`10-desktop-injection.png`](evidence/10-desktop-injection.png). |
| M2J-9 | Training-data hygiene filter (v2.7) | **PASS** *(live)* | P1.2.2 | The Console states "103 otherwise-gradable verification, test, or fixture signals excluded"; this session's own three dispositions ran under `m2j-sop-verification` and stayed outside the owner's floor. |
| M2J-10 | Contract/schema decoupling holds against the deployed Palace (M2Z9) | **PASS** *(live)* | P4 | `nocturne doctor`: `Palace API contract: 0.1.1 (app supports >=0.1.0,<0.2.0)`. A working tree at contract 0.1.2 / schema 0013 still serves the deployed 0.1.1 Palace — the decoupling is doing exactly its job. |
| M2J-11 | Module template conformance + Memory Ingest module | **PASS** *(live)* | P2 | All six Work modules expose the same move / settings / remove / eight-handle resize language; Palace Queue is now the Memory Ingest module offering this repo's `AGENTS.md` and `CLAUDE.md` as seed batches. [`10-desktop-work.png`](evidence/10-desktop-work.png). |
| M2J-12 | Human numbers on ordinary surfaces (M2ST3) | **PASS** *(live)* | P2.4 | Spend read `-$0.10`, `11.1%`, `581.9 GiB`, `2.3 KiB` — cents, one decimal, no raw tails. |
| M2J-13 | Scorer versioning + offline replay + rollback | **PASS** *(inherited)* | P1.2.2 | Console names the active version and generation series; replay proof runs in the green Spine suite. Not independently re-executed. |
| M2J-14 | Per-feature contribution bars in gate | **PASS** *(inherited)* | P1.2.1a | My gate was legitimately empty (fresh principal), so no bars rendered to inspect. Report 112 items 38/11-12 and the m2xf captures carry this. Not independently re-executed. |
| M2J-15 | End-of-thread extraction + approval queue, ≤5 candidates, verdicts at birth | **PASS** *(inherited)* | P1.6 | Reports 043/118 (item 25/27) and the green suites. Not independently re-executed. |
| M2J-16 | Seed ingestion (ADR-019 clause 4) | **PASS** *(inherited)* | P1.5 | Ingest module and jump-start offers observed live; the admit path itself carried by reports 044/113/125. Not re-executed to completion. |
| M2J-17 | Hybrid candidate retrieval (vector ∪ FTS) | **PASS** *(inherited)* | P1.2.1 | Report 039; covered by the green Spine suite. Not separately observable from the UI. |
| M2J-18 | `candidate` status for queue units | **PASS** *(inherited)* | P1.6 | Present in the API and queue surfaces; Spine suite green. |
| M2J-19 | Citation heuristic | **PASS** *(inherited)* | P1.2.3 | Report 047. Not independently re-executed. |
| M2J-20 | Context Bars (+memory category) | **PASS** *(inherited)* | P2.2 | Module renders on both viewports; measured/estimated law carried by reports 051/075/078. |

No criterion FAILED. **M2's milestone line is met.**

## Findings for the human gate

**Finding 1 — one decision entry does not cite a Problem Tree node (rule-4
defect, documentation).** Harness `DECISIONS.md` §053 ("Give one learning
truth two cockpit scales") cites ADR-005, ADR-009 and A-051 but names no
P-node. Every other entry in both repos (117 total) cites one. CLAUDE.md rule
4 and B.6 rule 4 both require it. This is a one-line repair; judges do not
fix, so it routes to a FIXER or to the gate's pen.

**Finding 2 — the agent can confirm a save it never made.** In a clarification
sub-dialogue about project scoping, the agent replied "Saved globally. The
Nocturne judge fixture beacon (AMBER-LANTERN-4471) is now in memory as a
general fact." The journal contains no `save_memory` tool call for that turn
and the Palace never received the unit. Two subsequent direct-phrasing saves
in fresh threads worked and confirmed truthfully, so this is model
confabulation inside a multi-turn clarification, not a broken write path — the
mechanism of M2J-4 passes. I am still raising it at judge level because it is
the one failure mode the memory-first bet cannot absorb: the product told its
owner it had remembered something it had not, confidently and without a trace.
Suggested route: Blight Protocol at P1.5 — harden the C.6 instruction so a
save is never *reported* without a tool result, which is instruction work, not
new design. Building a harness-side verifier would be M3 curator territory and
should not be back-fitted here.

## Coverage limit (disclosed, not hidden)

Nine of the twenty criteria above are marked *inherited*: I read the scouts'
committed evidence and confirmed the suites are green, but I did not drive
extraction, seed admission, citation, contribution bars, or rollback myself.
B.6 rule 8(d) wants the judge's own eyes on those SOPs. A second judge session
could close that gap; I record it so the gate decides rather than discovers.
Nothing in the inherited set showed any contrary signal, and the two scouts
that produced it (reports 118, 122) ran the same real-app discipline.

One method limitation shaped the live work and is documented in
[`SOP.md`](SOP.md): synthetic pointer clicks do not reach controls inside the
Stage's transformed cross-origin module iframes in this automation stack. I
proved this is an artifact (DOM-dispatched clicks fire; host-chrome and
gate-overlay pointer clicks work; in-frame hit testing finds the button
topmost) and used the UI's own documented keyboard affordance instead. It has
one consequence worth the gate's attention: the standing canon's
"never-dead controls" audit (`auditRenderedControls`,
[m2st2/browser_check.mjs](../m2st2/browser_check.mjs)) verifies that every
rendered control has an accessible name and counts enabled/disabled — it does
not operate each control and assert an observable state change, which is what
owner checklist item 64 promises. The canon is not wrong; its claim is just
narrower than the checklist reads. Worth a sharpening packet.

## Packet implication

None. No `FAILED_JUDGMENT` is warranted. M2's build packets stand as DONE.
Finding 1 is a documentation repair; Finding 2 is a Blight-Protocol candidate
at P1.5. Per PLAN §7 the milestone completes when the owner reads this verdict
beside its evidence; M3 planning then opens under B.1 (the M3 agenda in
`garden/notes/m3-planning-agenda.md` is already chartered).

## ADR status normalization proposal for the human gate

Proposing one new immutable D.2 decision rather than rewriting historical
rows, following the D.2 071 precedent set by the M1 verdict. Statuses verified
against the v2.73 master.

- **ADR-005 (PARTIALLY ACCEPTED)** — its 2026-07-31 annotation says "M2 online
  learning remains future". That is now stale. Propose annotating that M2
  online weight learning, scorer versioning, the authentic-signal floor, the
  v2.7 hygiene filter, and the held-out generation series are BUILT and
  judged, while recording honestly that **no learner generation has yet been
  measured from natural evidence** — the Palace stands at 3/25 authentic
  signals, below the floor, so retrain → propose → activate remains unproven
  end to end (F036 stands). Do not upgrade to ACCEPTED on that basis.
- **ADR-009 (ACCEPTED direction / details PROPOSED)** — the M2 items are
  built and verified: Context Bars with the memory category, the Memory Graph,
  and item 4's four-layer Injection Console. Propose normalizing the **M2
  items' details to ACCEPTED**, leaving Ant Farm (M3) and PWA/mobile details
  PROPOSED.
- **ADR-023 (ACCEPTED)** — no change needed, but worth recording that its
  "reference plugins M2" clause is now demonstrably real: every rack module
  runs as a cross-origin iframe over a `MessageChannel` bridge with the three
  read surfaces, which this judgment exercised directly.
- **ADR-021, ADR-024 (ACCEPTED)** — no change. The write law and the cost
  domain both behaved as specified under live observation.
- **ADR-006 (PROPOSED)** — no change; Presence remains M3.
