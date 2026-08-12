# M2ST3 rendered SOP

1. Build the canonical web assets: `cd web && npm run build && cd ..`.
2. Start the isolated fixture on port 8807:
   `UV_CACHE_DIR=/tmp/n8-uv-cache-m2st3 uv run --locked --extra dev uvicorn verification.m2st3.scenario_app:create_scenario_app --factory --host 127.0.0.1 --port 8807`.
3. In another shell run `node web/../verification/m2st3/browser_check.mjs`.
4. Confirm the PASS line, inspect both screenshots, and stop only that fixture.

The script refuses raw precision, identity/readout overlap, full-width absent
gauges, graph-label overlap, missing priority declutter, console errors, or page
errors.
