import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isProjectContextConflict,
  snapshotErrorAfterReconciliation,
  snapshotBarrierRoute,
  snapshotRequestError,
} from '../src/snapshotBarrier.ts'

/** F028 and ADR-005 require the immutable-project conflict to cross the snapshot barrier,
 * while SPEC C.3/C.4 keep every unrelated live event behind authoritative hydration.
 */
test('admits only a same-thread error and snapshot while the barrier remains active', () => {
  const threadId = 'thread-a'
  const requestId = 'request-a'

  assert.deepEqual(snapshotBarrierRoute(threadId, requestId, threadId, 'error', null), {
    disposition: 'error', publish: true,
  })
  assert.deepEqual(snapshotBarrierRoute(threadId, requestId, threadId, 'run.started', null), {
    disposition: 'drop', publish: false,
  })
  assert.deepEqual(snapshotBarrierRoute(threadId, requestId, threadId, 'memory.panel.update', null), {
    disposition: 'drop', publish: false,
  })
  assert.deepEqual(snapshotBarrierRoute(
    threadId, requestId, threadId, 'thread.snapshot', requestId,
  ), {
    disposition: 'snapshot', publish: true,
  })
  assert.deepEqual(snapshotBarrierRoute(
    threadId, requestId, threadId, 'thread.snapshot', null,
  ), {
    disposition: 'drop', publish: false,
  }, 'an automatic snapshot cannot acknowledge the project-open request')
  assert.deepEqual(snapshotBarrierRoute(
    threadId, requestId, threadId, 'thread.snapshot', 'request-b',
  ), {
    disposition: 'drop', publish: false,
  }, 'an older request cannot acknowledge the current project-open request')
  assert.deepEqual(snapshotBarrierRoute(threadId, requestId, 'thread-b', 'run.started', null), {
    disposition: 'outside', publish: true,
  })
})

/** F028 and ADR-005 require the daemon's plain new-thread remedy to remain visible after
 * the immediately following authoritative snapshot reconciles the thread project.
 */
test('preserves only a project-context conflict through snapshot reconciliation', () => {
  const conflict = {
    message: 'This thread already belongs to unscoped history. Start a new thread.',
    detail: { code: 'project_context_conflict' },
  }
  const ordinary = { message: 'Run failed', detail: { code: 'run_failed' } }

  const conflictPending = isProjectContextConflict(conflict)
  assert.equal(snapshotErrorAfterReconciliation(conflict, conflictPending), conflict)
  assert.equal(snapshotErrorAfterReconciliation(ordinary, false), null)
  assert.equal(snapshotErrorAfterReconciliation(null, false), null)

  assert.equal(snapshotRequestError(conflict, conflictPending), conflict)
  assert.equal(snapshotRequestError(conflict, false), null)
  assert.equal(snapshotRequestError(ordinary, false), ordinary)
})
