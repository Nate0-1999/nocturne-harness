export interface GraphLabelCandidate {
  id: string
  label: string
  x: number
  y: number
  radius: number
  selected: boolean
  current: boolean
  pinned: boolean
  injections: number
}

export interface VisibleGraphLabel {
  id: string
  text: string
  x: number
  y: number
  priority: number
  box: { left: number; right: number; top: number; bottom: number }
}

const VIEWBOX_WIDTH = 100
const VIEWBOX_HEIGHT = 76
const MAX_CHARACTERS = 17
const CHARACTER_WIDTH = 1.05
const LABEL_HEIGHT = 3.2
const COLLISION_GAP = 1.5

/** PLAN M2ST3 finding 7a: higher-signal graph labels win; colliding labels stay hidden. */
export function declutterGraphLabels(
  candidates: readonly GraphLabelCandidate[],
): VisibleGraphLabel[] {
  const accepted: VisibleGraphLabel[] = []
  const ordered = [...candidates].sort((left, right) => (
    priority(right) - priority(left) || left.id.localeCompare(right.id)
  ))

  // The graph grows a row at a time; the lowest row's labels still fit below their nodes.
  const bottom = Math.max(VIEWBOX_HEIGHT, ...candidates.map((candidate) => candidate.y + candidate.radius + 6))
  for (const candidate of ordered) {
    const text = compactLabel(candidate.label)
    const width = Math.min(18, Math.max(4, text.length * CHARACTER_WIDTH))
    const below = candidate.y + candidate.radius + 4
    const above = candidate.y - candidate.radius - 2
    const x = clamp(candidate.x, width / 2 + 1, VIEWBOX_WIDTH - width / 2 - 1)
    // TASTE-06: a label that collides below its node tries above before it stays hidden.
    const placed = (below + 1 > bottom ? [above] : [below, above]).map((y) => ({
      y,
      box: { left: x - width / 2, right: x + width / 2, top: y - LABEL_HEIGHT, bottom: y + 0.6 },
    })).find(({ box }) => box.top >= 0 && !accepted.some((label) => boxesOverlap(box, label.box)))
    if (placed === undefined) {
      continue
    }
    accepted.push({ id: candidate.id, text, x, y: placed.y, priority: priority(candidate), box: placed.box })
  }

  return accepted.sort((left, right) => left.id.localeCompare(right.id))
}

function compactLabel(value: string): string {
  const normalized = value.trim().replace(/\s+/g, ' ')
  return normalized.length <= MAX_CHARACTERS
    ? normalized
    : `${normalized.slice(0, MAX_CHARACTERS - 1).trimEnd()}…`
}

function priority(candidate: GraphLabelCandidate): number {
  return (
    (candidate.selected ? 10_000 : 0) +
    (candidate.current ? 4_000 : 0) +
    (candidate.pinned ? 2_000 : 0) +
    Math.min(Math.max(candidate.injections, 0), 999)
  )
}

function boxesOverlap(
  left: VisibleGraphLabel['box'],
  right: VisibleGraphLabel['box'],
): boolean {
  return !(
    left.right + COLLISION_GAP <= right.left ||
    right.right + COLLISION_GAP <= left.left ||
    left.bottom + COLLISION_GAP <= right.top ||
    right.bottom + COLLISION_GAP <= left.top
  )
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}
