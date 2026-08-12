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
  text_renderer?: 'dom' | 'svg' | 'canvas'
  text_surface?: string
}

export interface LayoutCollision {
  first: LayoutAuditNode
  second: LayoutAuditNode
  overlap_width: number
  overlap_height: number
}

export interface LayoutTextCollision {
  first: LayoutAuditNode
  second: LayoutAuditNode
  overlap_width: number
  overlap_height: number
}

export interface LayoutAuditResult {
  collisions: LayoutCollision[]
  clipped: LayoutAuditNode[]
  text_collisions: LayoutTextCollision[]
}

const EDGE_TOLERANCE_PX = 0.5

export function auditLayout(nodes: readonly LayoutAuditNode[]): LayoutAuditResult {
  const collisions: LayoutCollision[] = []
  const textCollisions: LayoutTextCollision[] = []
  for (let firstIndex = 0; firstIndex < nodes.length; firstIndex += 1) {
    const first = nodes[firstIndex]
    for (let secondIndex = firstIndex + 1; secondIndex < nodes.length; secondIndex += 1) {
      const second = nodes[secondIndex]
      const { overlapWidth, overlapHeight } = overlap(first.rect, second.rect)
      if (
        first.interactive &&
        second.interactive &&
        overlapWidth > EDGE_TOLERANCE_PX &&
        overlapHeight > EDGE_TOLERANCE_PX
      ) {
        collisions.push({
          first,
          second,
          overlap_width: overlapWidth,
          overlap_height: overlapHeight,
        })
      }
      if (
        first.text_renderer !== undefined &&
        first.text_renderer !== 'dom' &&
        second.text_renderer !== undefined &&
        second.text_renderer !== 'dom' &&
        first.text_surface !== undefined &&
        first.text_surface === second.text_surface &&
        overlapWidth > EDGE_TOLERANCE_PX &&
        overlapHeight > EDGE_TOLERANCE_PX
      ) {
        textCollisions.push({
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
    text_collisions: textCollisions,
  }
}

function overlap(first: LayoutAuditRect, second: LayoutAuditRect) {
  return {
    overlapWidth: Math.min(
      first.x + first.width,
      second.x + second.width,
    ) - Math.max(first.x, second.x),
    overlapHeight: Math.min(
      first.y + first.height,
      second.y + second.height,
    ) - Math.max(first.y, second.y),
  }
}
