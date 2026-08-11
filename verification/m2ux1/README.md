# M2UX1 — No-overlap / no-clip sweep

This packet fixes the owner-observed Header collision and the thread-list title
that ended mid-word. The permanent unit test owns the width ladder and shared
geometry rule. `browser_check.mjs` supplies the rendered proof by translating
each sandboxed Rack module into host coordinates, then auditing the shell and
all five overlay modules at every width.

From the Harness repository, start the deterministic, local-only M2H fixture
with a fresh private journal home on a non-owner port:

```bash
M2UX1_HOME="$(mktemp -d /private/tmp/nocturne-m2ux1.XXXXXX)"
NOCTURNE_HOME="$M2UX1_HOME" PYTHONPATH=src:. uv run --locked python \
  -m verification.run_fixture verification.m2ux1.scenario_app:create_scenario_app \
  --port 8801
```

Then run:

```bash
npm run verify:m2ux1:browser --prefix web -- \
  --base-url http://127.0.0.1:8801
```

The driver creates one local fixture thread only. Stop the exact fixture
process, validate the temporary path, and remove only that private home.

## Evidence

- `00-owner-before.jpg` — read-only owner-app reproduction before the fix.
- `01-fixed-desktop-1280x900.png` — corrected shared Header lane.
- `02-thread-title-mobile-390x844.png` — word-safe title in the phone drawer.
- `03-ultrawide-1920x900.png` — upper end of the viewport ladder.
- `04-live-desktop-1280x720.jpg` — independent in-app browser walk with the
  Palace Queue open and the repaired Header still owner-operable.
- `rendered-sweep.json` — all audited viewport/module states and clean browser
  diagnostics.
- `SOP.md` — independent interactive browser walk.
