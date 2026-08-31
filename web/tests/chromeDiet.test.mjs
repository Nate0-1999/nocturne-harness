import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

/** PLAN M2ST2 / M2RR / P2 requires rare app choices to live behind one working gear instead of occupying the work lane. */
test('app settings own the live theme, transcript backup, and layout controls', async () => {
  const [app, rackCss] = await Promise.all([
    source('App.tsx'),
    source('assets/rack.css'),
  ])

  assert.match(app, /data-testid="app-settings-toggle"[\s\S]*aria-expanded=\{appSettingsOpen\}/u)
  assert.match(app, /data-testid="app-settings-panel"[\s\S]*data-testid="theme-control"[\s\S]*setTheme/u)
  assert.match(app, /data-testid="app-settings-panel"[\s\S]*data-testid="transcript-backup-toggle"[\s\S]*changeTranscriptBackup/u)
  assert.match(app, /Back up transcripts to your Palace/u)
  assert.match(app, /data-testid="app-settings-panel"[\s\S]*data-testid="layout-save"[\s\S]*data-testid="layout-restore"[\s\S]*data-testid="layout-reset"/u)
  assert.doesNotMatch(app, /<div className="stage-toolbar"[\s\S]*data-testid="theme-control"/u)
  assert.match(rackCss, /\.app-settings-toggle\s*\{[^}]*left:\s*11\.75rem/su)
})

/** PLAN M2ST2 and Invariant 10 forbid dead or decorative controls: mutable scope binds the real action; fixed scope explains its absence. */
test('module settings expose only bound scope controls and remove dead Palace scope', async () => {
  const [app, rack, graph, consoleSource, context, vitals] = await Promise.all([
    source('App.tsx'),
    source('rack.tsx'),
    source('MemoryGraph.tsx'),
    source('InjectionConsole.tsx'),
    source('ContextBars.tsx'),
    source('VitalsModule.tsx'),
  ])

  assert.match(app, /includes\('rack\.scope\.set'\)/u)
  assert.match(app, /type:\s*'rack\.scope\.set'/u)
  assert.match(app, /This module always shows the whole Palace\./u)
  assert.match(app, /This module follows the nearest thread or stack\./u)
  assert.match(rack, /palace_queue:[\s\S]*actions:\s*\['queue\.load', 'queue\.decide', 'seed\.jump-start\.load', 'seed\.upload', 'queue\.batch\.decide'\]/u)
  for (const moduleSource of [graph, consoleSource, context, vitals]) {
    assert.doesNotMatch(moduleSource, /className="(?:scope-switch|scope-toggle)"/u)
  }
})

/** P2 and NATES_VISION section 18 reserve labels for facts that change an owner decision. */
test('internal implementation labels do not reach the owner surface', async () => {
  const files = await Promise.all([
    source('App.tsx'),
    source('MemoryPanel.tsx'),
    source('MemoryGraph.tsx'),
    source('InjectionConsole.tsx'),
    source('ModelDevice.tsx'),
  ])
  const joined = files.join('\n')

  for (const internalLabel of [
    'Current principal',
    'Authoritative state',
    'Active channel',
    'Local channels',
    'consent surface',
    'Corpus door',
    'MEMORY INSTRUMENT',
    'MEMORY TUNING',
    'Factory-set navigation',
    'Link live',
    '>Linked<',
    'Waiting for daemon',
    'Awaiting daemon',
    'Daemon memory',
    'Daemon uptime',
  ]) {
    assert.doesNotMatch(joined, new RegExp(internalLabel, 'u'))
  }
})
