export type RecipeNodeKind = 'packet' | 'search' | 'judge'
export type RecipeNodeState =
  | 'blocked'
  | 'ready'
  | 'running'
  | 'review'
  | 'passed'
  | 'failed'
  | 'cancelled'

export interface RecipeGraphNode {
  node_id: string
  label: string
  kind: RecipeNodeKind
  state: RecipeNodeState
  bead_id: string | null
  motivation: string | null
}

export interface RecipeGraphEdge {
  source: string
  target: string
  kind: 'blocks' | 'judged_by'
}

export interface RecipeGraphSnapshot {
  schema_version: 1
  revision: number
  as_of: string
  packet_id: string | null
  bead_id: string | null
  nodes: RecipeGraphNode[]
  edges: RecipeGraphEdge[]
  ready_node_ids: string[]
}

export interface RecipeNodePosition {
  node_id: string
  x: number
  y: number
  depth: number
}

export interface RecipeCompletionCell {
  node_id: string
  judge_node_ids: string[]
  input_node_ids: string[]
  column: number
  row_start: number
  row_span: number
}

export interface RecipeCompletionGrid {
  rows: RecipeGraphNode[]
  cells: RecipeCompletionCell[]
  milestone_column: number
  milestone_state: RecipeNodeState
}

const NODE_KINDS = new Set<RecipeNodeKind>(['packet', 'search', 'judge'])
const NODE_STATES = new Set<RecipeNodeState>([
  'blocked', 'ready', 'running', 'review', 'passed', 'failed', 'cancelled',
])
const EDGE_KINDS = new Set<RecipeGraphEdge['kind']>(['blocks', 'judged_by'])

export function parseRecipeGraphSnapshot(value: unknown): RecipeGraphSnapshot {
  if (!isRecord(value) || value.schema_version !== 1 || !Number.isInteger(value.revision)) {
    throw new TypeError('Recipe query returned an unsupported graph')
  }
  if (
    typeof value.as_of !== 'string' ||
    !nullableString(value.packet_id) ||
    !nullableString(value.bead_id) ||
    !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges) ||
    !Array.isArray(value.ready_node_ids)
  ) {
    throw new TypeError('Recipe query returned a malformed graph')
  }

  const nodes = value.nodes.map(parseNode)
  const edges = value.edges.map(parseEdge)
  const readyNodeIds = stringArray(value.ready_node_ids, 'ready frontier')
  const known = new Set(nodes.map((node) => node.node_id))
  if (
    known.size !== nodes.length ||
    edges.some((edge) => !known.has(edge.source) || !known.has(edge.target)) ||
    readyNodeIds.some((nodeId) => !known.has(nodeId))
  ) {
    throw new TypeError('Recipe graph identities do not join')
  }
  const visibleReady = nodes
    .filter((node) => node.state === 'ready')
    .map((node) => node.node_id)
  if (!sameSet(readyNodeIds, visibleReady)) {
    throw new TypeError('Recipe ready frontier disagrees with visible state')
  }
  assertAcyclic(nodes, edges)

  return {
    schema_version: 1,
    revision: value.revision as number,
    as_of: value.as_of,
    packet_id: value.packet_id,
    bead_id: value.bead_id,
    nodes,
    edges,
    ready_node_ids: readyNodeIds,
  }
}

