# I1 v2.26/v2.27 J1-J2 repair evidence

Date: 2026-07-31

Result: **PASS — BUILDER REPAIR EVIDENCE COMPLETE**

This directory closes only the J1 and J2 evidence defects named by the prior
independent verdict. It is I1 builder evidence, not a replacement judge
verdict. The failing verdict under `verification/m1/` remains authoritative
until a fresh independent Claude Code J session re-runs these slices.

SPEC v2.26 (D.2 069) supplies the behavior law. SPEC v2.27 (D.2 070) landed
while this evidence run was in flight and adds motivation only; it changes no
semantics.

## Fresh-clone provenance

The live run used new clones in a disposable temporary directory:

```text
Harness 66f1cc1199e29fffae1d4fe6e94253ab6d5b37c8
Spine   7febef353783c981fb68055e00904fa33c98856c
```

Harness `66f1cc1` is the pushed `/model` implementation commit. Spine
`7febef3` is the then-current v2.26 docs freeze; no Spine product change was
needed. The fresh Harness installed from its lock, built the production SPA,
and served it at `127.0.0.1:8765`. The isolated Compose project
`n8i1v226` built fresh Spine/Postgres containers and a new named volume.

The synthetic principal was `nocturne-i1-20260731-7f26`; the daemon machine
was `i1-v226-sop-verification`; the agent was `i1-v226-agent`. The trace is
credential-free and records C.7 envelopes plus deliberately selected daemon
and Spine call/result metadata. It does not record request headers or secret
values.

## J1 — explicit same-thread model resolution point

Thread `fb3f7b5f-3fe9-4948-b998-6a30b8f53ff4` contains, in order:

1. `hello` on `openrouter:minimax/minimax-m3`;
2. `/model openrouter:x-ai/grok-4.5`;
3. one hosted exchange on `openrouter:x-ai/grok-4.5`.

[The expanded model-change event](04-j1-model-change-event.jpg) shows the
journaled old/new slugs, `reason=human_command`, `stickiness_epoch=1`,
`sacrificed_cached_prefix_tokens=956`, and the newly fetched 500000-token
context. [The complete visible exchange](05-j1-post-switch-exchange.jpg)
shows the default hello, command acknowledgment, updated header, and exact
post-switch response. [The reloaded thread](06-j1-reload-new-model.jpg)
independently shows the new resolved header after snapshot hydration.

The prior verdict already accepted the cold-browser screenshots. These
focused repair captures are persisted-state views after snapshot reload; they
repair the missing same-thread trace/action coupling rather than pretending to
be a second cold-start record.

The matching records in [the wire trace](wire-and-daemon.jsonl) are:

- sequences 13-31: hello submit, default-model `run.started`, zero-memory
  gate, hosted response, usage, and `run.done(end_turn)`;
- sequences 34-39: command submit, zero-request command run, top-level
  `resolved_model=openrouter:x-ai/grok-4.5`, nested `model_change`, and clean
  completion;
- sequences 42-72: post-switch submit, new-model `run.started`, hosted
  response, usage, and clean completion;
- sequences 75/77/176: authoritative snapshots retain all six messages and
  `resolved_model=openrouter:x-ai/grok-4.5`.

The command itself made zero model requests. The next model turn used the new
resolution. Unit coverage separately proves epoch-zero `session_id=thread_id`
and later `<thread_id>:epoch:<n>` stickiness IDs; the live journal proves the
epoch transition that selects that path.

## J2 — fresh-word similarity path, one tool call per prompt

Thread `f72c7b55-6c53-476d-b7b1-b97a4ec29760` sent two synthetic ordinary
chat turns. Each explicitly requested exactly one `save_memory` call with
`force=false`, no search/edit call, and no retry.

The first turn created memory
`c358ab87-4d96-4696-a82d-02cfb5683121`. [The panel](07-j2-created-memory-panel.jpg)
shows exactly one active revision-1 preference with the full body. The second
turn used a distinct label and fresh wording; [the visible result](08-j2-similar-memory-result.jpg)
reports the real near-duplicate response and score `0.9075139432499054`
without retrying `force=true`.

The prior verdict already accepted the first memory's visual and SQL ground.
This addendum couples the previously missing fresh-word action to Spine. The
full first-turn acknowledgment is also retained in trace sequences 116/118.

Trace coupling is exact:

- sequences 86/124 are the two visible prompt submissions;
- sequences 107/141 are the only `function_tool_call` events, both
  `save_memory`, both valid, both `force=false`, one in each run;
- sequences 108/142 are the only Spine create calls, preserving the two
  distinct labels/bodies and `force=false`;
- sequence 110 is `201 created`; sequence 144 is `200 similar` naming the
  first memory and the same score shown in the UI;
- sequences 111/145 return those results to the matching tool-call IDs;
- no `search_memory`, `edit_memory`, third save, or automatic retry exists.

`spine.create.result` is the instrumented wrapper's exact HTTP status/body
from the real isolated Spine service, not a copied container access-log line.
Its matching arguments, unique serial call/result, tool return, UI score, and
SQL state provide the action correlation.

[Pre-cleanup SQL](sql-before-cleanup.txt) proves one active unit at revision 1,
a non-null 1536-dimension embedding, and one root `memory_revision` with
`parent_uid IS NULL` and editor `agent:i1-v226-agent`.

## Cleanup and reproducibility

[Wrapper health](health-receipt.json) recorded exactly two create attempts and
the one created ID. The scoped [cleanup receipt](cleanup-receipt.json)
tombstones only that ID. [Post-cleanup SQL](sql-after-cleanup.txt) proves zero
active units for the synthetic principal and records the revision-2 tombstone
parented to the root. Trace sequence 179 records the same final status and
empty active-ID set.

Run the deterministic evidence audit from the Harness repository root:

```sh
python verification/i1/2026-07-31-v226/assert_trace.py
```

It prints `I1 v2.26 J1/J2 trace audit: PASS` only after checking the exact
thread/run coupling, model transition, single-call J2 behavior, Spine
outcomes, and cleanup record.

After evidence capture, the Uvicorn process stopped cleanly and the isolated
Compose containers, network, named volume, and temporary database were
removed. No persistent product or cloud data was used.
