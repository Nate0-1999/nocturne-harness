# I1 integration and acceptance-criteria dry run

Status: **PARTIAL — RETURNED TODO**

Date: 2026-07-30

This is the partial I1 builder handoff required by Garden PLAN §5. It records
substantial passing evidence and the exact closure work still missing; it does
not mark I1 complete. J must not start until a later relay closes these gaps
and the owner separately clears the H5 hold.

## Start the real local product

The source-checkout path needs one secret: an OpenRouter key. From the
directory containing the sibling `harness/` and `spine/` repositories:

```sh
cp harness/.env.example harness/.env
# Set OPENROUTER_API_KEY in harness/.env, then:
chmod 0600 harness/.env
```

Terminal 1:

```sh
cd spine
docker compose --env-file ../harness/.env up --build
```

Terminal 2:

```sh
cd harness
uv run --locked harness dev
```

Open `http://127.0.0.1:8765`. The local Spine bearer defaults to the same
`local-development-token` in Compose and `.env.example`; OpenRouter carries
both chat and embeddings. Local mode does not require an OpenAI, Anthropic, or
GCP credential. `harness dev` installs the locked web dependencies, builds the
SPA, and serves it with the daemon.

This repo-based startup is intentionally not the future `nocturne init/up/open`
packaging surface. Garden assigns that post-judge work to D3.

## C.8 criterion map

The browser path used the production SPA and daemon from the working checkout,
a newly created local Compose Spine/Postgres stack, and the live
`openrouter:minimax/minimax-m3` route. Chrome was driven through visible
clicks and typing. Screenshots 01–22 are the single end-to-end journey. The
database is replayable with [replay.sql](replay.sql); the full credential-free
receipt is [database-replay.json](2026-07-30/database-replay.json), with a
short human-readable [summary](2026-07-30/database-replay.txt).

