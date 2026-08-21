# M3GE real-owner Palace Nebula verification

Date: 2026-08-21

## Launch

The proof used the ordinary packaged app, its current built assets, a mode-0700
disposable Nocturne home, and the configured live Palace. It used no scenario app,
fixture query, fake memory reader, prompt, provider call, or Palace mutation.

```sh
set -a; source .env; set +a
NOCTURNE_HOME=/tmp/n8-m3ge-owner-home \
UV_CACHE_DIR=/tmp/n8-m3ge-uv \
PYTHONPATH=src \
uv run --locked uvicorn harness.packaged:create_app --factory \
  --host 127.0.0.1 --port 8893
```

In the real Rack, select Graph, open Stage Library, and add Palace Nebula. For a
focused view, create an empty Stage layer and add the same ordinary module there.
The module remains inside the `rack.localhost` sandbox and reads only the public
`memory_graph` Rack query through its plugin bridge.

## Observations

- The live immutable graph returned 52 rows, of which exactly 3 had
  `status=active`; the canvas and accessible label both reported exactly 3 bodies.
- Full tier rendered the Activity axes at 120 fps with device-pixel-ratio cap 2,
  antialiasing, richer material, and every-frame motion.
- Switching to Provenance issued a fresh public query; its visible snapshot changed
  to `2026-08-21T21:51:30.661010Z` and the bodies moved to the project, origin-thread,
  and origin-path bindings named in the legend.
- Efficient tier retained all 3 bodies and rendered at 120 fps with device-pixel-
  ratio cap 1, simpler material, and every-other-frame motion updates.
- Switching back to Activity and Full issued another fresh query; the visible
  snapshot changed to `2026-08-21T21:51:55.180360Z`.
- Both captures show PlayCanvas 2.21.4, body count, tier, FPS, snapshot timestamp,
  and the complete React-DOM bindings legend. No fixture curtain appears.

The first live mount exposed that the daemon's HTML frame-policy allowlist did not
yet know the new registered module; its `frame-ancestors 'none'` refusal was repaired
by registering `palace_nebula` at that existing security seam and adding a daemon
guard. The first visible engine pass also exposed a canvas-resize/layout mismatch;
the corrected module uses PlayCanvas automatic resolution with tier-specific pixel
ratio and a bounded viewport, leaving the complete DOM legend readable.

## Evidence

- `real-owner-full.png` — Activity axes, Full tier, 3/3 live active bodies, 120 fps.
- `real-owner-efficient.png` — Provenance axes, Efficient tier, 3/3 live active
  bodies, 120 fps, including released-Palace `thread_origin` compatibility binding.
- `engine-evaluation.md` — candidate method, exact artifacts, timings, FPS, licenses,
  sources, and rejection rationale.

No live records are eligible for cleanup because this proof made no live write.
The disposable local home may be removed after the process stops.
