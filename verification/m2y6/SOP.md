# M2Y6 — CURRENT Vitals reconciliation SOP

Status: **EXECUTED / PASS** on 2026-08-09.

## Identity and ground

- Verification principal: `m2y6-sop-verification`
- Verification machine: `m2y6-sop-verification`
- Verification agent: `harness-agent`
- Owner app: `harness.daemon:create_dev_app` on `http://127.0.0.1:8789/`
- Provider shown by the owner app: `openrouter:minimax/minimax-m3`
- Palace: the real configured owner Palace, not `scenario_app.py`
- Browser asset: `assets/index-CzPK_xER.js`, built from this checkout
- Thread: `79384fed-9c77-456b-a37d-133d456fe82d`

## Procedure executed

1. Started the real owner app with the verification identity and a fresh temporary `NOCTURNE_HOME`.
2. Opened the owner app in the in-app browser and sent: “Reply with one short sentence confirming this real M2Y6 Vitals run.”
3. Continued through the first-turn memory gate with zero selected, removed, or added memories.
4. Waited for the real OpenRouter turn to finish. The run reported `2 req · 1967 in · 245 out` and the model replied in the owner app.
5. Opened Palace Vitals and selected **CURRENT**.
6. Compared the visible UI with the exact browser-facing response for the same thread.
7. Exercised **GLOBAL → CURRENT → Refresh** and confirmed CURRENT remained selected and current.
8. Repeated the CURRENT observation at a 390×844 phone viewport, then reset the browser viewport.
9. Checked the browser console, finalized the task-created tabs, stopped the app, and removed the temporary home.

## Verdict

PASS. The browser-facing CURRENT query returned HTTP 200 with `status=live`, `source_view=spend_event`, a total of `$0.000607940000`, 9 receipt lines, and 0 unpriced lines. The owner UI rendered the same total, receipt count, purpose lanes, and model lanes. No stale or error message appeared.

The post-run scope exercise also passed:

- GLOBAL rendered successfully.
- Switching back to CURRENT preserved `aria-pressed=true`.
- Refresh preserved the exact `$0.000607940000` current total.
- The CURRENT panel text contained neither `stale` nor `error`.

Exact response excerpt: [`live-current-trace.json`](./live-current-trace.json)

## Responsive and unscripted observations

At 390×844, Palace Vitals correctly collapsed to a compact strip. Expanding it kept CURRENT selected and displayed the exact total and lanes without horizontal corruption. On desktop, the full owner layout kept thread, response, CURRENT Vitals, and Context Bars visible together.

The only model-level surprise was honest rather than a product failure: the model said it did not know what “M2Y6” meant. That is expected because the run deliberately injected no packet-specific memory. Provider execution and Vitals accounting were both real.

## Evidence

- Desktop CURRENT after the real run: [`current-vitals-desktop.jpg`](./current-vitals-desktop.jpg)
- Phone CURRENT after expanding the responsive strip: [`current-vitals-phone.jpg`](./current-vitals-phone.jpg)
- Exact live response excerpt: [`live-current-trace.json`](./live-current-trace.json)
- Browser console warning/error entries: `[]`

## Hygiene

- The memory gate used 0 memories; no memory was added, removed, saved, pinned, or superseded.
- The verification run used a fresh temporary local home only. Its transcript stayed inside that home.
- The owner app was stopped cleanly.
- `/private/tmp/nocturne-m2y6.6WLSjx` was removed and verified absent.
- The temporary browser viewport was reset and all task-created tabs were finalized.
- Nothing in this verification counts toward the owner floor.
