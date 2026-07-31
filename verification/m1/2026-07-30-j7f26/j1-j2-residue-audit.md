# J1/J2 stopped-agent residue audit

This audit distinguishes what the stopped J process actually proved from what
its filenames or adjacent evidence might suggest. The artifacts are all
synthetic and contain no credentials or private owner data.

## J1 — cold start

Result: **FAIL**

Tree nodes: **P3**, **P4**.

Sound evidence:

- `../2026-07-30-j4d73/01-j1-empty-state.jpg` shows a linked empty browser
  thread, usable composer, and zero active memories.
- `02-j1-zero-memory-gate.jpg` shows the first-turn hard pause with zero cards,
  injection `0ef56f3f-fe33-4499-b083-b3e558e6441e`, scorer `v0`.
- `03-j1-model-started.jpg` and `04-j1-live-reply.jpg` show `hello` streaming
  and completing through `openrouter:minimax/minimax-m3`.
- Read-only SQL confirmed thread
  `f79adc55-4ca4-49a0-957c-f6a2d60646ab` exists for principal
  `nocturne-j-4d73`, agent `harness-judge-4d73`, machine
  `j4d73-sop-verification`, with a snapshot timestamp.
- The stopped agent's fresh clones were initially clean and its isolated
  Spine/Postgres stack cold-started successfully.

Named proof that is absent:

- no daemon/wire trace for the `hello` run;
- no evidence of an explicit switch from a default-model exchange to a
  distinct OpenRouter-model exchange.

The three J2 wire traces contain 56 `run.delta` envelopes and all 56 have the
C.7 common fields plus string `payload.run_id` and `payload.kind`. Those
envelopes belong to J2 operations, not the J1 `hello` run. Adjacent C.7
evidence cannot be relabeled as J1's named trace.

## J2 — accumulation and curation

Result: **FAIL**

Tree nodes: **P1.4**, **P1.5**.

Sound evidence:

- `../2026-07-30-j4d73/05-j2-preference-ack-panel.jpg` shows the agent
  acknowledgement and the full atomic memory in the panel.
- `j2-create-wire.jsonl` records the successful tool call and created memory
  `5a31866e-8a57-4660-be05-172aa7e9e7af`.
- Read-only SQL before cleanup proved:
  - revision `1`;
  - embedding non-null;
  - embedding model `openai/text-embedding-3-small`;
  - root `memory_revision.parent_uid IS NULL`;
  - root editor `agent:harness-judge-4d73`.
- `06-j2-repeat-path.jpg` visibly shows a fresh-word restatement and an agent
  response that avoids a duplicate.
- `07-j2-duplicate-409.jpg` and `j2-duplicate-wire.jsonl` show a separate exact
  `/remember` command returning the existing memory with score `1.0`.

Critical mismatch:

- `j2-repeat-wire.jsonl` contains no `save_memory` call and no Spine request.
  The hosted model inferred duplication from conversation history.
- The separate exact `/remember` operation exercised the duplicate path, but
  its JSONL carries no HTTP status field. The isolated Spine log did record a
  `POST /v1/memories` `409 Conflict`, but it belongs to that separate command.

C.9 couples the fresh-word action to a traced `409` or `similar[]` response.
The available record proves both behaviors separately, not that coupling.
Calling that PASS would hide the central trace gap.

## Cleanup

After preserving the read-only SQL evidence, the three exact synthetic rows
left by the stopped process were tombstoned through C.4:

- `5a31866e-8a57-4660-be05-172aa7e9e7af`
- `f899a7cc-bf1f-4192-97d8-c71f7d60d064`
- `8035ef41-bb1d-4a05-b517-21f3674c2705`

The final ACTIVE count for principal `nocturne-j-4d73` was zero.
