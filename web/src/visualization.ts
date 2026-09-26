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

/** Half the width of the Roots work-order axis: the river runs long, like the plate. */
export const ACROSS = 14

export function rootWorkTimes(agents: WorkAgent[]): number[] {
  return [...new Set(agents.flatMap((agent) => [agent.started_at, agent.updated_at, ...(agent.turns ?? []),
    ...(agent.tool_calls ?? []), ...(agent.touched_files ?? []).map((file) => file.ts)]).map(Date.parse))].sort((a, b) => a - b)
}

export function rootWorkPosition(time: number, moments: number[]): number {
  const next = moments.findIndex((moment) => moment >= time)
  if (next <= 0) return next === 0 ? 0 : 1
  return (next - 1 + (time - moments[next - 1]) / Math.max(1, moments[next] - moments[next - 1])) / (moments.length - 1)
}

export function rootCurve(agent: WorkAgent, trail: RootPoint[], lane: number, begin: number, end: number, moments: number[] = [begin, end]): Point3[] {
  const duration = Math.max(1000, end - begin)
  const first = trail[0]?.ts ?? agent.started_at
  const last = trail.at(-1)?.ts ?? agent.updated_at
  const start = rootWorkPosition(Date.parse(first), moments)
  const stop = Math.max(start + 0.005, rootWorkPosition(Date.parse(last), moments))
  const seed = identitySeed(agent.id) * Math.PI * 2
  return Array.from({ length: 32 }, (_, i) => {
    const t = i / 31, work = Math.min(1, start + (stop - start) * t)
    const index = work * (moments.length - 1), before = Math.floor(index), after = Math.min(moments.length - 1, before + 1)
    const time = (moments[before] + (moments[after] - moments[before]) * (index - before) - begin) / duration
    return [-ACROSS + work * 2 * ACROSS, lane + Math.sin(t * 7 + seed) * Math.sin(t * Math.PI) * 0.55,
      -time * 3 + Math.sin(t * 5 + seed) * Math.sin(t * Math.PI) * 0.4]
  })
}

export function buildRootPaths(agents: WorkAgent[], trails: Record<string, RootPoint[]>, begin: number, end: number): Map<string, Point3[]> {
  const moments = rootWorkTimes(agents)
  const byId = new Map(agents.map((agent) => [agent.id, agent]))
  const project = (agent: WorkAgent): string => {
    const visited = new Set<string>()
    while (agent.parent_id && byId.has(agent.parent_id) && !visited.has(agent.id)) {
      visited.add(agent.id)
      agent = byId.get(agent.parent_id)!
    }
    return agent.root
  }
  const projects = [...new Set(agents.map(project))].sort()
  const paths = new Map<string, Point3[]>()
  const visit = (agent: WorkAgent): Point3[] => {
    const existing = paths.get(agent.id)
    if (existing) return existing
    const root = project(agent), peers = agents.filter((item) => project(item) === root)
      .sort((a, b) => a.started_at.localeCompare(b.started_at) || a.id.localeCompare(b.id))
    const lane = peers.findIndex((peer) => peer.id === agent.id) - (peers.length - 1) / 2
    const projectLane = (projects.indexOf(root) - (projects.length - 1) / 2) * 4.5
    const phase = identitySeed(root) * Math.PI * 2
    const points = rootCurve(agent, trails[agent.id] ?? [], 0, begin, end, moments).map((point, index): Point3 => {
      const time = (point[0] + ACROSS) / (2 * ACROSS), t = index / 31
      return [point[0], projectLane + Math.sin(time * 5 + phase) * 0.9
        + lane * (0.12 + 0.8 * Math.pow(1 - t, 3) + 0.8 * Math.pow(t, 2))
        + Math.sin(t * 7 + identitySeed(agent.id) * 6) * Math.sin(t * Math.PI) * 0.25, point[2]]
    })
    paths.set(agent.id, points)
    const parent = agent.parent_id ? byId.get(agent.parent_id) : undefined
    if (parent) {
      const parentPoints = visit(parent)
      const junction = parentPoints.reduce((closest, point) =>
        Math.abs(point[0] - points[0][0]) < Math.abs(closest[0] - points[0][0]) ? point : closest)
      // A fork leaves its parent at the junction and diverges like a limb; siblings fan to either side.
      const siblings = agents.filter((item) => item.parent_id === agent.parent_id)
        .sort((a, b) => a.started_at.localeCompare(b.started_at) || a.id.localeCompare(b.id))
      const order = siblings.findIndex((item) => item.id === agent.id)
      const side = order % 2 ? -1 : 1, reach = 1.1 + Math.floor(order / 2) * 0.9 + identitySeed(agent.id) * 0.6
      const depth = junction[2] - points[0][2], seed = identitySeed(agent.id) * 6
      points.forEach((point, index) => {
        const t = index / 31
        point[1] = junction[1] + side * reach * (1 - (1 - t) ** 2) + Math.sin(t * 6 + seed) * Math.sin(t * Math.PI) * 0.2
        point[2] += depth * Math.pow(1 - t, 2)
      })
      points[0] = [...junction]
    }
    return points
  }
  agents.forEach(visit)
  return paths
}

/** Recorded spend so far at each point of a root, as a share of its final spend (width = dollars over time). */
export function rootSpendShares(agent: WorkAgent, trail: RootPoint[], points: Point3[], moments: number[]): number[] {
  const total = Number(agent.cost_usd ?? 0)
  const recorded = trail.filter((point) => point.cost_usd !== null).map((point) => ({ time: Date.parse(point.ts), cost: Number(point.cost_usd) }))
  if (!(total > 0) || !recorded.length) return points.map(() => 1)
  return points.map(([x]) => {
    const index = Math.min(1, Math.max(0, (x + ACROSS) / (2 * ACROSS))) * (moments.length - 1), low = Math.floor(index)
    const time = moments[low] + ((moments[Math.min(moments.length - 1, low + 1)] ?? moments[low]) - moments[low]) * (index - low)
    const spent = recorded.filter((point) => point.time <= time).at(-1)?.cost ?? 0
    return Math.min(1, spent / total)
  })
}

