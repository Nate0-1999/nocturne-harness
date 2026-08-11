# M2UX1 independent browser SOP

Date: 2026-08-11

Harness source: `a1f45f6f0e556518072a187fadf965d4fef0fb82` plus the
uncommitted M2UX1 diff under review

Fixture: `verification.m2ux1.scenario_app:create_scenario_app`, isolated home,
port 8801

Owner app: port 8765, observed read-only and never clicked or stopped

## Motivation

The automated sweep is necessary but not sufficient: a geometry assertion can
miss an owner path that is technically present and practically unreachable.
This walk therefore used the in-app browser to operate the repaired controls
through their real iframe boundaries.

## Walk

1. Opened the real owner app at 1280×720 without interacting with it. The
   retained `00-owner-before.jpg` shows **Palace Queue** occupying the same
   topbar lane as **Factory set** before this patch.
2. Opened the isolated M2UX1 fixture at 1280×720. The accessibility tree showed
   one Header sequence—Palace Queue, Graph, Injection—and the separate Factory
   set sequence—Save, Restore, Factory—with both sets independently reachable.
3. Clicked **Palace Queue**. Its overlay opened while the Header and its active
   Queue control remained visible. `04-live-desktop-1280x720.jpg` preserves that
   state; the Queue begins below the Header instead of covering it.
4. Closed Queue from the same Header control, opened **Graph**, and verified the
   in-surface **Close instrument** control was visible. Closed it through that
   control.
5. Opened **Injection** and verified **Global**, **Current**, and **Close
   instrument** were all visible. Closed it through the in-surface control.
6. Read the complete browser diagnostic log after the walk: `[]`.
7. Independently ran the scripted rendered sweep at 390, 480, 768, 1024, 1280,
   1440, and 1920 CSS pixels. Factory and all five overlay modules passed at
   every width; the 390px run additionally exercised the Threads drawer. The
   resulting 43 states reported zero positive-area interactive collisions,
   zero clipped HTML text nodes, zero console errors, and zero page errors.

## Result

PASS. The owner-observed Header collision is reproduced in the before image,
the corrected controls are genuinely operable in the live browser, long titles
end at a complete-word boundary and wrap where space permits, and the permanent
rendered audit covers the standing 390→ultrawide no-overlap/no-clip charge.

The fixture created only disposable local thread/journal state under its private
home. No owner-app, Spine, provider, or cloud write was used.
