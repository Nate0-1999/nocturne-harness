# SYM10 capture SOP

1. Build the checked-out web shell with `cd web && npm run build`.
2. From the Harness root, start the isolated app on a non-owner port:
   `UV_CACHE_DIR=/tmp/n8-sym10-fixture-uv uv run uvicorn verification.sym10.scenario_app:create_scenario_app --factory --host 127.0.0.1 --port 8870`.
3. Open `http://127.0.0.1:8870/` in a browser and confirm both fixture banners
   are visible before capturing anything.
4. Create a new thread, send `Take this to a symphony.`, and confirm the
   deliberation card appears in that same transcript.
5. Enter an owner-authored outcome and motivation. Fill the recipe title and
   observable `Done when`, retain its search mark, then fill all three core
   judge rubrics/evidence requirements and the performance metric.
6. Keep the R22 defaults (3 attempts, $10, 3 rounds, depth 2, 4 children per
   attempt, 30 minutes), check the full T2 authority sentence, and capture the
   objective, charter, and authority views.
7. Press `Sign & run toy Symphony`. Confirm one returned result card says the
   conversation is already live, gives a separate Symphony identity, and
   repeats the signed wall and search-node count.
8. Reload the page. Confirm the completed draft no longer renders as an open
   form and the result card remains in the same transcript.
9. Read `/v1/symphonies/<identity from the result card>` and verify `completed`,
   `execution_kind: toy`, the same thread, the signed launch artifact, three
   charter digests, and the completed timeline.
10. Check browser warnings/errors, then regenerate `SHA256SUMS` with
    `shasum -a 256 verification/sym10/*.png`.
