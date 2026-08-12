# M2ST2 rendered SOP

1. Build the canonical web assets: `cd web && npm run build && cd ..`.
2. Start the isolated fixture on port 8777:
   `UV_CACHE_DIR=/tmp/n8-uv-cache-m2st2 uv run --locked --extra dev uvicorn verification.m2st2.scenario_app:create_scenario_app --factory --host 127.0.0.1 --port 8777`.
3. In another shell run `npm --prefix web run verify:m2st2:browser`.
4. Confirm the PASS line, inspect both screenshots, and stop only that fixture.

The script opens the title-adjacent app gear, changes the live theme through the
existing host-to-frame seam, and proves theme/layout controls no longer occupy
the work toolbar. It changes Spend to “This thread” through the declared Rack
scope action, confirms Channel Stack replaces a dead scope toggle with a reason,
refuses the removed implementation labels, checks the 390×844 gear hit area
against the compact thread control, and fails on console or page errors.

The fixture is deterministic evidence, not owner-app or provider evidence.
