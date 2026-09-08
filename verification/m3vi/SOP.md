# Verification identity and home isolation

PRECEDENT: PLAN M3VI; F069; SPEC C.4 and D.2 113b; ADR-003/016/019;
Decision 109. A verification walk must not mix its memories or journals with
the owner's. Session: codex / 2026-09-08 / vi08.

## Build and scope

Continued the interrupted implementation already on main, `15f7368`, from
`04306e0`. Added the queue ownership guard in `2d6de23`. Tests and the real
walk used an isolated archive of that base with only the M3VI client/tests
overlaid, leaving M3RL's concurrent runtime, daemon, transcript and web edits
alone. Canonical built assets were served by `harness.packaged:create_app`.
This is packaged-factory evidence, not an installed-wheel certification.

The released Palace uses a static bearer with Palace-wide authority; it does
not derive principal from the token. The daemon supplies its configured
principal to scoped operations. The memory panel now uses the server-scoped
graph projection instead of downloading the global memory list. Foreign
memory IDs are refused at the daemon, and queue item/batch IDs must first be
proven to belong to its scoped queue. Same-process queue retries work;
already-decided IDs after restart fail closed because the pending queue can
no longer prove ownership. This does not turn the shared bearer into separate
user credentials or hide the intentionally global aggregate State/Spend APIs.

## Real walk

Real `init_nocturne(verification=True)` created a fresh home at
`/tmp/m3vi-vi08-verification/home`, including the browser runtime. Its principal
was `nocturne-verification-38c5c9a7-6657-43bc-a63f-ba0455aa16c3`.
The saved env contains both principal and canonical home; backup was off.
Keys came selectively from the authorized ignored project env, never the
owner's env. GATE section 4 already names this explicit setup.

The verification daemon ran at port 8883. A second, read-only observer at 8884
used principal `local` and its own fresh disposable `observer` home. The actual
owner daemon was not running. This substitute compared the same owner memory
scope without accessing the owner's home or capturing its rack. The observer
created only a local empty thread snapshot; no prompt or owner Palace write.
All screenshots are from the fresh verification origin in Codex's in-app browser.
Spend was removed before captures to avoid global thread labels in evidence.

1. PASS: the memory panel and graph started empty, while the observer had 52
   memory heads. `01-verification-memory-panel-empty.jpg` and
   `02-verification-memory-graph-empty.jpg`; identity and before JSON files.
2. The first `/remember The disposable verification lighthouse flashes violet
   twice at noon.` with `minimax/minimax-m3` ended `budget_exceeded`, with one
   request and no memory write. FAIL retained in
   `03-remember-metadata-budget-failure.jpg` and `restart-proof.json` (F075).
3. Changed model through `/model openrouter:openai/gpt-4.1-mini`, then repeated
   `/remember`. PASS: memory `10d6f0ad-9ce4-44e3-b39b-3ef52566f19f` saved in
   the verification principal. `04-verification-memory-saved.jpg`,
   `05-verification-memory-graph-own-node.jpg`, `saved-memory.json`.
4. Asked its color and frequency. PASS: the gate selected only that memory,
   with zero near misses; Continue produced “The disposable verification
   lighthouse flashes violet twice at noon.”
   `06-verification-gate-own-memory-only.jpg`. The observer's 52 heads retained
   the exact before hash and did not contain the verification memory.
5. Stopped only the verification daemon, sourced its saved env, and restarted
   the same packaged factory, without separately exporting NOCTURNE_HOME.
   PASS: identity unchanged, eight unique messages restored in the same thread,
   memory present. `07-verification-restart-restored.jpg`, `restart-proof.json`,
   `doctor.log` and `separate-journals.json`. Doctor reports the configured home;
   `/v1/identity` verifies the running daemon on this nonstandard port.
6. Created one seed in each of two disposable principals. The rack showed only
   `m3vi-own.md`; rejected that batch through the UI.
   `08-verification-queue-own-candidate.jpg`. Forged foreign item and batch
   decisions were blocked and the other queue stayed pending. The base daemon
   renders the raised client refusal as HTTP 500 (F076); no foreign write
   occurred. `foreign-queue-refusals.json` and `restart-daemon.log`.

Unscripted: explored Whole Stage, zoom, panning, and off-screen module focus;
the camera can leave modules clipped, as some retained captures show. Reframed
the restored conversation without changing content. No product repair was
inferred from this navigation experiment.

## Home trace and regression

The original M3RS session first launched with an explicit disposable home,
then restarted by sourcing `/tmp/nocturne-m3rs-home-rs02/env` and exporting
PRINCIPAL_ID without NOCTURNE_HOME. The old env writer omitted the latter;
the daemon journal root read process environment directly and fell back to
`Path.home() / '.nocturne'`. An explicit home was not being ignored in every
launch. Persisting the canonical home and resolving all daemon file roots
from HarnessSettings closes both the sourced-env and dotenv-loaded paths.

`home_trace.py` replays the old launch against `15f7368^`, using a fake user
home: `home-before.json` has zero verification journals and one fallback journal;
`home-after.json` has one verification journal and zero fallback journals.
Neither replay accesses the real owner home. The two required isolation tests
are `test_verification_daemon_cannot_list_owner_memories` and
`test_nondefault_home_env_keeps_all_daemon_files_out_of_owner_home`.
The first also refuses an owner sentinel pin and a browser-forged principal.
The six-test file covers init refusal, running-daemon mismatch, and both queue
decision forms. `queue-before.log` records the two expected old-code failures.

## Verification and cleanup

Boot: Spine 298, Harness 1702 including all three real Palace contracts, and
packaged heartbeat passed. Exit: Harness 1704, Spine 298, web 132, lint/build,
and full rendered UI canon passed, including the consecutive-send heartbeat.
Full-suite tests use a disposable system HOME with NOCTURNE_HOME unset so tests
can choose their own homes. Initial sandbox/Docker and conflicting-home test
invocations were setup errors; the corrected host runs are the retained results.
The motivation checker retains 31 inherited findings; M3VI's tests have valid
citations. No unrelated citation changes were made in peer-owned files.

Both seed candidates and the saved memory are tombstoned, zero active memories
or pending queue cards remain in either disposable principal, and neither has a
curator run. The own principal retains its honest admitted-write counter and
Palace audit history; these are not erased. `cleanup-receipts.json` and final
scope JSON record this. Graph totals include tombstones; active counts are zero.
The observer's 52 heads still hash to the exact original digest after cleanup.
The verification tab, both daemons, disposable homes and credentials were removed.
No access to the owner's ~/.nocturne occurred. Evidence hashes and a credential
scan accompany this handoff.
