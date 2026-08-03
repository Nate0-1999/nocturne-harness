# M2G — per-message re-scoring and disposition locks

Status: **builder verification complete**. This is packet evidence, not an
independent milestone judgment.

M2G keeps the first message's explicit memory review, then prepares every later
ordinary message autonomously. Human-confirmed memories remain binary locks;
newly relevant memories may enter, prior autonomous members may exit, and a
thread exclusion blocks automatic return until the human presses Re-add.

## Acceptance map

| Criterion | Rendered proof | Trace/adversarial proof |
|---|---|---|
| first message remains gated | `01-first-gate-desktop-1440x900.png` | first trace prepare is `mode=gate`; model follows commit |
| later messages re-score without a modal | `02-autonomous-rescore-desktop-1440x900.png` | second trace prepare is `mode=autonomous`, followed directly by model |
| confirmed locks survive | deterministic and owner panel screenshots | live passive row for the confirmed memory remains `kept` |
| automatic entry is visible | `sop-02-owner-autonomous-entry-desktop-1440x900.png` | live passive selected membership; rule-7 trace adds the ambient ID |
| remove and re-add are symmetric | `03-excluded-readd-desktop-1440x900.png`, `04-readded-desktop-1440x900.png` | same injection membership receives removed then added feedback |
| responsive law | `05-memory-drawer-mobile-390x844.png`, `sop-05-owner-readded-mobile-390x844.png` | both final phone captures expose the complete controls without horizontal overflow |

`scenario_app.py` is a clearly bannered deterministic rule-7 fixture on port
8783. It is not the owner app. `SOP.md` records the separate rule-8 pass through
the real owner composition on port 8765 with real OpenRouter chat and embeddings.

