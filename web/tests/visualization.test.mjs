import assert from 'node:assert/strict'
import test from 'node:test'
import { buildChambers, buildRootPaths, rootCurve } from '../src/visualization.ts'

/** ADR-018 / FL-126: a frozen tree has repeatable geometry, including empty chambers. */
test('directory layout preserves every chamber and cell and replays identically', () => {
  const project = { root: '/work', nodes: [
    { path: '.', kind: 'directory', bytes: 0 },
    { path: 'src', kind: 'directory', bytes: 0 },
    { path: 'empty', kind: 'directory', bytes: 0 },
    { path: 'src/a.py', kind: 'file', bytes: 4 },
    { path: '.hidden', kind: 'file', bytes: 8 },
  ] }
  const before = buildChambers(project)
  assert.deepEqual(before, buildChambers(structuredClone(project)))
  assert.equal(before.length, 3)
  assert.equal(before.flatMap(c => c.files).length, 2)
  assert.equal(before.find(c => c.path === 'empty').files.length, 0)
  const after = buildChambers({ ...project, nodes: [...project.nodes, { path: 'src/b.py', kind: 'file', bytes: 9 }] })
  assert.deepEqual(before.map(c => c.position), after.map(c => c.position))
  assert.ok(after.find(c => c.path === 'src').radius > before.find(c => c.path === 'src').radius)
  assert.equal(after.find(c => c.path === '.').radius, before.find(c => c.path === '.').radius)
})

/** ADR-018 / FL-129/134: replay uses observed time; an elapsed run grows in temporal depth. */
test('roots grow only to their recorded end and preserve identity on replay', () => {
  const agent = { id: 'worker', started_at: '2026-09-16T00:00:00Z', updated_at: '2026-09-16T00:01:00Z' }
  const begin = Date.parse(agent.started_at), end = begin + 120000
  const short = rootCurve(agent, [], 0, begin, end)
  assert.deepEqual(short, rootCurve(agent, [], 0, begin, end))
  const long = rootCurve({ ...agent, updated_at: '2026-09-16T00:02:00Z' }, [], 0, begin, end)
  assert.ok(long.at(-1)[2] < short.at(-1)[2])
  assert.deepEqual(long[0], short[0])
})

/** ADR-018 / PLAN M3VL: nested forks attach to their actual parent's joined curve. */
test('project trunks preserve true child and grandchild junctions regardless of input order', () => {
  const parent = { id: 'parent', root: '/project', parent_id: null, started_at: '2026-09-16T00:00:00Z', updated_at: '2026-09-16T00:03:00Z' }
  const child = { ...parent, id: 'child', root: '/attempt', parent_id: 'parent', started_at: '2026-09-16T00:01:00Z' }
  const grandchild = { ...child, id: 'grandchild', parent_id: 'child', started_at: '2026-09-16T00:02:00Z' }
  const agents = [grandchild, parent, child], begin = Date.parse(parent.started_at), end = Date.parse(parent.updated_at)
  const paths = buildRootPaths(agents, {}, begin, end)
  const replay = buildRootPaths([...agents].reverse(), {}, begin, end)
  for (const agent of agents) assert.deepEqual(paths.get(agent.id), replay.get(agent.id))
  for (const agent of [child, grandchild]) assert.ok(paths.get(agent.parent_id).some(point => JSON.stringify(point) === JSON.stringify(paths.get(agent.id)[0])))
  const independent = { ...child, id: 'other-project', parent_id: null }
  const separate = buildRootPaths([parent, independent], {}, begin, end)
  assert.ok(Math.abs(separate.get(parent.id).at(-1)[1] - separate.get(independent.id).at(-1)[1]) > 3)
})
