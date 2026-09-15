# M3WF walk fixture

This is disposable regression data, never owner history. Use ports 8902 (Spine),
8903 (first identity), 8904 (second identity), and 55436 (Postgres).
The launcher refuses the product port and displays the fixture curtain.

From `harness/`, with the sibling Spine source and the normal development
environment installed:

```sh
docker compose -f verification/m3wf/compose.yaml up -d --wait
NOCTURNE_HOME=/private/tmp/m3fx-step6-home PYTHONPATH=src:../spine/src .venv/bin/python -c 'from verification.m3wf.scenario_app import fixture_config; from spine.db.migrate import upgrade_head; upgrade_head(fixture_config().database_url)'
```

Export `M3WF_OPENROUTER_API_KEY` from an authorized disposable credential source
in each Harness shell. M3SC uses `openrouter:minimax/minimax-m3`; the local Qwen
fixture did not reliably call tools. The database and lexical embeddings stay
local. Start each command in a separate foreground shell:

```sh
NOCTURNE_HOME=/private/tmp/m3fx-step6-home PYTHONPATH=src:../spine/src /usr/bin/sandbox-exec -f verification/m3wf/local-only.sb .venv/bin/python -m verification.run_fixture verification.m3wf.scenario_app:create_spine_app --port 8902
NOCTURNE_HOME=/private/tmp/m3fx-step6-home PYTHONPATH=src:../spine/src .venv/bin/python -m verification.run_fixture verification.m3wf.scenario_app:create_harness_app --port 8903
NOCTURNE_HOME=/private/tmp/m3fx-step6-second-home PYTHONPATH=src:../spine/src .venv/bin/python -m verification.run_fixture verification.m3wf.scenario_app:create_second_harness_app --port 8904
```

The Spine process's macOS policy allows only loopback traffic. Spine uses deterministic lexical
fixture vectors, not learned semantic embeddings. Only the first fixture
principal **and** machine qualify for learning in this fixture process; production
exclusion is unchanged. Curators have no cloud key.

Seed the corpus once on a fresh database. Then restore the recorded gate history:

```sh
NOCTURNE_HOME=/private/tmp/m3fx-step6-home PYTHONPATH=src:../spine/src .venv/bin/python -m verification.m3wf.seed
NOCTURNE_HOME=/private/tmp/m3fx-step6-home PYTHONPATH=src:../spine/src .venv/bin/python -m verification.m3wf.seed --recorded-history
```

`recorded-gates.json` contains 102 real gate records from the M3FX browser walk,
including subsequent citations, with original identities, event IDs and times.
History restoration is idempotent and does not activate a scorer. Imported
records are replayed fixture history, not new human activity. Their frozen memory
bodies support replay independently of the newly seeded memory IDs.

Open `http://127.0.0.1:8903/?fixture=M3WF+REGRESSION`. For fresh signals, ask about
orchard delivery, keep the four orchard facts and remove telescope facts as not
relevant; reverse that judgment for an observatory request. Never mark an
otherwise correct fact globally wrong merely because it is irrelevant. Four
eight-memory gates clear the 25-signal floor; share/threshold learning needs 100.
Unpin the corpus after the pin-overflow walk. Use Force Retrain, then simulate.
For Audition, place the Injection Console nearest a Focused Conversation and
choose Nearest source; a whole-stack target has no single frozen gate.

For ingestion, focus the existing “Drop, paste, or choose Markdown” control and
paste fictional Markdown. This avoids a native file chooser. Before walking agent
behavior, ask it to read a disposable file and confirm a successful tool result
in the journal. Fixture limits mean unproven rows, not product regressions.
The second identity is a same-host stand-in;
FL-001's real second machine and FL-101's phone still need hardware.

After saving evidence, stop these foreground processes, remove only their named
disposable homes/caches as appropriate, and run:

```sh
docker compose -f verification/m3wf/compose.yaml down --volumes
```
