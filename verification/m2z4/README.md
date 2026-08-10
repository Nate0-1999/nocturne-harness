# M2Z4 evidence

Visibly isolated deterministic evidence for A-051's authentic learning cockpit:
floor and hygiene status, server-authored right/wrong scores, live and generation
series, bodyless manual retrain refusal, proposal polling, pure audition, and an
explicit activation control that the fixture will not enact.

The evidence has deliberately separate scopes:

- `integration_app.py` and `integration_check.mjs` provide the primary connected
  proof: a fresh disposable pgvector database, the real Spine app lifespan and
  worker, a winning inactive background proposal, the canonical Harness
  Console poll, rendered proposal, real read-only audition, unchanged `v0`, and
  zero activation attempts. Fixture-graded events exist only inside this test
  database.
- `scenario_app.py`, screenshots, and `trace.json` prove Harness presentation,
  polling, owner navigation, and refusal to activate. The scenario-only
  background transition remains a deterministic layout fallback, not a worker
  claim.
- The live-Postgres regression
  `spine/tests/test_learner_api.py::test_real_worker_startup_and_work_wake_persists_background_inactive_winner`
  proves that the real worker wakes at startup and after work, persists the
  winning background receipt/proposal, and leaves the incumbent active. The
  companion Postgres test
  `test_background_retrain_crosses_authentic_floor_and_never_activates` retains
  the authentic-floor and non-activation proof.
- `real-composition-summary.json` records the disposable current-Harness +
  current-Spine + Postgres composition check. It is not owner-Palace evidence.

Artifacts:

- `connected-trace.json` — automated cross-stack trace joining the real worker,
  database receipt/config state, canonical Console snapshot, rendered proposal,
  real audition, and zero activation attempts.
- `08-connected-worker-proposal-audition.png` — current built Console after the
  real worker proposal was polled and auditioned without activation.
- `01-learning-desktop-1440x900.jpg` — initial 18/25 learning state.
- `02-proposal-audition-desktop-1440x900.jpg` — polled proposal and audition at
  1440×900.
- `03-real-composition-empty-palace-1440x900.jpg` — disposable real composition,
  empty authentic-signal state.
- `04-proposal-audition-mobile-390x844.jpg` — mobile proposal/audition view.
- `05-vitals-desktop-1440x900.jpg` — expanded desktop Vitals containment and
  learning scoreboard.
- `06-vitals-mobile-390x844.jpg` — mobile Vitals containment.
- `07-vitals-mobile-collapsed-detail.jpg` — exact collapsed mobile learning
  scoreboard detail.
- `trace.json` — exact pretty-printed response preserved from the final
  `GET /__scenario__/trace` journey.
- `real-composition-summary.json` — structured observations from the disposable
  real composition.

See `SOP.md` for the journey and recorded acceptance measurements.
