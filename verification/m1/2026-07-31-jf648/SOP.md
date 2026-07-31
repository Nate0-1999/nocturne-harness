# J re-judgment SOP — first-person record

Judge session: `claude-code / 2026-07-31 / f648`
Scope: re-execution of the J1 and J2 slices only, per report 028's minimum
repair charge and the standing verdict's instruction. J0 and J3–J8 were
confirmed by audit (see VERDICT.md), not re-executed.

## Method note (honest disclosure)

I drove a real Chrome instance (dedicated scratch profile, CDP port 9223)
step-by-step: one action per invocation, reading the saved screenshot after
each step and choosing the next action from what I saw. This is live
interactive use with my own eyes on the rendered pixels, not a pre-scripted
assertion run; the screenshots in this directory are the frames I actually
observed, in the order I observed them. Environment: fresh clones of both
repos (Harness `b64cc82`, Spine `2eb85b9`) in a disposable scratchpad,
isolated Compose project `n8jf648` with a new named volume, `harness dev`
serving the production SPA at `127.0.0.1:8765`. Synthetic principal
`nocturne-j-20260731-f648`, machine `m1-judge-sop-verification` (hygiene
pattern per B.6 rule 9), agent `j-f648-agent`. The local Spine bearer was the
compose default; the only real credential (OpenRouter) was copied into the
clone's mode-0600 `.env` without ever being printed, and the clone was
deleted at teardown.

A first attempt at wire retention — a passive second WebSocket connection —
received zero envelopes: this daemon delivers live run events to the
originating connection, and a subscriber that never selects a thread hears
nothing. That instrument was discarded (its empty file removed) and replaced
with frame listeners on the browser's own socket (`wire-frames.jsonl`),
which is the correct tap: it records exactly the envelopes the UI acted on.

## J1 — cold start and the v2.26 `/model` resolution point

1. **Opened `http://127.0.0.1:8765`.** [`01-j1-empty-state.png`]. A truly
   empty product: one browser-local "New thread" (8C60C48A), `LINK LIVE`,
   `MODEL Awaiting daemon`, memory rail `0 ACTIVE UNITS / NO ACTIVE
   MEMORIES`. The empty-state copy — "Nothing here demands a response" —
   reads Invariant 14 back at me. Authenticated `/healthz` on the fresh
   compose stack had already returned 200.
2. **Typed `hello`, pressed Enter.** The first-turn memory gate opened as a
   hard pause [`02a-j1-hello-inflight.png`]: stage `review`, injection
   `5c1b2455-6134-438f-904f-3178ed877bb4`, scorer `v0`, "The model has not
   started", zero injected cards and zero near misses on the fresh DB. This
   is A-019's claimed first ordinary turn, honestly empty. I clicked
   CONTINUE.
3. **Watched the hello reply stream** on the default model
   [`02-j1-hello-default-model.png`]: header `MODEL
   openrouter:minimax/minimax-m3`, hosted usage `1 REQ · 905 IN · 57 OUT`,
   reply "Hello! 👋 How can I help you today?", 3 RUN EVENTS disclosure.
4. **Sent `/model openrouter:x-ai/grok-4.5`.**
   [`03a-j1-model-command-ack.png`]. The acknowledgment names both slugs and
   the new 500000-token context; the header re-resolved immediately; the
   command run's own usage row reads `0 REQ · 0 IN · 0 OUT` — the command
   made no model request. Expanded the `1 RUN EVENT`
   [`03-j1-model-change-event.png`] and read the journaled JSON on screen
   (full rendered text captured):
   `event_kind=model_change, old_model=openrouter:minimax/minimax-m3,
   new_model=openrouter:x-ai/grok-4.5, reason=human_command,
   stickiness_epoch=1, sacrificed_cached_prefix_tokens=962,
   context_tokens=500000`.
5. **Post-switch hosted exchange** in the same thread: sent "Reply exactly:
   judge post-switch exchange complete." and received exactly that reply on
   grok-4.5, `1 REQ · 818 IN · 24 OUT` [`04-j1-post-switch-exchange.png`,
   which also shows the full model_change JSON expanded].
6. **Reloaded the page.** [`05-j1-reload-resolved-model.png`]. Snapshot
   hydration rebuilt the thread: all 6 messages, header still
   `openrouter:x-ai/grok-4.5`. The daemon, not the browser, owns this state.
