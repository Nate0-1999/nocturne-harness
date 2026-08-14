import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** PLAN M2UX2, PLAN M2ST1, and SPEC B.6 keep lifecycle overlays dismissible while Graph and Injection become stage modules. */
test('lifecycle overlays return in one click while instruments live on the stage', async () => {
  const [app, graph, injection, css, stage] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/MemoryGraph.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8'),
    readFile(new URL('../src/stageLayout.ts', import.meta.url), 'utf8'),
  ])

  for (const moduleId of [
    'thread_end',
    'model_device',
  ]) {
    assert.match(app, new RegExp(`${moduleId}:\\s*'rack-overlay-module--`, 'u'))
  }
  assert.doesNotMatch(app, /memory_graph:\s*'rack-overlay-module--/u)
  assert.doesNotMatch(app, /injection_console:\s*'rack-overlay-module--/u)
  assert.doesNotMatch(app, /palace_queue:\s*'rack-overlay-module--/u)
  assert.match(stage, /'memory_graph', 'injection_console', 'palace_queue'/u)
  assert.match(app, /data-stage-return="one-click"/u)
  assert.match(app, /data-testid="back-to-stage"/u)
  assert.match(app, /Back to stage/u)
  assert.match(app, /onClick=\{clearRackSelection\}/u)
  assert.doesNotMatch(graph, /InstrumentClose/u)
  assert.doesNotMatch(injection, /InstrumentClose/u)
  assert.match(css, /\.rack-overlay-module--dismissible\s*\{[^}]*display:\s*grid/u)
  assert.match(css, /\.rack-stage-back\s*\{/u)
})

/** PLAN M2UX2 and ADR-021 clause 4 require a thread-list archive act to reuse ordinary extraction instead of inventing deletion. */
test('thread-list archive targets the existing extraction action by thread identity', async () => {
  const [app, rack] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(rack, /actions:\s*\['thread\.create', 'thread\.select', 'thread\.archive'/u)
  assert.match(rack, /\{ type: 'thread\.archive'; thread_id\?: string \}/u)
  assert.match(rack, /action\.thread_id \?\? getRackSnapshot\(\)\.selectedThreadId/u)
  assert.match(rack, /\/v1\/threads\/\$\{encodeURIComponent\(threadId\)\}\/archive/u)
  assert.match(rack, /rackSelectionSurface\.select\(\{ kind: 'module', id: 'thread_end' \}\)/u)
  assert.match(app, /aria-label=\{`Archive \$\{visibleThreadTitle\(entry\.title\)\}`\}/u)
  assert.match(app, /type: 'thread\.archive', thread_id: entry\.thread_id/u)
})

/** PLAN M2ST1 and SPEC B.6 require Graph and Injection to use ordinary stage geometry instead of overlay insets. */
test('instrument remotes remain scrollable without being fixed host overlays', async () => {
  const css = await readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8')

  assert.match(css, /\.stage-canvas > \.rack-module\s*\{[^}]*position:\s*absolute/su)
  assert.match(css, /\.rack-remote--memory_graph\s*,\s*\.rack-remote--injection_console/u)
})

/** PLAN M2ST2 and ADR-023 move scope into shared settings while preserving the existing persisted action. */
test('Injection scope is owned by the shared module settings slot', async () => {
  const [app, source] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(source, /type:\s*'rack\.scope\.get'/u)
  assert.doesNotMatch(source, /className="scope-switch"/u)
  assert.match(app, /className="rack-module__settings-toggle"/u)
  assert.match(app, /type:\s*'rack\.scope\.set'/u)
  assert.match(app, /scope=\{layout\.scopes\[module\.module_id\]\}/u)
  assert.match(app, /key=\{`\$\{manifest\.id\}:\$\{scope\}`\}/u)
})

/** SPEC B.6 and A-051 require M2Z4 secondary acts to remain visibly readable. */
test('Run DEEP and Audition share explicit readable secondary-action states', async () => {
  const [source, css, seamSource] = await Promise.all([
    readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8'),
    readFile(new URL('../src/themes/seam-colors.json', import.meta.url), 'utf8'),
  ])
  const seam = JSON.parse(seamSource).colors
  const classUses = source.match(/className="console-secondary-action"/gu) ?? []
  const normal = /\.instrument--console \.console-secondary-action\s*\{(?<body>[^}]*)\}/u.exec(css)
  const disabled = /\.instrument--console \.console-secondary-action:disabled\s*\{(?<body>[^}]*)\}/u.exec(css)

  assert.equal(classUses.length, 2)
  assert.notEqual(normal, null)
  assert.match(normal.groups.body, /border:\s*1px solid/u)
  assertSeamValue(normal.groups.body, 'background', '#071118', seam)
  assertSeamValue(normal.groups.body, 'color', '#dce9ee', seam)
  assert.match(css, /\.instrument--console \.console-secondary-action:hover:not\(:disabled\)/u)
  assert.match(css, /\.instrument--console \.console-secondary-action:focus-visible/u)
  assert.notEqual(disabled, null)
  assertSeamValue(disabled.groups.body, 'background', '#081016', seam)
  assertSeamValue(disabled.groups.body, 'color', '#60767e', seam)
})

function assertSeamValue(cssBody, property, neoNoirValue, seam) {
  const match = new RegExp(`(?:^|\\n)\\s*${property}:\\s*var\\((--seam-[0-9a-f]{12})\\)`, 'u').exec(cssBody)
  assert.notEqual(match, null)
  const entry = seam.find((color) => color.variable === match[1])
  assert.equal(entry?.neo_noir, neoNoirValue)
}
