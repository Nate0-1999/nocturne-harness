# M2UX3 module-template verification

M2UX3 replaces two handling systems with one constrained-grid template for the
five composable stage modules: Channel Stack, Active Channel, Memory Palace,
Palace Vitals, and Context Bars. Full-screen modules remain in M2UX2's
host-owned lifecycle; M3 still owns the freeform infinite canvas.

## Evidence

- `module-template.json` records the exact mounted template set, hover cursors,
  Vitals geometry after pointer drag, edge resize, corner resize, and reload.
- `01-vitals-moved-edge-resized-1280x900.png` shows Vitals after moving behind
  Context Bars and changing to 10×2 grid units.
- `02-vitals-layout-restored-1280x900.png` shows the moved layout after reload.
- `SOP.md` records the bounded human-readable walkthrough.

The fixture is explicitly labelled `M2UX3 REGRESSION`, uses a private
disposable `NOCTURNE_HOME`, and refuses port 8765. It serves the production SPA
and exercises real pointer events plus browser localStorage; only its model and
Spine dependencies are deterministic.

## Reproduce

```sh
cd harness/web
npm run build
cd ..
NOCTURNE_HOME=<private-temp-home> PYTHONPATH=src:. uv run --locked python \
  -m verification.run_fixture verification.m2ux3.scenario_app:create_scenario_app \
  --port 8804
cd web
npm run verify:m2ux3:browser -- --base-url http://127.0.0.1:8804
```

The retained result must enumerate all five stage modules, record the three
cursor classes, restore Vitals at `x=4,width=9,height=4`, and contain empty
console/page-error arrays.
