import type { PalaceNebulaSnapshot } from './nebulaBindings'

export type DetailTier = 'full' | 'efficient'
export type Point3 = [number, number, number]
export interface WorkAgent {
  id: string; thread_id: string; parent_id: string | null; label: string
  root: string; location: string; state: string; started_at: string; updated_at: string
  waiting_since: string | null; cost_usd: number | string | null
  touched_files?: { path: string; ts: string }[]; turns?: string[]; tool_calls?: string[]
}
export interface DirectoryEntry { path: string; kind: 'directory' | 'file' | 'link'; bytes: number }
export interface WorkProject { root: string; nodes: DirectoryEntry[]; errors: { path: string; error: string }[] }
export interface RootPoint { ts: string; location: string; cost_usd: number | string | null; state: string }
export interface CuratorProgressEvent {
  event_id: number; run_uid: string; phase: string; memory_ids: string[]
  finding_uid: string | null; action: string | null; ts: string
}
export interface VisualizationSnapshot {
  as_of: string; live: boolean; recorded_since: string; timeline: string[]
  projects: WorkProject[]; agents: WorkAgent[]; trails: Record<string, RootPoint[]>
  palace: PalaceNebulaSnapshot | null
  curation: { latest_run: Record<string, unknown> | null } | null
  progress?: { events: CuratorProgressEvent[]; cursor: number } | null
  errors: { feed: string; error: string }[]
}

// ADR-018: stable identity determines the geometry and fleet color, never wall-clock randomness.
export function identitySeed(id: string): number {
  let value = 2166136261
  for (const char of id) value = Math.imul(value ^ char.charCodeAt(0), 16777619)
  return (value >>> 0) / 4294967296
}
export function agentColor(id: string): string {
  return ['#89dbef', '#e8b29f', '#bec6fc', '#94dfbf', '#efcadf', '#d6df96'][Math.floor(identitySeed(id) * 6)]
}
export function parentPath(path: string): string {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '.'
}
export interface Chamber {
  path: string; position: Point3; radius: number; parent: string | null; files: DirectoryEntry[]; beneath: number
}

/** The folder a chamber stands for: everything inside a `.git` store folds into that one chamber. */
function chamberOf(path: string): string {
  const inner = path.startsWith('.git/') ? 0 : path.indexOf('/.git/')
  return inner < 0 ? path : path.slice(0, inner === 0 ? 4 : inner + 5)
}

/** One chamber per folder (a `.git` store is one chamber holding all its files), laid out as a branching
 * tree: the root folder at the centre, each folder's children fanned outward from it at chamber-sized spacing.
 * Position depends only on the folder structure, so replay and file changes keep every chamber in place;
 * size follows the files a folder holds. One pass over the entries, so large trees stay cheap (F122). */
export function buildChambers(project: WorkProject): Chamber[] {
  const children = new Map<string, string[]>(), files = new Map<string, DirectoryEntry[]>()
  const folders = project.nodes.filter((node) => node.kind === 'directory' && chamberOf(node.path) === node.path)
  for (const node of project.nodes) {
    if (node.path === '.') continue
    if (node.kind === 'directory') {
      if (chamberOf(node.path) !== node.path) continue
      const parent = parentPath(node.path), kids = children.get(parent)
      if (kids) kids.push(node.path)
      else children.set(parent, [node.path])
    } else {
      const parent = chamberOf(parentPath(node.path)), held = files.get(parent)
      if (held) held.push(node)
      else files.set(parent, [node])
    }
  }
  for (const kids of children.values()) kids.sort()
  // Each folder fans its children around itself, weighted by their leaf folders, at the distance that keeps
  // siblings apart; a relaxation pass on a spatial grid then separates any cousins that still touch.
  const SIZE = 1.7, CLEAR = 2 * SIZE + 0.5
  const leaves = new Map<string, number>(), beneath = new Map<string, number>()
  const count = (path: string): void => {
    const kids = children.get(path) ?? []
    kids.forEach(count)
    leaves.set(path, kids.length ? kids.reduce((sum, kid) => sum + leaves.get(kid)!, 0) : 1)
    beneath.set(path, (files.get(path)?.length ?? 0) + kids.reduce((sum, kid) => sum + beneath.get(kid)!, 0))
  }
  count('.')
  const points = new Map<string, [number, number]>()
  const place = (path: string, x: number, y: number, facing: number, root: boolean): void => {
    points.set(path, [x, y])
    const kids = children.get(path) ?? []
    if (!kids.length) return
    const sweep = root ? Math.PI * 2 : Math.min(Math.PI, 0.95 * kids.length)
    const total = leaves.get(path)!
    let cursor = facing - sweep / 2
    const directions = kids.map((kid) => {
      const share = sweep * leaves.get(kid)! / total, angle = cursor + share / 2
      cursor += share
      return angle
    })
    const closest = kids.length < 2 ? Math.PI : Math.min(...directions.slice(1).map((angle, i) => angle - directions[i]),
      root ? directions[0] + Math.PI * 2 - directions.at(-1)! : Math.PI)
    const reach = Math.max(CLEAR, CLEAR / (2 * Math.sin(Math.min(Math.PI, closest) / 2)))
    kids.forEach((kid, i) => place(kid, x + Math.cos(directions[i]) * reach, y + Math.sin(directions[i]) * reach, directions[i], false))
  }
  place('.', 0, 0, -Math.PI / 2, true)
  const paths = [...points.keys()]
  for (let pass = 0; pass < 40; pass++) {
    const grid = new Map<string, string[]>()
    const cell = (value: number) => Math.floor(value / CLEAR)
    for (const path of paths) {
      const [x, y] = points.get(path)!, key = `${cell(x)},${cell(y)}`
      const bucket = grid.get(key)
      if (bucket) bucket.push(path)
      else grid.set(key, [path])
    }
    let moved = false
    for (const path of paths) {
      const [x, y] = points.get(path)!
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        for (const other of grid.get(`${cell(x) + dx},${cell(y) + dy}`) ?? []) {
          if (other <= path) continue
          const a = points.get(path)!, b = points.get(other)!
          const gapX = b[0] - a[0], gapY = b[1] - a[1], distance = Math.hypot(gapX, gapY) || 1e-6
          if (distance >= CLEAR) continue
          const push = (CLEAR - distance) / 2 + 0.01, ux = gapX / distance, uy = gapY / distance
          if (path !== '.') { a[0] -= ux * push; a[1] -= uy * push }
          if (other !== '.') { b[0] += ux * push; b[1] += uy * push }
          moved = true
        }
      }
    }
    if (!moved) break
  }
  // Centre the layout on its own extent so the camera frames the whole farm.
  const xs = [...points.values()].map(([x]) => x), ys = [...points.values()].map(([, y]) => y)
  const middle = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]
  const positions = new Map<string, Point3>([...points].map(([path, [x, y]]) =>
    [path, [x - middle[0], y - middle[1], path === '.' ? 0 : (identitySeed(path) - 0.5) * 0.9]]))
  return folders.map(({ path }) => {
    const held = files.get(path) ?? []
    return { path, parent: path === '.' ? null : parentPath(path), position: positions.get(path) ?? [0, 0, 0],
      files: held, beneath: beneath.get(path) ?? 0, radius: 1.05 + Math.min(0.65, Math.sqrt(held.length) * 0.16) }
  })
}

