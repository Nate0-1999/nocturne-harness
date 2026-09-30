import assert from 'node:assert/strict'
import test from 'node:test'

import {
  rackSnapshotForIframe,
  rackValueForIframe,
} from '../src/rackSnapshotProjection.ts'

/** A-052, A-018, and B.6 r12 require exact bytes to survive in the volatile host outbox while
 * forbidding those bytes and local filenames from the rack-wide snapshot fanout.
 */
test('rack iframe boundary strips private image material without mutating the host outbox', () => {
  const view = {
    kind: 'image',
    media_type: 'image/jpeg',
    byte_count: 3,
    sha256: 'a'.repeat(64),
  }
  const snapshot = {
    catalog: [],
    selectedThreadId: 'thread-1',
    currentProjectKey: null,
    projectPaths: [],
    connection: 'connected',
    globalError: null,
    threads: {
      'thread-1': {
        outboundPrompts: [{
          prompt_id: '01ARZ3NDEKTSV4RRFFQ69G5FAV',
          prompt: 'What is shown?',
          image_input: {
            kind: 'image',
            media_type: 'image/jpeg',
            data_base64: '/9j/',
          },
          image_view: view,
          local_filename: 'private-name.jpg',
          image_preview_data_url: 'data:image/jpeg;base64,/9j/',
        }],
      },
    },
  }

  const projected = rackSnapshotForIframe(snapshot)
  const wire = JSON.stringify(projected)
  assert.doesNotMatch(wire, /data_base64|private-name|image_preview_data_url|\/9j\//u)
  assert.deepEqual(projected.threads['thread-1'].outboundPrompts[0].image_view, view)
  assert.equal(snapshot.threads['thread-1'].outboundPrompts[0].image_input.data_base64, '/9j/')
  assert.equal(snapshot.threads['thread-1'].outboundPrompts[0].local_filename, 'private-name.jpg')

  const projectedEnvelope = rackValueForIframe({
    type: 'envelope',
    event: {
      direction: 'outbound',
      envelope: {
        type: 'prompt.submit',
        payload: {
          prompt: 'What is shown?',
          image: {
            kind: 'image',
            media_type: 'image/jpeg',
            data_base64: '/9j/',
          },
        },
      },
    },
  })
  assert.doesNotMatch(JSON.stringify(projectedEnvelope), /data_base64|\/9j\//u)
  assert.equal(projectedEnvelope.event.envelope.payload.prompt, 'What is shown?')
})

/** M3HW: every store change re-copied the whole rack once per module frame; an unchanged value
 * keeps its one projection, and only what the change replaced is walked again. */
test('a snapshot change projects only the values it replaced', () => {
  const quiet = { messages: [{ role: 'assistant', content: 'done', events: [{ event_kind: 'part_end' }] }] }
  const busy = { messages: [{ role: 'assistant', content: 'wor', events: [] }] }
  const before = { selectedThreadId: 'busy', threads: { quiet, busy } }
  const after = {
    ...before,
    threads: { quiet, busy: { messages: [{ ...busy.messages[0], content: 'working', image_input: { data_base64: '/9j/' } }] } },
  }
  const first = rackSnapshotForIframe(before)
  const second = rackSnapshotForIframe(after)
  assert.equal(second.threads.quiet, first.threads.quiet)
  assert.notEqual(second.threads.busy, first.threads.busy)
  assert.equal(second.threads.busy.messages[0].content, 'working')
  assert.doesNotMatch(JSON.stringify(second), /data_base64|\/9j\//u)
  assert.deepEqual(first, { selectedThreadId: 'busy', threads: { quiet, busy } })
})
