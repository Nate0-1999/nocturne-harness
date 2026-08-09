export interface MemoryGraphSelectableNode {
  memory: { memory_id: string }
}

export type MemoryGraphScope = 'GLOBAL' | 'CURRENT'

export interface KeyedMemoryGraphSnapshot<SnapshotType> {
  requestKey: string
  data: SnapshotType
}

export function memoryGraphRequestKey(
  scope: MemoryGraphScope,
  selectedThreadId: string | null,
): string {
  return JSON.stringify({
    scope,
    thread_id: scope === 'CURRENT' ? selectedThreadId : null,
  })
}

export function memoryGraphRequestIsQueryable(
  scope: MemoryGraphScope,
  selectedThreadId: string | null,
): boolean {
  return scope === 'GLOBAL' || selectedThreadId !== null
}

export function memoryGraphSnapshotForRequest<SnapshotType>(
  loaded: KeyedMemoryGraphSnapshot<SnapshotType> | null,
  requestKey: string,
): SnapshotType | null {
  return loaded?.requestKey === requestKey ? loaded.data : null
}

export function reconcileMemoryGraphSelection<
  NodeType extends MemoryGraphSelectableNode,
>(
  selected: NodeType | null,
  nodes: readonly NodeType[],
): NodeType | null {
  if (selected === null) {
    return null
  }
  return nodes.find(
    (node) => node.memory.memory_id === selected.memory.memory_id,
  ) ?? null
}
