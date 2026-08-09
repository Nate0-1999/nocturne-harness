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

  assert.deepEqual(snapshotBarrierRoute(threadId, threadId, 'error'), {
    disposition: 'error', publish: true,
  })
  assert.deepEqual(snapshotBarrierRoute(threadId, threadId, 'run.started'), {
    disposition: 'drop', publish: false,
  })
  assert.deepEqual(snapshotBarrierRoute(threadId, threadId, 'memory.panel.update'), {
    disposition: 'drop', publish: false,
  })
  assert.deepEqual(snapshotBarrierRoute(threadId, threadId, 'thread.snapshot'), {
    disposition: 'snapshot', publish: true,
  })
  assert.deepEqual(snapshotBarrierRoute(threadId, 'thread-b', 'run.started'), {
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
