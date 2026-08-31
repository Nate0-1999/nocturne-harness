import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  buildNebulaBodies,
  buildNebulaCreatureFamilies,
  buildNebulaEvents,
  buildNebulaFilaments,
  NEBULA_BINDINGS,
} from '../src/nebulaBindings.ts'

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
  assert.ok(first[0].recency_glow > first[1].recency_glow, 'recent updates glow brighter at the frozen snapshot')
  assert.equal(first[1].pinned, true)
})

/** ADR-018: M3GE requires the owner axis switch to rebind actual data, not rename a fixed layout. */
test('activity and provenance modes produce different named data transforms', () => {
  const activity = buildNebulaBodies(snapshot, 'activity', Date.parse('2026-08-21T20:00:00Z'))
  const provenance = buildNebulaBodies(snapshot, 'provenance', Date.parse('2026-08-21T20:00:00Z'))
  assert.notDeepEqual(activity.map((body) => body.position), provenance.map((body) => body.position))
  assert.deepEqual(NEBULA_BINDINGS.activity, [
    'X · memory.created_at (chronological rank)',
    'Y · memory.stats.injections (log scale)',
    'Z · memory.revision (linear scale)',
  ])
  assert.equal(NEBULA_BINDINGS.shared.length, 7)
})

/** SPEC D.2 146 and PLAN M3SL make the torrent a pure one-mark-per-revision projection. */
test('memory current emits only real revision events and replays byte-identically', () => {
  const source = {
    ...snapshot,
    nodes: [
      node('a', { status: 'tombstoned' }, [
        revision('ra1', null, 1, '2026-08-01T00:00:00Z', 'remember/create'),
        revision('ra2', 'ra1', 2, '2026-08-02T00:00:00Z', 'curator/retired'),
      ]),
      node('b', {}, [
        revision('rb1', null, 1, '2026-08-01T12:00:00Z', 'remember/create'),
        revision('rb2', 'rb1', 2, '2026-08-03T00:00:00Z', 'curator/merge-with-lineage'),
        revision('rb3', 'rb2', 3, '2026-08-04T00:00:00Z', 'remember/split-child'),
        revision('rb4', 'rb3', 4, '2026-08-05T00:00:00Z', 'owner/edit'),
      ]),
    ],
  }
  const first = buildNebulaEvents(source)
  const replay = buildNebulaEvents(structuredClone(source))
  assert.deepEqual(first, replay)
  assert.equal(first.length, source.nodes.flatMap((item) => item.revisions).length)
  assert.deepEqual(first.map((event) => event.event_class), [
    'add', 'add', 'delete', 'merge', 'split', 'modify',
  ])
  assert.deepEqual(buildNebulaEvents({ as_of: source.as_of, nodes: [], edges: [] }), [])
})

/** ADR-018 and PLAN M3SL bind constellation filaments and creature stipple to graph truth. */
test('real graph edges alone create filaments and duplicate-family creatures', () => {
  const source = {
    ...snapshot,
    nodes: [node('a'), node('b'), node('c')],
    edges: [
      { kind: 'similarity', from_memory_id: 'a', to_memory_id: 'b', similarity: '0.91' },
      { kind: 'lineage', from_memory_id: 'b', to_memory_id: 'c', edge_type: 'merged_from' },
      { kind: 'edit_trail', from_memory_id: 'a', to_memory_id: 'a', revision_count: 2 },
    ],
  }
  const bodies = buildNebulaBodies(source, 'activity')
  const events = buildNebulaEvents(source)
  const filaments = buildNebulaFilaments(source, bodies)
  const families = buildNebulaCreatureFamilies(source, bodies, events)
  assert.deepEqual(filaments.map((item) => item.kind), ['similarity', 'lineage'])
  assert.deepEqual(families.map((item) => item.memory_ids), [['a', 'b']])
  assert.equal(families[0].stipple_count, 96)
  assert.deepEqual(buildNebulaCreatureFamilies({ ...source, edges: [] }, bodies, events), [])
})

/** ADR-018: M3SL keeps absorbed duplicate history visible without reviving tombstoned memories as bodies. */
test('historical similarity families anchor to their latest real events', () => {
  const absorbed = node('absorbed', { status: 'tombstoned' }, [revision('absorbed-1', null, 1, '2026-08-01T00:00:00Z', 'add')])
  const survivor = node('survivor', {}, [revision('survivor-1', null, 1, '2026-08-02T00:00:00Z', 'merge duplicate family')])
  const source = {
    as_of: snapshot.as_of,
    nodes: [absorbed, survivor],
    edges: [{ kind: 'similarity', from_memory_id: 'absorbed', to_memory_id: 'survivor', similarity: '0.93' }],
  }
  const bodies = buildNebulaBodies(source, 'activity')
  const events = buildNebulaEvents(source)
  const families = buildNebulaCreatureFamilies(source, bodies, events)

  assert.deepEqual(bodies.map((body) => body.id), ['survivor'])
  assert.deepEqual(families.map((family) => family.memory_ids), [['absorbed', 'survivor']])
  assert.equal(families[0].merge_events, 1)
})

/** SPEC C.4: the visual projection must bind the released thread_origin compatibility field. */
test('provenance binds the released Palace thread_origin compatibility field', () => {
  const legacy = node('legacy', { thread_origin: 'released-thread', origin_thread_id: undefined })
  const absent = node('absent')
  const bodies = buildNebulaBodies({ as_of: snapshot.as_of, nodes: [legacy, absent] }, 'provenance')
  assert.notEqual(bodies[0].position[1], bodies[1].position[1])
})

/** ADR-018/023 and D.2 130: Three/r3f/TSL replace PlayCanvas without moving text into the scene. */
test('production source uses the ruled Three stack and forbids random geometry', async () => {
  const [component, bindings, packageText] = await Promise.all([
    readFile(new URL('src/PalaceNebula.tsx', webRoot), 'utf8'),
    readFile(new URL('src/nebulaBindings.ts', webRoot), 'utf8'),
    readFile(new URL('package.json', webRoot), 'utf8'),
  ])
  const dependencies = JSON.parse(packageText).dependencies
  assert.match(component, /className="palace-nebula__legend"/u)
  assert.match(component, /query\.query\(\{ resource: 'memory_graph', as_of: 'now', thread_id: threadId \}\)/u)
  assert.match(component, /<Canvas/u)
  assert.match(component, /new WebGPURenderer\(parameters\)/u)
  assert.match(component, /new MeshStandardNodeMaterial/u)
  assert.match(component, /tslColor/u)
  assert.match(component, /useFrame/u)
  assert.match(component, /name="memory-event-current"/u)
  assert.match(component, /<instancedMesh/u)
  assert.match(component, /<octahedronGeometry/u)
  assert.match(component, /name="memory-relationships"/u)
  assert.match(component, /data-grammar="torrent-constellation"/u)
  assert.doesNotMatch(component, /clock\.elapsedTime|motion_hz|motion_amplitude/u)
  assert.doesNotMatch(bindings, /Date\.now/u)
  assert.equal(dependencies.three, '0.182.0')
  assert.equal(dependencies['@react-three/fiber'], '9.7.0')
  assert.equal(dependencies.playcanvas, undefined)
  assert.doesNotMatch(component, /playcanvas|PlayCanvas/u)
  assert.doesNotMatch(`${component}\n${bindings}`, /Math\.random/u)
})

function node(id, overrides = {}, revisions = []) {
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
    revisions,
  }
}

function revision(rev_uid, parent_uid, number, ts, reason) {
  return { rev_uid, parent_uid, revision: number, ts, reason }
}
