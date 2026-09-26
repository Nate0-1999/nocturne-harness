import assert from 'node:assert/strict'
import test from 'node:test'
import { HAIR, buildChambers, buildRootTree, rootGap, rootWidth } from '../src/visualization.ts'

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

/** ADR-018 / F115 (M3VL send-back 2): a `.git` store is one chamber; the rest keep one chamber per folder,
 * never overlapping, and a large tree lays out in one pass. */
test('farm folds the git store and spaces every other folder without overlap', () => {
  const project = { root: '/work', nodes: [
    { path: '.', kind: 'directory', bytes: 0 }, { path: '.git', kind: 'directory', bytes: 0 },
    { path: '.git/objects', kind: 'directory', bytes: 0 }, { path: '.git/objects/ab', kind: 'directory', bytes: 0 },
    { path: '.git/objects/ab/cd', kind: 'file', bytes: 40 }, { path: '.git/HEAD', kind: 'file', bytes: 20 },
    ...Array.from({ length: 12 }, (_, i) => ({ path: `pkg${i}`, kind: 'directory', bytes: 0 })),
    ...Array.from({ length: 12 }, (_, i) => ({ path: `pkg${i}/mod`, kind: 'directory', bytes: 0 })),
  ] }
  const chambers = buildChambers(project)
  assert.deepEqual(chambers.filter((c) => c.path.startsWith('.git')).map((c) => [c.path, c.files.length]), [['.git', 2]])
  assert.equal(chambers.length, 1 + 1 + 24)
  for (const [i, a] of chambers.entries()) for (const b of chambers.slice(i + 1)) {
    assert.ok(Math.hypot(a.position[0] - b.position[0], a.position[1] - b.position[1]) > a.radius + b.radius, `${a.path} overlaps ${b.path}`)
  }
  const big = { root: '/big', nodes: [{ path: '.', kind: 'directory', bytes: 0 }, ...Array.from({ length: 3000 }, (_, i) => (
    { path: `d${i % 60}${i >= 60 ? `/e${i}` : ''}`, kind: 'directory', bytes: 0 })),
  ...Array.from({ length: 30000 }, (_, i) => ({ path: `d${i % 60}/f${i}`, kind: 'file', bytes: 10 }))] }
  const started = performance.now()
  assert.equal(buildChambers(big).length, 3001)
  assert.ok(performance.now() - started < 500)
})

const at = (seconds) => new Date(Date.parse('2026-09-16T00:00:00Z') + seconds * 1000).toISOString()
const thread = { id: 'thread', root: '/project', parent_id: null, state: 'waiting', started_at: at(0), updated_at: at(600), cost_usd: 0.3,
  turns: [at(1), at(300)], tool_calls: [at(2), at(3), at(60), at(301)],
  touched_files: [{ path: '/project/a.py', ts: at(3.5) }, { path: '/project/b.py', ts: at(302) }] }
const worker = { id: 'worker', root: '/project/.worktree', parent_id: 'thread', state: 'stopped', started_at: at(305), updated_at: at(400), cost_usd: 0.2,
  turns: [at(306), at(330)], tool_calls: [at(306)], touched_files: [] }
const trails = { thread: [{ ts: at(1), cost_usd: 0 }, { ts: at(200), cost_usd: 0.05 }, { ts: at(600), cost_usd: 0.3 }],
  worker: [{ ts: at(306), cost_usd: 0.01 }, { ts: at(400), cost_usd: 0.2 }] }
