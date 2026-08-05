# NOCTURNE

NOCTURNE is a local agent harness backed by its Memory Palace. The public
Python distribution is `nocturne-ai`; the product and command remain
`nocturne`.

## Local quickstart

Prerequisites: Python 3.12, [pipx](https://pipx.pypa.io/), and Docker Desktop
or Colima. You do not need Git, a repository checkout, or Node.

```sh
pipx install nocturne-ai
nocturne init
nocturne up
```

`nocturne init` asks for one value: an OpenRouter API key. It generates the
database password, Spine bearer token, and local identity, then stores them in
`~/.nocturne/env` with owner-only permissions. Set `OPENROUTER_API_KEY` before
running it to use an existing environment secret without a prompt.

`nocturne up` pulls pgvector, applies the packaged database migrations, starts
the installed Spine and Harness wheels, and opens <http://127.0.0.1:8765>.
Keep that command running; Ctrl-C stops the two Python services while retaining
the local database volume. `nocturne open` reopens an already-running UI.

`nocturne up` saves a verified private database backup before it attempts a
migration. While the local Palace is running, `nocturne backup` creates another
backup on demand. Each generation lives under `$NOCTURNE_HOME/backups` with a
receipt containing its database revision, size, and SHA-256 digest. NOCTURNE
keeps five generations by default; set `NOCTURNE_BACKUP_GENERATIONS` in the
private config to retain between 1 and 50.

For an isolated install root, set `NOCTURNE_HOME` before `init`, `up`, and
`deploy`. Set `NOCTURNE_POSTGRES_PORT` before `init` when port 5432 is already
owned by another local database.

While the daemon runs, it durably appends each thread's messages and run events
to owner-only JSONL files under `$NOCTURNE_HOME/transcripts`. These files are
local, append-only, and never stored in Git. This is capture-only in M2: a
daemon restart preserves the files but does not yet reload them into the UI.

Archiving a thread runs the memory extractor over that durable journal, then
opens the law-bound Thread Memory Review rack module. Candidate memories remain
invisible to search and model context until approved. Rows wholly visible in
the viewport may be passively kept when the card resolves; unseen rows and
contradictions remain pending. `EXTRACTION_IDLE_HOURS` controls the abandoned-
thread fallback (24 hours by default). The queue never sends notifications.

The Palace Queue also accepts `.md` and `.markdown` seed files up to 24 KiB.
NOCTURNE semantically splits each document into standalone, lineaged candidate
memories and groups them by source document. Seed batches are corpus-born:
they never appear in thread-end cards, never resolve passively, and enter the
Palace only through an explicit whole-batch approve action.

## Cloud deployment

```sh
nocturne deploy --dry-run
nocturne deploy
```

Cloud mode additionally requires the Google Cloud CLI with the human's existing
`gcloud auth`, Docker Buildx, and the Cloud SQL Auth Proxy available as
`cloud-sql-proxy`. It uses the same OpenRouter key. Under the current D1
contract it reconciles only the named
`n8-memory-palace` foundation in `us-central1`: the project must already be
ACTIVE and billed, and the PostgreSQL 16 Cloud SQL instance
`n8-memory-palace-db` must already exist. Missing foundation resources stop the
run; the command never creates a project, changes billing or budgets, deletes
resources, grants broad IAM, or invokes Cloud Build.

The dry run performs read-only inspection and labels each operation as a no-op,
create, monotonic update, human boundary, or blocker. Apply rechecks state,
packages the installed `nocturne-spine` source, migrates separately, builds and
pushes locally for `linux/amd64`, and reconciles the single protected Spine
service. The billing breaker is a final, real-TTY human gate: an exact armed
topology is a no-op, a completely fresh topology requires the destructive
confirmation, and partial or drifted topology stops for the recovery runbook.

The Garden governance repository is intentionally absent from both wheels.
