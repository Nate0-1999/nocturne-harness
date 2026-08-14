# M2TC template-conformance evidence

M2TC makes the Stage template a visible owner contract instead of a family of
near-matching controls. Spend and Context Bars now use the same chrome as every
other Stage module, every module gear opens the same host-owned dialog, and the
finite Stage grid is the only resize limit.

## Evidence

- `01-spend-settings-dialog.jpg` shows the shared Spend gear and settings dialog.
- `02-spend-tiny.jpg` shows Spend resized to the minimum `1 x 1` grid cell.
- `03-spend-huge.jpg` shows Spend resized to the full `32 x 22` Stage grid.
- `04-model-device-open.jpg` proves the visible Model control opens Model Device.
- `trace-summary.json` records the measured geometry, exact tooltip/dialog copy,
  restored factory geometry, and empty browser diagnostic log.
- `SOP.md` records the bounded browser walk and its fixture boundary.

The walk reused the already-isolated `M2UX3 REGRESSION` production-Rack fixture
instead of inventing another product seam. It is deterministic evidence, not an
owner-app or provider claim. No prompt, archive action, memory write, provider
request, deployment, or cloud mutation occurred.