/** Compressed time between two recorded events (milliseconds in, length out). A longer gap is always a longer
 * bare stretch, yet an hour of waiting does not dwarf a burst of seconds (PLAN M3VL send-back 3). */
export function rootGap(ms: number): number {
  return Math.log1p(Math.max(0, ms) / 500) ** 1.2
}

/** One recorded thing drawn as a tube: a root (an agent), a turn, a tool call or a file touch. `radii` follow
 * the dollars flowing through each point; `pink` is the blush a branch leaves its junction with, and `blush` the wash
 * each child leaves on this tube's side facing it (`at` and `reach` in point indices, `dir` the way the child leaves). */
export interface RootTube {
  agent: string; kind: 'root' | 'turn' | 'tool' | 'file'; key: string
  points: Point3[]; radii: number[]; dollars: number[]; pink: number[]; blush: RootBlush[]
}
export interface RootBlush { at: number; reach: number; dir: Point3; weight: number }
export interface RootTree { tubes: RootTube[]; sources: { agent: string; point: Point3 }[]; gauge: number }

interface Segment {
  kind: RootTube['kind']; key: string; agent: WorkAgent; time: number; stop: number
  tip: number; dollars: number; children: Segment[]
  /** The end of the window whose recorded spend it carries, and its agent's own spend so far at a moment. */
  end: number; own: (time: number) => number
}

/** Recorded spend so far at `time`, read linearly between priced trail samples ([time, spend]); the agent's price once it ended. */
function spendAt(agent: WorkAgent, samples: number[][], time: number): number {
  const total = Number(agent.cost_usd ?? 0)
  if (time >= Date.parse(agent.updated_at)) return total
  const next = samples.findIndex(([at]) => at > time)
  if (next === 0) return 0
  if (next < 0) return Math.min(total, samples.at(-1)?.[1] ?? 0)
  const [[t0, c0], [t1, c1]] = [samples[next - 1], samples[next]]
  return c0 + (c1 - c0) * (time - t0) / Math.max(1, t1 - t0)
}

/** The agent's own spend so far: its recorded spend less what its trail rolled up of each returned fork. A fork's
 * roll-up is read from the trail itself (the first rise after the fork returned, at most the fork's price), taken off
 * across that same rise, so later spend of the agent's own always shows. */
function ownSpend(agent: WorkAgent, trail: RootPoint[], forks: Segment[]): (time: number) => number {
  const samples = trail.filter((point) => point.cost_usd !== null).map((point) => [Date.parse(point.ts), Number(point.cost_usd)])
  const claimed = new Set<number>()
  const rolls = [...forks].sort((a, b) => Date.parse(a.agent.updated_at) - Date.parse(b.agent.updated_at)).flatMap((fork) => {
    const back = Date.parse(fork.agent.updated_at)
    const rise = samples.findIndex(([at, cost], k) => k > 0 && at > back && !claimed.has(k) && cost > samples[k - 1][1])
    if (rise < 0) return []
    claimed.add(rise)
    return [{ from: samples[rise - 1][0], to: samples[rise][0], dollars: Math.min(fork.dollars, samples[rise][1] - samples[rise - 1][1]) }]
  })
  return (time) => Math.max(0, spendAt(agent, samples, time)
    - rolls.reduce((sum, roll) => sum + roll.dollars * Math.min(1, Math.max(0, (time - roll.from) / Math.max(1, roll.to - roll.from))), 0))
}

/** An agent's recorded history as a tree: turns leave its root, each tool call its latest turn before it (a burst
 * nesting under the event that opened it), each file touch the latest call before it, and a forked agent leaves its
 * parent's latest event before it started. Dollars flow down it by time, never by counting events: each branch
 * carries the agent's own spend recorded in its window (from its moment to its next sibling's, or its parent's end),
 * scaled so the parent's dollars are conserved; what was spent before a parent's first branch stays in the parent, and
 * a fork carries its own price. */
