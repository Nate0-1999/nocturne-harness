# M2FX2 verification

This fixture uses the production daemon, Rack, memory panel, and browser
protocol with a local `m2fx2-verification` Spine double. It keeps transcript
state in a temporary directory and never reads or writes the owner Palace.

The walkthrough proves F040 experientially: Memory opens with one active unit,
an edited body returns as revision 2, the editor stays open with `Saved`, and a
second unchanged Save is refused without creating revision 3. F041 is defended
at the rendered boundary by showing only `Loading...` while a new thread awaits
its daemon snapshot and projecting the accepted project only afterward. Setting
`M2FX2_CONFLICT_THREAD_ID` before launch preloads that fixture thread as
`build-test`; a browser catalog that requests another project for the same ID
therefore receives the real daemon conflict plus authoritative snapshot. F038's
plain reinforcement acknowledgement is exercised through the ordinary chat
composer; the cited Harness and Spine tests additionally pin its exact
stats/lineage behavior.

`trace-summary.json` records the final in-app browser pass. The edit advanced
exactly r1 to r2 and left Saved visible; an unchanged retry stayed r2 with a
plain refusal. The duplicate command then advanced to r3 with one reinforcement
and the required owner sentence. A preloaded project conflict replaced the
requested `m2fx2-draft` catalog value with daemon-authoritative `build-test`.
