# SYM12 capture SOP

1. Build the checked-out shell with `cd web && npm run build`.
2. Start the isolated fixture on a non-owner port:
   `UV_CACHE_DIR=/tmp/n8-sym12-fixture-uv PYTHONPATH=src uv run --locked python -m verification.run_fixture verification.sym12.scenario_app:create_scenario_app --port 8872`.
3. Open `http://127.0.0.1:8872/?fixture=SYM12%20REGRESSION` and confirm the
   deterministic-evidence banner is visible before capturing.
4. Open the Graph layer and use Library to add Recipe. Confirm it touches Memory
   Graph in the same proximity frame and remains independently movable,
   resizable, removable, and recoverable from Library.
5. Confirm the graph visibly distinguishes ordinary packets, the diamond search
   node, and the three judge gates; dependency arrows run left to right; the
   ready search glows; running, blocked, and passed nodes remain distinguishable.
6. Select `Find the hard answer`. Confirm the inspector states its motivation
   and the selection does not open or leave the Stage.
7. Open Recipe settings. Confirm the local choice says `This frame`, the only
   escape says `Everything`, and no cross-layer or link-color control exists.
8. Resize Recipe narrow and wide. Confirm labels, graph, counts, and inspector
   remain readable and keyboard selection still works.
9. Check browser warnings/errors. Capture only this fixture; it is not owner-app
   evidence and must never be labelled as such.
