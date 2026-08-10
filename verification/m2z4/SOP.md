# M2Z4 experiential verification

## One connected worker-to-Console proof

Run from `harness/` with Docker available, both checkout environments synced,
and the current `web/dist` built:

`node verification/m2z4/integration_check.mjs`

The script owns a fresh pgvector Testcontainer and performs one connected path:

1. Start the real Spine app lifespan and `LearnerWorker`, then the current
   Harness daemon with its existing scorer callbacks and built Console.
2. Wait for the worker's real startup due-check to complete with no work due.
3. Open Injection in a real headless Chrome session and switch to **Current**.
4. Call the verification-only, bodyless `POST /__scenario__/graded-work`. It
   inserts two fixture-graded gates plus one ungraded audition gate into only
   that disposable database, commits, and calls the real worker's `notify()`.
5. Wait for the worker to complete a winning `background` run and persist its
   proposal inactive. Then wait for the Console's normal five-second polling
   path to render that canonical proposal.
6. Click **Audition**, assert the real Spine replay says `No silent inference`
   `would add`, and assert **Activate** remains visible but is never clicked.
7. Assert the canonical Console and database still report `v0` active, the
   proposal inactive, zero activation rows, zero Harness activation callbacks,
   and zero browser activation requests.

On success it preserves `connected-trace.json` and
`08-connected-worker-proposal-audition.png`. The JSON joins the worker
notification/completion, background receipt, inactive database proposal,
canonical Harness Console payload, rendered browser text, audition request and
response, incumbent state, and activation counts. The process stops and removes
its disposable database on exit. It never opens, copies, or mutates an owner
Palace.

The fixture-graded input is permitted only because this is an isolated test
driver against a fresh disposable database. Production identity hygiene is not
weakened or bypassed.

## Deterministic presentation fallback

This separate deterministic Harness rack/UI regression fixture is useful for
manual layout inspection. Its scenario-only transition does **not** prove
Spine's background worker. The connected proof above and the live-Postgres
regression
`spine/tests/test_learner_api.py::test_real_worker_startup_and_work_wake_persists_background_inactive_winner`
provide the real-worker evidence.
The deterministic worker tests in `spine/tests/test_learner_worker.py` and the
Postgres-backed
`test_background_retrain_crosses_authentic_floor_and_never_activates` remain
companion scheduling, authentic-floor, and non-activation proof.

1. Build `web`, then launch the isolated fixture:
   `PYTHONPATH=src:. uv run --locked python -m verification.run_fixture verification.m2z4.scenario_app:create_scenario_app --port 8794`.
2. Reset it with `curl -X POST http://127.0.0.1:8794/__scenario__/reset`, then
   open `http://127.0.0.1:8794/?fixture=M2Z4%20REGRESSION` at 1440×900. Keep the
   `M2Z4 REGRESSION` banner visible.
3. Open Vitals and Injection. Verify `18 / 25` authentic signals, `7 to floor`,
   six excluded verification/test/fixture signals, right/wrong agreement, and
   both the live sawtooth and held-out generation series with annotations.
4. In Injection, tap **FORCE RETRAIN** once. Verify the plain refusal says the
   `Not enough authentic signals yet: 18 / 25 available.`; the Network request is bodyless
   `POST /v1/rack/scorers/retrain`. The separate informed control remains
   labeled **Force values**.
5. Leave Injection open. In a terminal run
   `curl -X POST http://127.0.0.1:8794/__scenario__/background-proposal` and wait
   up to seven seconds for the Console's normal five-second poll. Verify the
   floor becomes met and `BACKGROUND PROPOSAL` / `m2z4-proposal` / its held-out
   score appear without closing or reopening the module.
6. Switch to Current and tap **Audition** on `m2z4-proposal`. Verify the preview
   marks the second memory `would add`, while the current recipe remains
   `m2z4-incumbent`.
7. Verify **Activate** is visible, but do not tap it. Read
   `/__scenario__/trace`: `auditions` is non-empty, `activation_attempts` is
   empty, and `active_version` is still `m2z4-incumbent`.
8. Repeat the open Console and Vitals views at 390×844; verify no horizontal
   overflow. Preserve screenshots and the exact trace response as fixture
   evidence.

## Recorded deterministic-fixture evidence

The final browser journey recorded these measurements and owner-visible
behaviors:

- At 1440×900, the outer page measured `clientWidth=1440` and
  `scrollWidth=1440`. Injection Console measured `1352/1352`; its box remained
  within `x=44.2..1395.8`. Expanded Vitals children fit within its 271 px
  content height.
- At 390×844, the outer page measured `390/390` and Injection Console measured
  `388/388`. Collapsed Vitals still exposed `Learn 25 / 25`, `Right 10`, and
  `Wrong 2`.
- Keyboard scrolling inside the Console reached the proposal actions. The
  owner-visible **GLOBAL**, **CURRENT**, and **CLOSE** controls remained
  available; closing and reopening preserved **Current** scope.
- Exactly one **FORCE RETRAIN** control was present. The below-floor refusal
  remained attached to 18/25 and disappeared when the authoritative count
  changed to 25/25.
- The audition result survived the normal five-second polling cycle while the
  current recipe remained `m2z4-incumbent`.
- The preserved `trace.json` is the actual response from the final journey. Its
  two audition rows record the repeated desktop/mobile preview; its
  `activation_attempts` list is empty, so no activation was attempted.

## Disposable real-composition proof

`real-composition-summary.json` records a separate current-Harness +
current-Spine run against disposable Postgres schema `0011`. The authoritative
view was 0/25. One real bodyless manual retrain appended an
`insufficient_data` receipt at eligible count 0; no proposal was created, and
`v0` remained active without a learner marker.

The fixture refuses activation even if the SOP is violated. It never changes
an owner Palace, synthesizes a production signal, deploys anything, or claims
worker proof.
