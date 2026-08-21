import type { RackBounds } from './rackLayout'
import { STAGE_COLUMNS, STAGE_ROWS } from './stageLayout.ts'

export type StageRackModuleId =
  | 'threads'
  | 'chat'
  | 'memory'
  | 'vitals'
  | 'context_bars'
  | 'memory_graph'
  | 'palace_nebula'
  | 'injection_console'
  | 'palace_queue'
  | 'recipe'
  | 'deck'

export type RackResizeDirection = 'n' | 'e' | 's' | 'w' | 'ne' | 'se' | 'sw' | 'nw'

export interface RackTemplateManifest {
  id: string
  name: string
  slot: 'header' | 'panel' | 'strip' | 'overlay'
  bounds: RackBounds
  movable: boolean
}

export function stageGridBounds(preferred: RackBounds['preferred']): RackBounds {
  return {
    min: { w: 1, h: 1 },
    preferred: { ...preferred },
    max: { w: STAGE_COLUMNS, h: STAGE_ROWS },
  }
}

export const STAGE_RACK_MODULE_IDS: readonly StageRackModuleId[] = [
  'threads',
  'chat',
  'memory',
  'vitals',
  'context_bars',
  'memory_graph',
  'palace_nebula',
  'injection_console',
  'palace_queue',
  'recipe',
  'deck',
]

export function rackResizeDirections(
  manifest: RackTemplateManifest,
): readonly RackResizeDirection[] {
  if (manifest.slot === 'panel' || manifest.slot === 'strip') {
    return ['n', 'e', 's', 'w', 'ne', 'se', 'sw', 'nw']
  }
  return []
}

export function assertRackModuleTemplate(
  manifests: Record<string, RackTemplateManifest>,
): void {
  for (const moduleId of STAGE_RACK_MODULE_IDS) {
    const manifest = manifests[moduleId]
    if (manifest === undefined) {
      throw new Error(`Rack module template is missing ${moduleId}`)
    }
    if (!manifest.movable) {
      throw new Error(`${manifest.name} must use the shared drag affordance`)
    }
    assertGridBounds(manifest)
    if (
      manifest.bounds.min.w !== 1 || manifest.bounds.min.h !== 1 ||
      manifest.bounds.max.w !== STAGE_COLUMNS || manifest.bounds.max.h !== STAGE_ROWS
    ) {
      throw new Error(`${manifest.name} must let the Stage grid govern resize limits`)
    }
    const directions = rackResizeDirections(manifest)
    if (
      !directions.some((direction) => direction.length === 1) ||
      !directions.some((direction) => direction.length === 2)
    ) {
      throw new Error(`${manifest.name} needs edge and corner resize affordances`)
    }
  }
}

function assertGridBounds(manifest: RackTemplateManifest): void {
  for (const axis of ['w', 'h'] as const) {
    const minimum = manifest.bounds.min[axis]
    const preferred = manifest.bounds.preferred[axis]
    const maximum = manifest.bounds.max[axis]
    if (
      !Number.isInteger(minimum) ||
      !Number.isInteger(preferred) ||
      !Number.isInteger(maximum) ||
      minimum < 1 ||
      minimum > preferred ||
      preferred > maximum
    ) {
      throw new Error(`${manifest.name} has invalid ${axis} grid-unit bounds`)
    }
  }
}
