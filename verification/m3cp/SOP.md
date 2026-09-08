# Consecutive composer sends

PRECEDENT: PLAN M3CP; F072; SPEC C.7 and B.6; Decision 100; ancestors M3AT,
M3OM, M3FP, M3TL, M3FZ. The owner needs to send again after an answer.

## Real walk, 2026-09-08

I opened `harness.packaged:create_app` in Chrome at `127.0.0.1:8881`, using the
canonical built assets, Palace 0.1.10/schema 0021, and real OpenRouter
`minimax/minimax-m3`. The home and empty project were under
`/tmp/nocturne-m3cp-cp08`; principal `m3cp-sop-verification-cp08`, machine/agent
`m3cp-sop-verification`, transcript backup off. Credentials came from the authorized
ignored env. This exercises the packaged factory directly; it does not certify
installed-wheel startup or the ordinary CLI identity path.

1. I asked for “First send received,” approved the empty first-turn memory gate,
   and saw that exact answer. The composer was empty and editable. PASS:
   `01-first-send-composer-clear.png`.
2. Without reload, mode switch or thread switch, I asked for `printf COMPOSER-OK`.
   The real bash tool returned that word, the answer completed, and the composer
   cleared again. PASS: `02-second-send-tool-complete.png`.
3. I asked what the shell printed. The answer correctly recalled `COMPOSER-OK`;
   the thread showed six messages and the composer was empty and editable.
   PASS: `03-three-consecutive-sends.png`. `real-turns.json` records exactly three
   completed user turns, three non-partial answers and the one successful tool call.
4. Unscripted: I typed an unsent draft and tried changing the project label. The
   draft remained editable and Transmit enabled, but rename said it failed.
   `04-unsent-draft-and-rename-refusal.png`. The Conversation manifest omits
   `thread.rename_project`; its action check rejects before any snapshot request.
   I restored the label text and cleared the draft without sending a fourth prompt.

Startup Palace reads returned HTTP 429: queue/curation surfaced a global 500 and
Spend showed its unavailable copy. Readiness, memory and Palace State recovered;
the global error and Spend copy remained in the screenshots. The three prompt
turns succeeded. `palace-read-throttling.log` preserves the separate read failures.

## Regression, verification and cleanup

Removing the heartbeat's between-turn reload fails on the original build
(`heartbeat-before.log`). `diagnosis-before.json` shows a live connection, no
snapshot wait or active run, and a replacement module handshake without an action
reply. The corrected heartbeat passes both sends, tool completion, receipts, journal
and failure restoration. Web lint/build, 132 web tests and the full UI canon pass;
Harness 1698 (including three live contracts) and Spine 298 pass.

The motivation checker reports 31 inherited findings; its inputs are unchanged.
Cleanup found zero active memories in the disposable project, zero queue cards,
zero curator runs, no project files and no pending receipt files. No browser-walk
tombstones were needed; contract tests clean their own disposable memories.
The browser tab, owned daemon, diagnostic fixture and disposable homes were removed.
Cleanup receipts and SHA256SUMS accompany the captures. No owner home was used.
