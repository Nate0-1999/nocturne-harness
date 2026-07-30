# I1 closure evidence

Date: 2026-07-30

Result: **PASS**

This directory closes the five gaps returned in the original I1 dry run. It is
builder integration evidence, not the independent M1 judge verdict.

## Fresh-clone provenance

The relay cloned the two pushed remotes into a new temporary directory and
verified their exact heads before starting either product:

```text
Harness  https://github.com/Nate0-1999/nocturne-harness.git
         b2eebec65fe8473757e78aae5ba88677418c67c7
Spine    https://github.com/Nate0-1999/nocturne-spine.git
         5c9ac726dbd7da6e12e0020f684be4bf50712d68
```

No `.env` file or credential was copied into either clone. The existing
mode-0600 Harness `.env` was sourced into the two process environments, while
the documented `local-development-token` was explicitly shared between the
fresh Compose Spine and fresh Harness daemon. OpenRouter was the one external
secret used for chat and embeddings.

The fresh Spine image built from the clone, Postgres initialized a new named
volume, both migrations ran, and authenticated health returned
`{"ok":true,"version":"0.1.0"}`. The fresh Harness clone created its own
virtual environment, installed 104 locked Python packages and 252 locked web
packages, built the production SPA, and served it at `127.0.0.1:8765`.

## AC1 — literal cold start and live browser chat

1. [Fresh-clone empty state](01-ac1-fresh-clone-empty.jpg) shows the real
   production SPA connected to the new daemon and the new Spine database with
   zero active units.
2. Through visible Chrome typing and clicks, I sent a prompt on
   `openrouter:minimax/minimax-m3`, reviewed the zero-memory first gate, and
   clicked Continue.
3. [Live reply and created memory](02-ac1-fresh-clone-live-reply-and-memory.jpg)
   show the completed hosted-model turn and the new memory in the panel.

Judgment: **PASS**. This is the post-push fresh-clone path C.8 AC1 literally
requires.

## AC2 — same visible action reaches the exact duplicate path

In the same visible thread, I asked `save_memory` twice with different labels,
`force=false`, and this exact body:

```text
For I1 fresh-clone verification, I prefer amber status lights for release dashboards.
```

The first action created memory
`6e8f5821-9840-4e60-9eec-9e8ff783878c`. The second action visibly returned:

```text
memory not saved: duplicate memory exists
```

It named that same memory and score `1.0`; the panel still contained one unit.
[The visible duplicate result](03-ac2-visible-exact-duplicate-409.jpg) is the
experiential side. [The timestamped Spine log](ac1-ac2-spine-log.txt) is the
same-action trace: one `POST /v1/memories` returned `201 Created`, then the
repeat returned `409 Conflict`.

Judgment: **PASS**.

## AC7 — dependency death, fail-open completion, and recovery

The adversarial run used the fresh-clone production SPA, `/ws` daemon,
`RunLoop`, `MemoryGateTurnRunner`, and real local Spine. Only the downstream
chat model was the deterministic H8 verification model so the dependency
boundary was isolated.

1. [A healthy first-turn gate](04-ac7-gate-before-spine-stop.jpg) opened before
   the model.
2. I stopped only the Compose `spine` service.
3. [The already-open thread](05-ac7-same-thread-chat-survives.jpg) completed
   another model turn while the Memory rail clearly reported the outage.
4. I created a new thread and sent the same visible prompt.
   [The new-thread result](06-ac7-new-thread-memoryless-warning.jpg) showed
   `Memory is unavailable; continuing without injected context.` and still
   completed the answer.
5. I restarted the same Spine service and verified authenticated health.
6. A new visible thread opened
   [the recovered first-turn gate](07-ac7-recovered-gate.jpg), then completed
   after Continue.

[The wire trace](ac7-wire-trace.jsonl) ties the offline new-thread prompt and
run ID to `wire.error` code `memory_unavailable`, phase `prepare`, subsequent
model text, and `wire.run.done(end_turn, partial=false)`. It also records the
later recovered thread's completion; together with screenshot 07's reopened
gate, that proves recovery. [The complete daemon stdout](ac7-daemon-stdout.txt)
spans one server PID from startup through clean shutdown with no restart,
traceback, or crash.

Judgment: **PASS**.

## B.6 rule-8 SOP re-execution

Every action below used the connected Chrome extension against the rendered
product. HTTP was limited to fixture setup, deterministic turn release where
applicable, and exact-ID cleanup.

| Packet | Timed unscripted segment | Evidence | Result |
|---|---:|---|---|
| H4 | 13:51:10–13:56:57 CDT, 5m47s | [08–17](08-h4-explore-arrival-390x844.jpg), [trace](h4-exploration-trace.jsonl), [first-person addendum](../../h4/SOP.md) | PASS |
| H5 | 13:57:53–14:03:45 CDT, 5m52s | [18–32](18-h5-explore-arrival-1440x900.jpg), [trace](h5-exploration-trace.jsonl), [first-person addendum](../../h5/SOP.md) | PASS |
| H6 | 14:05:18–14:10:22 CDT, 5m04s | [33–45](33-h6-explore-arrival-1440x900.jpg), [trace](h6-exploration-trace.jsonl), [first-person addendum](../../h6/SOP.md) | PASS |

H5 stopped before review commit, so its temporary remove/add/reason choices
never became feedback. Its five exact synthetic IDs were tombstoned. H6
committed an unchanged synthetic context under machine
`h6-sop-verification`; no panel mutation was saved, and its five visible IDs
plus foreign-principal sentinel were tombstoned with
`remaining_active_ids=[]`. [Cleanup receipts](sop-cleanup-receipts.txt) retain
the exact IDs.

All 45 screenshots are JPEG/JFIF bytes with matching `.jpg` extensions.
