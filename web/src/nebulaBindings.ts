export type NebulaAxisMode = 'activity' | 'provenance'
export type NebulaHardwareTier = 'efficient' | 'full'
export type NebulaEventClass = 'add' | 'delete' | 'modify' | 'merge' | 'split'

export interface RevisionTrailItem {
  rev_uid: string
  parent_uid: string | null
  revision: number | null
  ts: string
  reason: string
}

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
  revisions: RevisionTrailItem[]
}

export interface PalaceMemoryEdge {
  kind: 'similarity' | 'lineage' | 'edit_trail'
  from_memory_id: string
  to_memory_id: string
  similarity?: string | null
  edge_type?: string | null
  revision_count?: number | null
}

export interface PalaceNebulaSnapshot {
  as_of: string
  nodes: PalaceMemoryNode[]
  edges?: PalaceMemoryEdge[]
}

export interface NebulaBody {
  id: string
  label: string
  kind: string
  position: readonly [number, number, number]
  scale: readonly [number, number, number]
  color: readonly [number, number, number]
  recency_glow: number
  pinned: boolean
  in_current_context: boolean
}

export interface NebulaMemoryEvent {
  id: string
  memory_id: string
  memory_label: string
  event_class: NebulaEventClass
  reason: string
  ts: string
  position: readonly [number, number, number]
  color: readonly [number, number, number]
}

export interface NebulaFilament {
  id: string
  kind: 'similarity' | 'lineage'
  from: readonly [number, number, number]
  to: readonly [number, number, number]
  color: readonly [number, number, number]
}

export interface NebulaCreatureFamily {
  id: string
  memory_ids: string[]
  center: readonly [number, number, number]
  stipple_count: number
  split_events: number
  merge_events: number
  phase: number
}

export const NEBULA_EVENT_COLORS: Record<NebulaEventClass, readonly [number, number, number]> = {
  add: [0.55, 0.31, 0.96],
  delete: [1, 0.35, 0.34],
  modify: [0.96, 0.68, 0.25],
  merge: [0.28, 0.91, 0.78],
  split: [0.98, 0.42, 0.68],
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
    'Glow · memory.updated_at at snapshot time',
    'Brightness · memory.pin or current-context membership',
    'Filament · real similarity or lineage edge',
    'Stipple family · similarity-connected graph cluster at latest event positions',
  ],
  current: [
    'Particle · one memory revision event (never decorative)',
    'Hue · add / delete / modify / merge / split',
    'Curve position · event timestamp; density · event rate',
    'No revision event · no particle; replay · identical current',
  ],
} as const

export function buildNebulaBodies(
  snapshot: PalaceNebulaSnapshot,
  axis: NebulaAxisMode,
  asOfMs = timestamp(snapshot.as_of),
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
    const ageDays = updated === 0 || asOfMs === 0
      ? Number.POSITIVE_INFINITY
      : Math.max(0, asOfMs - updated) / 86_400_000
    const position = axis === 'activity'
      ? [
          spread(rank(created, index), 9),
          spread(normalizeLog(injection, injections), 7),
          spread(normalize(revision, revisions), 6),
        ] as const
      : [
          spread(identity(node.memory.project_key), 9),
          spread(identity(node.memory.origin_thread_id ?? node.memory.thread_origin), 7),
          spread(normalize(pathDepths[index], pathDepths), 6),
        ] as const
    const radius = 0.28 + 0.17 * Math.log2(injection + 1)
    const stretch = 1 + Math.min(revision, 12) * 0.055
    return {
      id: node.memory.memory_id,
      label: node.memory.label,
      kind: node.memory.kind,
      position,
      scale: [radius, radius * stretch, radius],
      color: colorForKind(node.memory.kind),
      recency_glow: 0.18 + 0.82 / (1 + ageDays / 14),
      pinned: node.memory.pin,
      in_current_context: node.in_current_context,
    }
  })
}

