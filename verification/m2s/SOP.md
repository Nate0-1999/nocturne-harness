# M2S remote startup walkthrough

Executed 2026-08-05 from fresh local wheels against the owner-operated Spine.
Secrets were read only from the ignored owner environment and the generated
mode-0600 config; no secret value was printed or copied into this evidence.

## Setup

- Built `nocturne-spine==0.1.0` and `nocturne-ai==0.1.0` wheels from the
  current sibling repositories.
- Installed both wheels into an isolated Python 3.12 environment.
- Used an isolated `NOCTURNE_HOME` so the walkthrough could not alter the
  owner's normal Nocturne config or journal.

## Walkthrough

1. Ran `nocturne init --remote <owner-spine-origin>`. The OpenRouter key came
   from the environment; the command prompted only for the Palace access token and
   wrote a private version-4 config with `remote` mode and the normalized
   service origin.
2. Ran `nocturne doctor`. The scale-to-zero service reached authenticated
   `/health` within the bounded startup window. Doctor reported remote health,
   journal bytes, and disk bytes, then said plainly that local database and
   backup checks were skipped.
3. Ran `nocturne up --no-open`. The installed command started one Uvicorn
   process for `harness.packaged:create_app`; it did not invoke Docker, start a
   local Spine, or run migrations. The Rack root returned HTTP 200.
4. Opened `http://127.0.0.1:8765/` in the in-app browser. The installed,
   bundled Rack rendered with title `NOCTURNE`, `Linked`, and `Link live`.
   Remote memories loaded. The browser console contained no warnings or
   errors. A measured 8px gap separated the connection label from the Palace
   queue control after the visual pass corrected their collision.
5. Stopped the daemon with Ctrl-C. It closed its WebSocket and exited cleanly.

## Result

PASS for M2S: after installation, each Palace rung uses the same two-command
startup vocabulary (`init`, then `up`). Existing checkout-based remote users
have a README migration line and no longer need to source `.env` or know the
developer command.

## Gate carry-forward

The owner cloud service currently answers health and current memory calls, but
its Vitals and scorer-console endpoints return HTTP 503 when queried by the
assembled M2 Harness. This is deployment-version skew outside M2S's startup
charge, not a reason to hide a green startup result. The M2X scout must resolve
or classify that skew before presenting the owner with the gate-day session.