function agentSegment(agent: WorkAgent, trails: Record<string, RootPoint[]>, forks: Map<string, WorkAgent[]>): Segment {
  const segment = (kind: Segment['kind'], key: string, time: number): Segment =>
    ({ kind, key, agent, time, stop: time, tip: 0, dollars: 0, children: [], end: time, own: () => 0 })
  const times = (values: string[] = []) => values.map(Date.parse).filter(Number.isFinite).sort((a, b) => a - b)
  const latest = (list: Segment[], time: number) => list.reduce<Segment | undefined>((found, item) => item.time <= time ? item : found, undefined)
  const root = segment('root', agent.id, Date.parse(agent.started_at))
  const turns = times(agent.turns).map((time, index) => segment('turn', `${agent.id}:turn:${index}`, time))
  const calls = times(agent.tool_calls).map((time, index) => segment('tool', `${agent.id}:tool:${index}`, time))
  // Within its turn (turns within the root), an event leaves the latest earlier event that followed a longer wait than
  // its own, so a burst sub-forks from the event that opened it and only an event after a longer wait starts a new
  // branch on the turn (single linkage over the recorded gaps, no threshold). Events at one moment are siblings.
  const nest = (ceiling: Segment, list: Segment[]) => {
    const open: { item: Segment; gap: number; parent: Segment }[] = []
    for (const item of list) {
      const before = open.at(-1), gap = item.time - (before?.item.time ?? ceiling.time)
      while (open.length && open.at(-1)!.gap < gap) open.pop()
      const parent = before && gap === 0 ? before.parent : open.at(-1)?.item ?? ceiling
      parent.children.push(item)
      open.push({ item, gap, parent })
    }
  }
  nest(root, turns)
  for (const turn of [root, ...turns]) nest(turn, calls.filter((call) => (latest(turns, call.time) ?? root) === turn))
  const files = (agent.touched_files ?? []).map((file) => ({ path: file.path, time: Date.parse(file.ts) }))
    .sort((a, b) => a.time - b.time || a.path.localeCompare(b.path))
  files.forEach((file, index) => (latest(calls, file.time) ?? latest(turns, file.time) ?? root).children.push(segment('file', `${agent.id}:file:${index}`, file.time)))
  const events = [...turns, ...calls].sort((a, b) => a.time - b.time)
  const limbs = (forks.get(agent.id) ?? []).map((child) => agentSegment(child, trails, forks))
  for (const limb of limbs) (latest(events, limb.time) ?? root).children.push(limb)
  const finish = (item: Segment) => {
    item.children.sort((a, b) => a.time - b.time || a.key.localeCompare(b.key))
    item.children.forEach((child) => { if (child.kind !== 'root') finish(child) })
    item.stop = Math.max(item.time, ...item.children.map((child) => child.time), item === root ? Date.parse(agent.updated_at) : 0)
  }
  finish(root)
  // A turn, call or file touch reaches past its last recorded moment until the agent's next event: how long the work sat there.
  const moments = [...events.map((event) => event.time), root.stop].sort((a, b) => a - b)
  const leaves = (item: Segment): Segment[] => item.children.flatMap((child) => child.kind === 'root' ? [] : [child, ...leaves(child)])
  for (const event of leaves(root)) event.tip = (moments.find((time) => time > event.stop) ?? event.stop) - event.stop
  const own = ownSpend(agent, trails[agent.id] ?? [], limbs)
  // Forks' prices beneath a branch: it carries at least those.
  const forked = (item: Segment): number => item.children.reduce((sum, child) => sum + (child.kind === 'root' ? child.dollars : forked(child)), 0)
  const pour = (item: Segment, dollars: number, end: number) => {
    Object.assign(item, { dollars, end, own })
    const shared = item.children.filter((child) => child.kind !== 'root'), ends = shared.map((_, index) => shared[index + 1]?.time ?? end)
    const spent = Math.max(0, own(end) - own(item.time)), free = Math.max(0, dollars - forked(item))
    shared.forEach((child, index) => pour(child, forked(child) + (spent > 0 ? free * Math.max(0, own(ends[index]) - own(child.time)) / spent : 0), ends[index]))
  }
  // A parent carries its own spend and its forks' prices: its price where its trail rolled up each fork in full, more
  // where a fork has not yet returned or was rolled up for less than its price.
  pour(root, Math.max(Number(agent.cost_usd ?? 0), own(root.stop) + forked(root)), root.stop)
  return root
}

/** Moments along a segment, spaced by compressed time: `along[i]` is the stretch from the first moment to `moments[i]`. */
function timeline(moments: number[], unit: number) {
  const along = moments.map(() => 0)
  for (let i = 1; i < moments.length; i++) along[i] = along[i - 1] + rootGap(moments[i] - moments[i - 1]) * unit
  const stretch = (time: number) => {
    const next = moments.findIndex((moment) => moment >= time)
    if (next <= 0) return next === 0 ? 0 : along.at(-1)!
    const gap = rootGap(moments[next] - moments[next - 1])
    return along[next - 1] + (along[next] - along[next - 1]) * (gap > 0 ? rootGap(time - moments[next - 1]) / gap : 1)
  }
  const when = (s: number) => {
    const next = along.findIndex((value) => value >= s)
    if (next <= 0) return next === 0 ? moments[0] : moments.at(-1)!
    // The exact inverse of `stretch`: the compressed gap unrolled back into time.
    const gap = rootGap(moments[next] - moments[next - 1]) * (s - along[next - 1]) / Math.max(1e-9, along[next] - along[next - 1])
    return Math.min(moments[next], moments[next - 1] + 500 * Math.expm1(gap ** (1 / 1.2)))
  }
  return { along, stretch, when }
}

/** A share of the dollars that only counts once it is large: a heavy child makes a Y; the rest leave as side branches. */
const heavy = (share: number) => Math.max(0, share - 0.3) / 0.7
/** The angle a branch leaves at: its own seed, leaning downstream (a call or touch more than a turn), narrowed for a
 * heavy child so the parent's line continues into it. */
