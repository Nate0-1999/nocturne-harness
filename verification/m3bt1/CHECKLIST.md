# M3BT1 execution checklist — 2026-08-21

- [x] Fresh Harness and Spine clones used; shared builder checkout not used by
  the product agent.
- [x] Disposable home, principal, machine, and scratch root used.
- [x] Released Palace 0.1.5 health verified.
- [x] Real OpenRouter model resolved in both ordinary chat threads.
- [x] Both fixed acceptance scripts authored and hashed before round 1.
- [x] Round 1 completed; raw time, ledger cost, churn, and pass rates recorded.
- [x] Same accumulating Palace used in round 2.
- [x] Round-2 automatic retrieval and owner-added near misses recorded exactly.
- [x] Round 2 completed; raw time, ledger cost, churn, and pass rates recorded.
- [x] Agent-working, saved-memory, gate, Vitals, and cleanup screenshots kept.
- [x] Four experiment memories tombstoned by exact ID; zero remain active.
- [x] Bounded credential scan clean.
- [x] Spine suite green: 281 passed in 16.49s with
  `TESTCONTAINERS_RYUK_DISABLED=true`.
- [x] Harness suite green: 1677 passed, 3 contract tests deselected in 51.46s
  with `-m 'not contract'`.

The first exit attempts are retained as environmental diagnostics: Spine had
161 passing unit tests and 120 setup errors when Ryuk tried to mount the Colima
socket through Docker Desktop (`operation not supported`); Harness had 1677
passing tests and three setup errors because the live-contract environment was
not supplied. The bounded reruns above match each suite's ordinary local
ground and passed without product changes.
