import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ACTIVATE_LABEL,
  AUDITION_LABEL,
  FORCE_RETRAIN_LABEL,
  FORCE_VALUES_LABEL,
  chartPolyline,
  consoleRefreshResetPolicy,
  generationAccuracyCopy,
  learningAgreementCopy,
  learningCadenceCopy,
  learningFloorCopy,
  learningHygieneCopy,
  learningNoticeAfterSnapshot,
  learningTimelineModel,
  learningWeightedTotalsCopy,
  scorerConsoleTelemetry,
} from '../src/learning.ts'

function learning(overrides = {}) {
  return {
    eligible_dispositions: 18,
    hygiene_excluded_dispositions: 7,
    minimum_dispositions: 25,
    remaining_to_floor: 7,
    floor_met: false,
    retrain_signal_stride: 25,
    evaluated_through: null,
    signals_since_last_run: 18,
    signals_until_next_run: 7,
    active_scorer_version: 'v0',
    right: 900,
    wrong: 1,
    weighted_right: '14.25',
    weighted_wrong: '2.10',
    weighted_agreement_percent: '87.125',
    live_agreement: [
      {
        event_uid: 'live-a',
        ts: '2026-08-09T12:00:00Z',
        scorer_version: 'v0',
        right: 3,
        wrong: 1,
        weighted_right: '2.5',
        weighted_wrong: '1',
        weighted_agreement_percent: '71.428571',
      },
      {
        event_uid: 'live-b',
        ts: '2026-08-09T12:02:00Z',
        scorer_version: 'v0',
        right: 4,
        wrong: 1,
        weighted_right: '3.5',
        weighted_wrong: '1',
        weighted_agreement_percent: '77.777778',
      },
    ],
    retrain_runs: [],
    annotations: [
      {
        kind: 'retrain',
        event_uid: 'run-a',
        ts: '2026-08-09T12:03:00Z',
        version: 'v0',
        result: 'not_better',
      },
    ],
    ...overrides,
  }
}

const accuracy = [
  {
    version: 'v1',
    created_at: '2026-08-09T12:01:00Z',
    status: 'measured',
    accuracy_percent: '62.5',
    holdout_dispositions: 5,
    disagreements: 2,
    weighted_dispositions: '4.0',
    weighted_wrong: '1.5',
  },
  {
    version: 'legacy',
    created_at: '2026-08-09T11:59:00Z',
    status: 'not_recorded',
    accuracy_percent: null,
    holdout_dispositions: null,
    disagreements: null,
    weighted_dispositions: null,
    weighted_wrong: null,
  },
]

/** A-051 makes the browser a presenter of exact learner counts, never a second referee. */
test('presents exact server-authored floor, hygiene and weighted scoreboard values', () => {
  const snapshot = learning()

  assert.equal(learningFloorCopy(snapshot), '18 / 25 authentic signals · 7 to floor')
  assert.equal(
    learningHygieneCopy(snapshot),
    '7 otherwise-gradable verification, test, or fixture signals excluded',
  )
  assert.equal(
    learningAgreementCopy(snapshot),
    '900 right · 1 wrong · 87.125% weighted agreement',
  )
  assert.equal(
    learningWeightedTotalsCopy(snapshot),
    '14.25 weighted right · 2.10 weighted wrong',
  )
})

/** A-051 distinguishes floor readiness from a completed retrain receipt. */
test('describes the first background retrain honestly before a durable run exists', () => {
  assert.equal(
    learningCadenceCopy(learning()),
    '7 authentic signals until the first background retrain',
  )
  assert.equal(
    learningCadenceCopy(learning({ floor_met: true, remaining_to_floor: 0, signals_until_next_run: 0 })),
    'Floor met · waiting for the first background retrain',
  )
  assert.equal(
    learningCadenceCopy(learning({
      floor_met: true,
      remaining_to_floor: 0,
      evaluated_through: 25,
      signals_since_last_run: 4,
      signals_until_next_run: 21,
    })),
    '4 / 25 since the last retrain · 21 to next',
  )
})

