import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { auditLayout, LAYOUT_SWEEP_WIDTHS } from '../src/layoutAudit.ts'

const webRoot = new URL('../', import.meta.url)

/** SPEC B.6 / M2UX1 makes the 390-to-ultrawide ladder and positive-area collision rule standing law. */
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

/** SPEC B.6 / M2UX1 treats text scroll beyond its visible box as a first-class regression. */
test('layout audit reports clipped text independently of box collisions', () => {
  const clipped = { ...node('thread-title', 0, 0, 120, 40), clipped: true }
  const result = auditLayout([clipped])

  assert.deepEqual(result.collisions, [])
  assert.deepEqual(result.clipped.map((item) => item.id), ['thread-title'])
})

/** SPEC B.6 / M2UX1 and PLAN M2UX4 reserve the host layout/theme lane and remove thread-title clipping at their source. */
test('rack source reserves the host control lane and lets thread titles wrap in full', async () => {
  const [app, graph, rackCss, shellCss] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/MemoryGraph.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
    readFile(new URL('src/assets/shell.css', webRoot), 'utf8'),
  ])

  assert.match(app, /className="rack-set-reserve" aria-hidden="true"/)
  assert.match(app, /data-testid="theme-control"/)
  assert.match(app, /matchMedia\('\(max-width: 48\.9rem\)'\)/)
  assert.match(app, /data-testid="seed-upload"[\s\S]*tabIndex=\{-1\}[\s\S]*aria-hidden="true"/)
  assert.match(rackCss, /grid-template-columns:\s*11\.5rem 22rem max-content minmax\(0, 1fr\) max-content/)
  assert.match(rackCss, /@media \(max-width: 48\.9rem\)[\s\S]*\.rack-set-controls\s*\{[\s\S]*top:\s*3\.25rem/)
  assert.match(rackCss, /\.rack-shell--vitals-collapsed \.rack-module\[data-rack-module="chat"\]\s*\{[^}]*inset:\s*5\.35rem 0 3\.1rem/s)
  assert.match(rackCss, /\.rack-overlay-module--palace-queue,[\s\S]*inset:\s*3\.25rem 0 0/)
  assert.match(rackCss, /@media \(max-width: 48\.9rem\)[\s\S]*\.rack-drawer-scrim\s*\{\s*display:\s*none/)
  assert.match(rackCss, /\.learning-summary__metric > small\s*\{[^}]*overflow-wrap:\s*anywhere/s)
  assert.match(graph, /<g className="graph-node"[\s\S]*<title>\{node\.memory\.label\}<\/title>[\s\S]*<\/g>\s*<text className="graph-node-label"/)
  assert.match(shellCss, /\.thread-item__title\s*\{[^}]*overflow-wrap:\s*anywhere/s)
  assert.match(shellCss, /\.thread-item__meta\s*\{[^}]*flex-wrap:\s*wrap/s)
  assert.match(shellCss, /\.chat-header h1\s*\{[^}]*overflow-wrap:\s*anywhere/s)
  assert.doesNotMatch(shellCss, /\.thread-item__title\s*\{[^}]*line-clamp/s)
})

function node(id, x, y, width, height) {
  return {
    id,
    label: id,
    scope: 'fixture',
    rect: { x, y, width, height },
    interactive: true,
    clipped: false,
  }
}