const build = (agents) => buildRootTree(agents, trails, Date.parse(at(0)))
/** How far `target` lies from the polyline `points`: 0 where a branch leaves it. */
const onto = (points, target) => Math.min(...points.slice(1).map((point, i) => {
  const a = points[i], d = point.map((value, axis) => value - a[axis]), span = d.reduce((sum, value) => sum + value * value, 0) || 1
  const u = Math.min(1, Math.max(0, d.reduce((sum, value, axis) => sum + value * (target[axis] - a[axis]), 0) / span))
  return Math.hypot(...target.map((value, axis) => value - (a[axis] + d[axis] * u)))
}))
const length = (points) => points.slice(1).reduce((sum, point, i) => sum + Math.hypot(...point.map((value, axis) => value - points[i][axis])), 0)
/** Distance along `points` to the point nearest `target`: where a child leaves its parent. */
const along = (points, target) => {
  const near = points.reduce((best, point, i) => Math.hypot(...point.map((v, a) => v - target[a])) < Math.hypot(...points[best].map((v, a) => v - target[a])) ? i : best, 0)
  return length(points.slice(0, near + 1))
}

/** ADR-018 / F115 (PLAN M3VL send-back 3): the same recorded data draws the same river, whatever order it arrives in;
 * an earlier replay keeps every tube it already had under the same identity. */
test('roots tree is a pure, stable function of the recorded data', () => {
  const tree = build([thread, worker])
  assert.deepEqual(tree, build([structuredClone(worker), structuredClone(thread)]))
  const earlier = buildRootTree([{ ...thread, turns: thread.turns.slice(0, 1), tool_calls: thread.tool_calls.slice(0, 3), touched_files: thread.touched_files.slice(0, 1) }],
    trails, Date.parse(at(0)))
  const keys = new Set(tree.tubes.map((tube) => tube.key))
  assert.ok(earlier.tubes.every((tube) => keys.has(tube.key)))
})

/** ADR-018 / F115 (PLAN M3VL send-back 3 review): a live river grows without snapping. A new event adds its own branch;
 * every branch already drawn keeps its place and course (sides, angles and kinks come from each branch's own seed; the
 * layout has one fixed scale), except the parent's stretch past its previous last event and the branch that waited for
 * the new one, whose window (and so dollars) the new event splits. */
test('roots keep every drawn branch in place when a later event arrives', () => {
  const before = build([thread, worker])
  const later = { ...worker, turns: [...worker.turns, at(350)], tool_calls: [...worker.tool_calls, at(351)] }
  const after = new Map(build([thread, later]).tubes.map((tube) => [tube.key, tube]))
  const growing = new Set(['worker', 'worker:turn:1'])
  for (const tube of before.tubes) {
    const now = after.get(tube.key)
    assert.ok(now, tube.key)
    const moved = Math.max(...tube.points.slice(0, Math.min(tube.points.length, now.points.length)).map((point, i) => Math.hypot(...point.map((value, axis) => value - now.points[i][axis]))))
    if (growing.has(tube.key)) assert.ok(Math.hypot(...tube.points[0].map((value, axis) => value - now.points[0][axis])) < 0.01, tube.key)
    else assert.ok(moved < 0.01, `${tube.key} moved ${moved}`)
  }
  // A trunk-level event (a later turn of the thread): the trunk up to the turn that waited for it, and every branch
  // before that turn, stay exactly where they were.
  const turned = new Map(build([{ ...thread, turns: [...thread.turns, at(500)], tool_calls: [...thread.tool_calls, at(501)] }, worker]).tubes.map((tube) => [tube.key, tube]))
  const waited = turned.get('thread:turn:1').points[0][0], earlier = ['thread:turn:0', 'thread:tool:0', 'thread:tool:1', 'thread:file:0', 'thread:tool:2']
  for (const tube of before.tubes) {
    const now = turned.get(tube.key), kept = tube.key.startsWith('trunk:') ? tube.points.filter((point) => point[0] < waited - 1) : earlier.includes(tube.key) ? tube.points : []
    assert.ok(now, tube.key)
    for (const [i, point] of kept.entries()) assert.ok(Math.hypot(...point.map((value, axis) => value - now.points[i][axis])) < 0.01, `${tube.key} moved at ${i}`)
  }
})

/** ADR-018 / F115 (PLAN M3VL send-back 3, spacing): one tube per real event, not a comb: every turn, tool call and file
 * touch is its own branch, a forked agent is its own limb, and a project's roots fuse into one trunk. */
