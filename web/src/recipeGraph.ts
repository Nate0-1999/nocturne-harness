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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
