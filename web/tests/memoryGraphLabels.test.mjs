import assert from 'node:assert/strict'
import test from 'node:test'

import { declutterGraphLabels } from '../src/memoryGraphLabels.ts'

/** PLAN M2ST3 finding 7a and SPEC P2.3 require graph labels to declare priority and never collide. */
test('keeps the highest-signal label when graph labels collide', () => {
  const labels = declutterGraphLabels([
    candidate('ordinary', 'An ordinary long memory label', 40, { injections: 9 }),
    candidate('current', 'Current context memory label', 45, { current: true }),
    candidate('selected', 'Selected memory label', 50, { selected: true }),
  ])

  assert.deepEqual(labels.map((label) => label.id), ['selected'])
  assert.equal(labels[0].text, 'Selected memory…')
  assert.ok(labels[0].priority >= 10_000)
})

/** SPEC P2.3 and PLAN M2ST3 require the declutter result itself to be mechanically non-overlapping. */
test('retains separated labels with non-overlapping boxes inside the graph viewbox', () => {
  const labels = declutterGraphLabels([
    candidate('left', 'Left memory', 8),
    candidate('middle', 'Middle memory', 50),
    candidate('right', 'Right memory', 96),
  ])

  assert.equal(labels.length, 3)
  for (const label of labels) {
    assert.ok(label.box.left >= 0)
    assert.ok(label.box.right <= 100)
  }
  for (let index = 0; index < labels.length; index += 1) {
    for (let other = index + 1; other < labels.length; other += 1) {
      assert.equal(overlap(labels[index].box, labels[other].box), false)
    }
  }
})

function candidate(id, label, x, overrides = {}) {
  return {
    id, label, x, y: 18, radius: 3,
    selected: false, current: false, pinned: false, injections: 0,
    ...overrides,
  }
}

function overlap(left, right) {
  return !(
    left.right <= right.left || right.right <= left.left ||
    left.bottom <= right.top || right.bottom <= left.top
  )
}