test('roots draw one branch per recorded event and one limb per fork', () => {
  const tree = build([thread, worker])
  const count = (kind, agent) => tree.tubes.filter((tube) => tube.kind === kind && tube.agent === agent).length
  assert.deepEqual([count('turn', 'thread'), count('tool', 'thread'), count('file', 'thread')], [2, 4, 2])
  assert.deepEqual([count('turn', 'worker'), count('tool', 'worker'), count('root', 'worker')], [2, 1, 1])
  assert.equal(count('root', '/project'), 1)
  assert.deepEqual(tree.sources.map((source) => source.agent), ['thread'])
  // The fork leaves the parent's latest event before it started: the thread's tool call at 301 s.
  const limb = tree.tubes.find((tube) => tube.key === 'worker'), turn = tree.tubes.find((tube) => tube.key === 'thread:tool:3')
  assert.ok(turn.points.some((point) => Math.hypot(...point.map((value, axis) => value - limb.points[0][axis])) < 1e-6 + length(turn.points) / (turn.points.length - 1)))
  // A file touch sub-branches from the tool call before it.
  const call = tree.tubes.find((tube) => tube.key === 'thread:tool:1'), touch = tree.tubes.find((tube) => tube.key === 'thread:file:0')
  assert.ok(along(call.points, touch.points[0]) < length(call.points))
  assert.ok(Math.min(...call.points.map((point) => Math.hypot(...point.map((value, axis) => value - touch.points[0][axis])))) < length(call.points) / (call.points.length - 1))
})

/** ADR-018 / F115 (PLAN M3VL send-back 3, spacing): along a branch, events sit apart by the compressed time between them,
 * so a longer gap is always a longer bare stretch; a leaf reaches as long as the wait for the agent's next event. */
test('roots space events by the time between them', () => {
  for (const [short, long] of [[0, 1], [1000, 2000], [59000, 60000], [3.6e6, 7.2e6]]) assert.ok(rootGap(long) > rootGap(short))
  const tree = build([thread])
  const tube = (key) => tree.tubes.find((item) => item.key === key).points
  // Calls at 2 s, 3 s and 60 s: the call at 3 s, 1 s after the one at 2 s (a shorter wait than that call's own), nests
  // on it; the call at 60 s, after a 57 s wait, leaves the turn again, a longer stretch past the call at 2 s than the
  // 1 s stretch along it to the call at 3 s.
  assert.ok(onto(tube('thread:tool:0'), tube('thread:tool:1')[0]) < 1e-6)
  assert.ok(onto(tube('thread:turn:0'), tube('thread:tool:2')[0]) < 1e-6)
  const turn = tube('thread:turn:0'), [a, c] = [tube('thread:tool:0')[0], tube('thread:tool:2')[0]].map((start) => along(turn, start))
  assert.ok(c - a > 2 * along(tube('thread:tool:0'), tube('thread:tool:1')[0]))
  // The call at 60 s waits 240 s for the next event; the call at 2 s waits 1 s: its twig reaches further.
  const reach = (key) => length(tree.tubes.find((tube) => tube.key === key).points)
  assert.ok(reach('thread:tool:2') > reach('thread:tool:0'))
})

/** ADR-018 / F115 (PLAN M3VL send-back 3, form): tubes, never fins: every branch is round, widest where dollars flow,
 * thinning as its children take their share, to a fine tip; a turn is as wide as the spend recorded in its window. */
