import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** PLAN M2UX2 and SPEC B.6 require every dismissible full-screen view to return to the stage in one obvious click. */
test('every dismissible overlay shares the host-owned back-to-stage control', async () => {
  const [app, graph, injection, css] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/MemoryGraph.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8'),
  ])

  for (const moduleId of [
    'thread_end',
    'palace_queue',
    'model_device',
    'memory_graph',
    'injection_console',
  ]) {
    assert.match(app, new RegExp(`${moduleId}:\\s*'rack-overlay-module--`, 'u'))
  }
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

/** SPEC B.6 requires the effective overlay rule to retain usable desktop/mobile insets. */
test('instrument inset rules outrank the later generic overlay reset', async () => {
  const css = await readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8')
  const genericIndex = css.indexOf('.rack-overlay-module {')
  const instrumentIndex = css.indexOf('.rack-overlay-module.rack-overlay-module--instrument {')

  assert.ok(genericIndex >= 0)
  assert.ok(instrumentIndex > genericIndex)
  assert.match(
    css.slice(instrumentIndex),
    /\.rack-overlay-module\.rack-overlay-module--instrument\s*\{\s*inset:\s*4\.5rem 3vw 2rem;/u,
  )
  assert.match(
    css.slice(instrumentIndex),
    /@media \(max-width:\s*760px\)[^{]*\{[\s\S]*?\.rack-overlay-module\.rack-overlay-module--instrument\s*\{\s*inset:\s*3\.25rem 0 0;/u,
  )
})

/** ADR-005 and A-051 require Injection scope to survive close/reopen like Graph scope. */
test('Injection scope buttons persist through rack.scope.set', async () => {
  const source = await readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8')

  assert.match(source, /type:\s*'rack\.scope\.set'/u)
  assert.match(source, /module_id:\s*'injection_console'/u)
  assert.match(source, /onClick=\{\(\) => changeScope\('GLOBAL'\)\}/u)
  assert.match(source, /onClick=\{\(\) => changeScope\('CURRENT'\)\}/u)
})

/** SPEC B.6 and A-051 require M2Z4 secondary acts to remain visibly readable. */
test('Run DEEP and Audition share explicit readable secondary-action states', async () => {
  const [source, css] = await Promise.all([
    readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8'),
  ])
  const classUses = source.match(/className="console-secondary-action"/gu) ?? []
  const normal = /\.instrument--console \.console-secondary-action\s*\{(?<body>[^}]*)\}/u.exec(css)
  const disabled = /\.instrument--console \.console-secondary-action:disabled\s*\{(?<body>[^}]*)\}/u.exec(css)

  assert.equal(classUses.length, 2)
  assert.notEqual(normal, null)
  assert.match(normal.groups.body, /border:\s*1px solid/u)
  assert.match(normal.groups.body, /background:\s*#071118/u)
  assert.match(normal.groups.body, /color:\s*#dce9ee/u)
  assert.match(css, /\.instrument--console \.console-secondary-action:hover:not\(:disabled\)/u)
  assert.match(css, /\.instrument--console \.console-secondary-action:focus-visible/u)
  assert.notEqual(disabled, null)
  assert.match(disabled.groups.body, /background:\s*#081016/u)
  assert.match(disabled.groups.body, /color:\s*#60767e/u)
})
