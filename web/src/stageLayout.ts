import type { RackScope } from './rackLayout'

export const STAGE_LAYOUT_STORAGE_KEY = 'nocturne.stage.layout.v3'
export const STAGE_SAVED_SET_STORAGE_KEY = 'nocturne.stage.saved-set.v3'
const LEGACY_STAGE_LAYOUT_STORAGE_KEY = 'nocturne.stage.layout.v2'
const LEGACY_STAGE_SAVED_SET_STORAGE_KEY = 'nocturne.stage.saved-set.v2'
const LEGACY_RACK_LAYOUT_STORAGE_KEY = 'nocturne.rack.layout.v1'
const LEGACY_STAGE_COLUMNS = 32
const LEGACY_STAGE_ROWS = 22
const STAGE_COORDINATE_SCALE = 2
export const STAGE_COLUMNS = 256
export const STAGE_ROWS = 176
export const STAGE_UNIT_WIDTH = 48
export const STAGE_UNIT_HEIGHT = 36
export const STAGE_FINE_GRID_SIZE = 12
export const STAGE_MIN_ZOOM = 0.06
export const STAGE_MAX_ZOOM = 1.6
const STAGE_ORIGIN_X = (STAGE_COLUMNS - LEGACY_STAGE_COLUMNS * STAGE_COORDINATE_SCALE) / 2
const STAGE_ORIGIN_Y = (STAGE_ROWS - LEGACY_STAGE_ROWS * STAGE_COORDINATE_SCALE) / 2

export type StageModuleId =
  | 'threads'
  | 'chat'
  | 'memory'
  | 'vitals'
  | 'context_bars'
  | 'memory_graph'
  | 'injection_console'
  | 'palace_queue'

export const STAGE_MODULE_IDS: readonly StageModuleId[] = [
  'threads', 'chat', 'memory', 'vitals', 'context_bars',
  'memory_graph', 'injection_console', 'palace_queue',
]
const FACTORY_LAYER_IDS = ['work', 'graph', 'injection'] as const

export interface StageCamera {
  x: number
  y: number
  zoom: number
}

export interface StageModuleLayout {
  module_id: StageModuleId
  x: number
  y: number
  width: number
  height: number
}

export interface StageLayer {
  layer_id: string
  name: string
  camera: StageCamera
  modules: StageModuleLayout[]
  removed_modules: StageModuleLayout[]
}

export interface StageLayoutSet {
  version: 3
  active_layer_id: string
  layers: StageLayer[]
  removed_layers: StageLayer[]
  scopes: Record<string, RackScope>
}

interface ParsedStageLayout extends Omit<StageLayoutSet, 'version'> {
  version: 2 | 3
}

const DEFAULT_SCOPES: Record<string, RackScope> = {
  header: 'GLOBAL', threads: 'CURRENT', chat: 'CURRENT', memory: 'CURRENT',
  vitals: 'GLOBAL', context_bars: 'CURRENT', gate: 'CURRENT', thread_end: 'CURRENT',
  palace_queue: 'GLOBAL', model_device: 'CURRENT', memory_graph: 'GLOBAL',
  injection_console: 'GLOBAL',
}

const DEFAULT_MODULES: Record<StageModuleId, StageModuleLayout> = {
  threads: expandLegacyModule({ module_id: 'threads', x: 1, y: 1, width: 4, height: 10 }),
  chat: expandLegacyModule({ module_id: 'chat', x: 5, y: 1, width: 10, height: 10 }),
  memory: expandLegacyModule({ module_id: 'memory', x: 15, y: 1, width: 4, height: 10 }),
  vitals: expandLegacyModule({ module_id: 'vitals', x: 1, y: 12, width: 12, height: 4 }),
  context_bars: expandLegacyModule({ module_id: 'context_bars', x: 13, y: 12, width: 6, height: 4 }),
  memory_graph: expandLegacyModule({ module_id: 'memory_graph', x: 2, y: 2, width: 12, height: 10 }),
  injection_console: expandLegacyModule({
    module_id: 'injection_console', x: 2, y: 2, width: 12, height: 10,
  }),
  palace_queue: expandLegacyModule({
    module_id: 'palace_queue', x: 20, y: 1, width: 5, height: 10,
  }),
}

