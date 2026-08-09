import assert from 'node:assert/strict'
import test from 'node:test'

import {
  queueDecisionPayload,
  seedBatchDecisionPayload,
} from '../src/approvalQueue.ts'

/** F023 requires queue taps to carry intent only so the daemon remains provenance authority. */
test('queue decision payloads never claim a machine identity', () => {
  const item = queueDecisionPayload({
    decision: 'approve',
    approval_mode: 'passive',
    actor_class: 'passive',
  })
  const batch = seedBatchDecisionPayload('deny')

  assert.deepEqual(item, {
    decision: 'approve',
    approval_mode: 'passive',
    actor_class: 'passive',
  })
  assert.deepEqual(batch, {
    decision: 'deny',
    approval_mode: 'explicit',
    actor_class: 'human',
  })
  assert.equal(Object.hasOwn(item, 'machine_id'), false)
  assert.equal(Object.hasOwn(batch, 'machine_id'), false)
})
