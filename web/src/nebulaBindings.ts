export type NebulaAxisMode = 'activity' | 'provenance'
export type NebulaHardwareTier = 'efficient' | 'full'

export interface PalaceMemoryNode {
  memory: {
    memory_id: string
    label: string
    kind: string
    status: string
    pin: boolean
    revision: number
    project_key: string | null
    origin_thread_id?: string | null
    thread_origin?: string | null
    origin_path?: string | null
    created_at?: string | null
    updated_at?: string | null
    stats: { injections?: number }
  }
  in_current_context: boolean
  revisions: unknown[]
}

export interface PalaceNebulaSnapshot {
  as_of: string
  nodes: PalaceMemoryNode[]
}

export interface NebulaBody {
  id: string
  label: string
  kind: string
  position: readonly [number, number, number]
  scale: readonly [number, number, number]
  color: readonly [number, number, number]
  motion_hz: number
  motion_amplitude: number
  pinned: boolean
  in_current_context: boolean
}

export const NEBULA_BINDINGS = {
  activity: [
    'X · memory.created_at (chronological rank)',
    'Y · memory.stats.injections (log scale)',
    'Z · memory.revision (linear scale)',
  ],
  provenance: [
    'X · memory.project_key (deterministic identity)',
    'Y · memory origin thread (origin_thread_id; legacy thread_origin)',
    'Z · memory.origin_path (path depth)',
  ],
  shared: [
    'Size · memory.stats.injections (log scale)',
    'Color · memory.kind (deterministic palette)',
    'Shape · memory.revision (vertical stretch)',
    'Motion · memory.updated_at (recency speed)',
    'Motion amplitude · memory.stats.injections',
    'Brightness · memory.pin or current-context membership',
  ],
} as const

export function buildNebulaBodies(
  snapshot: PalaceNebulaSnapshot,
  axis: NebulaAxisMode,
  nowMs = Date.now(),
): NebulaBody[] {
  const active = snapshot.nodes.filter((node) => node.memory.status === 'active')
  const created = active.map((node) => timestamp(node.memory.created_at))
  const injections = active.map(injectionCount)
  const revisions = active.map((node) => Math.max(0, node.memory.revision))
  const pathDepths = active.map((node) => pathDepth(node.memory.origin_path))

  return active.map((node, index) => {
    const injection = injections[index]
    const revision = revisions[index]
    const updated = timestamp(node.memory.updated_at)
    const ageDays = updated === 0 ? Number.POSITIVE_INFINITY : Math.max(0, nowMs - updated) / 86_400_000
    const position = axis === 'activity'
      ? [
          spread(rank(created, index)),
          spread(normalizeLog(injection, injections)),
          spread(normalize(revision, revisions)),
        ] as const
      : [
          spread(identity(node.memory.project_key)),
          spread(identity(node.memory.origin_thread_id ?? node.memory.thread_origin)),
          spread(normalize(pathDepths[index], pathDepths)),
        ] as const
    const radius = 0.38 + 0.18 * Math.log2(injection + 1)
    const stretch = 1 + Math.min(revision, 12) * 0.055
    return {
      id: node.memory.memory_id,
      label: node.memory.label,
      kind: node.memory.kind,
      position,
      scale: [radius, radius * stretch, radius],
      color: colorForKind(node.memory.kind),
      motion_hz: 0.025 + 0.22 / (1 + ageDays / 14),
      motion_amplitude: 0.025 + Math.min(injection, 30) * 0.006,
      pinned: node.memory.pin,
      in_current_context: node.in_current_context,
    }
  })
}

function injectionCount(node: PalaceMemoryNode): number {
  const value = Number(node.memory.stats.injections ?? 0)
  return Number.isFinite(value) ? Math.max(0, value) : 0
}

function timestamp(value: string | null | undefined): number {
  const parsed = value === null || value === undefined ? Number.NaN : Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function pathDepth(value: string | null | undefined): number {
  return value?.split('/').filter(Boolean).length ?? 0
}

function normalize(value: number, values: readonly number[]): number {
  const minimum = Math.min(...values, 0)
  const maximum = Math.max(...values, 0)
  return maximum === minimum ? 0.5 : (value - minimum) / (maximum - minimum)
}

function normalizeLog(value: number, values: readonly number[]): number {
  return normalize(Math.log2(value + 1), values.map((item) => Math.log2(item + 1)))
}

function rank(values: readonly number[], index: number): number {
  if (values.length <= 1) return 0.5
  const sorted = [...values].sort((left, right) => left - right)
  const position = sorted.indexOf(values[index])
  return position / (values.length - 1)
}

function identity(value: string | null | undefined): number {
  if (!value) return 0.5
  return (stableHash(value) % 10_001) / 10_000
}

function spread(value: number): number {
  return (value - 0.5) * 7
}

function colorForKind(kind: string): readonly [number, number, number] {
  const hue = (stableHash(kind) % 360) / 360
  return hslToRgb(hue, 0.64, 0.58)
}

function stableHash(value: string): number {
  let hash = 2_166_136_261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16_777_619)
  }
  return hash >>> 0
}

function hslToRgb(h: number, s: number, l: number): readonly [number, number, number] {
  const channel = (offset: number) => {
    const k = (offset + h * 12) % 12
    return l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1))
  }
  return [channel(0), channel(8), channel(4)]
}
