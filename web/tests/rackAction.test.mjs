import assert from 'node:assert/strict'
import test from 'node:test'

import { runRackAction } from '../src/rackAction.ts'

/** F022 requires an unproven async archive failure to reach the owner-visible error surface. */
test('reports an asynchronous rack action failure before rethrowing it', async () => {
  const reported = []
  const failure = new Error('Rack action failed (503)')

  await assert.rejects(
    runRackAction(async () => { throw failure }, (message) => reported.push(message)),
    failure,
  )

  assert.deepEqual(reported, ['Rack action failed (503)'])
})

/** F022 requires successful reconciliation to stay quiet and continue to its review handoff. */
test('does not report a rack action that reconciles successfully', async () => {
  const reported = []

  const result = await runRackAction(async () => ({ cards: ['existing'] }), (message) => {
    reported.push(message)
  })

  assert.deepEqual(result, { cards: ['existing'] })
  assert.deepEqual(reported, [])
})
