export interface SpatialModuleRect {
  module_id: string
  x: number
  y: number
  width: number
  height: number
}

export interface SpatialAddress {
  layer_id: string
  frame_id: string
}

export interface SpatialSelectionContext extends SpatialAddress {
  scope: 'GLOBAL' | 'ATTUNED'
}

/** Resolve snap-touching modules into deterministic proximity frames. */
export function spatialAddresses(
  layerId: string,
  modules: readonly SpatialModuleRect[],
): Map<string, SpatialAddress> {
  const remaining = new Set(modules.map((module) => module.module_id))
  const byId = new Map(modules.map((module) => [module.module_id, module]))
  const result = new Map<string, SpatialAddress>()

  while (remaining.size > 0) {
    const seed = [...remaining].sort()[0]
    const members = new Set([seed])
    const queue = [seed]
    remaining.delete(seed)
    while (queue.length > 0) {
      const current = byId.get(queue.shift()!)!
      for (const candidateId of [...remaining]) {
        const candidate = byId.get(candidateId)!
        if (rectanglesTouch(current, candidate)) {
          members.add(candidateId)
          queue.push(candidateId)
          remaining.delete(candidateId)
        }
      }
    }
    const frameId = `${layerId}:${[...members].sort().join('+')}`
    for (const member of members) {
      result.set(member, { layer_id: layerId, frame_id: frameId })
    }
  }
  return result
}

/** GLOBAL is the one escape; attuned watchers see only their resolved frame. */
export function spatialSelectionIsVisible(
  origin: SpatialAddress | null,
  target: SpatialSelectionContext,
): boolean {
  return origin === null || target.scope === 'GLOBAL' || (
    origin.layer_id === target.layer_id && origin.frame_id === target.frame_id
  )
}

function rectanglesTouch(left: SpatialModuleRect, right: SpatialModuleRect): boolean {
  const separated =
    left.x + left.width < right.x ||
    right.x + right.width < left.x ||
    left.y + left.height < right.y ||
    right.y + right.height < left.y
  return !separated
}