| C.8 | Builder result | Experiential evidence | Trace or adversarial evidence | Tree node |
|---|---|---|---|---|
| AC1 — cold start and model-string chat | PARTIAL | [empty](2026-07-30/01-ac1-empty-local-compose.jpg), [zero-memory first gate](2026-07-30/02-ac1-zero-memory-gate.jpg), [live reply](2026-07-30/03-ac1-live-model-reply.jpg) | New Compose migrations and authenticated health passed in the working checkout. Harness now delegates non-default prefixes to Pydantic AI's provider registry while keeping OpenRouter/Anthropic/OpenAI credentials settings-owned; provider-registry and credential-boundary tests pass. Missing: repeat the startup and visible chat from post-push fresh clones, as C.8 literally requires. | P3, P4 |
| AC2 — preference and repeat/similar path | PARTIAL | [agent-created preference](2026-07-30/04-ac2-agent-preference-visible.jpg), [rephrased save updates the same card](2026-07-30/05-ac2-similar-updated-same-card.jpg) | Memory `5835cff3-a653-4627-8dbe-debdaed13694` has a non-null embedding; r1 and r2 have the same ID and lineaged agent revisions. Missing: a retained API/daemon trace showing the actual repeated browser action received a 409 or `similar[]` response before the same-card update. | P1.4, P1.5 |
| AC3 — gate decisions | PASS | [feature scores and near misses](2026-07-30/06-ac3-gate-feature-scores-near-misses.jpg), [canonical gate](2026-07-30/07-ac3-canonical-gate-open.jpg), [remove/add-back](2026-07-30/08-ac3-not-relevant-and-add-back.jpg), [committed response](2026-07-30/09-ac3-committed-response-and-panel.jpg) | Injection `757de54b-d1b1-4a0a-8294-a3fbd43e3161` records formatter `removed:not_relevant`, cobalt `added_back`, llama untouched, full frozen `_memory` features, prompt text, and scorer `v0`. The integrated replay test proves removed-body exclusion and added-back-body inclusion in the committed `final_block`. | P1.2.1a, P1.2.2, P1.2.3 |
| AC4 — three Never removals quarantine | PASS | [pass 1](2026-07-30/10-ac4-never-pass-1-open.jpg), [pass 1 menu](2026-07-30/11-ac4-never-pass-1-menu.jpg), [pass 1 selected](2026-07-30/12-ac4-never-pass-1-selected.jpg), [pass 2](2026-07-30/13-ac4-never-pass-2-open.jpg), [pass 2 selected](2026-07-30/14-ac4-never-pass-2-selected.jpg), [pass 3](2026-07-30/15-ac4-never-pass-3-open.jpg), [pass 3 selected](2026-07-30/16-ac4-never-pass-3-selected.jpg), [fourth-gate absence](2026-07-30/17-ac4-fourth-gate-llama-absent.jpg) | Memory `694df145-0caf-46f0-97c4-8ba343f6e7c7` is quarantined at revision 5 with `never_kills=3`, `removals=3`, and bias `-0.45000002`. The fourth injection contains zero rows for it. | P1.2.1b, P1.4 |
| AC5 — `/remember` and panel edit | PASS | [`/remember` desktop](2026-07-30/52-h8-desktop-remember-model-slug.jpg), [`/remember` phone](2026-07-30/55-h8-mobile-remember-model-slug.jpg), [edited panel card](2026-07-30/18-ac5-panel-edit-revision.jpg) | Memory `a93ae3df-9f28-4f68-95a9-d786deb284ad` has r1 `user`, r2 `system:inject`, and r3 `user` / `panel/edit`, each parented to the prior revision. The H6 replay below also forces and surfaces a real stale-revision conflict. | P1.2.1d, P1.3 |
| AC6 — injection replay | PASS | AC3 screenshots above are the rendered side of the same gate. | `spine/tests/test_inject_api.py::test_prepare_commit_replays_gate_and_prepare_updates_only_injected` performs prepare → commit → SQL replay and compares memory identity, presentation class, score, all six features, frozen memory data, prompt, scorer version, and outcomes; it also proves removed/add-back final-block membership and prepare-time CAS isolation. The complete JSON receipt reconstructs the canonical gate one-for-one. | P1.2.1a |
| AC7 — Spine death never bricks chat | PARTIAL | [gate before kill](2026-07-30/19-ac7-gate-before-spine-kill.jpg), [current thread survives](2026-07-30/20-ac7-chat-survives-spine-death.jpg), [new thread warns and runs memoryless](2026-07-30/21-ac7-new-thread-memoryless.jpg), [gate recovers after restart](2026-07-30/22-ac7-recovered-gate.jpg) | Compose Spine was stopped after a gate opened. The UI shows fail-open current/new-thread replies and a recovered gate. Missing: a committed daemon-log excerpt for this same action proving graceful degradation and no crash/stack trace. | P1.1, P3 |

The seeded local demo set is deliberately small and inspectable:

- `5835cff3-a653-4627-8dbe-debdaed13694` — active/pinned formatting preference;
- `a93ae3df-9f28-4f68-95a9-d786deb284ad` — active cobalt fact, edited from
  drawer seven to drawer eight;
- `694df145-0caf-46f0-97c4-8ba343f6e7c7` — quarantined magenta-llama junk;
- `596cd22e-8695-457c-9792-07718414fb07` — active release-note memory.

Fixture-owned H4/H5/H6/H8 memories were cleaned by exact ID after their runs.
The H5 exact states are retained in its
[cleanup receipt](2026-07-30/h5-cleanup-receipt.txt); H6/H8 cleanup events are
in their dated traces. The four I1 demo memories above remain in the local
Compose volume for inspection.

## Current UI SOP replay

I1 replayed every canonical UI path with the production SPA in connected
Chrome. The model is deterministic only where a packet fixture needs exact
ordering; no browser state was injected or advanced by scripted protocol
calls. That is strong rule-7 evidence, but it is not equivalent to the full
rule-8 SOP requirement: H4/H5/H6 still need a current five-minute unscripted
segment, with each action, screenshot, and first-person observation recorded.