export const FACTORY_STAGE_LAYOUT: StageLayoutSet = {
  version: 3,
  active_layer_id: 'work',
  scopes: DEFAULT_SCOPES,
  layers: [
    {
      layer_id: 'work',
      name: 'Work',
      camera: expandLegacyCamera({ x: 36, y: 30, zoom: 0.64 }),
      modules: ['threads', 'chat', 'memory', 'vitals', 'context_bars', 'palace_queue']
        .map((moduleId) => ({ ...DEFAULT_MODULES[moduleId as StageModuleId] })),
      removed_modules: [],
    },
    {
      layer_id: 'graph',
      name: 'Graph',
      camera: expandLegacyCamera({ x: 50, y: 36, zoom: 0.86 }),
      modules: [{ ...DEFAULT_MODULES.memory_graph }],
      removed_modules: [],
    },
    {
      layer_id: 'injection',
      name: 'Injection',
      camera: expandLegacyCamera({ x: 50, y: 36, zoom: 0.86 }),
      modules: [{ ...DEFAULT_MODULES.injection_console }],
      removed_modules: [],
    },
  ],
  removed_layers: [],
}

export function cloneFactoryStageLayout(): StageLayoutSet {
  return cloneStageLayout(FACTORY_STAGE_LAYOUT)
}

export function cloneStageLayout(layout: StageLayoutSet): StageLayoutSet {
  return {
    version: 3,
    active_layer_id: layout.active_layer_id,
    scopes: { ...layout.scopes },
    layers: layout.layers.map(cloneLayer),
    removed_layers: layout.removed_layers.map(cloneLayer),
  }
}

export function loadStageLayout(storage: Storage): StageLayoutSet {
  const current = parseStageLayout(storage.getItem(STAGE_LAYOUT_STORAGE_KEY))
  if (current !== null) return current
  const legacyStage = parseStageLayoutVersion(
    storage.getItem(LEGACY_STAGE_LAYOUT_STORAGE_KEY),
    2,
    LEGACY_STAGE_COLUMNS,
    LEGACY_STAGE_ROWS,
  )
  if (legacyStage !== null) return expandLegacyStageLayout(legacyStage)
  const legacy = parseLegacyRackLayout(storage.getItem(LEGACY_RACK_LAYOUT_STORAGE_KEY))
  return legacy ?? cloneFactoryStageLayout()
}

export function loadSavedStageSet(storage: Storage): StageLayoutSet | null {
  const current = parseStageLayout(storage.getItem(STAGE_SAVED_SET_STORAGE_KEY))
  if (current !== null) return current
  const legacy = parseStageLayoutVersion(
    storage.getItem(LEGACY_STAGE_SAVED_SET_STORAGE_KEY),
    2,
    LEGACY_STAGE_COLUMNS,
    LEGACY_STAGE_ROWS,
  )
  return legacy === null ? null : expandLegacyStageLayout(legacy)
}

export function persistStageLayout(storage: Storage, layout: StageLayoutSet): void {
  storage.setItem(STAGE_LAYOUT_STORAGE_KEY, JSON.stringify(layout))
}

export function saveStageSet(storage: Storage, layout: StageLayoutSet): void {
  storage.setItem(STAGE_SAVED_SET_STORAGE_KEY, JSON.stringify(layout))
}

export function activeStageLayer(layout: StageLayoutSet): StageLayer {
  return layout.layers.find((layer) => layer.layer_id === layout.active_layer_id)
    ?? layout.layers[0]
}

export function selectStageLayer(layout: StageLayoutSet, layerId: string): StageLayoutSet {
  return layout.layers.some((layer) => layer.layer_id === layerId)
    ? { ...cloneStageLayout(layout), active_layer_id: layerId }
    : layout
}

export function createStageLayer(layout: StageLayoutSet): StageLayoutSet {
  const occupiedIds = new Set([
    ...layout.layers.map((layer) => layer.layer_id),
    ...layout.removed_layers.map((layer) => layer.layer_id),
  ])
  let sequence = 1
  while (occupiedIds.has(`layer-${sequence}`)) sequence += 1
  const layerId = `layer-${sequence}`
  const currentCamera = activeStageLayer(layout).camera
  const layers = layout.layers.filter((layer) => !isEmptyReplacement(layer)).map(cloneLayer)
  return {
    ...cloneStageLayout(layout),
    active_layer_id: layerId,
    layers: [
      ...layers,
      {
        layer_id: layerId,
        name: `Layer ${sequence}`,
        camera: { ...currentCamera },
        modules: [],
        removed_modules: [],
      },
    ],
  }
}