export function buildNebulaEvents(snapshot: PalaceNebulaSnapshot): NebulaMemoryEvent[] {
  const raw = snapshot.nodes.flatMap((node) => node.revisions.map((revision) => ({
    node,
    revision,
    timestamp: timestamp(revision.ts),
  }))).sort((left, right) => (
    left.timestamp - right.timestamp ||
    left.node.memory.memory_id.localeCompare(right.node.memory.memory_id) ||
    left.revision.rev_uid.localeCompare(right.revision.rev_uid)
  ))
  const times = raw.map((event) => event.timestamp)
  return raw.map(({ node, revision, timestamp: eventTime }, index) => {
    const progress = times.length <= 1 ? 0.5 : normalizeRange(eventTime, times)
    const lane = ((stableHash(`${node.memory.memory_id}:${revision.rev_uid}`) % 10_001) / 10_000) - 0.5
    const eventClass = classifyRevision(revision)
    return {
      id: `${node.memory.memory_id}:${revision.rev_uid}`,
      memory_id: node.memory.memory_id,
      memory_label: node.memory.label,
      event_class: eventClass,
      reason: revision.reason,
      ts: revision.ts,
      position: [
        -7.5 + progress * 15,
        -3.1 + Math.sin(progress * Math.PI) * 6.2 + lane * 1.15,
        -1.8 + lane * 4.6 + (index % 3) * 0.08,
      ],
      color: NEBULA_EVENT_COLORS[eventClass],
    }
  })
}

export function buildNebulaFilaments(
  snapshot: PalaceNebulaSnapshot,
  bodies: readonly NebulaBody[],
): NebulaFilament[] {
  const positions = new Map(bodies.map((body) => [body.id, body.position]))
  return (snapshot.edges ?? []).flatMap((edge, index) => {
    if (edge.kind === 'edit_trail' || edge.from_memory_id === edge.to_memory_id) return []
    const from = positions.get(edge.from_memory_id)
    const to = positions.get(edge.to_memory_id)
    if (from === undefined || to === undefined) return []
    return [{
      id: `${edge.kind}:${edge.from_memory_id}:${edge.to_memory_id}:${index}`,
      kind: edge.kind,
      from,
      to,
      color: edge.kind === 'lineage' ? [0.96, 0.66, 0.34] : [0.65, 0.72, 0.92],
    } satisfies NebulaFilament]
  })
}

export function buildNebulaCreatureFamilies(
  snapshot: PalaceNebulaSnapshot,
  bodies: readonly NebulaBody[],
  events: readonly NebulaMemoryEvent[],
): NebulaCreatureFamily[] {
  const graphIds = new Set(snapshot.nodes.map((node) => node.memory.memory_id))
  const adjacency = new Map([...graphIds].map((id) => [id, new Set<string>()]))
  for (const edge of snapshot.edges ?? []) {
    if (edge.kind !== 'similarity' || !graphIds.has(edge.from_memory_id) || !graphIds.has(edge.to_memory_id)) continue
    adjacency.get(edge.from_memory_id)?.add(edge.to_memory_id)
    adjacency.get(edge.to_memory_id)?.add(edge.from_memory_id)
  }
  const positions = new Map<string, readonly [number, number, number]>(bodies.map((body) => [body.id, body.position]))
  for (const event of events) positions.set(event.memory_id, event.position)
  const visited = new Set<string>()
  const families: NebulaCreatureFamily[] = []
  for (const id of [...graphIds].sort()) {
    if (visited.has(id)) continue
    const pending = [id]
    const members: string[] = []
    while (pending.length > 0) {
      const current = pending.pop()!
      if (visited.has(current)) continue
      visited.add(current)
      members.push(current)
      pending.push(...[...(adjacency.get(current) ?? [])].sort().reverse())
    }
    if (members.length < 2) continue
    members.sort()
    const anchors = members.flatMap((member) => {
      const position = positions.get(member)
      return position === undefined ? [] : [position]
    })
    if (anchors.length === 0) continue
    const center = anchors.reduce<[number, number, number]>((sum, position) => {
      return [sum[0] + position[0], sum[1] + position[1], sum[2] + position[2]]
    }, [0, 0, 0]).map((value) => value / anchors.length) as [number, number, number]
    const familyEvents = events.filter((event) => members.includes(event.memory_id))
    const familyId = members.join(':')
    families.push({
      id: familyId,
      memory_ids: members,
      center,
      stipple_count: members.length * 48,
      split_events: familyEvents.filter((event) => event.event_class === 'split').length,
      merge_events: familyEvents.filter((event) => event.event_class === 'merge').length,
      phase: ((stableHash(familyId) % 10_001) / 10_000) * Math.PI * 2,
    })
  }
  return families
}

function classifyRevision(revision: RevisionTrailItem): NebulaEventClass {
  const reason = revision.reason.toLowerCase()
  if (reason.includes('split')) return 'split'
  if (reason.includes('merge')) return 'merge'
  if (/tombstone|retire|delete|denied|loser/u.test(reason)) return 'delete'
  if (revision.parent_uid === null || revision.revision === 1) return 'add'
  return 'modify'
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

function normalizeRange(value: number, values: readonly number[]): number {
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
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

function spread(value: number, extent: number): number {
  return (value - 0.5) * extent
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
