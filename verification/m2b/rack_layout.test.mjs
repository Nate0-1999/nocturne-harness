import assert from 'node:assert/strict'
import test from 'node:test'

import {
  FACTORY_RACK_LAYOUT,
  RACK_LAYOUT_STORAGE_KEY,
  cloneFactoryLayout,
  loadRackLayout,
  moduleGridColumn,
  moveRackModule,
  persistRackLayout,
  resizeRackModule,
} from '../../web/src/rackLayout.ts'

test('factory rack is a bounded twelve-unit row', () => {
  const layout = cloneFactoryLayout()

  assert.deepEqual(layout, FACTORY_RACK_LAYOUT)
  assert.notEqual(layout, FACTORY_RACK_LAYOUT)
  assert.equal(layout.modules.reduce((total, module) => total + module.width, 0), 12)
  assert.deepEqual(moduleGridColumn(layout, 'threads'), { x: 1, w: 2 })
  assert.deepEqual(moduleGridColumn(layout, 'chat'), { x: 3, w: 8 })
  assert.deepEqual(moduleGridColumn(layout, 'memory'), { x: 11, w: 2 })
})

test('resize trades whole units with a neighbor and respects both manifests', () => {
  const grown = resizeRackModule(cloneFactoryLayout(), 'threads', 99)
  const stable = resizeRackModule(grown, 'threads', 99)

  assert.deepEqual(grown.modules.map(({ module_id, width }) => [module_id, width]), [
    ['threads', 4],
    ['chat', 6],
    ['memory', 2],
  ])
  assert.equal(grown.modules.reduce((total, module) => total + module.width, 0), 12)
  assert.equal(stable, grown)
})

test('dock order and persisted layout restore without accepting malformed state', () => {
  const storage = memoryStorage()
  const moved = moveRackModule(cloneFactoryLayout(), 'memory', 'threads')
  persistRackLayout(storage, moved)

  assert.deepEqual(loadRackLayout(storage), moved)
  storage.setItem(
    RACK_LAYOUT_STORAGE_KEY,
    JSON.stringify({
      version: 1,
      modules: [
        { module_id: 'chat', order: 0, width: 12 },
        { module_id: 'chat', order: 1, width: 0 },
      ],
    }),
  )
  assert.deepEqual(loadRackLayout(storage), FACTORY_RACK_LAYOUT)
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
