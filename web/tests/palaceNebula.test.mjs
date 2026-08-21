import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { buildNebulaBodies, NEBULA_BINDINGS } from '../src/nebulaBindings.ts'

const webRoot = new URL('../', import.meta.url)

const snapshot = {
  as_of: '2026-08-21T20:00:00Z',
  nodes: [
    node('a', { kind: 'episodic', revision: 1, injections: 0, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-08-20T00:00:00Z', project_key: 'garden', origin_thread_id: 'thread-a', origin_path: '/garden/one' }),
    node('b', { kind: 'semantic', revision: 5, injections: 12, created_at: '2026-08-01T00:00:00Z', updated_at: '2026-02-01T00:00:00Z', project_key: 'spine', origin_thread_id: 'thread-b', origin_path: '/spine/two/deep', pin: true }),
    node('gone', { status: 'tombstoned', injections: 99 }),
  ],
}

/** SPEC D.2 124: every active memory is one body; inactive rows are not decoration. */
test('nebula creates exactly one deterministic body per active memory', () => {
  const first = buildNebulaBodies(snapshot, 'activity', Date.parse('2026-08-21T20:00:00Z'))
  const second = buildNebulaBodies(snapshot, 'activity', Date.parse('2026-08-21T20:00:00Z'))
  assert.deepEqual(first, second)
  assert.deepEqual(first.map((body) => body.id), ['a', 'b'])
  assert.ok(first[1].scale[0] > first[0].scale[0], 'injections enlarge the body')
  assert.ok(first[1].scale[1] / first[1].scale[0] > first[0].scale[1] / first[0].scale[0], 'revision stretches shape')
  assert.ok(first[0].motion_hz > first[1].motion_hz, 'recent updates move faster')
  assert.equal(first[1].pinned, true)
})

/** M3GE requires the owner axis switch to rebind actual data, not rename a fixed layout. */
test('activity and provenance modes produce different named data transforms', () => {
  const activity = buildNebulaBodies(snapshot, 'activity', Date.parse('2026-08-21T20:00:00Z'))
  const provenance = buildNebulaBodies(snapshot, 'provenance', Date.parse('2026-08-21T20:00:00Z'))
  assert.notDeepEqual(activity.map((body) => body.position), provenance.map((body) => body.position))
  assert.deepEqual(NEBULA_BINDINGS.activity, [
    'X · memory.created_at (chronological rank)',
    'Y · memory.stats.injections (log scale)',
    'Z · memory.revision (linear scale)',
  ])
  assert.equal(NEBULA_BINDINGS.shared.length, 6)
})

test('provenance binds the released Palace thread_origin compatibility field', () => {
  const legacy = node('legacy', { thread_origin: 'released-thread', origin_thread_id: undefined })
  const absent = node('absent')
  const bodies = buildNebulaBodies({ as_of: snapshot.as_of, nodes: [legacy, absent] }, 'provenance')
  assert.notEqual(bodies[0].position[1], bodies[1].position[1])
})

/** ADR-018/023: text stays in React DOM and the engine has no random decorative variables. */
test('production source keeps the legend in DOM and forbids random geometry', async () => {
  const [component, bindings] = await Promise.all([
    readFile(new URL('src/PalaceNebula.tsx', webRoot), 'utf8'),
    readFile(new URL('src/nebulaBindings.ts', webRoot), 'utf8'),
  ])
  assert.match(component, /className="palace-nebula__legend"/u)
  assert.match(component, /query\.query\(\{ resource: 'memory_graph', as_of: 'now' \}\)/u)
  assert.match(component, /new Application\(canvas/u)
  assert.doesNotMatch(`${component}\n${bindings}`, /Math\.random/u)
})

function node(id, overrides = {}) {
  const { injections = 1, ...memoryOverrides } = overrides
  return {
    memory: {
      memory_id: id,
      label: `Memory ${id}`,
      kind: 'semantic',
      status: 'active',
      pin: false,
      revision: 1,
      project_key: null,
      origin_thread_id: null,
      origin_path: null,
      created_at: null,
      updated_at: null,
      stats: { injections },
      ...memoryOverrides,
    },
    in_current_context: false,
    revisions: [],
  }
}
