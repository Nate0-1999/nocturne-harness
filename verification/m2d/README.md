# M2D — Durable transcript capture evidence

Date: 2026-08-02
Session: `codex / 2026-08-02 / fe58`

M2D is capture-only. The production daemon writes one standard-JSONL file per
opaque thread beneath `$NOCTURNE_HOME/transcripts`; it does not load those rows
into `thread.snapshot`, answer transcript queries, rewind a thread, or create
M3's session schema.

## Acceptance map

- `src/harness/transcript.py` hashes thread ids into filenames, refuses a Git
  ancestor and replaced/symlinked roots or thread files, enforces directory and
  file modes 0700/0600, and appends complete newline-delimited records under a
  file lock. Each completed record is `fsync`ed. A failed partial append is
  truncated to its starting offset, and a pre-existing incomplete tail is
  separated before the next valid row.
- `src/harness/run_loop.py` captures prompts before asynchronous model
  resolution, serializes same-thread resolution in capture order, and captures
  daemon-authored C.7 events before delivery even with no subscriber. Capture
  failure poisons in-flight and future work rather than permitting an
  unjournaled continuation.
- Message snapshots contain ADR-016 `parentId`. Each row also records the
  current logical `tail_message_id`, so queued-message revisions cannot move
  restart continuity backward. Restart reads only that tail id for the next
  link; it does not hydrate process state.
- Captured events include text/thinking/event deltas, usage, gates, errors,
  terminal events, tool results, and `/model` `model_change`. Snapshot resyncs
  and `memory.panel.update` query replies remain serving artifacts and are not
  copied into JSONL.
- `src/harness/onboarding.py` propagates the initialized `NOCTURNE_HOME` to
  both services. The repository README documents the owner-local path and the
  capture-only restart boundary. Decision 025 records the P3 design boundary.

## Regression evidence

`tests/test_transcript.py` covers hashed paths and modes, Git/root/leaf safety,
record fsync and rollback, incomplete-tail recovery, prompt-before-resolution,
same-thread resolver ordering, detached capture, event identity and payload
kinds, queued-parent correction without tail regression, restart continuity,
and the empty snapshot/no-write serving boundary. `tests/test_daemon.py`
covers gate/error capture plus panel-response exclusion. `tests/test_onboarding.py`
covers the shared home propagation.

Final Harness commands:

```text
PYTHONPATH=src uv run --locked pytest -q -m 'not contract'
549 passed, 3 deselected in 1.66s

.venv/bin/ruff check .
All checks passed!

.venv/bin/ruff format --check src tests
45 files already formatted

Spine final suite (from the sibling `spine` checkout):
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock \
TESTCONTAINERS_RYUK_DISABLED=true PYTHONPATH=src uv run --locked pytest -q
174 passed in 5.82s
```
