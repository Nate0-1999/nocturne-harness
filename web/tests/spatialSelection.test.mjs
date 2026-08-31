import assert from 'node:assert/strict'
import test from 'node:test'

import {
  spatialAddresses,
  spatialSelectionIsVisible,
} from '../src/spatialSelection.ts'

/** P2.3 makes visible position the Recipe selection primitive, including transitive frames. */
test('snap-touching modules form one transitive frame within their layer', () => {
  const addresses = spatialAddresses('recipe', [
    { module_id: 'recipe', x: 0, y: 0, width: 8, height: 8 },
    { module_id: 'vitals', x: 8, y: 2, width: 4, height: 3 },
    { module_id: 'memory', x: 12, y: 2, width: 4, height: 3 },
    { module_id: 'conversation', x: 30, y: 30, width: 8, height: 8 },
  ])

  assert.equal(addresses.get('recipe').frame_id, addresses.get('vitals').frame_id)
  assert.equal(addresses.get('vitals').frame_id, addresses.get('memory').frame_id)
  assert.notEqual(addresses.get('recipe').frame_id, addresses.get('conversation').frame_id)
})

/** P2.3 keeps local selection spatial while preserving one deliberate global escape. */
test('a local watcher sees only its frame while GLOBAL escapes position', () => {
  const origin = { layer_id: 'recipe', frame_id: 'recipe:recipe+vitals' }
  assert.equal(spatialSelectionIsVisible(origin, { ...origin, scope: 'ATTUNED' }), true)
  assert.equal(spatialSelectionIsVisible(origin, {
    layer_id: 'recipe', frame_id: 'recipe:conversation', scope: 'ATTUNED',
  }), false)
  assert.equal(spatialSelectionIsVisible(origin, {
    layer_id: 'work', frame_id: 'work:conversation', scope: 'ATTUNED',
  }), false)
  assert.equal(spatialSelectionIsVisible(origin, {
    layer_id: 'work', frame_id: 'work:conversation', scope: 'GLOBAL',
  }), true)
})
