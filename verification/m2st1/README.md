# M2ST1 Stage verification

This retained deterministic browser pass drives the production-composed Rack
through the host camera and layer controls. It proves whole-stage zoom, Graph
as an ordinary module, exact module and layer removal/restore, off-screen
recall, independent per-layer geometry, and reload persistence.

Run from the Harness root after building `web/dist`:

```sh
PYTHONPATH=src uv run uvicorn verification.m2st1.scenario_app:create_scenario_app \
  --factory --host 127.0.0.1 --port 8806
node verification/m2st1/browser_check.mjs --base-url http://127.0.0.1:8806
```

The server is an isolated `M2ST1 REGRESSION` fixture and refuses product port
8765. `stage.json` and the two screenshots are generated evidence.
