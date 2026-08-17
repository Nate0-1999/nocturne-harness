# SYM11 capture SOP

1. Build the checked-out web shell with `cd web && npm run build`.
2. From the Harness root, start the isolated app on a non-owner port:
   `UV_CACHE_DIR=/tmp/n8-sym11-fixture-uv uv run uvicorn verification.sym11.scenario_app:create_scenario_app --factory --host 127.0.0.1 --port 8871`.
3. Open `http://127.0.0.1:8871/?fixture=SYM11%20REGRESSION`. Confirm both fixture banners are visible before capturing anything.
4. Create a thread and send `Take this to a symphony.` Fill the deliberation exactly as in the SYM10 SOP, sign T2, and also check `Hold the toy run live on the Deck so I can exercise steering`.
5. Press `Sign & run toy Symphony`, then use the Work-layer module list to focus `The Deck`. Confirm three running attempts and the exact stack identity are visible.
6. In `Clarify inside the signed charge`, choose `attempt-1`, enter `Show the owner-visible lineage mark.`, and press `Log clarification`. Confirm the follow-up appears without a new stack identity.
7. Press `Cancel attempt` on `attempt-2`. Confirm it becomes cancelled, retains evidence marks, says memories were not admitted, and the run remains live.
8. In `Change a charter by forking`, change the motivation rubric to `Preserves the revised owner reason`, change evidence to `A fresh signed fork`, sign the fork, and press `Sign & fork`.
9. Confirm the parent is an amber `Owner demand` card with full `Continue in` identity, while a separately identified running child shows full `Forked from` identity. The parent must remain visible and append-only.
10. Reload the page. Confirm the blocked parent, its demand, and running child rehydrate from the transcript. Finish the child with `Finish surviving attempts`; confirm the completed stack remains on the Deck.
11. Check browser warnings/errors, then regenerate `SHA256SUMS` with `shasum -a 256 verification/sym11/*.png`.
