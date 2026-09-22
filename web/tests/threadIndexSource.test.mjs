import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const protocol = readFileSync(new URL('../src/protocol.ts', import.meta.url), 'utf8')
// M3UI: the gate's feature display is the spider web in FeatureRadar.tsx.
const gate = readFileSync(new URL('../src/FeatureRadar.tsx', import.meta.url), 'utf8')
const contributions = readFileSync(
  new URL('../src/ContributionBars.tsx', import.meta.url),
  'utf8',
)

/** A-060 carries exact thread locality through the wire and its contribution display. */
test('thread locality is exact at the wire and visible after project provenance', () => {
  assert.match(protocol, /origin_thread_id: string \| null/)
  assert.match(protocol, /thread: number \| null/)
  assert.match(
    protocol,
    /'sem', 'kw', 'time', 'proj', 'freq', 'hist', 'loc', 'thread'/,
  )

  const project = gate.indexOf("{ key: 'proj', label: 'Project' }")
  const thread = gate.indexOf("{ key: 'thread', label: 'Thread' }")
  const location = gate.indexOf("{ key: 'loc', label: 'Location' }")
  assert.ok(project >= 0 && project < thread && thread < location)
  assert.match(contributions, /'proj', 'thread', 'loc'/)
})
