export const LAYOUT_SWEEP_WIDTHS = [390, 480, 768, 1024, 1280, 1440, 1920] as const

export interface LayoutAuditRect {
  x: number
  y: number
  width: number
  height: number
}

export interface LayoutAuditNode {
  id: string
  label: string
  scope: string
  rect: LayoutAuditRect
  interactive: boolean
  clipped: boolean
}

export interface LayoutCollision {
  first: LayoutAuditNode
  second: LayoutAuditNode
  overlap_width: number
  overlap_height: number
}

export interface LayoutAuditResult {
  collisions: LayoutCollision[]
  clipped: LayoutAuditNode[]
}

const EDGE_TOLERANCE_PX = 0.5

export function auditLayout(nodes: readonly LayoutAuditNode[]): LayoutAuditResult {
  const collisions: LayoutCollision[] = []
  for (let firstIndex = 0; firstIndex < nodes.length; firstIndex += 1) {
    const first = nodes[firstIndex]
    if (!first.interactive) {
      continue
    }
    for (let secondIndex = firstIndex + 1; secondIndex < nodes.length; secondIndex += 1) {
      const second = nodes[secondIndex]
      if (!second.interactive) {
        continue
      }
      const overlapWidth = Math.min(
        first.rect.x + first.rect.width,
        second.rect.x + second.rect.width,
      ) - Math.max(first.rect.x, second.rect.x)
      const overlapHeight = Math.min(
        first.rect.y + first.rect.height,
        second.rect.y + second.rect.height,
      ) - Math.max(first.rect.y, second.rect.y)
      if (overlapWidth > EDGE_TOLERANCE_PX && overlapHeight > EDGE_TOLERANCE_PX) {
        collisions.push({
          first,
          second,
          overlap_width: overlapWidth,
          overlap_height: overlapHeight,
        })
      }
    }
  }
  return {
    collisions,
    clipped: nodes.filter((node) => node.clipped),
  }
}
