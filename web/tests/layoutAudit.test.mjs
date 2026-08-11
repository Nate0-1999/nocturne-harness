import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { auditLayout, LAYOUT_SWEEP_WIDTHS } from '../src/layoutAudit.ts'

const webRoot = new URL('../', import.meta.url)

/** M2UX1 / PLAN charge makes the 390-to-ultrawide ladder and positive-area collision rule standing law. */
test('layout audit catches interactive overlap without rejecting shared edges', () => {
  assert.deepEqual(LAYOUT_SWEEP_WIDTHS, [390, 480, 768, 1024, 1280, 1440, 1920])
  const result = auditLayout([
    node('save', 10, 10, 40, 20),
    node('restore', 50, 10, 40, 20),
    node('queue', 80, 10, 40, 20),
  ])

  assert.deepEqual(
    result.collisions.map(({ first, second }) => [first.id, second.id]),
    [['restore', 'queue']],
  )
})

/** M2UX1 / PLAN charge treats text scroll beyond its visible box as a first-class regression. */
test('layout audit reports clipped text independently of box collisions', () => {
  const clipped = { ...node('thread-title', 0, 0, 120, 40), clipped: true }
  const result = auditLayout([clipped])

  assert.deepEqual(result.collisions, [])
  assert.deepEqual(result.clipped.map((item) => item.id), ['thread-title'])
})

/** M2UX1 / PLAN charge fixes the layout-control lane and removes thread-title clipping at their source. */
test('rack source reserves the host control lane and lets thread titles wrap in full', async () => {
  const [app, rackCss, shellCss] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
    readFile(new URL('src/assets/shell.css', webRoot), 'utf8'),
  ])

  assert.match(app, /className="rack-set-reserve" aria-hidden="true"/)
  assert.match(rackCss, /grid-template-columns:\s*11\.5rem 13\.25rem max-content minmax\(0, 1fr\) max-content/)
  assert.match(shellCss, /\.thread-item__title\s*\{[^}]*overflow-wrap:\s*anywhere/s)
  assert.doesNotMatch(shellCss, /\.thread-item__title\s*\{[^}]*line-clamp/s)
})

function node(id, x, y, width, height) {
  return {
    id,
    label: id,
    scope: 'fixture',
    rect: { x, y, width, height },
    clipped: false,
  }
}
