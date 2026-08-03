export const RACK_COLUMNS = 12
export const RACK_ROWS = 12
export const RACK_BODY_ROWS = RACK_ROWS - 1
export const VITALS_COLLAPSED_ROWS = 1
export const VITALS_EXPANDED_ROWS = 4
export const RACK_LAYOUT_STORAGE_KEY = 'nocturne.rack.layout.v1'
export const RACK_SAVED_SET_STORAGE_KEY = 'nocturne.rack.saved-set.v1'

export type DockedModuleId = 'threads' | 'chat' | 'memory'

export interface RackSize {
  w: number
  h: number
}

export interface RackBounds {
  min: RackSize
  preferred: RackSize
  max: RackSize
}

export interface DockedModuleLayout {
  module_id: DockedModuleId
  order: number
  width: number
}

export interface RackLayoutSet {
  version: 1
  modules: DockedModuleLayout[]
}

export const RACK_BOUNDS: Record<DockedModuleId, RackBounds> = {
  threads: {
    min: { w: 2, h: RACK_BODY_ROWS - VITALS_EXPANDED_ROWS },
    preferred: { w: 2, h: RACK_BODY_ROWS - VITALS_EXPANDED_ROWS },
    max: { w: 4, h: RACK_BODY_ROWS - VITALS_COLLAPSED_ROWS },
  },
  chat: {
    min: { w: 5, h: RACK_BODY_ROWS - VITALS_EXPANDED_ROWS },
    preferred: { w: 8, h: RACK_BODY_ROWS - VITALS_EXPANDED_ROWS },
    max: { w: 10, h: RACK_BODY_ROWS - VITALS_COLLAPSED_ROWS },
  },
  memory: {
    min: { w: 2, h: RACK_BODY_ROWS - VITALS_EXPANDED_ROWS },
    preferred: { w: 2, h: RACK_BODY_ROWS - VITALS_EXPANDED_ROWS },
    max: { w: 4, h: RACK_BODY_ROWS - VITALS_COLLAPSED_ROWS },
  },
}

export const VITALS_RACK_BOUNDS: RackBounds = {
  min: { w: RACK_COLUMNS, h: VITALS_COLLAPSED_ROWS },
  preferred: { w: RACK_COLUMNS, h: VITALS_EXPANDED_ROWS },
  max: { w: RACK_COLUMNS, h: VITALS_EXPANDED_ROWS },
}

export function rackBodyRowAllocation(vitalsCollapsed: boolean): {
  panelRows: number
  vitalsRows: number
  vitalsStart: number
} {
  const vitalsRows = vitalsCollapsed ? VITALS_COLLAPSED_ROWS : VITALS_EXPANDED_ROWS
  const panelRows = RACK_BODY_ROWS - vitalsRows
  return {
    panelRows,
    vitalsRows,
    vitalsStart: 2 + panelRows,
  }
}

export const FACTORY_RACK_LAYOUT: RackLayoutSet = {
  version: 1,
  modules: [
    { module_id: 'threads', order: 0, width: 2 },
    { module_id: 'chat', order: 1, width: 8 },
    { module_id: 'memory', order: 2, width: 2 },
  ],
}

export function loadRackLayout(storage: Storage): RackLayoutSet {
  return parseRackLayout(storage.getItem(RACK_LAYOUT_STORAGE_KEY)) ?? cloneFactoryLayout()
}

export function loadSavedRackSet(storage: Storage): RackLayoutSet | null {
  return parseRackLayout(storage.getItem(RACK_SAVED_SET_STORAGE_KEY))
}

export function persistRackLayout(storage: Storage, layout: RackLayoutSet): void {
  storage.setItem(RACK_LAYOUT_STORAGE_KEY, JSON.stringify(layout))
}

export function saveRackSet(storage: Storage, layout: RackLayoutSet): void {
  storage.setItem(RACK_SAVED_SET_STORAGE_KEY, JSON.stringify(layout))
}

export function cloneFactoryLayout(): RackLayoutSet {
  return {
    version: 1,
    modules: FACTORY_RACK_LAYOUT.modules.map((module) => ({ ...module })),
  }
}