const leaveOf = (item: Segment, share: number) => (item.kind === 'turn' ? 0.35 + 0.55 * identitySeed(item.key) : 0.25 + 0.35 * identitySeed(item.key)) * (1 - 0.9 * heavy(share))
const smooth = (u: number) => { const v = Math.min(1, Math.max(0, u)); return v * v * (3 - 2 * v) }
/** A heading kept inside a forward fan: the river runs left to right and never turns back on itself. */
const forward = (angle: number) => 1.3 * Math.tanh(angle / 1.3)
/** The river's layout gauge (lanes, merges, source rings): one fixed scale, so no position depends on the river's length (ADR-018). */
const GAUGE = 2
/** Width is dollars on one fixed scale, whatever else the river holds: radius = HAIR + WIDTH·√$ (so a tube's cross-section
 * grows with the dollars through it, and at a fork the limbs' shares of the parent's cross-section are their shares of
 * its dollars: Leonardo's rule over dollars only). A big spender arriving never thins an older root. An unpriced tube
 * keeps its kind's hair: a file touch is the finest, never a flat fin. */
export const WIDTH = 6
export const HAIR = { root: 0.12, turn: 0.07, tool: 0.055, file: 0.045 } as const
export const rootWidth = (kind: keyof typeof HAIR, dollars: number) => HAIR[kind] + WIDTH * Math.sqrt(Math.max(0, dollars))
/** A leaf reaches past its last moment as long as the wait for its agent's next event (a bare leaf: or its own spend
 * window, whichever is longer), on the compressed scale (LEAF · gap^0.75): a longer wait is always a longer reach. */
export const LEAF = 3.2
const leafLength = (wait: number) => LEAF * rootGap(wait) ** 0.75
/** The wait `u` of the way along a leaf's reach: the exact inverse of leafLength. */
const leafWait = (u: number, wait: number) => 500 * Math.expm1((Math.min(1, Math.max(0, u)) ** (4 / 3) * rootGap(wait)) ** (1 / 1.2))
/** Red-pink marks every junction at least this strongly; a child's share of its parent's dollars adds to it and sets how far it reaches. */
const PINK = 0.6
const resting = (agent: WorkAgent | undefined) => agent?.state !== 'running' && agent?.state !== 'waiting'
/** A tube's last stretch closes to a point over eight of its diameters there, never a cap: the tip exception to the
 * width law. It starts no earlier than `floor` (its last recorded moment), so a tip never reshapes what is recorded
 * before it. `at(k)` is how far along the tube point k lies. */
const closeTip = (radii: number[], at: (k: number) => number, hair: number, least: number, floor: number) => {
  const last = radii.length - 1, total = at(last)
  let close = last
  while (close > 0 && at(close - 1) >= floor && total - at(close) < Math.max(16 * radii[close], least)) close--
  const from = at(close)
  return radii.map((radius, k) => at(k) <= from ? radius : radius + (0.2 * hair - radius) * smooth((at(k) - from) / Math.max(1e-9, total - from)))
}
/** What a branch keeps of its own dollars still to come at a moment: the spend recorded before its first child (for a
 * leaf, in its window), running out as that spend is made, so a branch thins to its hair from data. */
function keeper(item: Segment): (time: number) => number {
  const kept = Math.max(0, item.dollars - item.children.reduce((sum, child) => sum + child.dollars, 0))
  const until = item.children[0]?.time ?? item.end, spent = item.own(until) - item.own(item.time)
  return (time) => kept * (until <= item.time ? (time <= item.time ? 1 : 0)
    : 1 - smooth(spent > 0 ? (item.own(time) - item.own(item.time)) / spent : (time - item.time) / (until - item.time)))
}

/** How a branch grows out of its parent: the parent's course behind the junction, its heading there, its depth in
 * the tree, which side it leaves on, the parent's drawn width there (`joined`, and `room` just past it), the child's share of what still flows there (its Y), its share of the parent's dollars
 * (its blush) and the parent's own blush there. */
interface Sprout {
  upstream: (d: number) => Point3; heading: number; level: number; side: number
  joined: number; room: number; share: number; tint: number; pink: number; leave?: number
}

/** The Roots as the plate's river (PLAN M3VL send-back 3). A project's agents enter as roots at one left edge and
 * braid into one trunk; along the trunk (and along every branch) events are spaced by the compressed time
 * between them, so long waits stay bare. Each turn, call, touch and fork leaves its parent at its recorded
 * moment as a tube whose width is the dollars flowing through it and which thins as its children take their
 * share. Depth is time. Meander, side and angle come from each branch's own identity seed (ADR-018): same data,
 * same river, and a new event adds its branch without moving the ones already drawn. */