test('roots are tubes whose width is the dollars flowing through them', () => {
  const tree = build([thread, worker])
  for (const tube of tree.tubes) {
    assert.equal(tube.radii.length, tube.points.length)
    assert.ok(tube.radii.every((radius) => radius > 0))
    assert.ok(tube.radii.at(-1) < Math.max(...tube.radii))
  }
  // The trail records less spend in the first turn's window (to 300 s) than in the second's (300 s to the end).
  const base = (key) => Math.max(...tree.tubes.find((tube) => tube.key === key).radii)
  assert.ok(base('thread:turn:1') > base('thread:turn:0'))
  assert.ok(base('thread:turn:0') > base('thread:tool:0'))
  // The trunk thins where a turn takes its dollars away.
  const trunk = tree.tubes.find((tube) => tube.key === 'trunk:/project').radii
  assert.ok(trunk.at(-trunk.length / 4) < Math.max(...trunk))
  // Depth is time on the across scale, so a long wait never kinks the trunk in depth (it read as a ringed seam).
  const course = tree.tubes.find((tube) => tube.key === 'trunk:/project').points
  const sinks = course.slice(1).map((point, i) => (point[2] - course[i][2]) / (point[0] - course[i][0]))
  assert.ok(Math.max(...sinks) - Math.min(...sinks) < 0.01)
  // A forked limb thins as its turns take its dollars, to a hair at its tip, never an even pipe.
  const limb = tree.tubes.find((tube) => tube.key === 'worker').radii
  assert.ok(limb[Math.floor(0.9 * limb.length)] < Math.max(...limb) / 2 && limb.at(-1) < Math.max(...limb) / 5)
  // An unpriced agent keeps the stated finest width of each kind rather than guessed ones.
  const unpriced = buildRootTree([{ ...thread, cost_usd: null }], {}, Date.parse(at(0)))
  const turns = (river) => river.tubes.filter((tube) => tube.kind === 'turn').map((tube) => Math.max(...tube.radii))
  assert.ok(Math.max(...turns(unpriced)) < Math.min(...turns(build([thread]))))
  assert.ok(Math.max(...turns(unpriced)) <= 1.05 * HAIR.turn)
  // A branch's blush comes in as it leaves its parent's body, then fades and never rises again: no ring, band or bead.
  for (const tube of tree.tubes) {
    const peak = tube.pink.indexOf(Math.max(...tube.pink))
    assert.ok(tube.pink.every((pink, i) => i === 0 || (i <= peak ? pink >= tube.pink[i - 1] - 1e-9 : pink <= tube.pink[i - 1] + 1e-9)), tube.key)
  }
})

/** ADR-018 / F115 (PLAN M3VL send-back 3, width): width is dollars on one fixed scale (radius = hair + WIDTH·√$, so a
 * tube's cross-section grows with its dollars), never a share of the river's biggest spender: a big spender arriving
 * leaves every tube already drawn exactly as wide as it was. */
test('roots widths are an absolute function of the dollars flowing', () => {
  const before = build([thread, worker])
  const spender = { ...thread, id: 'spender', root: '/other', cost_usd: 40, turns: [], tool_calls: [], touched_files: [] }
  const after = new Map(buildRootTree([thread, worker, spender], { ...trails, spender: [{ ts: at(1), cost_usd: 0 }, { ts: at(600), cost_usd: 40 }] },
    Date.parse(at(0))).tubes.map((tube) => [tube.key, tube]))
  for (const tube of before.tubes) assert.deepEqual(after.get(tube.key).radii, tube.radii, tube.key)
  // A root carrying all its dollars is exactly the law's width, and four times the dollars is twice the width above its hair.
  const widest = (cost) => Math.max(...buildRootTree([{ ...spender, cost_usd: cost, updated_at: at(36000) }], {}, Date.parse(at(0))).tubes[0].radii)
  for (const cost of [0.01, 0.3, 40]) assert.ok(Math.abs(widest(cost) / rootWidth('root', cost) - 1) < 1e-4, `${cost}`)
  assert.ok(Math.abs((widest(1.2) - HAIR.root) / (widest(0.3) - HAIR.root) - 2) < 1e-4)
})

/** ADR-018 / F115 (M3VL send-back 3 polish, width): the drawn width is the law's everywhere but four named stretches,
 * never a seeded taper or a cap: the junction flare (three of its diameters past the parent's body), a root's swell from
 * its hair (at most 10 units), a leaf too short for its dollars (never thicker than a twelfth of its length) and the
 * tip, which closes to a point over eight diameters. Over 20–80% of every priced tube
 * the radius is rootWidth of the dollars flowing there (±10%); those dollars are the spend recorded in each branch's
 * window (worked by hand from the trail below), and a branch's dollars are what it keeps plus what its children carry. */
