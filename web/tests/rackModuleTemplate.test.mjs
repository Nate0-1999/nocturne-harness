import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  FACTORY_RACK_LAYOUT,
  cloneFactoryLayout,
  loadRackLayout,
  moveRackModule,
  orderedStrips,
  persistRackLayout,
  resizeRackModuleHeight,
  resizeRackModule,
  resizeRackStrip,
  stripGridColumn,
} from '../src/rackLayout.ts'
import {
  STAGE_RACK_MODULE_IDS,
  assertRackModuleTemplate,
  rackResizeDirections,
} from '../src/rackModuleTemplate.ts'

const webRoot = new URL('../', import.meta.url)

/** PLAN M2UX3 / P2.5 requires every mounted stage module to inherit one drag and edge-plus-corner resize contract. */
test('the module template enumerates the complete mounted stage and refuses a partial affordance', () => {
  assert.deepEqual(STAGE_RACK_MODULE_IDS, [
    'threads',
    'chat',
    'memory',
    'vitals',
    'context_bars',
    'memory_graph',
    'injection_console',
  ])

  const manifests = Object.fromEntries(STAGE_RACK_MODULE_IDS.map((id) => [
    id,
    {
      id,
      name: id,
      slot: id === 'vitals' || id === 'context_bars' ? 'strip' : 'panel',
      bounds: id === 'vitals' || id === 'context_bars'
        ? { min: { w: 2, h: 1 }, preferred: { w: 3, h: 2 }, max: { w: 6, h: 4 } }
        : { min: { w: 2, h: 7 }, preferred: { w: 4, h: 7 }, max: { w: 10, h: 10 } },
      movable: true,
    },
  ]))

  assert.doesNotThrow(() => assertRackModuleTemplate(manifests))
  assert.ok(rackResizeDirections(manifests.chat).some((direction) => direction.length === 1))
  assert.ok(rackResizeDirections(manifests.chat).some((direction) => direction.length === 2))
  assert.throws(
    () => assertRackModuleTemplate({
      ...manifests,
      vitals: { ...manifests.vitals, movable: false },
    }),
    /Palace Vitals|vitals.*shared drag affordance/iu,
  )
})

/** ADR-023 resize law and PLAN M2UX3 require Vitals drag and grid-unit resize to survive reload. */
test('Vitals moves, resizes inside manifest bounds, and restores from persisted layout', () => {
  const storage = memoryStorage()
  const moved = moveRackModule(cloneFactoryLayout(), 'vitals', 'context_bars')
  const widened = resizeRackStrip(moved, 'vitals', 8)
  const shortened = resizeRackModuleHeight(widened, 'vitals', 2)
  persistRackLayout(storage, shortened)

  const restored = loadRackLayout(storage)
  assert.deepEqual(orderedStrips(restored).map((module) => module.module_id), [
    'context_bars',
    'vitals',
  ])
  assert.deepEqual(stripGridColumn(restored, 'vitals'), { x: 5, w: 8 })
  assert.equal(restored.strip_rows, 2)
  assert.equal(restored.strips.reduce((total, module) => total + module.width, 0), 12)
  assert.notDeepEqual(restored, FACTORY_RACK_LAYOUT)
})

/** ADR-023 grid resize law requires the approached panel edge to trade units with that edge's neighbor. */
test('panel edge resize trades with the neighbor under that edge', () => {
  const fromLeft = resizeRackModule(cloneFactoryLayout(), 'chat', 7, 'left')
  const fromRight = resizeRackModule(cloneFactoryLayout(), 'chat', 7, 'right')

  assert.deepEqual(fromLeft.modules.map(({ module_id, width }) => [module_id, width]), [
    ['threads', 3], ['chat', 7], ['memory', 2],
  ])
  assert.deepEqual(fromRight.modules.map(({ module_id, width }) => [module_id, width]), [
    ['threads', 2], ['chat', 7], ['memory', 3],
  ])
})

/** P2.5 / PLAN M2UX3 makes the pure conformance assertion a gate on the actual production manifest and shared chrome. */
test('production manifests and frames are wired through the shared template', async () => {
  const [app, rack, rackCss] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/rack.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
  ])

  assert.match(rack, /assertRackModuleTemplate\(RACK_MANIFESTS\)/u)
  assert.match(app, /data-rack-template-module=\{usesTemplate \? 'true' : undefined\}/u)
  assert.match(app, /rackResizeDirections\(manifest\)/u)
  assert.match(app, /onPointerDown=\{beginMove\}/u)
  assert.match(rackCss, /\.rack-module:hover > \.rack-module__resize-handle/u)
  assert.match(rackCss, /cursor:\s*ew-resize/u)
  assert.match(rackCss, /cursor:\s*ns-resize/u)
  assert.match(rackCss, /cursor:\s*(?:ne|nw)sw-resize/u)
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