export function buildRootTree(agents: WorkAgent[], trails: Record<string, RootPoint[]>, begin: number): RootTree {
  const byId = new Map(agents.map((agent) => [agent.id, agent]))
  const forks = new Map<string, WorkAgent[]>()
  for (const agent of agents) if (agent.parent_id && byId.has(agent.parent_id)) forks.set(agent.parent_id, [...(forks.get(agent.parent_id) ?? []), agent])
  const order = (a: WorkAgent, b: WorkAgent) => a.started_at.localeCompare(b.started_at) || a.id.localeCompare(b.id)
  for (const children of forks.values()) children.sort(order)
  const tops = agents.filter((agent) => !agent.parent_id || !byId.has(agent.parent_id)).sort(order)
  const projects = [...new Set(tops.map((agent) => agent.root))].sort()
  const trunks = projects.map((root) => {
    const roots = tops.filter((agent) => agent.root === root).map((agent) => agentSegment(agent, trails, forks))
    const moments = [...new Set(roots.flatMap((item) => [item.time, item.stop, ...item.children.map((child) => child.time)]))].sort((a, b) => a - b)
    return { root, roots, line: timeline(moments, 1) }
  })
  const gauge = GAUGE
  // Depth is time: the trunk sinks by its compressed time since the first start, and every branch sinks from where it
  // leaves at the same rate along its length, so no tube ever comes nearer as it runs later.
  const DEPTH = 0.16
  const width = rootWidth
  const flowAt = (item: Segment, time: number) => item.dollars - item.children.reduce((sum, child) => sum + (child.time <= time ? child.dollars : 0), 0)
  const tubes: RootTube[] = [], sources: RootTree['sources'] = []

  // A tube clears its parent's body, then its own moments follow at their compressed times, then its tip reaches on
  // by the wait after its last event. Side, angle, curl and meander are its own seeds; a forked limb that takes a large
  // share of the dollars leaves nearly straight while its parent bends away (a Y, not a T); any other branch only jogs it.
  // It returns where the branch has cleared its parent, the way its wash on the parent faces.
  const grow = (item: Segment, { upstream, heading, level, side, joined, room, share, tint, pink: inherited, leave: fan }: Sprout): Point3 => {
    const seed = (salt: string) => identitySeed(`${item.key}:${salt}`), limb = item.kind === 'root', unit = 0.82 ** level
    // A forked limb thins like any branch as its turns take its dollars, down to a hair at its tip, never a pipe.
    const fine = limb ? 'turn' : item.kind
    // A branch that carries on most of its parent's dollars starts a little upstream, inside the parent, so it is
    // already full width where it leaves: the continuation has no waist and no open rim.
    const back = heavy(share) * joined, origin = upstream(back)
    const stem = (limb ? 0.4 : 0.6) * joined + back
    const moments = [...new Set([item.time, ...item.children.map((child) => child.time), item.stop])].sort((a, b) => a - b)
    const line = timeline(moments, limb ? 0.6 * unit : unit), stretch = (time: number) => stem + line.stretch(time)
    // Siblings leaving close together fan across an arc: alternating sides from the first one's seeded side, each pair
    // leaning wider than the last, so a burst spreads rather than running as parallel needles. Forked limbs fan by their
    // order of birth on the side this branch left its parent toward (away from it), the first born widest and each
    // next one 0.35 rad narrower, so sibling limbs diverge and never cross back over their parent.
    const limbs = item.children.filter((child) => child.kind === 'root')
    const places = item.children.map((child) => stretch(child.time))
    const bursts = item.children.map((child, index) => {
      let lead = index
      while (child.kind !== 'root' && lead > 0 && item.children[lead - 1].kind !== 'root' && places[lead] - places[lead - 1] < unit) lead--
      return lead
    })
    const sides = item.children.map((child, index) => {
      if (child.kind === 'root') return side
      const opened = identitySeed(`${item.children[bursts[index]].key}:side`) < 0.5 ? -1 : 1
      return (index - bursts[index]) % 2 ? -opened : opened
    })
    // A child's share of this branch's dollars (its blush), and for a fork its share of what still flows where it leaves (its Y).
    const parts = item.children.map((child) => Math.min(1, child.dollars / Math.max(1e-9, item.dollars)))
    const shares = item.children.map((child) => child.kind === 'root' ? Math.min(1, child.dollars / Math.max(1e-9, flowAt(item, child.time - 1))) : 0)
    const angles = item.children.map((child, index) => child.kind === 'root'
      ? (0.25 + 0.35 * (limbs.length - 1 - limbs.indexOf(child)) + 0.1 * identitySeed(child.key)) * (1 - 0.9 * heavy(shares[index]))
      : leaveOf(child, shares[index]) + 0.16 * Math.floor((index - bursts[index]) / 2))
    // A child's dollars leave its parent over the stretch it takes the child to clear the parent's body (longer for a
    // heavy child leaving at a narrow angle), so the parent tapers through the crotch instead of ending in a stub.
    // At least two of the pair's diameters, so a heavy last child never leaves its parent ending in a club.
    const clears = item.children.map((child, index) => {
      const pair = width(child.kind === 'root' ? 'turn' : child.kind, child.dollars) + width(fine, flowAt(item, child.time - 1))
      return Math.max(2 * pair, Math.min(4 * unit, Math.max(0.3 * unit, pair / Math.max(0.35, Math.sin(angles[index])))))
    })
    // It reaches past its last moment by its leaf (a limb a little further), and always until its children's dollars
    // have left it, so it thins to its hair before it closes.
    const wait = item.children.length ? item.tip : Math.max(item.tip, item.end - item.stop)
    const reach = stem + line.along.at(-1)!, total = Math.max(reach + (limb ? 1.2 * unit : leafLength(wait) * unit),
      ...places.map((place, index) => place + clears[index] + Math.max(1.2 * unit, 16 * width(fine, flowAt(item, item.children[index].time - 1) - item.children[index].dollars))))
    const step = 0.4 * unit, count = Math.max(4, Math.ceil(total / step) + 1), at = (k: number) => Math.min(total, k * step)
    // The moment each point stands for: its junction, then its own moments, then the wait its leaf reaches over.
    const timeAt = (s: number) => s <= stem ? item.time : s <= reach ? line.when(s - stem) : item.stop + leafWait((s - reach) / (total - reach), wait)
    const leave = fan ?? leaveOf(item, share), hold = 0.75 + 0.25 * seed('bend')
    // A fine branch meanders within its own length: its wave is a share of it, so a short hair still curves.
    const wave = limb ? (3 + 9 * seed('wave')) * unit : Math.min((1.5 + 4.5 * seed('wave')) * unit, (0.1 + 0.2 * seed('wave')) * total)
    const sway = (limb ? 0.05 : 0.08) + (limb ? 0.12 : 0.3) * seed('sway'), phase = identitySeed(item.key) * Math.PI * 2
    // The dollars flowing at each point: what it keeps still to come, and every child not yet left.
    const keeps = keeper(item)
    const flow = (s: number) => keeps(timeAt(s)) + item.children.reduce((sum, child, index) => sum + child.dollars * (1 - smooth((s - places[index]) / clears[index])), 0)
    // A fine branch curls outward within its own length, by its seed and more the longer it is, so hairs arc away from
    // their parent and a burst fans out (the forward limit keeps every heading downstream); a branch still over two
    // hairs wide where its tip starts barely curls, so a thick end never hooks.
    const curl = limb ? 0 : (0.1 + 0.4 * seed('curl:depth')) * Math.min(2, 0.5 + total / (8 * unit)) * (1 - smooth(width(fine, flow(reach)) / HAIR[fine] - 1))
    // A forked limb first runs along its parent inside the parent's body, then turns out: the two diverge as one Y.
    const emerge = limb ? 1.5 * room + unit : 0
    const turning = (s: number) => limb
      ? leave * smooth(s / emerge) - leave * (1 - hold) * smooth((s - emerge) / (4 * unit))
      : leave * (hold + (1 - hold) * (1 - smooth(s / Math.min(4 * unit, total)))) + curl * smooth(s / total)
    const headingAt = (s: number) => forward(heading + side * turning(s)
      + sway * Math.sin(s / wave + phase) * Math.min(1, s / wave)
      - item.children.reduce((sum, _, index) => {
        const u = (s - places[index]) / (1.2 * unit)
        return sum + sides[index] * (0.7 * heavy(shares[index]) * smooth(u) + 0.12 * Math.exp(-u * u))
      }, 0))
    const points: Point3[] = [origin]
    for (let k = 1; k < count; k++) {
      const s = at(k), angle = headingAt((s + at(k - 1)) / 2), [x, y] = points[k - 1], ds = s - at(k - 1)
      points.push([x + Math.cos(angle) * ds, y + Math.sin(angle) * ds, origin[2] - DEPTH * s])
    }
    const dollars = points.map((_, k) => flow(at(k)))
    // Its width is the law's (the dollars flowing there) everywhere but three named stretches: the junction of a branch
    // with children, where it is closed inside its parent's body and flares a little as it leaves it (never wider than
    // the parent, like the farm's limbs flaring into a basin; a heavy child starts at its parent's width, so the
    // hand-over has no step), a leaf, which is never thicker than a twelfth of its length (so it reads as a hair, never
    // a blade), and its tip, which closes to a point (closeTip).
    const bare = !item.children.length, leaving = width(fine, dollars[Math.min(count - 1, Math.ceil(stem / step))])
    const flare = bare ? leaving : Math.max(leaving, 0.93 * smooth(2 * heavy(share)) * joined, limb ? Math.min(0.8 * room, 1.3 * leaving) : Math.min(0.85 * room, (1 + 0.5 * smooth(leaving / 0.4)) * leaving))
    const junction = stem + (limb ? 3 : 2) * leaving + (limb ? 1 : 0.3) * unit, slender = bare ? Math.max(HAIR[fine], (total - stem) / 24) : Infinity
    const joinShape = (s: number) => (1 + (flare / leaving - 1) * (1 - smooth(s / junction))) * (0.04 + 0.96 * smooth(s / (0.5 * joined)))
    // Until it has diverged it stays under 0.9 of its parent's drawn width at the junction, so it never breaks
    // through the parent's surface as a ring; past that it is released over one parent width.
    const inside = Math.max(stem, emerge)
    const within = (s: number, radius: number) => {
      const held = Math.min(radius, 0.9 * joined)
      return held + (radius - held) * smooth((s - inside) / Math.max(1e-3, joined))
    }
    const radii = closeTip(dollars.map((flowing, k) => { const law = Math.min(slender, width(fine, flowing)); return within(at(k), law * joinShape(at(k))) }), at, HAIR[fine], 0.6 * unit, reach)
    // Red-pink where a fine branch (under three hairs wide where it leaves) leaves its parent: at least PINK, more for a
    // larger share of the parent's dollars, reaching further along it, and into the fine branches that leave within
    // that reach, the larger that share. A thicker body carries none of its own: its fork shows as the wash on its
    // parent's side, one diameter long. It comes in only as the branch leaves its parent's body (inside, the parent's
    // wash carries it) and never rises again. A stopped agent carries none, except where its limb leaves a live
    // parent: there its fork is marked in full and fades within one diameter.
    const still = resting(item.agent), strength = PINK + (1 - PINK) * Math.sqrt(tint)
    const blushed = leaving >= 3 * HAIR[fine] ? 0 : still ? (limb && !resting(byId.get(item.agent.parent_id ?? '')) ? strength : 0) : Math.max(inherited, strength)
    const fade = still ? 2 * leaving : ((limb ? 2.5 : 0.6) + (limb ? 14 : 2.5) * Math.sqrt(tint)) * unit
    const blooms = stem + 0.5 * joined
    const pink = points.map((_, k) => blushed * smooth((at(k) - back) / Math.max(1e-6, blooms - back)) * (1 - smooth((at(k) - Math.max(emerge, blooms)) / fade)))
    const tube: RootTube = { agent: item.agent.id, kind: item.kind, key: item.key, points, radii, dollars, pink, blush: [] }
    tubes.push(tube)
    const point = (s: number): [Point3, number, number] => {
      const k = Math.max(0, Math.min(count - 2, Math.floor(s / step))), u = Math.min(1, (s - at(k)) / Math.max(1e-9, at(k + 1) - at(k)))
      return [points[k].map((value, axis) => value + (points[k + 1][axis] - value) * u) as Point3, radii[k] + (radii[k + 1] - radii[k]) * u, pink[k] + (pink[k + 1] - pink[k]) * u]
    }
    item.children.forEach((child, index) => {
      // A branch's flare never outgrows its parent once the branch has taken its dollars, so its base stays inside the
      // parent's body; a forked limb flares to the parent's width there, as the parent tapers through the crotch.
      const [from, radius, there] = point(places[index]), past = width(fine, flow(places[index]) - child.dollars)
      const out = grow(child, { upstream: (d) => point(places[index] - d)[0], heading: headingAt(places[index]),
        level: level + 1, side: sides[index], joined: radius, room: child.kind === 'root' ? radius : Math.min(radius, past), share: shares[index],
        tint: parts[index], pink: still ? 0 : there, leave: angles[index] })
      if (!still) tube.blush.push(wash(from, out, places[index] / step, 2 * radius / step, parts[index], child.kind === 'root'))
    })
    return point(Math.min(total, Math.max(emerge, stem) + 1.5 * unit))[0]
  }
  // The wash a child leaves on its live parent's side facing it, over one of the parent's diameters from the junction,
  // as strong as the child's share of the parent's dollars; a fork's wash is at least PINK.
  const wash = (from: Point3, out: Point3, at: number, reach: number, share: number, fork: boolean): RootBlush => {
    const dir = out.map((value, axis) => value - from[axis]), length = Math.hypot(...dir) || 1
    return { at, reach, dir: dir.map((value) => value / length) as Point3, weight: fork ? PINK + (1 - PINK) * Math.sqrt(share) : 0.7 * Math.sqrt(share) }
  }

  trunks.forEach(({ root, roots, line }, project) => {
    const middle = (project - (projects.length - 1) / 2) * 50, phase = identitySeed(root) * Math.PI * 2
    // Depth is time on the same compressed scale as across: a project that started later sits further back.
    const lag = -DEPTH * rootGap(line.when(0) - begin)
    const starts = roots.map((item) => line.stretch(item.time)), last = line.along.at(-1)!, entry = Math.min(...starts)
    // Every root enters at the river's one left edge. The first working root runs on the trunk's line; every other root
    // runs straight in its own lane on alternate sides (working roots nearest), bare until it starts, then swells and
    // converges on the trunk at a shallow angle (over 3.6 lane widths, under about 23°) until it fuses into it: the
    // longer after the first start it began, the longer its bare approach. Source rings never overlap.
    const busy = roots.filter((item) => item.dollars > 0 || item.children.length), laned = [...busy, ...roots.filter((item) => !busy.includes(item))]
    const lanes = roots.map((item) => { const k = laned.indexOf(item); return k > 0 ? (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 12 : 0 })
    // The trunk is the first working root grown on from its source, so there is no hand-over (and no seam) between
    // an approach and the trunk.
    const lead = Math.max(0, roots.findIndex((item) => busy.includes(item)))
    const merges = lanes.map((lane) => Math.max(13, 3.6 * Math.abs(lane)))
    // The trunk's course before any bend: straight until its lead root starts, then a seeded meander.
    const meander = (x: number) => middle + smooth((x - starts[lead]) / 20) * (6.5 * Math.sin(x / 18.6 + phase) + 2.6 * Math.sin(x / 7.6 + 2 * phase))
    // How far a root's approach lies off that course: its lane, closing over its merge stretch.
    const converge = (index: number, x: number) => index === lead ? 1 : smooth((x - starts[index]) / merges[index])
    const offset = (index: number, x: number) => (middle + lanes[index] - meander(x)) * (1 - converge(index, x))
    // A root is handed to the trunk once their bodies come within one combined diameter (centre gap under twice their
    // radii summed), then over three of those radii it moves onto the trunk's centreline and its dollars move into the trunk: one tube, never two
    // side by side, and every dollar drawn once. A root that has not reached the trunk by the river's last moment runs
    // on in its lane with all its dollars.
    const contacts = roots.map((item, index) => {
      if (index === lead) return { at: starts[index], fuse: 1 }
      let x = starts[index]
      const reach = (at: number) => width('root', flowAt(item, line.when(at))) + width('root', flowAt(roots[lead], line.when(at)))
      while (x <= last && Math.abs(offset(index, x)) >= 2 * reach(x)) x += 0.4
      return x > last ? { at: Infinity, fuse: 1 } : { at: x, fuse: Math.min(Math.max(3, 3 * reach(x)), Math.max(1, last + 1.5 - x)) }
    })
    const joined = (index: number, x: number) => index === lead ? 1 : smooth((x - contacts[index].at) / contacts[index].fuse)
    const close = (index: number) => contacts[index].at + contacts[index].fuse
    // A turn that takes a large share of the trunk's dollars bends the trunk away from it: the fork reads as a Y.
    const bends = roots.flatMap((item, index) => item.children.map((child) => {
      const x = line.stretch(child.time), before = roots.reduce((sum, other, j) => sum + (x >= starts[j] && child.time - 1 <= other.stop ? joined(j, x) * flowAt(other, child.time - 1) : 0), 0)
      const share = Math.min(1, child.dollars / Math.max(1e-9, before))
      // A heavy turn leaves on the side away from the other bodies still apart from its own (an approach leaves away
      // from the trunk; the trunk away from the nearest approach not yet fused), so it never passes through one; any
      // other turn leaves on its seeded side.
      const apart = index === lead ? roots.map((_, j) => j).filter((j) => j !== lead && joined(j, x) < 1 && x <= close(j) + 2)
        .map((j) => -offset(j, x)).sort((a, b) => Math.abs(a) - Math.abs(b))[0] : offset(index, x)
      const side = heavy(share) > 0 && apart ? Math.sign(apart) : identitySeed(`${child.key}:side`) < 0.5 ? -1 : 1
      return { child, x, side, share, index }
    }))
    // The trunk runs straight until its lead root starts, then meanders; it steps aside by a heavy turn's share over a
    // short stretch, then drifts back to its course.
    const centre = (x: number) => meander(x) - bends.reduce((sum, bend) => sum + bend.side * 2.5 * heavy(bend.share) * smooth((x - bend.x) / 6) * Math.exp(-Math.max(0, x - bend.x - 6) / 25), 0)
    const place = (index: number, x: number): Point3 => [x, centre(x) + (middle + lanes[index] - centre(x)) * (1 - converge(index, x)) * (1 - joined(index, x)), lag - DEPTH * x]
    const heading = (index: number, x: number) => {
      const a = place(index, x - 1.3), b = place(index, x + 1.3)
      return Math.atan2(b[1] - a[1], Math.max(1e-6, b[0] - a[0]))
    }
    // Samples at one fixed spacing from where a tube starts, so a river that grows keeps every sample it already had.
    const samples = (from: number, to: number) => Array.from({ length: Math.max(2, Math.ceil((to - from) / 0.8) + 1) }, (_, k) => Math.min(to, from + 0.8 * k))
    // Drawn, a turn's dollars leave a root over a short stretch past its junction, so the river tapers, never steps.
    // A turn that carries on most of them takes them once it is full width, so the root it leaves thins inside it.
    const spans = new Map(bends.map(({ child, share }) => [child, [7 * (1 - 0.85 * heavy(share)), 1.5 * heavy(share)]]))
    const keeps = roots.map(keeper)
    const drawn = (index: number, x: number) => keeps[index](line.when(x)) + roots[index].children.reduce((flowing, child) => {
      const [span, delay] = spans.get(child)!
      return flowing + child.dollars * (1 - smooth((x - line.stretch(child.time) - delay) / span))
    }, 0)
    // The trunk: a project's roots fused into one, as wide as the dollars all of them still carry. It runs on until
    // its last turn has taken its dollars, so it is a hair where it closes.
    const flowing = (x: number) => roots.reduce((sum, _, index) => sum + (x >= starts[index] ? joined(index, x) * drawn(index, x) : 0), 0)
    const end = Math.max(last, ...bends.map(({ child, x }) => x + spans.get(child)!.reduce((sum, value) => sum + value, 0))) + 1.5
    // Each root waits as the finest hair (a capillary's) until it starts, then swells to its dollars over two of its
    // diameters (3 to 10 units), so its start reads as a swelling; any but the lead closes past the merge, inside the
    // trunk that has taken it over.
    const swelling = (index: number) => Math.min(10, Math.max(3, 4 * width('root', roots[index].dollars)))
    const swell = (index: number, x: number, share = 1) => x < starts[index] ? HAIR.file
      : HAIR.file + (width('root', share * drawn(index, x)) - HAIR.file) * smooth((x - starts[index]) / swelling(index))
    // An approach draws only the dollars not yet handed to the trunk.
    const approachAt = (index: number, x: number) => swell(index, x, 1 - joined(index, x)) * (1 - 0.9 * smooth((x - close(index)) / 2))
    const along = samples(Math.min(last, entry), end), eased = along.map(flowing)
    const trunkAt = (x: number, dollars: number) => x < starts[lead] + swelling(lead) ? Math.min(width('root', dollars), swell(lead, x)) : width('root', dollars)
    const trunk: RootTube = { agent: root, kind: 'root', key: `trunk:${root}`, points: along.map((x) => place(lead, x)),
      radii: closeTip(along.map((x, k) => trunkAt(x, eased[k])), (k) => along[k] - along[0], HAIR.root, 1, last - along[0]),
      dollars: eased, pink: along.map(() => 0), blush: [] }
    tubes.push(trunk)
    const trunkWidth = (x: number) => {
      const next = along.findIndex((value) => value > x), k = Math.max(0, next < 0 ? along.length - 2 : Math.min(along.length - 2, next - 1)), u = (x - along[k]) / Math.max(1e-9, along[k + 1] - along[k])
      return trunk.radii[k] + (trunk.radii[k + 1] - trunk.radii[k]) * Math.min(1, Math.max(0, u))
    }
    // Where each tube's samples lie across, so a junction at `x` can be named by its point index there.
    const extents = new Map<RootTube, [number, number]>([[trunk, [along[0], along.at(-1)!]]])
    roots.forEach((item, index) => {
      if (index === lead) return void sources.push({ agent: item.agent.id, point: trunk.points[0] })
      // Each other root enters at the left edge, runs its lane and fuses into the trunk over its merge stretch (a root
      // that started and stopped at once, with nothing recorded, still reaches the trunk as a hair).
      const across = samples(entry, Math.min(close(index) + 2, end))
      const points = across.map((x) => place(index, x))
      const tube: RootTube = { agent: item.agent.id, kind: 'root', key: item.key, points,
        radii: closeTip(across.map((x) => approachAt(index, x)), (k) => across[k] - across[0], HAIR.root, 1, last - across[0]),
        dollars: across.map((x) => x < starts[index] ? 0 : (1 - joined(index, x)) * drawn(index, x)), pink: across.map(() => 0), blush: [] }
      tubes.push(tube)
      extents.set(tube, [across[0], across.at(-1)!])
      sources.push({ agent: item.agent.id, point: points[0] })
    })
    const indexAt = (tube: RootTube, x: number) => { const [from, to] = extents.get(tube)!; return (x - from) / Math.max(1e-9, to - from) * (tube.points.length - 1) }
    // The body a turn leaves, as drawn at `x`: its root's approach, or the trunk once merged.
    const bodyAt = (index: number, x: number) => index === lead ? trunkWidth(x)
      : Math.max(x <= close(index) + 2 ? approachAt(index, x) : 0, joined(index, x) > 0.5 ? trunkWidth(x) : 0)
    // Turns leave after the trunk's course is set by every bend. A turn is never wider than the body it leaves.
    for (const { child, x, side, share, index } of bends) {
      const body = bodyAt(index, x)
      const out = grow(child, { upstream: (d) => place(index, x - d), heading: heading(index, x), level: 1, side,
        joined: body, room: body, share, tint: share, pink: 0 })
      // Its wash lands on whichever body it leaves: its root's approach, the trunk, or both where they fuse; it reaches
      // along one of that body's diameters.
      // Where the approach already touches the trunk just downstream, both carry it, so no colour seam shows where one
      // body sinks into the other.
      const touching = Math.abs(place(index, x + 2)[1] - place(lead, x + 2)[1]) < approachAt(index, x + 2) + trunkWidth(x + 2)
      const leaves = [...index !== lead && x <= close(index) + 2 ? [tubes.find((tube) => tube.key === roots[index].key)!] : [],
        ...index === lead || touching ? [trunk] : []]
      for (const tube of resting(roots[index].agent) ? [] : leaves) {
        const unit = (extents.get(tube)![1] - extents.get(tube)![0]) / Math.max(1, tube.points.length - 1)
        tube.blush.push(wash(place(index, x), out, indexAt(tube, x), 2 * body / unit, share, heavy(share) > 0))
      }
    }
  })
  return { tubes, sources, gauge }
}