7. **Wire retention.** With frame listeners attached I reloaded once more and
   ran one supplementary exchange on the switched thread
   [`08-j1-wire-capture-exchange.png`, `wire-frames.jsonl`]: seq 9 is the
   daemon's authoritative J1 snapshot (6 messages, top-level
   `resolved_model=openrouter:x-ai/grok-4.5`, and the assistant message
   carrying the full `model_change` event); seqs 12–40 are the live
   `prompt.submit → run.started (resolved_model=grok-4.5) → run.delta
   thinking/text/event → run.usage (1 req, 861 in, 20 out) → run.done
   (end_turn, partial=false)` chain — C.7/A-016 shapes throughout. My own
   hello exchange's live delta stream was watched but not retained (the
   failed passive tap); its retained trace is the snapshot record, the
   usage-bearing screenshots, the SQL thread row, and the builder's
   independently audited hello-specific delta record (their trace seqs
   13–31), which I verified without using their audit script.

## J2 — accumulation and the fresh-word similar path

8. **New thread, durable preference.** Sent: "Please remember this durable
   preference of mine: I prefer tabs over spaces for code indentation. Save
   it to memory now with exactly one save_memory call, force=false. …" The
   new thread's gate opened first [`06a-j2-first-gate.png`] — injection
   `ef3afb95-e2d5-412f-9734-a978f5005fa5`, still zero cards (the save
   happens after the gate; nothing to inject yet). Continued.
9. **Watched the save.** [`06-j2-preference-saved.png`]. The reply — "Saved
   your indentation preference: tabs over spaces for code." — and, without
   any action from me, the memory rail flipped to `1 ACTIVE UNIT`:
   `indentation-tabs-over-spaces` · STORED · PREFERENCE · R1, full body
   "User prefers tabs over spaces for code indentation in source files."
   Note the header: this thread runs the DEFAULT model
   (`openrouter:minimax/minimax-m3`) — the J1 `/model` switch was
   thread-scoped, exactly as A-020(b) requires.
10. **Fresh-word restatement.** Sent: "One more note in different words:
    when indenting source code, tabs are what I want, not spaces. Save this
    too with exactly one save_memory call using a new label and
    force=false. … report the one tool response verbatim."
    [`07-j2-similar-result.png`]. The agent reported the tool response
    verbatim, and I captured the full rendered line:
    `similar memory exists: {"memory_id":"653cf054-6e03-432e-9dc6-0a5d4f1772e3",
    "label":"indentation-tabs-over-spaces","body":"User prefers tabs over
    spaces for code indentation in source files.","kind":"preference",
    "pin":false,"score":0.8366294031655829}; update it, or call again with
    force=true` — then declined to retry. The panel still shows exactly one
    active unit. The snapshot record (wire-frames seq 2) retains both
    `save_memory` tool calls with distinct labels
    (`indentation-tabs-over-spaces`, `source-code-indenting-prefers-tabs`)
    and genuinely different bodies; `force` is absent from both args — the
    A-015 schema default `false`.
11. **Trace coupling.** [`spine-access-log.txt`]: two prepare/commit pairs
    (both zero-card gates), then `POST /v1/memories 201 Created` and
    `POST /v1/memories 200 OK` — the similar[] response, score 0.8366 inside
    the [0.80, 0.92) band. [`sql-trace.txt`]: one ACTIVE unit
    `653cf054-6e03-432e-9dc6-0a5d4f1772e3` at revision 1, embedding NOT NULL
    at 1536 dims; one root `memory_revision` (parent_uid NULL, editor
    `agent:j-f648-agent`, machine `m1-judge-sop-verification`); zero
    `injection_event` rows (zero-card prepares persist none, per A-008);
    both threads stamped under the judge principal, their UUIDs matching the
    on-screen 8C60C48A / 7E118C08.

## Unscripted segment

The reload at step 6 and the thread-list hop at step 7 were my wandering:
I switched between both threads from the sidebar, watched each header
re-resolve to its own model (grok-4.5 vs minimax-m3) from snapshot alone,
and re-opened the memory rail — the tombstone I later wrote never appeared
as an active unit. Friction worth one sentence for the human gate, not a
defect: the run-event JSON block inside a message does not scroll into view
with the mouse wheel over the transcript's outer container; I had to rely on
the expanded block's position (the full JSON was on screen in
`04-j1-post-switch-exchange.png`) — at phone widths this is worth a look at
H-polish time. Second observation, lawful but worth knowing: live run
events are delivered only to the originating socket; a second passive
subscriber that never requests a thread receives nothing until it asks.

## Cleanup

Tombstoned the single fixture by exact ID via C.4 PATCH (editor
`verification:j-f648`, reason "J re-judgment cleanup: exact fixture only") —
[`sql-after-cleanup.txt`] shows status `tombstoned`, revision 2 parented to
the root revision, zero active units. Compose project `n8jf648` was brought
down with its volume and network removed; the dedicated Chrome instance and
its profile, the fresh clones, and the clone's `.env` were deleted; the
`harness dev` process was stopped. No persistent product or cloud data was
touched.
