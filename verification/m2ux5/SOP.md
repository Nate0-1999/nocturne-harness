# M2UX5 plate-press SOP

Status: **NOT COMPLETE**. The 2026-08-12 fixture walkthrough reached the
rendered `M2UX5 REGRESSION` Rack and the visible Theme / Press image controls.
Chrome then refused automation's file injection because the Codex extension
did not have **Allow access to file URLs** enabled. That refusal is environment
state, not acceptance evidence. No screenshots were committed.

## Isolated fixture

Start the fixture on an unused non-product port:

```sh
UV_CACHE_DIR=/tmp/nocturne-m2ux5-fixture-cache \
  PYTHONPATH=src uv run --locked python -m verification.run_fixture \
  verification.m2ux5.scenario_app:create_scenario_app --port 8808
```

Open `http://127.0.0.1:8808/?fixture=M2UX5%20REGRESSION`. Confirm the visible
fixture marker before taking evidence. Use only this isolated fixture; SPEC
v2.72 forbids committed owner-Rack captures.

## Human-style acceptance walk

1. Look at the ordinary Stage toolbar. Confirm the three curated themes remain
   present and `Press image` sits beside the one Theme selector. Capture the
   initial fixture state.
2. Click `Press image`, choose
   `web/src/themes/cobalt-seraph-plate.png`, and observe the busy then success
   voice. Confirm `PLATE 40BFC441` joins the selector and becomes worn. Capture
   the applied Rack, including at least one sandboxed module.
3. Reload. Confirm the named colorway and its visible Rack treatment persist.
   Select a curated face and the pressed face again; observe both changes.
4. Select the pressed face, click `Remove colorway`, and observe that NEO-NOIR
   becomes worn and the pressed option disappears. Reload and confirm removal.
5. Press `verification/m2ux4/02-seraph-dressed-1280x900.png`. Confirm a second
   named colorway becomes switchable, survives reload, and removes cleanly.
6. Press a deliberately low-contrast monochrome PNG. Confirm no option is
   added and the visible refusal names `accent / ground` plus the wider-color
   remedy. Capture the refusal.
7. Press the canonical plate twice. Compare the locally stored JSON after each
   press; it must be byte-identical. Confirm the UI still has only one option
   for that SHA-derived identity.
8. Unscripted exploration: resize the window to 390×844, move between Stage
   layers, interact with at least one module, and remove/reload the colorway.
   Record any clipped controls, stale iframe colors, dead actions, console
   errors, or confusing copy as defects rather than smoothing them over.

The standing suite already proves exact canonical clusters/shares, a lawful
second real image, deterministic double derivation, fail-closed monochrome,
validated data-only persistence, and cross-frame token projection. This SOP
owns the still-missing rendered experience and B.6 r7 screenshots.
