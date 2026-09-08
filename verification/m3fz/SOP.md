# M3FZ — complete tool turns and visible failures

PRECEDENT: garden/FLAGS.md F068/F064; PLAN M3FZ; ancestors M3RS, M3FP, M3DK.
Owner charge: fix the core text → tool → text failure and prove it in the packaged app.

## Real walk — 2026-09-08

Real `harness.packaged:create_app`, canonical built `web/dist`, Palace 0.1.10/schema
0021, and OpenRouter `minimax/minimax-m3`. The disposable process used port 8878,
`NOCTURNE_HOME=/tmp/nocturne-m3fz-fz08/home`, principal
`m3fz-sop-verification-fz08`, machine/agent `m3fz-sop-verification`, transcript backup
disabled, and an empty `/tmp/nocturne-m3fz-fz08/project`. Credentials were loaded from
the authorized ignored `.env`; no credential contents are retained here. This uses the
packaged factory directly, not an installed-wheel or ordinary `nocturne up --no-open` identity proof.

| Action | Observed result | Evidence |
|---|---|---|
| Create a folder-bound thread; ask for explanation, `printf M3FZ-REAL-OK`, then explanation; approve the empty memory gate. | PASS: real bash succeeded; both text parts remain; `end_turn`, `partial=false`. | `01-talk-tool-talk.png` |
| Open Conversation Stack. | PASS: one waiting editable proposed reply, zero live turns. | `02-tool-turn-proposed-reply.png` |
| Ask for a tiny `chime` CLI plan with exactly two tests, three judges, measurable criteria and $0.10; inspect the empty folder. | PASS for M3FZ completion: real `ls` succeeded, full answer and proposed reply reached Deck without error. | `03-tiny-cli-plan-on-deck.png` |
| Send the exact `Take this to a symphony` command. Enter the tiny-CLI outcome and $0.10 in its unsigned form. | PASS: the existing local deliberation card appeared. Launch stayed disabled and no workers ran. Form edits were not signed/persisted. | `04-symphony-deliberation-card.png` |

The second model answer incorrectly treated the requested dollar budget as allocations
to time, cognition and maintenance. It is preserved as model output, not accepted as a
real spending budget. The exact Symphony trigger opens a separate, initially blank local
form; this walk proves reaching that card, not automatic ratification or a real Symphony run.

After completed sends the composer retained its prompt and stayed disabled; reload or
Focused/Stack switching restored it. This also occurred in the deterministic heartbeat
and the zero-model Symphony command. F072 records the separate defect. The strengthened
heartbeat deliberately reloads between turns; it does not prove consecutive sends without
reload. Stage framing used ordinary zoom/pan; screenshots contain only disposable content.

## Verification and cleanup

The new `test_m3fz_text_tool_text_keeps_the_whole_answer_and_terminal_proposal` failed
against old code (`regression-before.log`) and passes now. A second test still rejects
actual terminal divergence. The standing packaged heartbeat now speaks, runs real bash,
speaks again, and checks exact complete text, proposal, terminal state and journal. Its
deliberately failed turn shows a plain reason before and after reload.

Exit: Harness **1698 passed** including three live contracts; Spine **298 passed**;
web **132 passed**, lint/build green; full rendered UI canon green. Changed Python Ruff
and diff checks passed. The standalone motivation checker has the same 31 inherited
findings on base `d9c7696` and the result, with zero new findings.

`trace-summary.json` records the three runs, exact terminal states, usage and tool results.
Only `bash` and `ls` ran; no memory-write tool or Symphony worker ran and the project
stayed empty. Server-filtered reads found zero active memories in both disposable projects;
principal-filtered reads found zero pending queue items and curator cards. No tombstones
were needed for this browser walk. The live contract suite owns its separate create/
tombstone fixtures. The tab and owned daemon were closed and the disposable tree removed.
The Palace has no principal-filtered memory-list API; cleanup did not issue a broad list.
