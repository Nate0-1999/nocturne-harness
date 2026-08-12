# M2UX5 plate-press SOP

Status: **COMPLETE** on 2026-08-12. This rerun recovered the gate-certified-dead
`ux5b` claim and completed the rendered acceptance walk without enabling
Chrome extension access to file URLs.

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

## File-selection route-around

Chrome's extension file-URL permission remained disabled. I did not wait on or
change that setting. Following report 071's seam precedent, the isolated
fixture exposes only three whitelisted same-origin plate routes: the canonical
plate, the M2UX4 second real image, and a generated low-contrast PNG. A fixture
page fetches the selected bytes, constructs a browser `File`, and dispatches
the ordinary React file input's `change` event. Everything after native file
selection is therefore the production path: `pressPlate` -> `pressImage` ->
derivation and validation -> local persistence -> theme and iframe bridge.
The route cannot read arbitrary local paths and never touches an owner Rack.

## Completed human-style acceptance walk

1. I opened the ordinary Stage toolbar and confirmed exactly NEO-NOIR,
   SERAPH DRESSED, and GOLD LINES plus one `Press image` action. The fixture
   marker and empty initial state are visible in
   [`01-initial.png`](01-initial.png).
2. I delivered `web/src/themes/cobalt-seraph-plate.png` through the route-around.
   The real UI reported `PLATE 40BFC441 is ready.`, added and wore exactly one
   `PLATE 40BFC441` option, and recolored the rendered Rack and sandboxed module.
   See [`02-canonical-applied.png`](02-canonical-applied.png).
3. I reloaded and observed the same pressed option still selected. I switched
   to NEO-NOIR and back to `pressed-40bfc4414de3fe5d`; both host and rendered
   modules changed. I removed the colorway, observed `PLATE 40BFC441 removed.`,
   reloaded, and saw only the three curated themes.
4. I delivered `verification/m2ux4/02-seraph-dressed-1280x900.png`. The real UI
   reported and wore `PLATE 42110AFB` / `pressed-42110afb2d7c6e3c`; it survived
   reload and removed cleanly. See [`03-second-applied.png`](03-second-applied.png).
5. I delivered the low-contrast PNG. No option was added. The rendered refusal
   says `This plate has no distinct accent / ground pair. Try an image with a
   wider range of color.` See [`04-monochrome-refusal.png`](04-monochrome-refusal.png).
6. The first browser pass found that this full remedy existed in the status
   tree but the toolbar visually ellipsized it. I moved transient plate status
   into a wrapping Stage status row and added a standing CSS seam assertion. The
   retaken refusal image shows the complete problem and remedy; I did not count
   the clipped pre-fix capture as acceptance.
7. I pressed the canonical plate twice. The fixture recorded the exact stored
   JSON's SHA-256 after each completed press as
   `a61d449cf26ae630f01ac28da2a2ecc491286474e4dfeeb83a4e310f7e23a163`
   both times. The stored count remained one and the selector had one option
   for that identity. See [`05-canonical-repeat.png`](05-canonical-repeat.png).
8. At 390x844 I used ordinary keyboard activation to move from Work to Graph,
   selected `Owner architecture` inside the sandboxed Memory Graph module, and
   read its inspector. The horizontally scrollable Stage toolbar remained
   operable; the full success status remained readable. See
   [`06-phone-canonical.png`](06-phone-canonical.png). I then removed the
   colorway and reloaded; only the three curated themes remained, shown in
   [`07-phone-removed.png`](07-phone-removed.png). Chrome recorded no warnings
   or errors during this final responsive sequence.

The standing suite proves the exact canonical clusters/shares, a lawful second
real image, deterministic derivation, fail-closed monochrome, validated
data-only persistence, and cross-frame token projection. This completed walk
adds the rendered experience and B.6 r7 screenshot evidence.