export function updateStageCamera(
  layout: StageLayoutSet,
  camera: StageCamera,
): StageLayoutSet {
  return updateActiveLayer(layout, (layer) => ({
    ...layer,
    camera: normalizeCamera(camera),
  }))
}

export function moveStageModule(
  layout: StageLayoutSet,
  moduleId: StageModuleId,
  x: number,
  y: number,
): StageLayoutSet {
  return updateActiveModule(layout, moduleId, (module) => ({
    ...module,
    x: clamp(Math.round(x), 0, STAGE_COLUMNS - module.width),
    y: clamp(Math.round(y), 0, STAGE_ROWS - module.height),
  }))
}

export function resizeStageModule(
  layout: StageLayoutSet,
  moduleId: StageModuleId,
  width: number,
  height: number,
  direction: string,
): StageLayoutSet {
  return updateActiveModule(layout, moduleId, (module) => {
    const nextWidth = clamp(Math.round(width), 1, STAGE_COLUMNS)
    const nextHeight = clamp(Math.round(height), 1, STAGE_ROWS)
    const nextX = direction.includes('w')
      ? clamp(module.x + module.width - nextWidth, 0, STAGE_COLUMNS - nextWidth)
      : clamp(module.x, 0, STAGE_COLUMNS - nextWidth)
    const nextY = direction.includes('n')
      ? clamp(module.y + module.height - nextHeight, 0, STAGE_ROWS - nextHeight)
      : clamp(module.y, 0, STAGE_ROWS - nextHeight)
    return { ...module, x: nextX, y: nextY, width: nextWidth, height: nextHeight }
  })
}

export function removeStageModule(
  layout: StageLayoutSet,
  moduleId: StageModuleId,
): StageLayoutSet {
  return updateActiveLayer(layout, (layer) => {
    const module = layer.modules.find((item) => item.module_id === moduleId)
    if (module === undefined) return layer
    return {
      ...layer,
      modules: layer.modules.filter((item) => item.module_id !== moduleId),
      removed_modules: [
        ...layer.removed_modules.filter((item) => item.module_id !== moduleId),
        { ...module },
      ],
    }
  })
}

export function restoreStageModule(
  layout: StageLayoutSet,
  moduleId: StageModuleId,
): StageLayoutSet {
  return updateActiveLayer(layout, (layer) => {
    if (layer.modules.some((item) => item.module_id === moduleId)) return layer
    const removed = layer.removed_modules.find((item) => item.module_id === moduleId)
    const fallback = DEFAULT_MODULES[moduleId]
    return {
      ...layer,
      modules: [...layer.modules, { ...(removed ?? fallback) }].sort(
        (left, right) => STAGE_MODULE_IDS.indexOf(left.module_id) - STAGE_MODULE_IDS.indexOf(right.module_id),
      ),
      removed_modules: layer.removed_modules.filter((item) => item.module_id !== moduleId),
    }
  })
}

export function removeStageLayer(layout: StageLayoutSet, layerId: string): StageLayoutSet {
  const layer = layout.layers.find((item) => item.layer_id === layerId)
  if (layer === undefined) return layout
  const remaining = layout.layers.filter((item) => item.layer_id !== layerId)
  const replacement = remaining.length > 0 ? remaining : [emptyLayer()]
  const activeLayerId = replacement.some((item) => item.layer_id === layout.active_layer_id)
    ? layout.active_layer_id
    : replacement[0].layer_id
  return {
    ...cloneStageLayout(layout),
    active_layer_id: activeLayerId,
    layers: replacement.map(cloneLayer),
    removed_layers: [
      ...layout.removed_layers.filter((item) => item.layer_id !== layerId),
      cloneLayer(layer),
    ],
  }
}

