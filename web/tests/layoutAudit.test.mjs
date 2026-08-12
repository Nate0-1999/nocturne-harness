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
  assert.deepEqual(result.text_collisions, [])
})

/** SPEC B.6 / M2UX1 treats text scroll beyond its visible box as a first-class regression. */
test('layout audit reports clipped text independently of box collisions', () => {
  const clipped = { ...node('thread-title', 0, 0, 120, 40), clipped: true }
  const result = auditLayout([clipped])

  assert.deepEqual(result.collisions, [])
  assert.deepEqual(result.clipped.map((item) => item.id), ['thread-title'])
})

/** PLAN M2ST4 and SPEC B.6 require non-DOM SVG/canvas labels to join the standing collision sweep. */
test('layout audit reports visual text collisions within each rendered surface', () => {
  const result = auditLayout([
    visualText('svg-a', 'svg', 'graph', 0, 0, 60, 18),
    visualText('svg-b', 'svg', 'graph', 50, 0, 60, 18),
    visualText('canvas-a', 'canvas', 'stage-canvas', 0, 40, 60, 18),
    visualText('canvas-b', 'canvas', 'stage-canvas', 20, 40, 60, 18),
    visualText('other-surface', 'svg', 'other-graph', 20, 40, 60, 18),
  ])

  assert.deepEqual(
    result.text_collisions.map(({ first, second }) => [first.id, second.id]),
    [['svg-a', 'svg-b'], ['canvas-a', 'canvas-b']],
  )
})

/** SPEC B.6 / M2UX1 and PLAN M2ST1/M2ST2 keep the working lane sparse and owner text un-clipped. */
test('stage source keeps rare controls in settings and lets thread titles wrap in full', async () => {
  const [app, graph, rackCss, shellCss] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/MemoryGraph.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
    readFile(new URL('src/assets/shell.css', webRoot), 'utf8'),
  ])

  assert.match(app, /data-testid="app-settings-toggle"/)
  assert.match(app, /data-testid="app-settings-panel"/)
  assert.match(app, /data-testid="theme-control"/)
  assert.match(app, /data-testid="theme-control"[\s\S]*onChange=\{\(event\) => setTheme/u)
  assert.doesNotMatch(app, /className="stage-toolbar"[\s\S]*className="theme-control"/u)
  assert.match(app, /data-testid="stage-viewport"/)
  assert.match(app, /data-testid="stage-fit"/)
  assert.match(app, /role="tablist" aria-label="Stage layers"/)
  assert.match(app, /data-testid="seed-upload"[\s\S]*tabIndex=\{-1\}[\s\S]*aria-hidden="true"/)
  assert.match(rackCss, /\.rack-shell--stage\s*\{[^}]*grid-template-rows:\s*3\.35rem 2\.65rem/s)
  assert.match(rackCss, /\.rack-stage-header\s*\{[^}]*grid-row:\s*1/s)
  assert.match(rackCss, /\.stage-toolbar\s*\{[^}]*grid-row:\s*2/s)
  assert.match(rackCss, /\.plate-press-status\s*\{[^}]*grid-row:\s*3/s)
  assert.match(rackCss, /\.stage-viewport\s*\{[^}]*grid-row:\s*4;[^}]*overflow:\s*hidden/s)
  assert.match(rackCss, /\.m2c-regression-fixture\s*\{[^}]*grid-row:\s*1;[^}]*grid-column:\s*1;/s)
  assert.match(rackCss, /\.stage-canvas\s*\{[^}]*transform-origin:\s*0 0/s)
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

function visualText(id, renderer, surface, x, y, width, height) {
  return {
    ...node(id, x, y, width, height),
    interactive: false,
    text_renderer: renderer,
    text_surface: surface,
  }
}
