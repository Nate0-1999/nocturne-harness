# M3FP — packaged front-door heartbeat

This fixture guards the owner app's first ordinary action:

`fresh packaged Rack → first prompt → memory gate → answer → receipt → transcript journal`

M3AT commit `9984d80e` introduced `contextualRackAction`; M3OM commit `94f54e1`
made focused Conversation send through that shared path and activated the regression.
The adapter reselected the already-selected thread immediately before `prompt.submit`.
Reselection correctly raises the snapshot barrier; the immediately following send then
correctly fails closed. The repair keeps that ordering and removes only the redundant
same-thread selection.

`browser_check.mjs` drives Chrome headlessly against the packaged assets and asserts
one prepare, one commit, at least one receipt line, and the prompt plus answer in the
journal. `scripts/run_ui_canon.py` runs it first, making this a standing red-ground
check for clean-room CI and future boot sequences.

## Durable evidence

- `evidence/01-first-prompt-gate.png` — headless packaged heartbeat at the existing gate.
- `evidence/02-first-answer.png` — the same heartbeat after answer, receipt, and journal.
- `evidence/heartbeat.json` — exact machine-readable boundary counts.
- `evidence/03-chrome-first-prompt-gate.png` — required visible Chrome exit, fresh daemon.
- `evidence/04-in-app-first-prompt-gate.png` — required in-app-browser exit, fresh thread and daemon.
- `evidence/05-real-packaged-front-door.png` — D.2 149 owner-app walk on the real Palace,
  with no fixture curtain; the walk stops at the gate before provider or memory mutation.
- `evidence/real-walk.json` — machine-readable owner-app walk facts.

All screenshots are visibly marked `M3FP REGRESSION` and `NOT THE OWNER APP`.
