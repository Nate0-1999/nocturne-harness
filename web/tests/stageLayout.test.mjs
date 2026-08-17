import assert from 'node:assert/strict'
import test from 'node:test'

import {
  FACTORY_STAGE_LAYOUT,
  STAGE_COLUMNS,
  STAGE_LAYOUT_STORAGE_KEY,
  STAGE_MIN_ZOOM,
  STAGE_ROWS,
  STAGE_UNIT_HEIGHT,
  STAGE_UNIT_WIDTH,
  activeStageLayer,
  cloneFactoryStageLayout,
  createStageLayer,
  fitStageCamera,
  loadStageLayout,
  moduleIsOffscreen,
  moveStageModule,
  persistStageLayout,
  removeStageLayer,
  removeStageModule,
  resizeStageModule,
  restoreStageLayer,
  restoreStageModule,
  selectStageLayer,
  updateStageCamera,
} from '../src/stageLayout.ts'

/** PLAN M2ST1 / P2 requires each layer to retain its own camera and grid-unit module geometry. */
test('layer switching preserves independent camera and module layouts through reload', () => {
  const storage = memoryStorage()
  let layout = moveStageModule(cloneFactoryStageLayout(), 'chat', 20, 8)
  layout = updateStageCamera(layout, { x: -410, y: 92, zoom: 0.48 })
  layout = selectStageLayer(layout, 'graph')
  layout = updateStageCamera(layout, { x: 75, y: 44, zoom: 1.15 })
  persistStageLayout(storage, layout)

  const restored = loadStageLayout(storage)
  assert.equal(storage.getItem(STAGE_LAYOUT_STORAGE_KEY) !== null, true)
  assert.deepEqual(activeStageLayer(restored).camera, { x: 75, y: 44, zoom: 1.15 })
  const work = restored.layers.find((layer) => layer.layer_id === 'work')
  assert.deepEqual(work?.camera, { x: -410, y: 92, zoom: 0.48 })
  assert.deepEqual(
    work?.modules.find((module) => module.module_id === 'chat'),
    { module_id: 'chat', x: 20, y: 8, width: 20, height: 20 },
  )
})

/** PLAN M2ST1 / P2 requires every module and layer removal to be recoverable without losing its layout. */
test('module and layer removal round-trip exact retained state through the library', () => {
  let layout = removeStageModule(cloneFactoryStageLayout(), 'memory')
  assert.equal(activeStageLayer(layout).modules.some((module) => module.module_id === 'memory'), false)
  assert.equal(activeStageLayer(layout).removed_modules[0]?.module_id, 'memory')

  layout = restoreStageModule(layout, 'memory')
  assert.deepEqual(
    activeStageLayer(layout).modules.find((module) => module.module_id === 'memory'),
    FACTORY_STAGE_LAYOUT.layers[0].modules.find((module) => module.module_id === 'memory'),
  )

  layout = removeStageLayer(layout, 'work')
  assert.equal(layout.layers.some((layer) => layer.layer_id === 'work'), false)
  assert.equal(layout.removed_layers.some((layer) => layer.layer_id === 'work'), true)
  layout = restoreStageLayer(layout, 'work')
  assert.equal(layout.active_layer_id, 'work')
  assert.deepEqual(activeStageLayer(layout), FACTORY_STAGE_LAYOUT.layers[0])
})

/** PLAN M2ST1 / P2 requires zoom-out overview and an exact recall signal for off-screen modules. */
test('whole-stage fit and off-screen classification use the same camera geometry', () => {
  const module = FACTORY_STAGE_LAYOUT.layers[0].modules[2]
  assert.equal(moduleIsOffscreen(module, { x: -2000, y: 0, zoom: 1 }, 1280, 720), true)

  const fitted = fitStageCamera(1280, 720)
  assert.ok(fitted.zoom >= STAGE_MIN_ZOOM)
  assert.equal(moduleIsOffscreen(module, fitted, 1280, 720), false)
})

/** PLAN M2ST1 / P2 keeps factory Graph and Injection ordinary removable Stage modules. */
test('factory layers contain Graph and Injection as stage modules, never fixed tabs', () => {
  const graph = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'graph')
  const injection = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'injection')

  assert.deepEqual(graph?.modules.map((module) => module.module_id), ['memory_graph'])
  assert.deepEqual(injection?.modules.map((module) => module.module_id), ['injection_console'])
})