test('roots draw every priced tube at the width of the dollars flowing through it', () => {
  const tree = build([thread, worker])
  // A trunk is a root's width; a forked limb thins to a turn's hair.
  const kindOf = (tube) => tube.kind === 'root' ? (tube.key.startsWith('trunk:') ? 'root' : 'turn') : tube.kind
  const priced = tree.tubes.filter((tube) => tube.dollars[0] > 0.0005)
  assert.ok(priced.length >= 10)
  let checked = 0
  for (const tube of priced) {
    const walked = tube.points.map((_, i) => length(tube.points.slice(0, i + 1))), total = walked.at(-1)
    const leaving = Math.max(...tube.radii.slice(0, Math.ceil(0.25 * tube.points.length)))
    for (let i = Math.floor(0.2 * tube.points.length); i <= Math.floor(0.8 * tube.points.length); i++) {
      const law = rootWidth(kindOf(tube), tube.dollars[i])
      if (walked[i] < (tube.kind === 'root' ? 10 : 6 * leaving + 1) || total - walked[i] < 16 * law || law > total / 24) continue
      checked++
      assert.ok(Math.abs(tube.radii[i] / law - 1) <= 0.1, `${tube.key} at ${i}: ${tube.radii[i]} drawn, ${law} by the law`)
    }
  }
  assert.ok(checked > 100, `${checked} points checked`)
  // The worker's trail: $0.01 by 306 s, $0.20 by 400 s. Its turns carry the spend recorded in their windows (306–330 s,
  // 330–400 s), and its root keeps what was spent before its first turn.
  const spend = (seconds) => seconds <= 306 ? 0.01 : 0.01 + 0.19 * (seconds - 306) / 94, base = (key) => tree.tubes.find((tube) => tube.key === key).dollars[0]
  assert.ok(Math.abs(base('worker:turn:0') - (spend(330) - spend(306))) < 1e-9)
  assert.ok(Math.abs(base('worker:turn:1') - (spend(400) - spend(330))) < 1e-9)
  assert.ok(Math.abs(base('worker') - (0.01 + base('worker:turn:0') + base('worker:turn:1'))) < 1e-9)
  // The turn's own calls: the call at 3 s nests on the one at 2 s, so the turn carries two.
  const turn = tree.tubes.find((tube) => tube.key === 'thread:turn:0'), calls = [0, 2].map((i) => tree.tubes.find((tube) => tube.key === `thread:tool:${i}`))
  const area = (kind, dollars) => (rootWidth(kind, dollars) - HAIR[kind]) ** 2
  const lost = area('turn', turn.dollars[0]) - area('turn', turn.dollars.at(-1)), carried = calls.reduce((sum, call) => sum + area('tool', call.dollars[0]), 0)
  // What it keeps is the spend recorded before its first call, a sliver here.
  assert.ok(carried <= lost * (1 + 1e-9) && carried >= 0.9 * lost, `${carried} carried of ${lost}`)
})

/** ADR-018 / F115 (M3VL send-back 3 polish r3, binding): a root's dollars are drawn once through its merge. Until its
 * body comes within reach of the trunk's it carries them all; then they move into the trunk as it moves onto the
 * trunk's centreline, so at every point the approach and the trunk together carry exactly both roots' dollars. */
