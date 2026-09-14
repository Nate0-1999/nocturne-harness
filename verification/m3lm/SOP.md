# M3LM — ledger tooling walk

ALIGNED: PLAN M3LM; SPEC B.6 / D.2 154. Tooling only; no product behavior changed.

1. I ran `garden/bin/ledger verify harness/verification/m3rs`, the last
   comprehensive scout's evidence. It exited 1, listing missing verdicts and
   row-named screenshots for all 149 currently required rows. I opened the
   actual output in TextEdit, moved to its end, and saw the individual missing
   files, `Handoff REFUSED: 149 required rows checked`, and exit code 1.
   Screenshot: `01-old-scout-refusal.png`; full output: `old-scout-refusal.log`.
2. I ran `garden/bin/ledger impacted 8dd702c^..8dd702c --repo harness`.
   It exited 0 and named conversation rows FL-104, FL-117, FL-120 plus shared
   module/attunement rows FL-105, FL-108, FL-110, FL-115, FL-116. The fix changed
   their common connection. `composer-impact.json` retains the exact map and
   unmapped file list; this is deliberately broader than only three rows.
3. I generated the composer builder skeleton into a disposable
   `verification/m3cp/` folder and verified it without filling evidence.
   It exited 1 and listed all eight missing screenshots, unmapped-file reasons,
   hashes, and subsequent changes to the recorded source. I opened the final
   output in TextEdit and saw all eight row refusals and exit code 1.
   Screenshot: `FL-195.png`; output: `composer-refusal-final.log`.
4. I explored the failure checks with isolated temporary Git repositories:
   renamed/deleted sources still select their consumers; removing a report row
   cannot remove its requirement; a copied old image, changed hash, path escape,
   symlink, invented flag or post-proof source change refuses. An unrelated
   peer change does not invalidate this build. An incomplete report cannot
   change BOARD to DONE. These are deterministic tooling tests, not live
   product screenshots (`ledger-tests.log`, 11 tests).

The two pictures are screenshots of actual CLI logs in a native text viewer.
Computer-use policy refused Terminal, Codex, and a local-file browser page;
TextEdit safely displayed plain text. No product-browser walk is claimed.
The unused HTML log views were removed. All three opened log windows were closed.
No Nocturne owner home, Palace scope, provider or credential was used.

The early wrongly targeted Harness invocation was interrupted; its three live
contracts failed before execution because SPINE_URL was absent. Its sandbox
failures are retained in `invalid-harness-invocation.log`, not counted as ground.
A later shared-checkout Spine run crossed the rules-machine session's edits;
it and the interrupted shared Harness attempt are retained as invalid final
checks. Both final suites ran from committed archives with snapshot source imports:
Harness d36d586, Spine d3daa9c. Their final results replace those attempts.

The source ledger preserves all 194 original rows exactly and adds FL-195 for
this tool. Its current 149 built/partial rows are requirements, not 149 claims
of working features. The separate motivation checker reports 18 inherited
omissions in the unchanged snapshot tests; M3LM's added test is cited.
Screenshots demonstrate execution; their claims and the completeness of the
source map remain human review, explicitly stated in `ledger-report.json`.
