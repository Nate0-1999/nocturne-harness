# M2UX2 no-dead-ends verification

M2UX2 repairs two owner-observed breaks in one lifecycle: a full-screen Rack
view could strand the owner away from the stage, and a known thread could not
enter the already-existing archive/extraction path from the thread list.

## Evidence

- `crawl.json` is the machine-readable result of the isolated rendered crawl.
- `01-graph-back-to-stage-1280x900.png` shows the shared desktop return chrome.
- `02-thread-list-archive-review-390x844.png` shows list Archive reaching the
  ordinary five-candidate Thread End review.
- `03-stage-restored-390x844.png` shows the phone stage after the same one-click
  return.
- `SOP.md` records the independent real-owner-composition walkthrough and its
  non-mutation boundary.

The deterministic fixture is explicitly labelled `M2UX2 REGRESSION`, uses a
private disposable `NOCTURNE_HOME`, and refuses port 8765. The browser crawl
uses the production SPA and actual archive HTTP route; only its model and Spine
dependencies are deterministic. The separate SOP uses
`harness.daemon:create_dev_app`, the production remote Palace client, a unique
verification principal, and a different disposable home.

## Reproduce

Build the SPA, start the isolated fixture, then run the rendered crawl:

```sh
cd web
npm run build
cd ..
NOCTURNE_HOME=<private-temp-home> PYTHONPATH=src:. uv run --locked python \
  -m verification.run_fixture verification.m2ux2.scenario_app:create_scenario_app \
  --port 8802
cd web
npm run verify:m2ux2:browser -- --base-url http://127.0.0.1:8802
```

The retained result must report seven reachable views, five extraction
candidates, and empty console/page-error arrays. Stop only the exact fixture
process and remove only its validated disposable home after the run.