test('roots conserve dollars where a root fuses into the trunk', () => {
  const first = { ...thread, id: 'first', cost_usd: 0.3, turns: [], tool_calls: [], touched_files: [], updated_at: at(36000) }
  const second = { ...first, id: 'second', cost_usd: 0.12, started_at: at(60) }
  const tree = buildRootTree([first, second], {}, Date.parse(at(0)))
  const trunk = tree.tubes.find((tube) => tube.key === 'trunk:/project'), approach = tree.tubes.find((tube) => tube.key === 'second')
  // Both are sampled on one grid from the river's left edge.
  assert.deepEqual(approach.points.map((point) => point[0]), trunk.points.slice(0, approach.points.length).map((point) => point[0]))
  // Neither has recorded spend before it stops, so each carries its whole price until then (the river's last moment).
  const started = approach.dollars.findIndex((dollars) => dollars > 0), last = rootGap(60e3) + rootGap(35940e3)
  assert.ok(started > 0)
  for (const [k, dollars] of approach.dollars.entries()) {
    if (approach.points[k][0] >= last) continue
    assert.ok(Math.abs(dollars + trunk.dollars[k] - (k < started ? 0.3 : 0.42)) < 1e-9, `at ${k}: ${dollars} + ${trunk.dollars[k]}`)
  }
  // It hands over, and ends as a hair on the trunk's centreline.
  assert.ok(approach.dollars[started] > 0.119 && approach.dollars.at(-1) < 1e-9)
  assert.ok(Math.abs(approach.points.at(-1)[1] - trunk.points[approach.points.length - 1][1]) < 1e-6)
})

/** ADR-018 / F115 (M3VL send-back 3 polish r3, binding): a parent's own spend is its trail less what the trail itself
 * rolled up of each returned fork, however much less than the fork's price that was, so its later spend still shows. */
test('roots read a fork roll-up from the parent trail and keep its later spend', () => {
  const parent = { ...thread, id: 'parent', cost_usd: 0.06, turns: [at(10), at(100)], tool_calls: [], touched_files: [], updated_at: at(150) }
  const fork = { ...worker, id: 'fork', parent_id: 'parent', cost_usd: 0.05, started_at: at(20), updated_at: at(60), turns: [], tool_calls: [] }
  // The fork cost $0.05 but its return rolled up only $0.03 at 65 s; the parent then spent $0.02 more.
  const trail = [[0, 0], [15, 0.01], [59, 0.01], [65, 0.04], [99, 0.04], [150, 0.06]].map(([seconds, cost]) => ({ ts: at(seconds), cost_usd: cost }))
  const tree = buildRootTree([parent, fork], { parent: trail }, Date.parse(at(0)))
  const dollars = (key) => tree.tubes.find((tube) => tube.key === key).dollars
  // Its last turn (100 s to the end) carries that spend: $0.02 recorded between 99 s and 150 s, 50 s of 51 in its window.
  assert.ok(Math.abs(dollars('parent:turn:1')[0] - 0.02 * 50 / 51) < 1e-9)
  // Drawn at its own spend plus its fork's price: more than its price, since the roll-up fell short.
  assert.ok(Math.abs(Math.max(...dollars('trunk:/project')) - 0.08) < 1e-9)
})

/** ADR-018 / F115 (M3VL send-back 3 polish r3, spacing): a leaf's reach is its wait alone, no seed: of any two leaves
 * on one branch, the one whose wait is at least twice the other's always reaches further. */
test('roots draw a longer wait as a longer leaf', () => {
  const waits = [1, 1.5, 3, 7, 20, 60, 400, 3600, 7200]
  const times = waits.reduce((list, wait) => [...list, list.at(-1) + wait], [2])
  const leafy = { ...thread, cost_usd: null, turns: [at(1)], tool_calls: times.slice(0, -1).map(at), touched_files: [], updated_at: at(times.at(-1)) }
  const tree = buildRootTree([leafy], {}, Date.parse(at(0)))
  const reach = waits.map((_, i) => length(tree.tubes.find((tube) => tube.key === `thread:tool:${i}`).points))
  for (const [i, a] of waits.entries()) for (const [j, b] of waits.entries()) if (b >= 2 * a) assert.ok(reach[j] > reach[i], `${b} s against ${a} s`)
})

/** ADR-018 / F115 (M3VL send-back 3 polish r3, form): a limb's last child takes its dollars over at least two
 * diameters and the limb runs on past it, so it thins to its hair before its tip closes: never a club. */