export function restoreStageLayer(layout: StageLayoutSet, layerId: string): StageLayoutSet {
  const layer = layout.removed_layers.find((item) => item.layer_id === layerId)
  if (layer === undefined) return layout
  const layers = layout.layers.filter((item) => !isEmptyReplacement(item))
  const restoredLayers = [...layers.map(cloneLayer), cloneLayer(layer)].sort((left, right) => {
    const leftIndex = FACTORY_LAYER_IDS.indexOf(left.layer_id as typeof FACTORY_LAYER_IDS[number])
    const rightIndex = FACTORY_LAYER_IDS.indexOf(right.layer_id as typeof FACTORY_LAYER_IDS[number])
    if (leftIndex < 0) return rightIndex < 0 ? 0 : 1
    if (rightIndex < 0) return -1
    return leftIndex - rightIndex
  })
  return {
    ...cloneStageLayout(layout),
    active_layer_id: layer.layer_id,
    layers: restoredLayers,
    removed_layers: layout.removed_layers
      .filter((item) => item.layer_id !== layerId)
      .map(cloneLayer),
  }
}

export function fitStageCamera(viewportWidth: number, viewportHeight: number): StageCamera {
  const zoom = clamp(
    Math.min(
      (viewportWidth - 48) / (STAGE_COLUMNS * STAGE_UNIT_WIDTH),
      (viewportHeight - 48) / (STAGE_ROWS * STAGE_UNIT_HEIGHT),
    ),
    STAGE_MIN_ZOOM,
    1,
  )
  return {
    x: Math.round((viewportWidth - STAGE_COLUMNS * STAGE_UNIT_WIDTH * zoom) / 2),
    y: Math.round((viewportHeight - STAGE_ROWS * STAGE_UNIT_HEIGHT * zoom) / 2),
    zoom,
  }
}

export function focusStageModule(
  module: StageModuleLayout,
  viewportWidth: number,
  viewportHeight: number,
  zoom: number,
): StageCamera {
  const normalizedZoom = clamp(zoom, STAGE_MIN_ZOOM, STAGE_MAX_ZOOM)
  const centerX = (module.x + module.width / 2) * STAGE_UNIT_WIDTH
  const centerY = (module.y + module.height / 2) * STAGE_UNIT_HEIGHT
  return {
    x: Math.round(viewportWidth / 2 - centerX * normalizedZoom),
    y: Math.round(viewportHeight / 2 - centerY * normalizedZoom),
    zoom: normalizedZoom,
  }
}

export function moduleIsOffscreen(
  module: StageModuleLayout,
  camera: StageCamera,
  viewportWidth: number,
  viewportHeight: number,
): boolean {
  const left = camera.x + module.x * STAGE_UNIT_WIDTH * camera.zoom
  const top = camera.y + module.y * STAGE_UNIT_HEIGHT * camera.zoom
  const right = left + module.width * STAGE_UNIT_WIDTH * camera.zoom
  const bottom = top + module.height * STAGE_UNIT_HEIGHT * camera.zoom
  return right < 0 || bottom < 0 || left > viewportWidth || top > viewportHeight
}

export function stageLayoutsEqual(left: StageLayoutSet, right: StageLayoutSet): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function updateActiveLayer(
  layout: StageLayoutSet,
  update: (layer: StageLayer) => StageLayer,
): StageLayoutSet {
  return {
    ...cloneStageLayout(layout),
    layers: layout.layers.map((layer) => (
      layer.layer_id === layout.active_layer_id ? update(cloneLayer(layer)) : cloneLayer(layer)
    )),
  }
}

function updateActiveModule(
  layout: StageLayoutSet,
  moduleId: StageModuleId,
  update: (module: StageModuleLayout) => StageModuleLayout,
): StageLayoutSet {
  return updateActiveLayer(layout, (layer) => ({
    ...layer,
    modules: layer.modules.map((module) => (
      module.module_id === moduleId ? update({ ...module }) : { ...module }
    )),
  }))
}

function cloneLayer(layer: StageLayer): StageLayer {
  return {
    ...layer,
    camera: { ...layer.camera },
    modules: layer.modules.map((module) => ({ ...module })),
    removed_modules: layer.removed_modules.map((module) => ({ ...module })),
  }
}

function emptyLayer(): StageLayer {
  return {
    layer_id: 'empty',
    name: 'Empty layer',
    camera: expandLegacyCamera({ x: 36, y: 30, zoom: 0.64 }),
    modules: [],
    removed_modules: [],
  }
}

