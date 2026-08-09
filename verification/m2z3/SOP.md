# M2Z3 real-owner SOP — project context and artificial paths

Status: **PASS for the F028 context chain** on 2026-08-09.

The point of this pass was not to prove that a dropdown can change text. It was
to prove that one daemon-owned artificial project path survives the whole
chain: thread binding → project-scoped save → injection score → search →
CURRENT Graph, while a sibling path cannot see the same memory.

## Provenance

- Owner app: real `harness.daemon:create_dev_app`, not the regression fixture.
- Chat route: `openrouter:openai/gpt-4.1` through real OpenRouter calls.
- Palace: the configured owner Spine service.
- Embedding model reported by the created memory:
  `openai/text-embedding-3-small`.
- Verification identity: principal, machine, and agent
  `m2z3-sop-verification`.
- Unique marker: `m2z3-20260809-a7c9`.
- Exact disposable memory:
  `513e4315-e13b-4e83-85cb-7e23f3894ffa`.

Secrets, service tokens, unrelated Palace rows, and provider payloads are not
retained in this directory.

## Execution and evidence

1. The real owner app opened a new thread at the seeded `build-test` path. The
   model used ordinary `save_memory(project_scoped=true)`—not `/remember` or a
   direct POST—to create the exact marker memory. The tool result returned the
   UUID above. The owner Palace row reported `project_key=build-test`,
   `origin_path=build-test`, and save-thread origin
   `845acd83-d609-4701-b7cb-125472c0271b`.

2. A fresh `build-test` thread
   `3c4e43f9-8aeb-4482-8057-6c559b37fc05` submitted a matching prompt. The
   normal first-turn gate returned injection
   `ef6ba888-a895-4dad-9558-00c58c4e1cac` with the exact memory ranked #1,
   shown as `injected`, total score `0.6499630808830261`, and
   `features.proj=1.0`. The owner accepted the gate without edits. The real
   model then answered from the injected project memory.

3. Memory Graph `CURRENT` for that thread returned the same UUID with
   `in_current_context=true`. Selecting the node kept the Graph open, published
   the shared memory selection, and rendered `Project · build-test` in the
   inspector.

4. One Enter on the same Project control jumped to sibling path `other-test`
   and created thread `4636def2-8703-479d-9852-b6428dace96c`; it did not rebind
   either `build-test` thread. The identical matching prompt produced injection
   `a09bb366-0298-4065-b0e6-9455286a29a4` with **0 injected and 0 near misses**.
   The real model called project-scoped search and reported no matches. Typed
   Palace verification independently returned zero `other-test` rows, zero
   search results, and no occurrence of the exact UUID. Graph `CURRENT` was
   empty and omitted no hidden IDs.

5. Restart continuity was exercised on the save thread: after stopping and
   restarting the daemon with the same `NOCTURNE_HOME`, the authoritative
   snapshot still rendered `build-test`, restored the transcript, and a
   continued real OpenRouter turn found the same project-scoped memory. The
   mandatory journal contains immutable `thread_context` rows for both later
   verification threads (`build-test` and `other-test`). A second, two-thread
   browser reload after the final process stop was not claimed: host-process
   approval review timed out twice while relaunching the local listener. The
   shipped restart/hydration tests cover both bindings, while the live
   save/injection/Graph/exclusion evidence above was already complete.

6. Cleanup used one CAS PATCH against only the exact disposable UUID at
   expected revision 5. The response was revision 6 with
   `status=tombstoned`. Active `build-test` list and scoped search no longer
   return it; a tombstoned exact-project list returns the single UUID at
   revision 6. Verification journals were retained, and no project rows exist
   to clean up because paths are derived keys rather than a second database.

## Browser artifacts

- `01-build-test-desktop-1440x900.png` — seeded Project control in the owner
  shell.
- `02-build-test-gate-1440x900.png` — exact injected UUID, score, and Project
  1.000.
- `03-build-test-graph-current-1440x900.png` — CURRENT node inspector with
  `Project · build-test`.
- `05-other-test-empty-gate-1440x900.png` — sibling path with 0 injected and 0
  near misses.
- `06-other-test-graph-current-1440x900.png` — empty sibling CURRENT Graph.

## Unscripted findings closed during the pass

- Graph node selection originally replaced the module selection and unmounted
  its own inspector. The final shared-selection mapping preserves the
  A-035/ADR-023 memory identity and keeps the Graph drawer mounted.
- Project Enter originally relied on implicit form submission. The final input
  calls the same factored open-project path as form submission, and the live
  retest switched to `other-test` with one Enter.
- Barrier-dropped events could still reach rack subscribers, a conflict remedy
  could persist forever, and a stale Graph snapshot could render under a new
  scope. Production-backed tests now close each boundary.

The control placement beside Model remains **PROVISIONAL-TASTE** for the owner
to overrule at M2X. This packet does not add a project table, filesystem
coupling, project CRUD, or M3 movement law.