export function buildRecipeCompletionGrid(snapshot: RecipeGraphSnapshot): RecipeCompletionGrid {
  const order = new Map(snapshot.nodes.map((node, index) => [node.node_id, index]))
  const packets = snapshot.nodes.filter((node) => node.kind !== 'judge')
  const packetIds = new Set(packets.map((node) => node.node_id))
  const dependencies = new Map(packets.map((node) => [node.node_id, [] as string[]]))
  const downstream = new Map(packets.map((node) => [node.node_id, [] as string[]]))
  const judges = new Map(packets.map((node) => [node.node_id, [] as string[]]))

  for (const edge of snapshot.edges) {
    if (edge.kind === 'blocks' && packetIds.has(edge.source) && packetIds.has(edge.target)) {
      dependencies.get(edge.target)?.push(edge.source)
      downstream.get(edge.source)?.push(edge.target)
    } else if (edge.kind === 'judged_by' && packetIds.has(edge.source)) {
      judges.get(edge.source)?.push(edge.target)
    }
  }
  for (const values of [...dependencies.values(), ...downstream.values(), ...judges.values()]) {
    values.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0))
  }

  const rowIds: string[] = []
  const visited = new Set<string>()
  function placeWithInputs(nodeId: string) {
    if (visited.has(nodeId)) return
    for (const dependency of dependencies.get(nodeId) ?? []) placeWithInputs(dependency)
    visited.add(nodeId)
    rowIds.push(nodeId)
  }
  const terminals = packets
    .filter((node) => (downstream.get(node.node_id) ?? []).length === 0)
    .sort((left, right) => (order.get(left.node_id) ?? 0) - (order.get(right.node_id) ?? 0))
  for (const node of terminals) placeWithInputs(node.node_id)
  for (const node of packets) placeWithInputs(node.node_id)

  const rows = rowIds.map((nodeId) => packets.find((node) => node.node_id === nodeId)!)
  const rowIndex = new Map(rows.map((node, index) => [node.node_id, index + 1]))
  const depths = new Map<string, number>()
  function depthOf(nodeId: string): number {
    const known = depths.get(nodeId)
    if (known !== undefined) return known
    const inputs = dependencies.get(nodeId) ?? []
    const depth = inputs.length === 0 ? 0 : Math.max(...inputs.map(depthOf)) + 1
    depths.set(nodeId, depth)
    return depth
  }

  const ancestry = new Map<string, Set<string>>()
  function inputsFor(nodeId: string): Set<string> {
    const known = ancestry.get(nodeId)
    if (known !== undefined) return known
    const result = new Set<string>([nodeId])
    for (const dependency of dependencies.get(nodeId) ?? []) {
      for (const input of inputsFor(dependency)) result.add(input)
    }
    ancestry.set(nodeId, result)
    return result
  }

  const occupied = new Map<number, Set<number>>()
  const cells: RecipeCompletionCell[] = []
  const staged = packets
    .filter((node) => (dependencies.get(node.node_id) ?? []).length > 0)
    .sort((left, right) => depthOf(left.node_id) - depthOf(right.node_id) ||
      (rowIndex.get(left.node_id) ?? 0) - (rowIndex.get(right.node_id) ?? 0))
  for (const node of staged) {
    const inputNodeIds = [...inputsFor(node.node_id)]
      .sort((left, right) => (rowIndex.get(left) ?? 0) - (rowIndex.get(right) ?? 0))
    const inputRows = inputNodeIds.map((nodeId) => rowIndex.get(nodeId)!)
    const rowStart = Math.min(...inputRows)
    const rowEnd = Math.max(...inputRows)
    let column = depthOf(node.node_id) + 2
    while ([...Array(rowEnd - rowStart + 1)].some((_, offset) => (
      occupied.get(column)?.has(rowStart + offset) ?? false
    ))) column += 1
    const columnRows = occupied.get(column) ?? new Set<number>()
    for (let row = rowStart; row <= rowEnd; row += 1) columnRows.add(row)
    occupied.set(column, columnRows)
    cells.push({
      node_id: node.node_id,
      judge_node_ids: judges.get(node.node_id) ?? [],
      input_node_ids: inputNodeIds,
      column,
      row_start: rowStart,
      row_span: rowEnd - rowStart + 1,
    })
  }

  return {
    rows,
    cells,
    milestone_column: Math.max(3, ...cells.map((cell) => cell.column + 1)),
    milestone_state: milestoneState(snapshot.nodes),
  }
}

