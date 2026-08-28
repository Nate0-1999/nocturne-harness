# NOCTURNE

NOCTURNE is an agent harness backed by its Memory Palace. The public
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
running it to use an existing environment secret without a prompt. Init also
installs the headless browser runtime used by the browser tools. The coding
tools are Python dependencies in the `nocturne-ai` wheel; init does not download
Node or a second agent runtime.

`nocturne up` pulls pgvector, applies the packaged database migrations, starts
the installed Spine and Harness wheels, and opens <http://127.0.0.1:8765>.
Keep that command running; Ctrl-C stops the two Python services while retaining
the local database volume. `nocturne open` reopens an already-running UI.

## Existing remote Palace

If your Palace is already running in your own cloud, connect the same installed
daemon directly to it:

```sh
nocturne init --remote https://YOUR-SPINE-SERVICE
nocturne up
```

`init` uses `OPENROUTER_API_KEY` when it is already exported, otherwise it
prompts for it, then privately prompts for your Palace access token. `up` checks that
Palace, starts only the local daemon, and opens the Rack; it does not start
Docker or a second Spine. Existing checkout users can replace sourcing `.env`
and running `uv run harness dev` with those two commands, entering the same
`SPINE_URL`, `SPINE_TOKEN`, and OpenRouter key when prompted. The private config
remains at `~/.nocturne/env` with owner-only permissions.

`nocturne doctor` checks the remote Spine plus the local conversation journal
and disk. It says plainly that local database and backup checks are skipped;
those remain the remote Palace operator's responsibility.

`nocturne up` saves a verified private database backup before it attempts a
migration. While the local Palace is running, `nocturne backup` creates another
backup on demand. Each generation lives under `$NOCTURNE_HOME/backups` with a
private receipt containing its database revision, size, and SHA-256 digest.
NOCTURNE keeps five generations by default; set
`NOCTURNE_BACKUP_GENERATIONS` in the private config to retain between 1 and 50.
Run `nocturne doctor` to re-check those backups and see the database,
conversation-journal, backup, and free-disk sizes before space is low.
`nocturne up` performs the same free-space check before Docker work and warns
without prompting or stopping. Palace Vitals passively shows current free disk,
database, journal, backup, daemon-memory, and daemon-uptime measurements.

To inspect an older generation without risking the live Palace, stop
`nocturne up` and run `nocturne restore BACKUP_ID`. NOCTURNE restores and
upgrades that generation in a fresh database volume, then prints the memories,
edits, pins, and event counts that would roll back. It switches only when you
type the displayed backup-bound confirmation phrase. The former volume is kept
and recorded under `$NOCTURNE_HOME/rollback-volumes`; a failed or cancelled
restore leaves the live Palace unchanged.

For an isolated install root, set `NOCTURNE_HOME` before `init`, `up`, and
`deploy`. Set `NOCTURNE_POSTGRES_PORT` before `init` when port 5432 is already
owned by another local database.

While the daemon runs, it durably appends each thread's messages and run events
to owner-only JSONL files under `$NOCTURNE_HOME/transcripts`. These files are
local, append-only, and never stored in Git. On startup, NOCTURNE verifies that
the journal can durably accept writes and reloads each conversation from its
durable tail before serving the UI.

Ordinary owner chat uses the official `pydantic-ai-harness` filesystem, shell,
and Skills capabilities through NOCTURNE's owned adapter. Reads are free. Edit
and write require the agent to stand in the file's exact directory; shell work
may span only the current location's subtree. The agent must move before a
deliberate file modification elsewhere in that project. On macOS, shell
commands run behind the operating-system sandbox with network denied and a
scrubbed environment. Remote pushes, deploy commands, and credential reads stop
with a plain boundary message. Skills in project `.agents/skills` or legacy
`.pi/skills`, plus their user-level equivalents, are deferred until useful;
their bundled references, assets, and scripts remain available through the
same fenced tools. Every tool call and result is appended through the same
conversation journal, and provider usage continues through the existing spend
ledger.

Chat also has five headless browser tools: navigate, click, type, read the page,
and take a screenshot. Localhost and files beneath the agent's current location
work by default. External sites stop at a thread-local wall until the owner sends
the exact command `/browser allow-web`; that one grant is retained in the thread
journal. Screenshots return to the model as images and appear in the existing
Tools detail in the conversation.

The Injection Console owns the memory-context share beside the other scorer
parameters. It can DEEP-simulate and informed-force a versioned starting point;
the ordinary learner resumes from that generation once 100 authentic owner
dispositions make share and threshold trainable. Context Bars shows the actual
memory block against the share and names pinned overflow. The share is a
ceiling, so unused room remains available to chat; pins always inject.

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
