import type { PalaceNebulaSnapshot } from './nebulaBindings'

export type DetailTier = 'full' | 'efficient'
export type Point3 = [number, number, number]
export interface WorkAgent {
  id: string; thread_id: string; parent_id: string | null; label: string
  root: string; location: string; state: string; started_at: string; updated_at: string
  waiting_since: string | null; cost_usd: number | string | null
}
export interface DirectoryEntry { path: string; kind: 'directory' | 'file' | 'link'; bytes: number }
export interface WorkProject { root: string; nodes: DirectoryEntry[]; errors: { path: string; error: string }[] }
export interface RootPoint { ts: string; location: string; cost_usd: number | string | null; state: string }
export interface VisualizationSnapshot {
  as_of: string; live: boolean; recorded_since: string; timeline: string[]
  projects: WorkProject[]; agents: WorkAgent[]; trails: Record<string, RootPoint[]>
  palace: PalaceNebulaSnapshot | null
  curation: { latest_run: Record<string, unknown> | null } | null
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
  path: string; position: Point3; radius: number; parent: string | null; files: DirectoryEntry[]
}
export function buildChambers(project: WorkProject): Chamber[] {
  const folders = project.nodes.filter((node) => node.kind === 'directory')
  const children = new Map<string, string[]>()
  for (const folder of folders) {
    if (folder.path === '.') continue
    const parent = parentPath(folder.path)
    children.set(parent, [...(children.get(parent) ?? []), folder.path])
  }
  const positions = new Map<string, Point3>()
  let leaf = 0
  const visit = (path: string, depth: number): number => {
    const descendants = (children.get(path) ?? []).sort().map((child) => visit(child, depth + 1))
    const y = descendants.length ? descendants.reduce((a, b) => a + b, 0) / descendants.length : leaf++ * 2.4
    positions.set(path, [y, -depth * 3.2, (identitySeed(path) - 0.5) * 1.8])
    return y
  }
  visit('.', 0)
  const center = Math.max(0, leaf - 1) * 1.2
  const verticalCenter = Math.min(0, ...[...positions.values()].map((point) => point[1])) / 2
  return folders.map(({ path }) => {
    const point = positions.get(path) ?? [0, 0, 0]
    const files = project.nodes.filter((node) => node.kind !== 'directory' && parentPath(node.path) === path)
    return { path, parent: path === '.' ? null : parentPath(path),
      position: [point[0] - center, point[1] - verticalCenter, point[2]], files,
      radius: 0.64 + Math.min(0.45, Math.sqrt(files.length) * 0.04) }
  })
}

export function rootCurve(agent: WorkAgent, trail: RootPoint[], lane: number, begin: number, end: number): Point3[] {
  const duration = Math.max(1000, end - begin)
  const first = trail[0]?.ts ?? agent.started_at
  const last = trail.at(-1)?.ts ?? agent.updated_at
  const start = Math.max(0, (Date.parse(first) - begin) / duration)
  const stop = Math.max(start + 0.005, (Date.parse(last) - begin) / duration)
  const seed = identitySeed(agent.id) * Math.PI * 2
  return Array.from({ length: 32 }, (_, i) => {
    const t = i / 31, time = start + (stop - start) * t
    return [-9 + time * 18, lane + Math.sin(t * 7 + seed) * Math.sin(t * Math.PI) * 0.55,
      -time * 3 + Math.sin(t * 5 + seed) * Math.sin(t * Math.PI) * 0.4]
  })
}
