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
    origin_location?: string | null
    created_at?: string | null
    updated_at?: string | null
    stats: { injections?: number }
    keywords?: string[]
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
  injections: number
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
  kind: 'lineage' | 'thread' | 'keyword'
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
  radial: [
    'Radius · 8 / (1 + injections); most-injected memories gather centrally',
    'Angle · related family, then creation order within that family',
    'Depth · memory.revision (linear scale)',
    'Color · memory.kind (deterministic palette)',
    'Shape · memory.revision (vertical stretch)',
  ],
  shared: [
    'Size · memory.stats.injections (log scale)',
    'Glow · memory.updated_at at snapshot time',
    'Brightness · memory.pin or current-context membership',
    'Filament · lineage; nearest links sharing an origin thread or keyword',
    'Family · connected by similarity, thread or keyword; curator streams join visited families',
  ],
  current: [
    'Particle · one memory revision event (never decorative)',
    'Hue · add / delete / modify / merge / split',
    'Curve around its memory · event timestamp; density · event rate',
    'No revision event · no particle; replay · identical current',
  ],
} as const

export function buildNebulaBodies(
  snapshot: PalaceNebulaSnapshot,
  asOfMs = timestamp(snapshot.as_of),
): NebulaBody[] {
  const active = snapshot.nodes.filter((node) => node.memory.status === 'active')
  const injections = active.map(injectionCount)
  const revisions = active.map((node) => Math.max(0, node.memory.revision))
  const families = memoryFamilies(snapshot).map((members) => active
    .filter((node) => members.includes(node.memory.memory_id))
    .sort((a, b) => timestamp(a.memory.created_at) - timestamp(b.memory.created_at)
      || a.memory.memory_id.localeCompare(b.memory.memory_id))).filter((members) => members.length)
  const angles = new Map(families.flatMap((members, family) => members.map((node, order) => [
    node.memory.memory_id,
    -Math.PI / 2 + (family + (order + 0.5) / members.length) / families.length * Math.PI * 2,
  ] as const)))

  return active.map((node, index) => {
    const injection = injections[index]
    const revision = revisions[index]
    const updated = timestamp(node.memory.updated_at)
    const ageDays = updated === 0 || asOfMs === 0
      ? Number.POSITIVE_INFINITY
      : Math.max(0, asOfMs - updated) / 86_400_000
    const orbit = 8 / (1 + injection), angle = angles.get(node.memory.memory_id)!
    const position = [Math.cos(angle) * orbit, Math.sin(angle) * orbit,
      spread(normalize(revision, revisions), 4)] as const
    const radius = 0.12 + 0.34 * Math.log2(injection + 1)
    const stretch = 1 + Math.min(revision, 12) * 0.015
    return {
      id: node.memory.memory_id,
      label: node.memory.label,
      kind: node.memory.kind,
      position,
      scale: [radius, radius * stretch, radius],
      color: colorForKind(node.memory.kind),
      recency_glow: 0.18 + 0.82 / (1 + ageDays / 14),
      injections: injection,
      pinned: node.memory.pin,
      in_current_context: node.in_current_context,
    }
  })
}