test('roots thin every limb to its hair before its tip', () => {
  const limb = { ...worker, turns: [at(306), at(330), at(395)], tool_calls: [], updated_at: at(400) }
  for (const tube of build([thread, limb]).tubes.filter((item) => item.kind === 'root' && !item.key.startsWith('trunk:'))) {
    const walked = tube.points.map((_, i) => length(tube.points.slice(0, i + 1)))
    assert.ok(tube.radii[walked.findIndex((value) => value >= 0.95 * walked.at(-1))] <= 1.5 * HAIR.turn, tube.key)
  }
})

/** Distance along `points` to where `target` lies on it (its exact projection onto the nearest segment). */
const exactly = (points, target) => {
  let best = Infinity, found = 0, walked = 0
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], d = points[i].map((value, axis) => value - a[axis]), span = Math.hypot(...d)
    const u = Math.min(1, Math.max(0, d.reduce((sum, value, axis) => sum + value * (target[axis] - a[axis]), 0) / (span * span || 1)))
    const miss = Math.hypot(...target.map((value, axis) => value - (a[axis] + d[axis] * u)))
    if (miss < best) { best = miss; found = walked + u * span }
    walked += span
  }
  return found
}

/** ADR-018 / F115 (PLAN M3VL send-back 3, spacing proof): each turn leaves the latest earlier turn that followed a
 * longer wait than its own (a burst nests; the first, and every turn after a longer wait, leaves the root), and along
 * every body, every consecutive pair of gaps between the turns leaving it draws in the same order: a longer gap is
 * always a longer bare stretch (across = ln(1 + gap / 0.5 s)^1.2). */
test('roots draw every longer gap between events as a longer bare stretch', () => {
  const gaps = [0.5, 2, 3, 1, 2, 4, 5, 60, 30, 90, 100, 20, 600, 0.5, 120, 3, 3.5, 900, 10, 11, 0.2]
  const times = gaps.reduce((list, gap) => [...list, list.at(-1) + gap], [306])
  // Worked by hand from the waits (the root started 1 s before the first turn): null is the root.
  const parents = [null, 0, null, null, 3, 3, null, null, null, 8, null, null, 11, null, 13, 13, 15, 15, null, 18, 18, 20]
  const walk = (tubes, root, key) => {
    const find = (name) => tubes.find((tube) => tube.key === name).points
    let pairs = 0
    for (const parent of [null, ...times.keys()]) {
      const body = find(parent === null ? root : key(parent)), kids = times.flatMap((_, i) => parents[i] === parent ? [i] : [])
      for (const i of kids) assert.ok(onto(body, find(key(i))[0]) < 0.01, `turn ${i} leaves ${parent}`)
      const places = kids.map((i) => exactly(body, find(key(i))[0]))
      for (let j = 2; j < kids.length; j++) {
        const [before, after] = [times[kids[j - 1]] - times[kids[j - 2]], times[kids[j]] - times[kids[j - 1]]]
        const [drawn, next] = [places[j - 1] - places[j - 2], places[j] - places[j - 1]]
        assert.ok(drawn > 0 && next > 0, `turn ${kids[j]} draws no stretch`)
        assert.equal(Math.sign(next - drawn), Math.sign(after - before), `gaps ${before} s, ${after} s`)
        pairs++
      }
    }
    return pairs
  }
  // A priced forked limb: its turns leave along its own length, or nest.
  const limb = { ...worker, turns: times.map(at), tool_calls: [], touched_files: [], updated_at: at(times.at(-1) + 60) }
  assert.ok(walk(build([thread, limb]).tubes, 'worker', (i) => `worker:turn:${i}`) >= 8)
  // The trunk: a thread's turns leave it at their moments, across.
  const lone = { ...thread, started_at: at(305), turns: times.map(at), tool_calls: [], touched_files: [], cost_usd: null, updated_at: at(times.at(-1) + 60) }
  assert.ok(walk(buildRootTree([lone], {}, Date.parse(at(0))).tubes, 'trunk:/project', (i) => `thread:turn:${i}`) >= 8)
})
