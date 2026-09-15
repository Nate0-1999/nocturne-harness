import assert from 'node:assert/strict'
import test from 'node:test'
import { installedRackPlugins, parseRackPlugin, rackPluginDocument } from '../src/rackPlugins.ts'
import { activeStageLayer, cloneFactoryStageLayout, loadStageLayout, persistStageLayout, registerStagePlugin, restoreStageModule } from '../src/stageLayout.ts'

/** SPEC D.2 / FL-105: imported modules keep the shared binding and isolation boundary. */
test('custom bundles cannot replace built-in modules and retain the isolated document policy', () => {
  const source = { id: 'plugin:compass', name: 'Compass', html: '<h1>Compass</h1>', streams: [], actions: [] }
  assert.throws(() => parseRackPlugin({ ...source, id: 'conversation' }))
  assert.throws(() => parseRackPlugin({ ...source, actions: 'prompt.submit' }))
  assert.throws(() => parseRackPlugin({ ...source, actions: ['prompt.submit'] }))
  assert.throws(() => parseRackPlugin({ ...source, bindings: 'model.temperature' }))
  const document = rackPluginDocument(parseRackPlugin(source))
  assert.ok(document.startsWith('<meta http-equiv="Content-Security-Policy"'))
  assert.ok(document.includes("connect-src 'none'"))
  assert.ok(document.endsWith(source.html))
})

/** SPEC D.2 / FL-105: an installed module must survive an ordinary reload. */
test('an imported plugin keeps its Stage placement across reload', () => {
  const plugin = parseRackPlugin({ id: 'plugin:reload', name: 'Reload', html: '<p>Reload</p>', streams: [], actions: [] })
  installedRackPlugins.push(plugin)
  registerStagePlugin(plugin.id)
  const values = new Map()
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  const layout = restoreStageModule(cloneFactoryStageLayout(), plugin.id)
  persistStageLayout(storage, layout)
  assert.ok(activeStageLayer(loadStageLayout(storage)).modules.some((module) => module.module_id === plugin.id))
})