export function buildNebulaEvents(snapshot: PalaceNebulaSnapshot): NebulaMemoryEvent[] {
  const anchors = new Map(buildNebulaBodies({ ...snapshot, nodes: snapshot.nodes.map((node) => ({
    ...node, memory: { ...node.memory, status: 'active' },
  })) }).map((body) => [body.id, body]))
  for (const body of buildNebulaBodies(snapshot)) anchors.set(body.id, body)
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
  return raw.map(({ node, revision, timestamp: eventTime }) => {
    const progress = times.length <= 1 ? 0.5 : normalizeRange(eventTime, times)
    const body = anchors.get(node.memory.memory_id)!
    const angle = progress * Math.PI * 2, radius = body.scale[1] + 0.15
    const eventClass = classifyRevision(revision)
    return {
      id: `${node.memory.memory_id}:${revision.rev_uid}`,
      memory_id: node.memory.memory_id,
      memory_label: node.memory.label,
      event_class: eventClass,
      reason: revision.reason,
      ts: revision.ts,
      position: [
        body.position[0] + Math.cos(angle) * radius,
        body.position[1] + Math.sin(angle) * radius,
        body.position[2] - (node.memory.revision - (revision.revision ?? 1)) * 0.12,
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
  const filaments: NebulaFilament[] = (snapshot.edges ?? []).flatMap((edge, index) => {
    if (edge.kind !== 'lineage' || edge.from_memory_id === edge.to_memory_id) return []
    const from = positions.get(edge.from_memory_id)
    const to = positions.get(edge.to_memory_id)
    if (from === undefined || to === undefined) return []
    return [{
      id: `${edge.kind}:${edge.from_memory_id}:${edge.to_memory_id}:${index}`,
      kind: edge.kind,
      from,
      to,
      color: [0.96, 0.86, 0.74],
    } satisfies NebulaFilament]
  })
  const seen = new Set<string>()
  for (const [key, nodes] of sharedMemoryGroups(snapshot)) {
    const members = nodes.filter((node) => positions.has(node.memory.memory_id))
      .sort((a, b) => injectionCount(b) - injectionCount(a) || a.memory.memory_id.localeCompare(b.memory.memory_id))
    for (let index = 1; index < members.length; index++) {
      const id = members[index].memory.memory_id, from = positions.get(id)!
      const distance = (node: PalaceMemoryNode) => positions.get(node.memory.memory_id)!
        .reduce((sum, value, axis) => sum + (value - from[axis]) ** 2, 0)
      for (const neighbor of members.slice(0, index).sort((a, b) => distance(a) - distance(b)).slice(0, 3)) {
        const other = neighbor.memory.memory_id, pair = [id, other].sort().join(':')
        if (seen.has(pair)) continue
        seen.add(pair)
        const kind = key.startsWith('thread:') ? 'thread' : 'keyword'
        filaments.push({ id: `${kind}:${pair}`, kind, from, to: positions.get(other)!,
          color: kind === 'thread' ? [0.65, 0.72, 0.92] : [0.78, 0.8, 0.88] })
      }
    }
  }
  return filaments
}

function sharedMemoryGroups(snapshot: PalaceNebulaSnapshot): Map<string, PalaceMemoryNode[]> {
  const groups = new Map<string, PalaceMemoryNode[]>()
  for (const node of snapshot.nodes) {
    const thread = node.memory.origin_thread_id ?? node.memory.thread_origin
    const keys = (node.memory.keywords ?? []).map((keyword) => keyword.trim().toLowerCase())
      .filter(Boolean).map((keyword) => `keyword:${keyword}`)
    if (thread) keys.unshift(`thread:${thread}`)
    for (const key of new Set(keys)) groups.set(key, [...(groups.get(key) ?? []), node])
  }
  return groups
}

function memoryFamilies(snapshot: PalaceNebulaSnapshot): string[][] {
  const graphIds = new Set(snapshot.nodes.map((node) => node.memory.memory_id))
  const adjacency = new Map([...graphIds].map((id) => [id, new Set<string>()]))
  for (const edge of snapshot.edges ?? []) {
    if (edge.kind !== 'similarity' || !graphIds.has(edge.from_memory_id) || !graphIds.has(edge.to_memory_id)) continue
    adjacency.get(edge.from_memory_id)?.add(edge.to_memory_id)
    adjacency.get(edge.to_memory_id)?.add(edge.from_memory_id)
  }
  for (const members of sharedMemoryGroups(snapshot).values()) {
    for (let index = 1; index < members.length; index++) {
      const a = members[index - 1].memory.memory_id, b = members[index].memory.memory_id
      adjacency.get(a)?.add(b); adjacency.get(b)?.add(a)
    }
  }
  const visited = new Set<string>()
  const families: string[][] = []
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
    members.sort()
    families.push(members)
  }
  return families
}

export function buildNebulaCreatureFamilies(
  snapshot: PalaceNebulaSnapshot,
  bodies: readonly NebulaBody[],
  events: readonly NebulaMemoryEvent[],
): NebulaCreatureFamily[] {
  const positions = new Map<string, readonly [number, number, number]>()
  for (const event of events) positions.set(event.memory_id, event.position)
  for (const body of bodies) positions.set(body.id, body.position)
  const families: NebulaCreatureFamily[] = []
  for (const members of memoryFamilies(snapshot)) {
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
      stipple_count: members.length > 1 ? members.length * 48 : 0,
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

function spread(value: number, extent: number): number {
  return (value - 0.5) * extent
}

function colorForKind(kind: string): readonly [number, number, number] {
  const hue = (200 + stableHash(kind) % 65) / 360
  return hslToRgb(hue, 0.82, 0.36)
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
