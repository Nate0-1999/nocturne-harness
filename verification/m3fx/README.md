# M3FX fixture-curtain verification

The standing UI canon runs `browser_check.mjs` against every canon fixture.
It asserts the server-injected banner is visible and names both the fixture and
its packet. The check launches Chromium with literal `headless: true`; it has
no headed fallback and writes evidence only into the canon's temporary tree.

The ordinary Python suite guards the whole verification class: every FastAPI
fixture installs the shared wrapper, scenario sources have no browser-opening
path, every Playwright launcher is explicitly headless, and every product-
starting SOP passes `--no-open`.

Authority: F052, F053, SPEC D.2 120, and PLAN M3FX.
