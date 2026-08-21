export const RACK_COLUMNS = 12
export const RACK_ROWS = 12
export const RACK_BODY_ROWS = RACK_ROWS - 1
export const VITALS_COLLAPSED_ROWS = 1
export const VITALS_EXPANDED_ROWS = 4
export const RACK_LAYOUT_STORAGE_KEY = 'nocturne.rack.layout.v1'
export const RACK_SAVED_SET_STORAGE_KEY = 'nocturne.rack.saved-set.v1'

export type DockedModuleId = 'threads' | 'chat' | 'memory'
export type StripModuleId = 'vitals' | 'context_bars'
export type StageModuleId = DockedModuleId | StripModuleId
export type RackScope = 'GLOBAL' | 'CURRENT'

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

export interface StripModuleLayout {
  module_id: StripModuleId
  order: number
  width: number
}

export interface RackLayoutSet {
  version: 1
  modules: DockedModuleLayout[]
  strips: StripModuleLayout[]
  strip_rows: number
  scopes: Record<string, RackScope>
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

export const STRIP_RACK_BOUNDS: Record<StripModuleId, RackBounds> = {
  vitals: {
    min: { w: 6, h: VITALS_COLLAPSED_ROWS },
    preferred: { w: 9, h: VITALS_EXPANDED_ROWS },
    max: { w: 10, h: VITALS_EXPANDED_ROWS },
  },
  context_bars: {
    min: { w: 2, h: VITALS_COLLAPSED_ROWS },
    preferred: { w: 3, h: VITALS_EXPANDED_ROWS },
    max: { w: 6, h: VITALS_EXPANDED_ROWS },
  },
}

export const VITALS_RACK_BOUNDS = STRIP_RACK_BOUNDS.vitals

export function rackBodyRowAllocation(stripRows: number): {
  panelRows: number
  vitalsRows: number
  vitalsStart: number
} {
  const vitalsRows = clamp(
    Math.round(stripRows),
    VITALS_COLLAPSED_ROWS,
    VITALS_EXPANDED_ROWS,
  )
  const panelRows = RACK_BODY_ROWS - vitalsRows
  return {
    panelRows,
    vitalsRows,
    vitalsStart: 2 + panelRows,
  }
}

export const FACTORY_RACK_LAYOUT: RackLayoutSet = {
  version: 1,
  scopes: {
    header: 'GLOBAL', threads: 'CURRENT', chat: 'CURRENT', memory: 'CURRENT',
    vitals: 'GLOBAL', context_bars: 'CURRENT', gate: 'CURRENT', thread_end: 'CURRENT', palace_queue: 'GLOBAL',
    model_device: 'CURRENT',
    memory_graph: 'GLOBAL', palace_nebula: 'GLOBAL', injection_console: 'GLOBAL',
  },
  modules: [
    { module_id: 'threads', order: 0, width: 2 },
    { module_id: 'chat', order: 1, width: 8 },
    { module_id: 'memory', order: 2, width: 2 },
  ],
  strips: [
    { module_id: 'vitals', order: 0, width: 9 },
    { module_id: 'context_bars', order: 1, width: 3 },
  ],
  strip_rows: VITALS_EXPANDED_ROWS,
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
    scopes: { ...FACTORY_RACK_LAYOUT.scopes },
    modules: FACTORY_RACK_LAYOUT.modules.map((module) => ({ ...module })),
    strips: FACTORY_RACK_LAYOUT.strips.map((module) => ({ ...module })),
    strip_rows: FACTORY_RACK_LAYOUT.strip_rows,
  }
}

export function orderedModules(layout: RackLayoutSet): DockedModuleLayout[] {
  return [...layout.modules].sort((left, right) => left.order - right.order)
}

export function orderedStrips(layout: RackLayoutSet): StripModuleLayout[] {
  return [...layout.strips].sort((left, right) => left.order - right.order)
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

export function stripGridColumn(
  layout: RackLayoutSet,
  moduleId: StripModuleId,
): { x: number; w: number } {
  let x = 1
  for (const module of orderedStrips(layout)) {
    if (module.module_id === moduleId) {
      return { x, w: module.width }
    }
    x += module.width
  }
  throw new RangeError(`unknown rack strip ${moduleId}`)
}

export function moveRackModule(
  layout: RackLayoutSet,
  sourceId: StageModuleId,
  targetId: StageModuleId,
): RackLayoutSet {
  if (sourceId === targetId) {
    return layout
  }
  if (isStripModuleId(sourceId) && isStripModuleId(targetId)) {
    const strips = orderedStrips(layout)
    const sourceIndex = strips.findIndex((module) => module.module_id === sourceId)
    const targetIndex = strips.findIndex((module) => module.module_id === targetId)
    if (sourceIndex < 0 || targetIndex < 0) {
      return layout
    }
    const [source] = strips.splice(sourceIndex, 1)
    strips.splice(targetIndex, 0, source)
    return {
      ...layout,
      scopes: { ...layout.scopes },
      modules: layout.modules.map((module) => ({ ...module })),
      strips: strips.map((module, order) => ({ ...module, order })),
    }
  }
  if (!isDockedModuleId(sourceId) || !isDockedModuleId(targetId)) {
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
    ...layout,
    scopes: { ...layout.scopes },
    strips: layout.strips.map((module) => ({ ...module })),
    modules: modules.map((module, order) => ({ ...module, order })),
  }
}

export function resizeRackModule(
  layout: RackLayoutSet,
  moduleId: DockedModuleId,
  requestedWidth: number,
  resizeEdge: 'left' | 'right' = 'right',
): RackLayoutSet {
  const modules = orderedModules(layout)
  const index = modules.findIndex((module) => module.module_id === moduleId)
  if (index < 0) {
    return layout
  }
  const module = modules[index]
  const requestedNeighborIndex = resizeEdge === 'left' ? index - 1 : index + 1
  const neighborIndex = requestedNeighborIndex >= 0 && requestedNeighborIndex < modules.length
    ? requestedNeighborIndex
    : resizeEdge === 'left'
      ? index + 1
      : index - 1
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
    ...layout,
    scopes: { ...layout.scopes },
    strips: layout.strips.map((item) => ({ ...item })),
    modules: modules.map((item, order) => ({ ...item, order })),
  }
}

