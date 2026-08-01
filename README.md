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

For an isolated install root, set `NOCTURNE_HOME` before `init`, `up`, and
`deploy`. Set `NOCTURNE_POSTGRES_PORT` before `init` when port 5432 is already
owned by another local database.

## Cloud deployment

```sh
nocturne deploy --dry-run
nocturne deploy
```

Cloud mode uses the same OpenRouter key plus the human's existing `gcloud`
authentication. Under the current D1 contract it reconciles only the named
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