function isEmptyReplacement(layer: StageLayer): boolean {
  return layer.layer_id === 'empty' && layer.modules.length === 0
}

function normalizeCamera(camera: StageCamera): StageCamera {
  return {
    x: Number.isFinite(camera.x) ? Math.round(camera.x) : 0,
    y: Number.isFinite(camera.y) ? Math.round(camera.y) : 0,
    zoom: clamp(camera.zoom, STAGE_MIN_ZOOM, STAGE_MAX_ZOOM),
  }
}

function parseStageLayout(raw: string | null): StageLayoutSet | null {
  const parsed = parseStageLayoutVersion(raw, 3, STAGE_COLUMNS, STAGE_ROWS)
  return parsed === null ? null : addMemoryIngestToExistingLayout(parsed as StageLayoutSet)
}

function parseStageLayoutVersion(
  raw: string | null,
  version: 2 | 3,
  columns: number,
  rows: number,
): ParsedStageLayout | null {
  if (raw === null) return null
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(value) || value.version !== version || !Array.isArray(value.layers)) return null
  const layers = value.layers.map((layer) => parseLayer(layer, columns, rows))
  const removedLayers = Array.isArray(value.removed_layers)
    ? value.removed_layers.map((layer) => parseLayer(layer, columns, rows))
    : []
  if (
    layers.length === 0 ||
    layers.some((layer) => layer === null) ||
    removedLayers.some((layer) => layer === null) ||
    typeof value.active_layer_id !== 'string' ||
    !layers.some((layer) => layer?.layer_id === value.active_layer_id)
  ) return null
  const allLayers = [...layers, ...removedLayers] as StageLayer[]
  if (new Set(allLayers.map((layer) => layer.layer_id)).size !== allLayers.length) return null
  return {
    version,
    active_layer_id: value.active_layer_id,
    layers: layers as StageLayer[],
    removed_layers: removedLayers as StageLayer[],
    scopes: parseScopes(value.scopes),
  }
}

function parseLayer(value: unknown, columns: number, rows: number): StageLayer | null {
  if (
    !isRecord(value) ||
    typeof value.layer_id !== 'string' || value.layer_id.trim() === '' ||
    typeof value.name !== 'string' || value.name.trim() === '' ||
    !isRecord(value.camera) ||
    typeof value.camera.x !== 'number' || typeof value.camera.y !== 'number' ||
    typeof value.camera.zoom !== 'number' ||
    !Array.isArray(value.modules) || !Array.isArray(value.removed_modules)
  ) return null
  const modules = value.modules.map((module) => parseModule(module, columns, rows))
  const removedModules = value.removed_modules.map((module) => parseModule(module, columns, rows))
  if (
    modules.some((module) => module === null) ||
    removedModules.some((module) => module === null)
  ) return null
  const allModules = [...modules, ...removedModules] as StageModuleLayout[]
  if (new Set(allModules.map((module) => module.module_id)).size !== allModules.length) return null
  return {
    layer_id: value.layer_id,
    name: value.name,
    camera: normalizeCamera(value.camera as unknown as StageCamera),
    modules: modules as StageModuleLayout[],
    removed_modules: removedModules as StageModuleLayout[],
  }
}

function parseModule(value: unknown, columns: number, rows: number): StageModuleLayout | null {
  if (
    !isRecord(value) || !isStageModuleId(value.module_id) ||
    !Number.isInteger(value.x) || !Number.isInteger(value.y) ||
    !Number.isInteger(value.width) || !Number.isInteger(value.height) ||
    (value.x as number) < 0 || (value.y as number) < 0 ||
    (value.width as number) < 1 || (value.height as number) < 1 ||
    (value.x as number) + (value.width as number) > columns ||
    (value.y as number) + (value.height as number) > rows
  ) return null
  return value as unknown as StageModuleLayout
}