export function orderedModules(layout: RackLayoutSet): DockedModuleLayout[] {
  return [...layout.modules].sort((left, right) => left.order - right.order)
}

export function moduleGridColumn(
  layout: RackLayoutSet,
  moduleId: DockedModuleId,
): { x: number; w: number } {
  let x = 1
  for (const module of orderedModules(layout)) {
    if (module.module_id === moduleId) {
      return { x, w: module.width }
    }
    x += module.width
  }
  throw new RangeError(`unknown rack module ${moduleId}`)
}

export function moveRackModule(
  layout: RackLayoutSet,
  sourceId: DockedModuleId,
  targetId: DockedModuleId,
): RackLayoutSet {
  if (sourceId === targetId) {
    return layout
  }
  const modules = orderedModules(layout)
  const sourceIndex = modules.findIndex((module) => module.module_id === sourceId)
  const targetIndex = modules.findIndex((module) => module.module_id === targetId)
  if (sourceIndex < 0 || targetIndex < 0) {
    return layout
  }
  const [source] = modules.splice(sourceIndex, 1)
  modules.splice(targetIndex, 0, source)
  return {
    version: 1,
    modules: modules.map((module, order) => ({ ...module, order })),
  }
}

export function resizeRackModule(
  layout: RackLayoutSet,
  moduleId: DockedModuleId,
  requestedWidth: number,
): RackLayoutSet {
  const modules = orderedModules(layout)
  const index = modules.findIndex((module) => module.module_id === moduleId)
  if (index < 0) {
    return layout
  }
  const module = modules[index]
  const neighborIndex = index < modules.length - 1 ? index + 1 : index - 1
  const neighbor = modules[neighborIndex]
  const bounds = RACK_BOUNDS[moduleId]
  const neighborBounds = RACK_BOUNDS[neighbor.module_id]
  const boundedRequest = clamp(Math.round(requestedWidth), bounds.min.w, bounds.max.w)
  const requestedDelta = boundedRequest - module.width
  const neighborWidth = clamp(
    neighbor.width - requestedDelta,
    neighborBounds.min.w,
    neighborBounds.max.w,
  )
  const actualDelta = neighbor.width - neighborWidth
  if (actualDelta === 0) {
    return layout
  }
  modules[index] = { ...module, width: module.width + actualDelta }
  modules[neighborIndex] = { ...neighbor, width: neighborWidth }
  return {
    version: 1,
    modules: modules.map((item, order) => ({ ...item, order })),
  }
}

export function rackLayoutsEqual(left: RackLayoutSet, right: RackLayoutSet): boolean {
  const leftModules = orderedModules(left)
  const rightModules = orderedModules(right)
  return leftModules.every((module, index) => {
    const other = rightModules[index]
    return module.module_id === other?.module_id && module.width === other.width
  })
}

function parseRackLayout(raw: string | null): RackLayoutSet | null {
  if (raw === null) {
    return null
  }
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(value) || value.version !== 1 || !Array.isArray(value.modules)) {
    return null
  }
  const modules: DockedModuleLayout[] = []
  for (const item of value.modules) {
    if (
      !isRecord(item) ||
      !isDockedModuleId(item.module_id) ||
      typeof item.order !== 'number' ||
      !Number.isInteger(item.order) ||
      typeof item.width !== 'number' ||
      !Number.isInteger(item.width)
    ) {
      return null
    }
    const bounds = RACK_BOUNDS[item.module_id]
    if (item.width < bounds.min.w || item.width > bounds.max.w) {
      return null
    }
    modules.push({
      module_id: item.module_id,
      order: item.order,
      width: item.width,
    })
  }
  if (
    modules.length !== 3 ||
    new Set(modules.map((module) => module.module_id)).size !== 3 ||
    new Set(modules.map((module) => module.order)).size !== 3 ||
    modules.reduce((total, module) => total + module.width, 0) !== RACK_COLUMNS
  ) {
    return null
  }
  return {
    version: 1,
    modules: orderedModules({ version: 1, modules }).map((module, order) => ({
      ...module,
      order,
    })),
  }
}

function isDockedModuleId(value: unknown): value is DockedModuleId {
  return value === 'threads' || value === 'chat' || value === 'memory'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}
