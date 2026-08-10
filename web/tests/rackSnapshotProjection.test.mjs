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