/** PLAN M2MI/P1.5 moves corpus ingestion off the header and onto the ordinary recoverable Stage. */
test('Memory Ingest is a factory Stage module and joins an existing v3 layout once', () => {
  const factoryWork = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'work')
  assert.equal(factoryWork?.modules.some((module) => module.module_id === 'palace_queue'), true)

  const storage = memoryStorage()
  const legacyV3 = cloneFactoryStageLayout()
  legacyV3.layers = legacyV3.layers.map((layer) => ({
    ...layer,
    modules: layer.modules.filter((module) => module.module_id !== 'palace_queue'),
    removed_modules: layer.removed_modules.filter((module) => module.module_id !== 'palace_queue'),
  }))
  storage.setItem(STAGE_LAYOUT_STORAGE_KEY, JSON.stringify(legacyV3))

  const migrated = loadStageLayout(storage)
  const work = migrated.layers.find((layer) => layer.layer_id === 'work')
  assert.equal(work?.modules.filter((module) => module.module_id === 'palace_queue').length, 1)

  const removed = removeStageModule(migrated, 'palace_queue')
  persistStageLayout(storage, removed)
  const reloaded = loadStageLayout(storage)
  assert.equal(activeStageLayer(reloaded).modules.some((module) => module.module_id === 'palace_queue'), false)
  assert.equal(activeStageLayer(reloaded).removed_modules.some((module) => module.module_id === 'palace_queue'), true)
})

/** SYM12 / P2.3 keeps Recipe owner-additive, removable, and exactly restorable. */
test('Recipe joins the chosen layer from Library and round-trips its placement', () => {
  const graphLayout = selectStageLayer(cloneFactoryStageLayout(), 'graph')
  const added = restoreStageModule(graphLayout, 'recipe')
  assert.deepEqual(activeStageLayer(added).modules.at(-1), {
    module_id: 'recipe', x: 124, y: 70, width: 24, height: 20,
  })

  const removed = removeStageModule(added, 'recipe')
  assert.equal(activeStageLayer(removed).modules.some((module) => module.module_id === 'recipe'), false)
  const restored = restoreStageModule(removed, 'recipe')
  assert.deepEqual(activeStageLayer(restored).modules.at(-1), {
    module_id: 'recipe', x: 124, y: 70, width: 24, height: 20,
  })
})

/** PLAN M2TC / P2 removes per-module size caps: only the finite Stage grid limits huge and tiny resizing. */
test('Spend can shrink to one cell and grow to the complete Stage grid', () => {
  const tiny = resizeStageModule(cloneFactoryStageLayout(), 'vitals', -20, 0, 'nw')
  assert.deepEqual(
    activeStageLayer(tiny).modules.find((module) => module.module_id === 'vitals'),
    { module_id: 'vitals', x: 121, y: 97, width: 1, height: 1 },
  )

  const huge = resizeStageModule(cloneFactoryStageLayout(), 'vitals', 1000, 1000, 'nw')
  assert.deepEqual(
    activeStageLayer(huge).modules.find((module) => module.module_id === 'vitals'),
    { module_id: 'vitals', x: 0, y: 0, width: STAGE_COLUMNS, height: STAGE_ROWS },
  )
})

/** PLAN M2SP / P2 requires a new layer to be one obvious click and immediately usable. */
test('create layer appends one active empty tab without disturbing existing layers', () => {
  const original = cloneFactoryStageLayout()
  const created = createStageLayer(original)

  assert.equal(created.layers.length, original.layers.length + 1)
  assert.equal(created.active_layer_id, 'layer-1')
  assert.deepEqual(activeStageLayer(created), {
    layer_id: 'layer-1',
    name: 'Layer 1',
    camera: original.layers[0].camera,
    modules: [],
    removed_modules: [],
  })
  assert.deepEqual(original, FACTORY_STAGE_LAYOUT)
})

/** PLAN M2SP / P2 enlarges and recenters the Stage without moving an owner's saved v2 layout on screen. */
test('v2 layouts migrate into the centered fine coordinate space with screen geometry preserved', () => {
  const storage = memoryStorage()
  storage.setItem('nocturne.stage.layout.v2', JSON.stringify({
    version: 2,
    active_layer_id: 'work',
    scopes: {},
    layers: [{
      layer_id: 'work',
      name: 'Work',
      camera: { x: 36, y: 30, zoom: 0.64 },
      modules: [{ module_id: 'chat', x: 5, y: 1, width: 10, height: 10 }],
      removed_modules: [],
    }],
    removed_layers: [],
  }))

  const migrated = loadStageLayout(storage)
  const chat = activeStageLayer(migrated).modules[0]
  assert.equal(migrated.version, 3)
  assert.ok(chat.x > STAGE_COLUMNS / 3)
  assert.ok(chat.y > STAGE_ROWS / 3)
  assert.equal(chat.width * STAGE_UNIT_WIDTH, 10 * 96)
  assert.equal(chat.height * STAGE_UNIT_HEIGHT, 10 * 72)
  assert.ok(Math.abs(
    migrated.layers[0].camera.x + chat.x * STAGE_UNIT_WIDTH * 0.64 -
    (36 + 5 * 96 * 0.64)
  ) < 1)
  assert.ok(Math.abs(
    migrated.layers[0].camera.y + chat.y * STAGE_UNIT_HEIGHT * 0.64 -
    (30 + 1 * 72 * 0.64)
  ) < 1)
})

function memoryStorage() {
  const values = new Map()
  return {
    getItem(key) {
      return values.get(key) ?? null
    },
    setItem(key, value) {
      values.set(key, value)
    },
  }
}