export function resizeRackStrip(
  layout: RackLayoutSet,
  moduleId: StripModuleId,
  requestedWidth: number,
): RackLayoutSet {
  const strips = orderedStrips(layout)
  const index = strips.findIndex((module) => module.module_id === moduleId)
  if (index < 0) {
    return layout
  }
  const module = strips[index]
  const neighborIndex = index === 0 ? 1 : 0
  const neighbor = strips[neighborIndex]
  const bounds = STRIP_RACK_BOUNDS[moduleId]
  const neighborBounds = STRIP_RACK_BOUNDS[neighbor.module_id]
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
  strips[index] = { ...module, width: module.width + actualDelta }
  strips[neighborIndex] = { ...neighbor, width: neighborWidth }
  return {
    ...layout,
    scopes: { ...layout.scopes },
    modules: layout.modules.map((item) => ({ ...item })),
    strips: strips.map((item, order) => ({ ...item, order })),
  }
}

export function resizeRackModuleHeight(
  layout: RackLayoutSet,
  moduleId: StageModuleId,
  requestedHeight: number,
): RackLayoutSet {
  const requestedStripRows = isStripModuleId(moduleId)
    ? requestedHeight
    : RACK_BODY_ROWS - requestedHeight
  const stripRows = clamp(
    Math.round(requestedStripRows),
    VITALS_COLLAPSED_ROWS,
    VITALS_EXPANDED_ROWS,
  )
  return stripRows === layout.strip_rows
    ? layout
    : {
        ...layout,
        modules: layout.modules.map((item) => ({ ...item })),
        strips: layout.strips.map((item) => ({ ...item })),
        scopes: { ...layout.scopes },
        strip_rows: stripRows,
      }
}

export function rackLayoutsEqual(left: RackLayoutSet, right: RackLayoutSet): boolean {
  const leftModules = orderedModules(left)
  const rightModules = orderedModules(right)
  const leftStrips = orderedStrips(left)
  const rightStrips = orderedStrips(right)
  return left.strip_rows === right.strip_rows && leftModules.every((module, index) => {
    const other = rightModules[index]
    return module.module_id === other?.module_id && module.width === other.width
  }) && leftStrips.every((module, index) => {
    const other = rightStrips[index]
    return module.module_id === other?.module_id && module.width === other.width
  }) && Object.keys(FACTORY_RACK_LAYOUT.scopes).every(
    (key) => left.scopes[key] === right.scopes[key],
  )
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
  const strips = parseStrips(value.strips)
  if (strips === null) {
    return null
  }
  const stripRows = value.strip_rows === undefined
    ? FACTORY_RACK_LAYOUT.strip_rows
    : value.strip_rows
  if (
    typeof stripRows !== 'number' ||
    !Number.isInteger(stripRows) ||
    stripRows < VITALS_COLLAPSED_ROWS ||
    stripRows > VITALS_EXPANDED_ROWS
  ) {
    return null
  }
  return {
    version: 1,
    scopes: parseScopes(value.scopes),
    modules: orderedModules({
      ...FACTORY_RACK_LAYOUT,
      modules,
      scopes: {},
    }).map((module, order) => ({
      ...module,
      order,
    })),
    strips,
    strip_rows: stripRows,
  }
}

function parseStrips(value: unknown): StripModuleLayout[] | null {
  if (value === undefined) {
    return FACTORY_RACK_LAYOUT.strips.map((module) => ({ ...module }))
  }
  if (!Array.isArray(value)) {
    return null
  }
  const strips: StripModuleLayout[] = []
  for (const item of value) {
    if (
      !isRecord(item) ||
      !isStripModuleId(item.module_id) ||
      typeof item.order !== 'number' ||
      !Number.isInteger(item.order) ||
      typeof item.width !== 'number' ||
      !Number.isInteger(item.width)
    ) {
      return null
    }
    const bounds = STRIP_RACK_BOUNDS[item.module_id]
    if (item.width < bounds.min.w || item.width > bounds.max.w) {
      return null
    }
    strips.push({ module_id: item.module_id, order: item.order, width: item.width })
  }
  if (
    strips.length !== 2 ||
    new Set(strips.map((module) => module.module_id)).size !== 2 ||
    new Set(strips.map((module) => module.order)).size !== 2 ||
    strips.reduce((total, module) => total + module.width, 0) !== RACK_COLUMNS
  ) {
    return null
  }
  return orderedStrips({
    version: 1,
    modules: [],
    strips,
    strip_rows: FACTORY_RACK_LAYOUT.strip_rows,
    scopes: {},
  }).map((module, order) => ({ ...module, order }))
}

function parseScopes(value: unknown): Record<string, RackScope> {
  const scopes = { ...FACTORY_RACK_LAYOUT.scopes }
  if (!isRecord(value)) return scopes
  for (const key of Object.keys(scopes)) {
    if (value[key] === 'GLOBAL' || value[key] === 'CURRENT') scopes[key] = value[key]
  }
  return scopes
}

export function isDockedModuleId(value: unknown): value is DockedModuleId {
  return value === 'threads' || value === 'chat' || value === 'memory'
}

export function isStripModuleId(value: unknown): value is StripModuleId {
  return value === 'vitals' || value === 'context_bars'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}
