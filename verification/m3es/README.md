# M3ES real-owner Three.js Palace Nebula verification

Date: 2026-08-31

## Ground

The proof used the ordinary `harness.packaged:create_app`, current production web
bundle, a mode-0700 disposable Nocturne home, and the configured live verification
Palace. It used no scenario app, fixture query, fake graph reader, prompt, provider
call, Palace write, release, or deployment. The in-app browser opened the real Rack
at `127.0.0.1:8894`; the Nebula remained inside the registered
`rack.localhost` plugin iframe and queried the public `memory_graph` surface with
`as_of: now`.

The final locked engine stack was:

- `three@0.182.0`
- `@react-three/fiber@9.7.0`
- `@types/three@0.182.0`

Three r182 is deliberate compatibility ground. Three deprecates `Clock` beginning
at r183 while current r3f Canvas still instantiates it; r183 and later emitted a
warning on every renderer mount. R182 is the last pre-deprecation release and lies
inside r3f's declared Three range. No dependency was patched or forked.

## Owner walk

1. Open Graph, restore Palace Nebula from the ordinary Stage Library, and wait for
   the live Palace query.
2. Full / Activity rendered all 3 active rows from the 52-row live graph at 120 FPS.
   The canvas reported `three.js r182 webgpu`; telemetry named `r3f + TSL`, the
   exact snapshot `2026-08-31T18:51:54.687253Z`, and every M3GE Activity/shared
   binding remained visible in React DOM.
3. Switch Axes to Provenance and Hardware to Efficient. A fresh query changed the
   snapshot to `2026-08-31T18:52:00.766155Z`. Efficient retained all 3 bodies at
   119 FPS and kept the same WebGPU/TSL path while reducing DPR, geometry/material
   cost, and motion cadence.
4. The Provenance legend still named `project_key`,
   `origin_thread_id; legacy thread_origin`, and `origin_path`. The six shared
   bindings remained byte-for-byte identical to M3GE. The browser recorded zero
   warnings and zero errors after the final reload and both tier mounts.

The renderer now uses Three's `WebGPURenderer` (native WebGL2 fallback), r3f scene
composition and `useFrame`, and `MeshStandardNodeMaterial` with TSL color/emissive
nodes. `nebulaBindings.ts` remains the sole deterministic data-transform authority;
no binding or active-body selection moved into the engine.

## Evidence

- `real-owner-three-full.jpg` — real Rack, Activity / Full, 3 bodies, 120 FPS,
  Three r182 + r3f + TSL + WebGPU, complete legend.
- `real-owner-three-efficient.jpg` — same real Rack, Provenance / Efficient,
  3 bodies, 119 FPS, fresh snapshot, complete legend.
- `trace-summary.json` — exact machine-readable observations and bindings.
- `SHA256SUMS` — capture digests.

This read-only proof created no Palace record, so there is no data-plane cleanup.

