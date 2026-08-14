# M2SP Stage polish — browser SOP

Date: 2026-08-14
Session: `codex / 2026-08-14 / sp7c`
Isolation: `verification.m2st4.scenario_app:create_scenario_app` on port 8807,
visibly labelled `M2ST4 REGRESSION FIXTURE` and `NOT THE OWNER APP`. This was
the production Rack SPA and deterministic fixture data, not an owner-app or
provider claim.

1. I opened the Work layer at 1670×936. The familiar module composition opened
   in place, but the old large rectangles had become a much tighter field of
   quiet points with stronger unit lines beneath the modules. `+ Layer` read as
   an action immediately; I did not have to open Library or Settings to find it.
2. I inspected the rendered Stage. It declared `256 × 176` units and measured
   12,288×6,336 pixels before zoom. The computed background sizes were
   `12px 12px, 48px 36px, 48px 36px`. Every module showed an opposing
   top-right/bottom-left cut instead of four square corners.
3. From open background I dragged hard from (1450, 820) to (250, 220), a
   1,200×600-pixel diagonal pan. I still saw only continuous grid. The canvas
   rectangle remained beyond every viewport edge (`left -4113`, `top -2258`,
   `right 3751`, `bottom 1797`), so no wall was visible. The ordinary off-screen
   recall appeared for the modules I had left behind.
4. I clicked `+ Layer` once. `Layer 1` appeared selected immediately with an
   empty Stage and no copied modules. The camera stayed where I was working.
5. I reloaded while `Layer 1` was selected. It returned selected, still empty,
   on the same `256 × 176` Stage. No browser warning or error was recorded.

Verdict: PASS. The grid feels continuous, one hard pan finds no boundary,
shells read as cut hardware rather than stacked rectangles, and a new layer is
one obvious click.
