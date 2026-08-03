# M2I seed ingestion walkthrough

1. Build the committed web bundle with `cd web && npm run build`.
2. Start the deterministic fixture on its isolated port:
   `PYTHONPATH=src:. uv run --locked uvicorn verification.m2i.scenario_app:create_scenario_app --factory --host 127.0.0.1 --port 8775`.
3. Open `http://127.0.0.1:8775/?fixture=M2I%20REGRESSION` and confirm the
   unmistakable `M2I REGRESSION FIXTURE` marker.
4. Open **Palace queue**. Confirm the empty state says seed work waits without
   expiring or interrupting the owner.
5. Choose one `.md` file no larger than 24 KiB. Confirm the resulting document
   appears as one batch whose semantic children have individual labels,
   keywords, bodies, and proposed verdicts.
6. Switch GLOBAL/CURRENT and confirm the module follows the shared rack scope.
7. Approve or reject the whole batch. Confirm the batch disappears, the empty
   state returns, and `/__scenario__/trace` records one explicit/human decision
   per child with zero pending cards.
8. Repeat at 390×844. The upload control, both batch actions, every child, and
   the resolved state must remain readable without horizontal scrolling.

The fixture is deterministic evidence, never the owner app and never evidence
of a live model call. During the M2I relay the in-app browser's file-chooser
event did not propagate from the sandboxed rack iframe, so the same local
`POST /v1/seeds` boundary was used to seed the fixture before steps 6–8. The
live service tests cover the upload route; screenshots cover the rendered
review and decision surfaces.
