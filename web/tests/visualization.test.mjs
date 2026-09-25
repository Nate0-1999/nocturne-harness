import assert from 'node:assert/strict'
import test from 'node:test'
import { buildChambers, buildRootPaths, buildRootRiver, rootCurve, rootSpendShares, rootWorkPosition, rootWorkTimes } from '../src/visualization.ts'

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

/** ADR-018 / FL-129: idle gaps cannot hide recorded capillaries; depth still carries elapsed time. */
test('file chronology spreads work across a root without compressing temporal depth', () => {
  const agent = { id: 'worker', started_at: '2026-09-16T00:00:00Z', updated_at: '2026-09-16T01:00:00Z',
    touched_files: [{ path: '/a', ts: '2026-09-16T00:00:01Z' }, { path: '/b', ts: '2026-09-16T00:00:02Z' }] }
  const moments = rootWorkTimes([agent]), begin = Date.parse(agent.started_at), end = Date.parse(agent.updated_at)
  assert.equal(rootWorkPosition(Date.parse(agent.touched_files[0].ts), moments), 1 / 3)
  assert.equal(rootWorkPosition(Date.parse(agent.touched_files[1].ts), moments), 2 / 3)
  const points = rootCurve(agent, [], 0, begin, end, moments)
  assert.ok(Math.abs(points[0][2]) < 1e-10)
  assert.equal(points.at(-1)[2], -3)
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

/** ADR-018 / F115 (PLAN M3VL send-back 1): a root branches at each recorded turn and tool call; file touches grow from those. */
test('root river grows one branch per turn, tool call and file touch from its recorded parent', () => {
  const agent = { id: 'worker', root: '/project', parent_id: null, started_at: '2026-09-16T00:00:00Z', updated_at: '2026-09-16T00:04:00Z',
    turns: ['2026-09-16T00:01:00Z', '2026-09-16T00:03:00Z'], tool_calls: ['2026-09-16T00:01:00Z', '2026-09-16T00:03:00Z'],
    touched_files: [{ path: '/a', ts: '2026-09-16T00:01:30Z' }, { path: '/b', ts: '2026-09-16T00:03:30Z' }] }
  const begin = Date.parse(agent.started_at), end = Date.parse(agent.updated_at), moments = rootWorkTimes([agent])
  const root = buildRootPaths([agent], {}, begin, end).get(agent.id)
  const river = buildRootRiver(agent, root, moments, begin, end)
  assert.deepEqual(river, buildRootRiver(structuredClone(agent), structuredClone(root), moments, begin, end))
  assert.deepEqual(river.map((branch) => [branch.kind, branch.parent]), [['turn', -1], ['turn', -1], ['tool', 0], ['tool', 1], ['file', 2], ['file', 3]])
  // A turn joins the root where the root is at that turn's work-order moment.
  assert.ok(Math.abs(river[1].points[0][0] - (-9 + rootWorkPosition(Date.parse(agent.turns[1]), moments) * 18)) < 1e-9)
  for (const branch of river.filter((item) => item.parent >= 0)) {
    const parent = river[branch.parent].points
    assert.ok(parent.some((point, index) => index > 0 && Math.hypot(...branch.points[0].map((value, axis) => value - (parent[index - 1][axis] + point[axis]) / 2)) <= Math.hypot(...point.map((value, axis) => value - parent[index - 1][axis]))))
  }
  assert.deepEqual(buildRootRiver({ ...agent, turns: [], tool_calls: [], touched_files: [] }, root, moments, begin, end), [])
})

/** ADR-018 / F115 (PLAN M3VL): root width follows recorded spend so far; unpriced roots keep one width. */
test('root spend shares rise with the recorded cost trail', () => {
  const agent = { id: 'worker', cost_usd: 0.4, started_at: '2026-09-16T00:00:00Z', updated_at: '2026-09-16T00:02:00Z' }
  const trail = [{ ts: '2026-09-16T00:00:00Z', cost_usd: null }, { ts: '2026-09-16T00:01:00Z', cost_usd: '0.1' }, { ts: '2026-09-16T00:02:00Z', cost_usd: '0.4' }]
  const moments = rootWorkTimes([{ ...agent, turns: ['2026-09-16T00:01:00Z'] }])
  const shares = rootSpendShares(agent, trail, [[-9, 0, 0], [0, 0, 0], [9, 0, 0]], moments)
  assert.deepEqual(shares, [0, 0.25, 1])
  assert.deepEqual(rootSpendShares({ ...agent, cost_usd: null }, trail, [[-9, 0, 0]], moments), [1])
})
