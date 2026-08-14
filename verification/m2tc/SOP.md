# M2TC browser SOP

Date: 2026-08-14

Surface: current built Rack SPA at 1670 x 936

Isolation: existing `verification.m2ux3.scenario_app:create_scenario_app`,
private disposable `NOCTURNE_HOME`, deterministic local model and Spine, port
8806, visibly labelled `M2UX3 REGRESSION FIXTURE` and `NOT THE OWNER APP`

## Motivation

Static tests can assert the shared template, but they cannot prove that an owner
can approach the controls, understand them, and make Spend genuinely tiny or
huge. This walk exercised the production UI through the in-app browser.

## Walk

1. Open the isolated Rack and verify that the five default Stage modules expose
   the shared title, gear, remove control, and eight resize handles.
2. Hover Spend's gear and read `Spend settings` plus the explanation
   `Open its view and module options.`
3. Activate the gear. Verify a real dialog headed `Spend` with a close control,
   `Choose what this module follows.`, `Everything`, and `This thread`.
4. Set the camera to Whole stage. Drag Spend's south-east corner inward until
   the measured geometry is `x=1,y=12,width=1,height=1`.
5. Drag Spend's north-west corner to the origin, then its south-east corner to
   the opposite edge. Verify `x=0,y=0,width=32,height=22`.
6. Hover the north-west handle and read `Resize Spend from the top-left corner`
   plus `Drag or use the arrow keys. The Stage grid sets the limit.`
7. Restore Factory layout through App settings. Verify Spend returns to
   `x=1,y=12,width=12,height=4`.
8. Hover the compact thread archive control and read `Archive New thread` plus
   the extraction/close explanation.
9. Hover the visibly bordered Model control and read `Open Model Device` plus
   its explanation, then activate it and verify Model Device opens.
10. Verify the browser diagnostic log is empty and stop the fixture.

## Result

PASS. Real pointer gestures reached both Stage-grid extremes, the settings
dialog remained readable above neighboring modules, controls explained
themselves on approach, the compact archive retained an accessible action, and
the Model control visibly opened Model Device. Factory layout was restored
before shutdown.
