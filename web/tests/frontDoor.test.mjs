import assert from 'node:assert/strict'
import test from 'node:test'

import { attunedThreadSelection } from '../src/frontDoor.ts'

/** SPEC D.2 148 and PLAN M3FP: a settled first prompt crosses the focused
 * Conversation bridge exactly once without reopening the snapshot barrier.
 */
test('focused Conversation does not reselect its already-authoritative thread before send', () => {
  const threadId = '307e6141-bc47-44d8-be1d-365dbc18f9d6'
  const target = {
    kind: 'thread',
    id: threadId,
    name: 'New thread',
    thread_ids: [threadId],
    source_instance_id: 'conversation',
  }

  assert.equal(attunedThreadSelection('prompt.submit', target, threadId), null)
  assert.equal(
    attunedThreadSelection(
      'prompt.submit',
      { ...target, id: 'fe00ef57-fbaa-454a-b264-6b7f676bc84e' },
      threadId,
    ),
    'fe00ef57-fbaa-454a-b264-6b7f676bc84e',
  )
})