/** ADR-009 item 4 requires two server-score series on one timeline plus retrain annotations. */
test('positions live and generation scores on one timeline without deriving either score', () => {
  const model = learningTimelineModel(learning(), accuracy)

  assert.deepEqual(model.live.map((point) => point.percent), ['71.428571', '77.777778'])
  assert.deepEqual(model.generations.map((point) => point.percent), ['62.5'])
  assert.equal(model.unmeasuredGenerations, 1)
  assert.equal(model.annotations[0].label, 'Retrain not better · v0')
  assert.ok(model.live[0].x < model.generations[0].x)
  assert.ok(model.generations[0].x < model.live[1].x)
  assert.match(chartPolyline(model.live), /^\d+(?:\.\d+)?,\d+(?:\.\d+)? /u)
})

/** A-051 keeps legacy, unweighted generations visibly unmeasured instead of guessing. */
test('does not invent a proposal score when weighted evidence is not recorded', () => {
  assert.equal(generationAccuracyCopy(accuracy[0]), '62.5% held-out agreement')
  assert.equal(generationAccuracyCopy(accuracy[1]), 'Held-out agreement not recorded')
  assert.equal(generationAccuracyCopy(undefined), 'Held-out agreement not recorded')
})

/** A-051 background polling must not erase an owner's exact-value work. */
test('quiet refresh preserves controls until scope or active generation changes', () => {
  const preserveEverything = {
    draft: false,
    preview: false,
    receipt: false,
    audition: false,
  }
  const resetEverything = {
    draft: true,
    preview: true,
    receipt: true,
    audition: true,
  }
  assert.deepEqual(consoleRefreshResetPolicy('v0', 'v0', false), preserveEverything)
  assert.deepEqual(consoleRefreshResetPolicy(null, 'v0', false), preserveEverything)
  assert.deepEqual(consoleRefreshResetPolicy('v0', 'v1', false), resetEverything)
  assert.deepEqual(consoleRefreshResetPolicy('v0', 'v0', true), resetEverything)
})

/** A-051 forbids a point-in-time refusal from contradicting newer authoritative progress. */
test('quiet progress refresh expires only a retrain notice and preserves owner interaction', () => {
  const refusal = {
    copy: 'Not enough authentic signals yet: 18 / 25 available.',
    eligibleDispositions: 18,
  }

  assert.equal(learningNoticeAfterSnapshot(refusal, 25), null)
  assert.deepEqual(consoleRefreshResetPolicy('v0', 'v0', false), {
    draft: false,
    preview: false,
    receipt: false,
    audition: false,
  })
  assert.equal(learningNoticeAfterSnapshot(refusal, 18), refusal)
  const activation = { copy: 'Activated v1.', eligibleDispositions: null }
  assert.equal(learningNoticeAfterSnapshot(activation, 25), activation)
})

/** A-051 gives the cockpit one retrain act, distinct values, and terse proposal controls. */
test('freezes the owner control copy', () => {
  assert.equal(FORCE_RETRAIN_LABEL, 'FORCE RETRAIN')
  assert.equal(FORCE_VALUES_LABEL, 'Force values')
  assert.equal(AUDITION_LABEL, 'Audition')
  assert.equal(ACTIVATE_LABEL, 'Activate')
})

/** A-051 requires Vitals and Console to consume the same scorer-console envelope. */
test('extracts one shared telemetry view and refuses a missing learning view', () => {
  const telemetry = scorerConsoleTelemetry({ learning: learning(), accuracy })
  assert.equal(telemetry?.learning.weighted_agreement_percent, '87.125')
  assert.equal(telemetry?.accuracy[0].weighted_dispositions, '4.0')
  assert.equal(scorerConsoleTelemetry({ accuracy }), null)
})
