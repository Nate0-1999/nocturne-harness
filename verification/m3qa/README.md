# M3QA — Quiet the 404

This evidence exercises the real packaged Rack against a deterministic
0.1.6-shaped Palace. The scenario routes curator activity through the shipped
`SpineClient`; its mock Palace returns the same endpoint-level HTTP 404 as the
released 0.1.6 service while the remaining Palace State reads stay live.

Observed on 2026-09-01:

- `/__scenario__/palace` declared version `0.1.6`, schema `0017`, API contract
  `0.1.6`, and absent curator activity.
- The upstream curator read returned 404; the local `/v1/curation` adapter
  returned HTTP 200 with JSON `null`.
- Palace State rendered `Activity unavailable` and stayed otherwise readable.
- Conversation contained zero `Rack action failed` rows; the in-app browser
  recorded zero warnings or errors.
- No owner data, Palace data, or provider path was touched.

Run the scenario from the Harness checkout:

```sh
NOCTURNE_HOME=/tmp/nocturne-m3qa-home PYTHONPATH=src:. \
  .venv/bin/uvicorn verification.m3qa.scenario_app:create_scenario_app \
  --factory --host 127.0.0.1 --port 8912
```

Then open `http://127.0.0.1:8912/`. The fixture banner is intentionally loud;
it prevents deterministic proof from being mistaken for the owner app.

Artifacts:

- `legacy-palace-contained.png` — the complete Rack capture.
- `legacy-palace-palace-state.png` — the Palace State crop.
- `owner-trace.json` — the exact compatibility and rendered outcomes.
- `SHA256SUMS` — integrity manifest for the evidence above.
