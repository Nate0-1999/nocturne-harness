# M2Y2 verification

M2Y2 restores the GLOBAL scope adapters used by the Memory Graph and Injection
Console without inventing a thread. Harness now preserves the explicit `null`
scope fields required by the Palace contracts.

## Owner-facing live proof

The production owner app was launched locally against the configured remote
Palace with a fresh, isolated `NOCTURNE_HOME`. No regression fixture was used.
Browser verification exercised the rendered instruments and observed:

- Memory Graph GLOBAL: 24 memories and 24 relationships, with no alert.
- Memory Graph CURRENT: 0 memories and 0 relationships for the fresh thread,
  with no alert.
- Injection Console GLOBAL: active recipe `v0`, 12 candidates, and no alert.
- Injection Console CURRENT: 0 candidates for the fresh thread, with no alert.
- GLOBAL DEEP simulation: 100% accuracy, one held-out disposition, digest prefix
  `313e805f38f7`, and no fabricated gate preview.
- Browser console: no warning or error entries.

The FORCE control was not clicked. The DEEP simulation was read-only and
non-enacting. The captured screenshot is cropped to the controls and receipt so
it does not contain owner memory labels or bodies.

Machine-readable observations are in `live-global-summary.json`; the rendered
receipt is in `injection-global-deep.jpg`.
