# M2UX3 browser SOP

Date: 2026-08-11

Production surface: current built Rack SPA

Isolated composition: `harness.daemon:create_dev_app`, deterministic local
dependencies, private disposable home, port 8804

## Motivation

Pure layout tests can prove bounds and persistence, but they cannot prove that
the visible chrome can actually be grabbed. This walk operates the production
React frame with browser pointer events and then reloads it. It does not touch
the owner's daemon on port 8765.

## Walk

1. Open the isolated Rack at 1280×900 and wait for **Link live**.
2. Count the shared-template frames: Channel Stack, Active Channel, Memory
   Palace, Palace Vitals, and Context Bars must be the exact five.
3. Hover Palace Vitals. Its west edge, north edge, and north-west corner must
   appear with horizontal, vertical, and diagonal resize cursors.
4. Grab the Vitals title chrome and drop it over Context Bars. Vitals must move
   to the right-hand dock and report `x=4,width=9,height=4`.
5. Drag the west edge left one grid unit and the north edge down two grid rows.
   The result must be `x=3,width=10,height=2` without leaving the 12-unit rack.
6. Drag the north-west corner right one unit and up two rows. The result must be
   `x=4,width=9,height=4`, proving the corner path changes both axes.
7. Reload. Context Bars must remain first, Vitals must retain the final
   geometry, and the browser console/page-error arrays must remain empty.

## Result

PASS. The production frame exposed the exact five template modules; approaching
the Vitals edge and corner produced the three directional cursor classes; real
pointer gestures moved it, resized each axis, and restored the moved geometry
after reload. `module-template.json` contains empty browser console and page-
error arrays. The exact fixture process was stopped, port 8804 was proved free,
and both validated disposable home/cache directories were removed.

No prompt, provider request, memory mutation, archive action, deployment,
owner-identity write, or cloud mutation belongs to this walk.
