# M2R rendered evidence

The isolated production Rack shows Context Bars beside Palace Vitals. The
desktop proof shows the measured request total and resolved model capacity,
four explicitly estimated categories, the 80% line, the compact token table,
and the statement that compaction is not active. The mobile proof shows the
same measured total in the collapsed bottom strip without covering Chat.

- `01-context-bars-desktop-1440x900.png` — expanded desktop Rack; GLOBAL scope
  is exercised and all four categories remain visible.
- `02-context-bars-mobile-390x844.png` — collapsed mobile Rack; the compact
  `102.4K / 128K` reading remains visible beside Palace Vitals.
- `scenario_app.py` — deterministic context and Vitals readers mounted behind
  the shared isolated-fixture boundary.

Browser verification used the production build at 1440×900 and 390×844. Both
runs had no console warnings or errors. The desktop module occupied columns
10–12 and stayed within the viewport; the mobile module occupied the right 42%
of the bottom strip and ended exactly at the viewport boundary.
