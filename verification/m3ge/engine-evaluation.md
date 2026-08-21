# M3GE engine evaluation — 2026-08-21

## Question

Which real game engine can render the Palace's active memories inside the existing
sandboxed Rack module while preserving fast owner startup, an npm/Vite build, named
data bindings, offline operation, and an honest lower hardware tier?

## Ground and method

- Hardware: MacBook Pro Mac16,5; Apple M4 Max; 14 CPU cores; 32 GPU cores;
  36 GB RAM; built-in 3456×2234 display.
- Browser: current Chrome, 120 Hz display ceiling.
- npm candidates installed exactly: `playcanvas@2.21.4`,
  `@babylonjs/core@9.22.1`, and `vite@8.1.5`.
- PlayCanvas and Babylon each rendered the same 256 lit sphere bodies, camera motion,
  and per-frame body motion. Production Vite entry sizes came from build output;
  readiness used `performance.now()`; stable FPS used request-animation-frame samples.
- Godot was measured from its current official 3D Sprites web demo because adopting
  Godot means adopting its export artifact rather than importing it into Vite. Its
  result is therefore a delivery-shape measurement, not an equivalent scene benchmark.

## Measurements

| Candidate | Delivery | gzip transfer | Ready | Stable FPS | License |
|---|---:|---:|---:|---:|---|
| PlayCanvas 2.21.4 | 1,952,955 B entry | 500,865 B | 37.0 ms | 121.706 | MIT |
| Babylon.js 9.22.1 | 6,377,404 B entry | 1,395,881 B | 61.5 ms | 120.197 | Apache-2.0 |
| Godot 4 official threaded demo | 37,322,260 B WASM + 216,092 B PCK | 9,413,536 B WASM + 87,195 B JS + 184,907 B PCK | 5,156 ms loading-status clearance | not compared | MIT |

The browser display capped both npm engines near 120 fps. The meaningful split is
therefore cost: Babylon supplied no visible frame benefit for 2.79× the gzip entry and
1.66× the initialization time. Godot's current official web shape is much larger and
adds a separate export pipeline plus threaded cross-origin-isolation requirements.

## Decision

Choose PlayCanvas. It is a real ECS game engine, installs directly into the existing
locked web package, supports WebGL2 and WebGPU with fallback, reaches the display
ceiling, and leaves the Rack's plugin bridge and React text law intact.

Official sources consulted:

- PlayCanvas engine: https://playcanvas.com/products/engine
- PlayCanvas Engine user manual: https://developer.playcanvas.com/user-manual/engine/
- PlayCanvas source/license: https://github.com/playcanvas/engine
- Babylon.js source/license: https://github.com/BabylonJS/Babylon.js
- Babylon.js WebGPU support: https://github.com/BabylonJS/Documentation/blob/master/content/setup/support/webGPU.md
- Godot web export: https://docs.godotengine.org/en/4.5/tutorials/export/exporting_for_web.html
- Godot official demos: https://godotengine.github.io/godot-demo-projects/
- Godot official 3D Sprites demo: https://godotengine.github.io/godot-demo-projects/3d/sprites/
