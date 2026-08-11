# M2UX4 real owner-app SOP — 2026-08-11

This walkthrough used the current editable Harness owner app against the
owner's live local Palace. It did not use `scenario_app.py`, did not send a
prompt, and made no provider call.

## Procedure and observations

1. Started `harness.packaged:create_app` on isolated port `8807` after moving an
   ignored stale `src/harness/_web` build artifact recoverably to
   `/tmp/nocturne-m2ux4-stale-bundled-web`. The canonical current `web/dist`
   asset names were served.
2. Selected NEO-NOIR. The Rack retained its worn dark face while live threads,
   memories, Vitals, and Context Bars loaded. Evidence:
   `sop-owner-neo-noir.png`.
3. Opened the real Memory Graph from the Header, then selected SERAPH DRESSED
   while the full-screen module was open. The overlay and the stage behind it
   shared the same dark face and thin fixed chrome rim; the real graph finished
   loading. Evidence: `sop-owner-seraph-dressed.png`.
4. Returned with **Back to stage**, selected GOLD LINES, and observed a coherent
   day face across the host and all six module frames. Evidence:
   `sop-owner-gold-lines.png`.
5. Reloaded the owner app. GOLD LINES remained selected in the host and frames.
6. At a `390 × 844` viewport, the Theme control remained visible in its own row
   and switched successfully to SERAPH DRESSED. Evidence:
   `sop-owner-gold-lines-phone.png`.
7. Unscripted exploration: opened the real Graph before changing theme, waited
   for live Palace nodes rather than a fixture payload, then changed theme with
   the overlay still open. This specifically exercised a full-screen module
   outside the five-module stage.
8. Checked both desktop and phone browser logs: no warnings or errors. Restored
   NEO-NOIR before releasing the browser tabs and stopped the isolated server.

## Outcome

PASS. The three faces are distinct, complete across sandboxed frames and the
Graph overlay, persistent across reload, reachable at phone width, and free of
browser console failures. The deterministic fixture remains solely the
repeatable regression surface; this SOP is the separate real-owner proof.
