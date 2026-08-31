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
  addStageModuleInstance,
  cloneFactoryStageLayout,
  createStageLayer,
  fitStageCamera,
  loadStageLayout,
  moduleFitsViewport,
  moduleIsOffscreen,
  moveStageModule,
  persistStageLayout,
  recoverStageModule,
  removeStageLayer,
  removeStageModule,
  resizeStageModule,
  restoreStageLayer,
  restoreStageModule,
  selectStageLayer,
  setConversationMode,
  updateStageCamera,
} from '../src/stageLayout.ts'

/** PLAN M2ST1 / P2 requires each layer to retain its own camera and grid-unit module geometry. */
test('layer switching preserves independent camera and module layouts through reload', () => {
  const storage = memoryStorage()
  let layout = moveStageModule(cloneFactoryStageLayout(), 'conversation', 20, 8)
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
    work?.modules.find((module) => module.module_id === 'conversation'),
    {
      instance_id: 'conversation', module_id: 'conversation', source_thread_id: undefined,
      conversation_mode: 'focused', x: 20, y: 8, width: 20, height: 20,
    },
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

/** F055, M3OM, and B.6 r8 require one phone recovery action for Recipe and the Conversation stack. */
test('off-screen recovery fits Recipe and Conversation stack at native scale inside 390 by 844', () => {
  const viewportWidth = 390
  const viewportHeight = 749

  let recipeLayout = selectStageLayer(cloneFactoryStageLayout(), 'graph')
  recipeLayout = restoreStageModule(recipeLayout, 'recipe')
  recipeLayout = updateStageCamera(recipeLayout, { x: -5000, y: -5000, zoom: 0.86 })
  recipeLayout = recoverStageModule(recipeLayout, 'recipe', viewportWidth, viewportHeight)
  const recipeLayer = activeStageLayer(recipeLayout)
  const recipe = recipeLayer.modules.find((module) => module.module_id === 'recipe')
  assert.deepEqual(recipe, { instance_id: 'recipe', module_id: 'recipe', x: 124, y: 70, width: 7, height: 20 })
  assert.equal(recipeLayer.camera.zoom, 1)
  assert.equal(moduleFitsViewport(
    recipe, recipeLayer.camera, viewportWidth, viewportHeight, 12,
  ), true)
  assert.equal(moduleIsOffscreen(
    recipe, recipeLayer.camera, viewportWidth, viewportHeight,
  ), false)

  let deckLayout = updateStageCamera(
    setConversationMode(cloneFactoryStageLayout(), 'conversation', 'stack'),
    { x: -5000, y: -5000, zoom: 0.64 },
  )
  deckLayout = recoverStageModule(deckLayout, 'conversation', viewportWidth, viewportHeight)
  const deckLayer = activeStageLayer(deckLayout)
  const deck = deckLayer.modules.find((module) => module.module_id === 'conversation')
  assert.deepEqual(deck, {
    instance_id: 'conversation', module_id: 'conversation',
    conversation_mode: 'stack', x: 106, y: 68, width: 7, height: 20,
  })
  assert.equal(deckLayer.camera.zoom, 1)
  assert.equal(moduleFitsViewport(
    deck, deckLayer.camera, viewportWidth, viewportHeight, 12,
  ), true)
})

/** F055 keeps ordinary desktop recovery geometry intact when the complete module already fits. */
test('off-screen recovery preserves module size when centered geometry fits', () => {
  let layout = selectStageLayer(cloneFactoryStageLayout(), 'graph')
  layout = restoreStageModule(layout, 'recipe')
  const before = activeStageLayer(layout).modules.find((module) => module.module_id === 'recipe')
  layout = updateStageCamera(layout, { x: -5000, y: -5000, zoom: 0.86 })
  layout = recoverStageModule(layout, 'recipe', 1440, 900)
  const layer = activeStageLayer(layout)
  const recovered = layer.modules.find((module) => module.module_id === 'recipe')

  assert.deepEqual(recovered, before)
  assert.equal(moduleFitsViewport(recovered, layer.camera, 1440, 900, 12), true)
})

/** PLAN M2ST1 / P2 keeps factory Graph and Injection ordinary removable Stage modules. */
test('factory layers contain Graph and Injection as stage modules, never fixed tabs', () => {
  const graph = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'graph')
  const injection = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'injection')

  assert.deepEqual(graph?.modules.map((module) => module.module_id), ['memory_graph'])
  assert.deepEqual(graph?.removed_modules.map((module) => module.module_id), ['palace_nebula'])
  assert.deepEqual(injection?.modules.map((module) => module.module_id), ['injection_console'])
})

