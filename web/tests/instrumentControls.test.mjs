import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** SPEC B.6 and A-051 require one reachable in-frame close path above the host scrim. */
test('both memory instruments share the selection-bridge close control', async () => {
  const [close, graph, injection, css] = await Promise.all([
    readFile(new URL('../src/InstrumentClose.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/MemoryGraph.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/InjectionConsole.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8'),
  ])

  assert.match(close, /aria-label="Close instrument"/u)
  assert.match(close, /selection\.select\(null\)/u)
  assert.match(graph, /<InstrumentClose\s*\/>/u)
  assert.match(injection, /<InstrumentClose\s*\/>/u)
  assert.match(css, /\.instrument\s*>\s*header\s*\{[^}]*position:\s*sticky/u)
  assert.match(
    css,
    /@media \(max-width:\s*760px\)[^{]*\{[\s\S]*?\.instrument\s*>\s*header\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/u,
  )
  assert.match(
    css,
    /\.instrument-header-actions\s*\{[^}]*justify-content:\s*space-between[^}]*width:\s*100%/u,
  )
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
