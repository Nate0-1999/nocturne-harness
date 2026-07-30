# H9 live catalog verification

Run from the Harness repository with the untracked `.env` present:

```sh
UV_CACHE_DIR=/tmp/n8-harness-uv-cache \
  uv run --locked python verification/h9/live_catalog_probe.py
```

The probe calls OpenRouter's Artificial Analysis benchmark and model listings
through the production H9 client. It prints only model metadata, policy
decisions, context lengths, and the fetch timestamp; it never prints the API
key or response headers. Unit tests own deterministic selection and fail-open
assertions because the live catalog changes independently of this repository.

`live-catalog-receipt.json` records the 2026-07-30 acceptance run. In that
snapshot `max`, `slope:0.05`, and `floor:52` resolved runnable standard routes
with positive contexts. `elbow` encountered a zero-priced frontier row and
therefore recorded A-025's static fail-open condition.