/** PLAN M3SP makes Palace State a small ordinary Stage module, including removal and restore. */
test('Palace State is mounted beside Spend and survives the shared library lifecycle', () => {
  const factory = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'work')
  assert.deepEqual(
    factory?.modules.filter((module) => ['vitals', 'palace_state'].includes(module.module_id)).map((module) => module.module_id),
    ['vitals', 'palace_state'],
  )

  const removed = removeStageModule(cloneFactoryStageLayout(), 'palace_state')
  assert.equal(activeStageLayer(removed).modules.some((module) => module.module_id === 'palace_state'), false)
  const restored = restoreStageModule(removed, 'palace_state')
  assert.deepEqual(
    activeStageLayer(restored).modules.find((module) => module.module_id === 'palace_state'),
    factory?.modules.find((module) => module.module_id === 'palace_state'),
  )
})

/** PLAN M3GE / P2 keeps the opt-in engine spike recoverable with one migration. */
test('Palace Nebula begins in the Graph library and migrates existing layouts once', () => {
  const factoryGraph = FACTORY_STAGE_LAYOUT.layers.find((layer) => layer.layer_id === 'graph')
  assert.deepEqual(factoryGraph?.removed_modules.map((module) => module.module_id), ['palace_nebula'])

  const storage = memoryStorage()
  const legacyV3 = cloneFactoryStageLayout()
  legacyV3.layers = legacyV3.layers.map((layer) => ({
    ...layer,
    modules: layer.modules.filter((module) => module.module_id !== 'palace_nebula'),
    removed_modules: layer.removed_modules.filter((module) => module.module_id !== 'palace_nebula'),
  }))
  storage.setItem(STAGE_LAYOUT_STORAGE_KEY, JSON.stringify(legacyV3))

  const migrated = loadStageLayout(storage)
  const graph = migrated.layers.find((layer) => layer.layer_id === 'graph')
  assert.equal(graph?.removed_modules.filter((module) => module.module_id === 'palace_nebula').length, 1)
  const restored = restoreStageModule(selectStageLayer(migrated, 'graph'), 'palace_nebula')
  assert.equal(activeStageLayer(restored).modules.some((module) => module.module_id === 'palace_nebula'), true)
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
    instance_id: 'recipe', module_id: 'recipe', x: 124, y: 70, width: 24, height: 20,
  })

  const removed = removeStageModule(added, 'recipe')
  assert.equal(activeStageLayer(removed).modules.some((module) => module.module_id === 'recipe'), false)
  const restored = restoreStageModule(removed, 'recipe')
  assert.deepEqual(activeStageLayer(restored).modules.at(-1), {
    instance_id: 'recipe', module_id: 'recipe', x: 124, y: 70, width: 24, height: 20,
  })
})

/** PLAN M2TC / P2 removes per-module size caps: only the finite Stage grid limits huge and tiny resizing. */
test('Spend can shrink to one cell and grow to the complete Stage grid', () => {
  const tiny = resizeStageModule(cloneFactoryStageLayout(), 'vitals', -20, 0, 'nw')
  assert.deepEqual(
    activeStageLayer(tiny).modules.find((module) => module.module_id === 'vitals'),
    { instance_id: 'vitals', module_id: 'vitals', x: 121, y: 97, width: 1, height: 1 },
  )

  const huge = resizeStageModule(cloneFactoryStageLayout(), 'vitals', 1000, 1000, 'nw')
  assert.deepEqual(
    activeStageLayer(huge).modules.find((module) => module.module_id === 'vitals'),
    { instance_id: 'vitals', module_id: 'vitals', x: 0, y: 0, width: STAGE_COLUMNS, height: STAGE_ROWS },
  )
})