export interface RootBranch { kind: 'turn' | 'tool' | 'file'; points: Point3[]; weight: number; parent: number }

/** A root's own history as a river: each turn branches off the root at the moment it began, each tool call
 * off its turn's branch, each file touch off the latest tool call before it. On the root, across = work order
 * and depth = time, so every turn joins at its recorded moment; along a branch, its calls and touches keep
 * their recorded order and relative time. A branch's reach grows with the work recorded beneath it. */
export function buildRootRiver(agent: WorkAgent, root: Point3[], moments: number[], begin: number, end: number): RootBranch[] {
  const across = (time: number) => -ACROSS + rootWorkPosition(time, moments) * 2 * ACROSS
  const depth = (time: number) => -((time - begin) / Math.max(1000, end - begin)) * 3
  const times = (values: string[] = []) => values.map(Date.parse).filter(Number.isFinite).sort((a, b) => a - b)
  const turns = times(agent.turns), calls = times(agent.tool_calls)
  const files = [...(agent.touched_files ?? [])].map((file) => ({ path: file.path, time: Date.parse(file.ts) }))
    .sort((a, b) => a.time - b.time || a.path.localeCompare(b.path))
  const owner = (time: number, starts: number[]) => starts.reduce((found, start, index) => start <= time ? index : found, -1)
  type Grown = RootBranch & { side: number; start: number; stop: number; index: number }
  const trunk: Grown = { kind: 'turn', points: root, weight: 0, parent: -1, side: 1, start: begin, stop: end, index: -1 }
  let count = 0
  // A point and heading on a parent: on the root by work order; on a branch by the time's share of its span.
  const junction = (parent: Grown, time: number, from: number): [Point3, number] => {
    const { points } = parent
    let index: number
    if (parent === trunk) {
      const x = across(time), next = points.findIndex((point) => point[0] >= x)
      index = next <= 0 ? (next === 0 ? 0 : points.length - 1) : next - 1 + (x - points[next - 1][0]) / Math.max(1e-6, points[next][0] - points[next - 1][0])
    } else {
      const share = parent.stop > parent.start ? (time - parent.start) / (parent.stop - parent.start) : 1
      index = (from + (1 - from) * Math.min(1, Math.max(0, share))) * (points.length - 1)
    }
    const low = Math.min(points.length - 2, Math.floor(index)), [a, b] = [points[low], points[low + 1]]
    const u = Math.min(1, index - low)
    return [a.map((value, axis) => value + (b[axis] - value) * u) as Point3, Math.atan2(b[1] - a[1], b[0] - a[0])]
  }
  // Leave the parent's heading at a seeded angle, then bend back toward the flow, like a river's distributary.
  const branch = (kind: RootBranch['kind'], parent: Grown, start: number, work: number[], side: number, seed: number,
    reach: number, turn: [number, number], from: number, steps: number): Grown => {
    const stop = Math.max(start, ...work)
    const [origin, heading] = junction(parent, start, from)
    const length = Math.max(reach, across(stop) - across(start))
    const first = Math.max(-1.1, Math.min(1.1, heading + side * (turn[0] + turn[1] * seed))), last = first * (0.1 + 0.6 * identitySeed(`${seed}:bend`))
    const points: Point3[] = [origin]
    for (let step = 1; step < steps; step++) {
      const u = step / (steps - 1), angle = first + (last - first) * u, previous = points[step - 1]
      points.push([previous[0] + Math.cos(angle) * length / (steps - 1), previous[1] + Math.sin(angle) * length / (steps - 1),
        origin[2] + depth(start + (stop - start) * u) - depth(start) + (seed - 0.5) * 0.6 * length * u])
    }
    return { kind, weight: work.length + 1, parent: parent.index, side, start, stop, points, index: count++ }
  }
  const turnBranches = turns.map((turn, index) => {
    const work = [...calls.filter((call) => owner(call, turns) === index), ...files.filter((file) => owner(file.time, turns) === index).map((file) => file.time)]
    const side = (index + Math.round(identitySeed(agent.id))) % 2 ? -1 : 1
    return branch('turn', trunk, turn, work, side, identitySeed(`${agent.id}:turn:${index}`), 1 + 0.9 * Math.sqrt(work.length + 1), [0.2, 0.75], 0, 14)
  })
  const toolBranches = calls.map((call, index) => {
    const parent = turnBranches[owner(call, turns)] ?? trunk
    const work = files.filter((file) => owner(file.time, calls) === index).map((file) => file.time)
    const seed = identitySeed(`${agent.id}:tool:${index}`)
    return branch('tool', parent, call, work, seed < 0.75 ? parent.side : -parent.side, seed, 0.7 + 0.5 * Math.sqrt(work.length + 1), [0.3, 0.5], 0.3, 9)
  })
  const fileBranches = files.map((file) => {
    const parent = toolBranches[owner(file.time, calls)] ?? turnBranches[owner(file.time, turns)] ?? trunk
    const seed = identitySeed(`${agent.id}:file:${file.path}`)
    return branch('file', parent, file.time, [], seed < 0.6 ? parent.side : -parent.side, seed, 0.7 + seed * 0.8, [0.3, 0.6], 0.55, 7)
  })
  return [...turnBranches, ...toolBranches, ...fileBranches].map(({ kind, points, weight, parent }) => ({ kind, points, weight, parent }))
}
