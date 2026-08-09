# M2Z1 — journal rehydration and startup preflight SOP

Status: **EXECUTED / PASS** on 2026-08-09.

## Identity and ground

- Verification principal: `m2z1-sop-verification`
- Verification machine: `m2z1-sop-verification`
- Verification agent: `harness-agent`
- Owner app: `harness.daemon:create_dev_app` at `http://127.0.0.1:8791/`
- Provider shown by the owner app: `openrouter:minimax/minimax-m3`
- Palace: the real configured owner Palace, not `scenario_app.py`
- Browser asset: `assets/index-CzPK_xER.js`, built from this checkout
- Threads: `a7204f81-a89a-4140-9f25-07c3f1ec6eb1` and
  `0ab4e266-5b8e-4be2-be17-1df09e8967b5`

## Procedure executed

1. Started the real owner app with a fresh temporary `NOCTURNE_HOME` and the
   verification identity.
2. Created two threads and continued both first-turn gates with zero memories.
3. Completed one real OpenRouter turn in each thread. The first returned
   `Moonlight continuity confirmed.`; the second returned an unscripted
   clarification rather than the requested fixture-like phrase.
4. Recorded two private journal files, their hashes, their exact two-message
   branches, and their durable tails.
5. Stopped the daemon with Ctrl-C and restarted the same checkout, identity,
   port, and `NOCTURNE_HOME`.
6. Reloaded the owner app. The active thread immediately rendered its exact
   user and assistant messages. Selecting the other thread rendered its exact
   two-message branch and changed its sidebar status from `Not loaded` to
   `2 messages`.
7. Continued the first restored thread with “What two-word phrase did you just
   confirm?” The real OpenRouter response was `Moonlight continuity`, proving
   model recency was also reconstructed rather than only repainting the UI.
8. Created a separate initialized owner home with its exact transcript
   directory set read-only and ran `nocturne up --no-open`. It exited 2 before
   starting a service and printed the plain permissions remedy.
9. Checked browser warning/error logs, stopped the app, finalized the task tab,
   and removed both temporary homes.

## Verdict

PASS. Both journal branches were readable exactly as left after daemon restart.
The untouched second transcript retained SHA-256
`1bbf0e1ed3ddfa60be0c0461e5bf3b1c6a42e257b8bcaf7af453ec173f88c941`
across restart. The first branch continued from its durable assistant tail and
the next provider call used its restored text history. The journal remained
append-only; snapshot reads added no message rows.

The real owner command's read-only refusal was:

> Conversation journal is not writable at [temporary path]. Fix that
> directory's permissions, then run `nocturne up` again.

Exact structured evidence is in
[`restart-trace.json`](./restart-trace.json).

## Unscripted observation

The continued post-restart turn briefly disclosed “Memory is unavailable;
continuing without injected context.” The ordinary-chat fail-open path behaved
as enacted, and the reconstructed recent conversation still produced the
correct answer. This did not alter any memory or the journal verdict.

## Hygiene

- Both first-turn gates used 0 memories; no memory was saved, removed, added,
  pinned, superseded, or tombstoned.
- The verification identity is not the owner identity and none of its activity
  counts toward the owner floor.
- Browser warning/error logs were `[]`.
- `/private/tmp/nocturne-m2z1.WxrCTx` and
  `/private/tmp/nocturne-m2z1-readonly.wGUqdQ` were removed and verified absent.
- The owner app was stopped and the task-created browser tab was finalized.