export function layoutRecipeGraph(snapshot: RecipeGraphSnapshot): RecipeNodePosition[] {
  const order = new Map(snapshot.nodes.map((node, index) => [node.node_id, index]))
  const incoming = new Map(snapshot.nodes.map((node) => [node.node_id, [] as string[]]))
  for (const edge of snapshot.edges) {
    incoming.get(edge.target)?.push(edge.source)
  }
  const depths = new Map<string, number>()
  const unresolved = new Set(snapshot.nodes.map((node) => node.node_id))
  while (unresolved.size > 0) {
    let progressed = false
    for (const nodeId of unresolved) {
      const dependencies = incoming.get(nodeId) ?? []
      if (dependencies.every((dependency) => depths.has(dependency))) {
        depths.set(
          nodeId,
          dependencies.length === 0
            ? 0
            : Math.max(...dependencies.map((dependency) => depths.get(dependency) ?? 0)) + 1,
        )
        unresolved.delete(nodeId)
        progressed = true
      }
    }
    if (!progressed) {
      for (const nodeId of unresolved) depths.set(nodeId, 0)
      break
    }
  }

  const columns = new Map<number, string[]>()
  for (const node of snapshot.nodes) {
    const depth = depths.get(node.node_id) ?? 0
    columns.set(depth, [...(columns.get(depth) ?? []), node.node_id])
  }
  const maxDepth = Math.max(0, ...columns.keys())
  const result: RecipeNodePosition[] = []
  for (const [depth, nodeIds] of [...columns].sort(([left], [right]) => left - right)) {
    nodeIds.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0))
    for (const [index, nodeId] of nodeIds.entries()) {
      result.push({
        node_id: nodeId,
        x: maxDepth === 0 ? 50 : 10 + (depth / maxDepth) * 68,
        y: 10 + ((index + 1) / (nodeIds.length + 1)) * 54,
        depth,
      })
    }
  }
  return result
}

function parseNode(value: unknown): RecipeGraphNode {
  if (
    !isRecord(value) ||
    typeof value.node_id !== 'string' || !value.node_id.trim() ||
    typeof value.label !== 'string' || !value.label.trim() ||
    typeof value.kind !== 'string' || !NODE_KINDS.has(value.kind as RecipeNodeKind) ||
    typeof value.state !== 'string' || !NODE_STATES.has(value.state as RecipeNodeState) ||
    !nullableString(value.bead_id) ||
    !nullableString(value.motivation)
  ) {
    throw new TypeError('Recipe query returned a malformed node')
  }
  return value as unknown as RecipeGraphNode
}

function parseEdge(value: unknown): RecipeGraphEdge {
  if (
    !isRecord(value) ||
    typeof value.source !== 'string' ||
    typeof value.target !== 'string' ||
    typeof value.kind !== 'string' || !EDGE_KINDS.has(value.kind as RecipeGraphEdge['kind'])
  ) {
    throw new TypeError('Recipe query returned a malformed edge')
  }
  return value as unknown as RecipeGraphEdge
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function stringArray(value: unknown[], label: string): string[] {
  if (value.some((item) => typeof item !== 'string')) {
    throw new TypeError(`Recipe ${label} must contain identities`)
  }
  return value as string[]
}

function sameSet(left: string[], right: string[]): boolean {
  return left.length === right.length && new Set(left).size === left.length &&
    left.every((item) => right.includes(item))
}

function assertAcyclic(nodes: RecipeGraphNode[], edges: RecipeGraphEdge[]) {
  const incoming = new Map(nodes.map((node) => [node.node_id, 0]))
  const outgoing = new Map(nodes.map((node) => [node.node_id, [] as string[]]))
  for (const edge of edges) {
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1)
    outgoing.get(edge.source)?.push(edge.target)
  }
  const ready = [...incoming].filter(([, count]) => count === 0).map(([nodeId]) => nodeId)
  let seen = 0
  while (ready.length > 0) {
    const nodeId = ready.shift()!
    seen += 1
    for (const target of outgoing.get(nodeId) ?? []) {
      const count = (incoming.get(target) ?? 0) - 1
      incoming.set(target, count)
      if (count === 0) ready.push(target)
    }
  }
  if (seen !== nodes.length) throw new TypeError('Recipe graph must remain a DAG')
}

function milestoneState(nodes: RecipeGraphNode[]): RecipeNodeState {
  if (nodes.length > 0 && nodes.every((node) => node.state === 'passed')) return 'passed'
  if (nodes.some((node) => node.state === 'failed')) return 'failed'
  if (nodes.some((node) => node.state === 'running' || node.state === 'review')) return 'running'
  if (nodes.some((node) => node.state === 'ready')) return 'ready'
  if (nodes.length > 0 && nodes.every((node) => (
    node.state === 'passed' || node.state === 'cancelled'
  ))) return 'cancelled'
  return 'blocked'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
