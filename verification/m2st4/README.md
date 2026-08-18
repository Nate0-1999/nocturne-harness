# M2ST4 standing UI canon

M2ST4 turns four rendered proofs into one clean-room test command. The shared
fixture is data-bearing for Spend, learning, Graph, and Injection; its archive
response is fixture-isolated so the proof cannot mutate owner transcripts.

Run from the Harness checkout:

```sh
npm --prefix web run build
UV_CACHE_DIR=/tmp/n8-m2st4-harness uv run --locked python scripts/run_ui_canon.py
```

The runner starts one isolated local fixture on a free loopback port and runs:

- the M3FX fixture curtain against every canon server: the server-injected
  banner visibly names the fixture and packet while Playwright stays headless;
- the seven-width, 43-state Rack sweep, including rendered-scale iframe
  geometry and SVG/canvas visual-text collision checks;
- Stage layer, camera, remove/recall, and reload behavior;
- live-control, accessible-name, fixed-scope, theme, and label-diet checks;
- ordinary-screen human-number and raw-precision-leak checks, including scorer
  contributions and audition previews from F044's exact decimal examples;
- owner-language checks for the F045 vocabulary leaks, plus a forced Palace
  query outage proving that a live app socket cannot produce a false healthy
  header.

Evidence is written only to a temporary directory and removed after the run.
The same command runs in the web CI job after a clean Spine and Harness install.
This canon is deterministic regression evidence, not owner-app, provider, or
M2XF scout evidence. Authority: `garden/PLAN.md` M2ST4/M2FX4, FLAGS F044/F045,
and SPEC B.6 rule 12.