| Packet | Desktop | Phone / exploration | Canonical traces | Result |
|---|---|---|---|---|
| H4 chat shell | [23–29](2026-07-30/23-h4-desktop-empty.jpg) | [30–33](2026-07-30/30-h4-mobile-empty.jpg), exact 390×844 | [desktop](2026-07-30/h4-trace-desktop.jsonl), [phone](2026-07-30/h4-trace-mobile.jsonl) | PARTIAL — canonical queue/hydration/release/Stop/terminal paths passed. The accidental Queue→Stop exploration is recorded in [H4 SOP](../h4/SOP.md) but lacks its own screenshot and timed five-minute segment. |
| H5 two-stage gate | [34–37](2026-07-30/34-h5-desktop-gate-paused.jpg) | [38–43](2026-07-30/38-h5-mobile-gate-paused.jpg), exact 390×844 | [desktop](2026-07-30/h5-trace-desktop.jsonl), [phone](2026-07-30/h5-trace-mobile.jsonl), [prepare fail](2026-07-30/h5-trace-prepare-fail.jsonl), [commit fail](2026-07-30/h5-trace-commit-fail.jsonl) | PARTIAL — current two-stage hard pauses, correction, second turn, and fail-open paths passed. The existing H5 SOP is pre-A-023 and I1 did not record a current unscripted addendum. |
| H6 live memory panel | [44–47](2026-07-30/44-h6-desktop-panel-five-units.jpg) | [48–51](2026-07-30/48-h6-mobile-gate.jpg), exact 390×844 | [desktop](2026-07-30/h6-trace-desktop.jsonl), [phone](2026-07-30/h6-trace-mobile.jsonl) | PARTIAL — current principal scope, edit/pin/remove, visible CAS conflict, retry/cancel, and frozen context passed. I1 did not record the SOP's current unscripted exploration addendum. |
| H8 polish | [52–54](2026-07-30/52-h8-desktop-remember-model-slug.jpg) | [55–63](2026-07-30/55-h8-mobile-remember-model-slug.jpg), exact 390×844 plus 320×844 | [desktop](2026-07-30/h8-trace-desktop.jsonl), [phone](2026-07-30/h8-trace-mobile.jsonl) | PASS — model truth, `/remember`, literal/sanitized rendering, reload, thread return, 320px drawer, odd unsent draft, and viewport restoration were re-executed and recorded. |

The numbered range links above open the first frame in each contiguous range;
all 63 immutable frames live in [the dated evidence directory](2026-07-30/).
Every screenshot is JPEG/JFIF and uses a matching `.jpg` extension.

## Recorded friction and limits

- On phone, Queue is stacked directly above Stop while a run is active. The
  first exploratory tap hit Stop; the fixture was reset and the canonical
  mobile path was repeated cleanly. The controls were legible, but proximity
  is worth watching in J.
- Old browser-local thread catalog entries remain visible across daemon
  restarts. The daemon snapshot is authoritative after selection; this did not
  duplicate or resurrect transcript state.
- The live model independently searched near misses and wrote a release-note
  memory during the journey. That is legitimate product behavior, but it makes
  live populations less deterministic than fixture traces.
- `injection_event` persists frozen inputs and decisions, not a separate
  rendered `final_block` column. The integrated prepare/commit test proves
  removed/add-back membership, while the H5 canonical daemon traces assert
  the full exact fixture block. SQL alone proves its reconstructable inputs.
- `npm audit` reports one high advisory in the dev-only
  ESLint → minimatch → brace-expansion chain. The production dependency tree
  is empty for that package. No blind dependency mutation was made.

## Next I1 relay

Do not dispatch J yet. A fresh I1 relay should preserve this evidence and do
only the missing closure work:

1. clone the pushed Harness and Spine revisions into fresh temporary
   directories; start with the one-secret commands above and perform a visible
   Chrome chat;
2. repeat AC2 and retain the exact 409 or `similar[]` API/daemon trace that
   caused the visible same-card handling;
3. repeat AC7 and commit the daemon log covering dependency failure, fail-open
   model completion, no stack-trace crash, restart, and recovered gate;
4. execute current H4, H5, and H6 five-minute unscripted SOP segments, adding
   per-action screenshots and first-person observations to their `SOP.md`
   files; and
5. rerun both suites, then mark I1 DONE only if all of the above passes.

After that, J still requires a fresh independent session and the owner's
separate H5 hold clearance.