function expandLegacyStageLayout(layout: ParsedStageLayout): StageLayoutSet {
  const expandLayer = (layer: StageLayer): StageLayer => ({
    ...layer,
    camera: expandLegacyCamera(layer.camera),
    modules: layer.modules.map(expandLegacyModule),
    removed_modules: layer.removed_modules.map(expandLegacyModule),
  })
  return addMemoryIngestToExistingLayout({
    version: 3,
    active_layer_id: layout.active_layer_id,
    layers: layout.layers.map(expandLayer),
    removed_layers: layout.removed_layers.map(expandLayer),
    scopes: { ...layout.scopes },
  })
}

function addMemoryIngestToExistingLayout(layout: StageLayoutSet): StageLayoutSet {
  const alreadyPlaced = [...layout.layers, ...layout.removed_layers].some((layer) =>
    [...layer.modules, ...layer.removed_modules].some(
      (module) => module.module_id === 'palace_queue',
    )
  )
  if (alreadyPlaced) return layout
  const targetLayerId = layout.layers.some((layer) => layer.layer_id === 'work')
    ? 'work'
    : layout.active_layer_id
  return {
    ...cloneStageLayout(layout),
    layers: layout.layers.map((layer) => layer.layer_id === targetLayerId
      ? {
          ...cloneLayer(layer),
          modules: [
            ...layer.modules.map((module) => ({ ...module })),
            { ...DEFAULT_MODULES.palace_queue },
          ],
        }
      : cloneLayer(layer)),
  }
}

function expandLegacyModule(module: StageModuleLayout): StageModuleLayout {
  return {
    ...module,
    x: STAGE_ORIGIN_X + module.x * STAGE_COORDINATE_SCALE,
    y: STAGE_ORIGIN_Y + module.y * STAGE_COORDINATE_SCALE,
    width: module.width * STAGE_COORDINATE_SCALE,
    height: module.height * STAGE_COORDINATE_SCALE,
  }
}

function expandLegacyCamera(camera: StageCamera): StageCamera {
  return normalizeCamera({
    x: camera.x - STAGE_ORIGIN_X * STAGE_UNIT_WIDTH * camera.zoom,
    y: camera.y - STAGE_ORIGIN_Y * STAGE_UNIT_HEIGHT * camera.zoom,
    zoom: camera.zoom,
  })
}

function parseLegacyRackLayout(raw: string | null): StageLayoutSet | null {
  if (raw === null) return null
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(value) || value.version !== 1 || !Array.isArray(value.modules)) return null
  const layout = cloneFactoryStageLayout()
  const work = layout.layers[0]
  let x = STAGE_ORIGIN_X + STAGE_COORDINATE_SCALE
  for (const item of [...value.modules].sort(legacyOrder)) {
    if (!isRecord(item) || !isStageModuleId(item.module_id) || !Number.isInteger(item.width)) {
      return null
    }
    const module = work.modules.find((candidate) => candidate.module_id === item.module_id)
    if (module === undefined) return null
    module.x = x
    module.width = (item.width as number) * STAGE_COORDINATE_SCALE
    x += module.width
  }
  if (Array.isArray(value.strips)) {
    x = STAGE_ORIGIN_X + STAGE_COORDINATE_SCALE
    for (const item of [...value.strips].sort(legacyOrder)) {
      if (!isRecord(item) || !isStageModuleId(item.module_id) || !Number.isInteger(item.width)) {
        return null
      }
      const module = work.modules.find((candidate) => candidate.module_id === item.module_id)
      if (module === undefined) return null
      module.x = x
      module.width = (item.width as number) * STAGE_COORDINATE_SCALE
      x += module.width
    }
  }
  layout.scopes = parseScopes(value.scopes)
  return layout
}

function legacyOrder(left: unknown, right: unknown): number {
  if (!isRecord(left) || !isRecord(right)) return 0
  return Number(left.order ?? 0) - Number(right.order ?? 0)
}

function parseScopes(value: unknown): Record<string, RackScope> {
  const scopes = { ...DEFAULT_SCOPES }
  if (!isRecord(value)) return scopes
  for (const key of Object.keys(scopes)) {
    if (value[key] === 'GLOBAL' || value[key] === 'CURRENT') scopes[key] = value[key]
  }
  return scopes
}

function isStageModuleId(value: unknown): value is StageModuleId {
  return value === 'threads' || value === 'chat' || value === 'memory' ||
    value === 'vitals' || value === 'context_bars' || value === 'memory_graph' ||
    value === 'injection_console' || value === 'palace_queue'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}