/** SPEC D.2 138-139 and M3OM: sources and consumers retain independent instance identity. */
test('Conversation, Context Bars, Spend, and Graph can each add independent Stage instances', () => {
  const storage = memoryStorage()
  let layout = cloneFactoryStageLayout()
  for (const moduleId of ['conversation', 'context_bars', 'vitals', 'memory_graph']) {
    layout = addStageModuleInstance(layout, moduleId)
  }
  persistStageLayout(storage, layout)

  const restored = loadStageLayout(storage)
  const instances = restored.layers.flatMap((layer) => layer.modules.map((module) => module.instance_id))
  assert.ok(instances.includes('conversation:2'))
  assert.ok(instances.includes('context_bars:2'))
  assert.ok(instances.includes('vitals:2'))
  assert.ok(instances.includes('memory_graph:2'))
  assert.equal(new Set(instances).size, instances.length)
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

/** PLAN M3OM / P2: v4 Chat and Deck instances migrate in place into one module with durable postures. */
test('v4 Chat and Deck layouts migrate cleanly into focused and stack Conversation instances', () => {
  const storage = memoryStorage()
  storage.setItem('nocturne.stage.layout.v4', JSON.stringify({
    version: 4,
    active_layer_id: 'work',
    scopes: { chat: 'ATTUNED', deck: 'GLOBAL' },
    layers: [{
      layer_id: 'work',
      name: 'Work',
      camera: { x: 12, y: 18, zoom: 0.75 },
      modules: [
        { instance_id: 'chat', module_id: 'chat', source_thread_id: 'thread-a', x: 8, y: 9, width: 20, height: 20 },
        { instance_id: 'deck', module_id: 'deck', x: 42, y: 11, width: 16, height: 20 },
      ],
      removed_modules: [],
    }],
    removed_layers: [],
  }))

  const migrated = loadStageLayout(storage)
  assert.equal(migrated.version, 5)
  assert.deepEqual(activeStageLayer(migrated).modules, [
    {
      instance_id: 'conversation', module_id: 'conversation', source_thread_id: 'thread-a',
      conversation_mode: 'focused', x: 8, y: 9, width: 20, height: 20,
    },
    {
      instance_id: 'conversation:2', module_id: 'conversation', source_thread_id: undefined,
      conversation_mode: 'stack', x: 42, y: 11, width: 16, height: 20,
    },
    FACTORY_STAGE_LAYOUT.layers[0].modules.find((module) => module.module_id === 'palace_queue'),
  ])
  assert.equal(migrated.scopes.conversation, 'ATTUNED')
  assert.equal(migrated.scopes['conversation:2'], 'GLOBAL')
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
  const conversation = activeStageLayer(migrated).modules[0]
  assert.equal(migrated.version, 5)
  assert.equal(conversation.module_id, 'conversation')
  assert.equal(conversation.conversation_mode, 'focused')
  assert.ok(conversation.x > STAGE_COLUMNS / 3)
  assert.ok(conversation.y > STAGE_ROWS / 3)
  assert.equal(conversation.width * STAGE_UNIT_WIDTH, 10 * 96)
  assert.equal(conversation.height * STAGE_UNIT_HEIGHT, 10 * 72)
  assert.ok(Math.abs(
    migrated.layers[0].camera.x + conversation.x * STAGE_UNIT_WIDTH * 0.64 -
    (36 + 5 * 96 * 0.64)
  ) < 1)
  assert.ok(Math.abs(
    migrated.layers[0].camera.y + conversation.y * STAGE_UNIT_HEIGHT * 0.64 -
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
