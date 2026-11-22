import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

/** ADR-018/ADR-023: the bridge has no unsolicited notify or hidden scorer-write channel. */
test('bridge message kinds stay closed and only control manifests receive scorer writes', () => {
  const source = ts.createSourceFile('rackBridge.tsx', readFileSync(new URL('../src/rackBridge.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const kinds = name => source.statements.find(n => ts.isTypeAliasDeclaration(n) && n.name.text === name)
    .type.types.map(n => n.members.find(m => m.name.text === 'type').type.literal.text).sort()
  // Snapshot and request/response transport are existing ADR-018 capabilities; dispatch is ADR-023.
  assert.deepEqual(kinds('HostMessage'), ['envelope', 'error', 'resize', 'response', 'selection', 'snapshot'])
  assert.deepEqual(kinds('RemoteMessage'), ['dispatch', 'query', 'selection'])
  const rack = ts.createSourceFile('rack.tsx', readFileSync(new URL('../src/rack.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const manifests = rack.statements.filter(ts.isVariableStatement).flatMap(n => [...n.declarationList.declarations])
    .find(n => n.name.getText(rack) === 'RACK_MANIFESTS').initializer.properties
  let visualizers = 0
  for (const manifest of manifests) {
    const fields = manifest.initializer.properties
    if (fields.find(n => n.name?.getText(rack) === 'class')?.initializer.text !== 'visualizer') continue
    visualizers++
    const actions = fields.find(n => n.name?.getText(rack) === 'actions').initializer.elements.map(n => n.text)
    assert.equal(actions.some(a => /^(?:scorer|learning)\./u.test(a)), false, manifest.name.getText(rack))
  }
  assert.ok(visualizers > 0)
})

/** ADR-023 (3) / A-034 / SD-101: a module writes only the descriptors its manifest binds; the
 * conversation binds the model alone, and its header list is that one write, never a saved policy. */
test('every writing manifest binds what it writes and the header list only switches the conversation', () => {
  const read = name => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8')
  const rack = ts.createSourceFile('rack.tsx', read('rack.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const manifests = rack.statements.filter(ts.isVariableStatement).flatMap(n => [...n.declarationList.declarations])
    .find(n => n.name.getText(rack) === 'RACK_MANIFESTS').initializer.properties
  const list = (manifest, field) => manifest.initializer.properties
    .find(n => n.name?.getText(rack) === field)?.initializer.elements.map(n => n.text) ?? []
  const writers = manifests.filter(manifest => list(manifest, 'actions').includes('parameter.write'))
  assert.deepEqual(writers.map(manifest => manifest.name.getText(rack)).sort(), ['conversation', 'model_device'])
  for (const manifest of writers) assert.ok(list(manifest, 'bindings').length > 0, manifest.name.getText(rack))
  assert.deepEqual(list(writers.find(manifest => manifest.name.getText(rack) === 'conversation'), 'bindings'), ['model.slug'])
  // The host refuses an unbound write from any manifest, not only an imported one.
  assert.match(read('rack.tsx'), /if \(action\.type === 'parameter\.write' && !manifest\.bindings\?\.includes\(action\.parameter_id\)\)/u)
  const device = read('ModelDevice.tsx')
  const headerList = device.slice(device.indexOf('export function ModelSwitch('), device.indexOf('export function ModelDevice('))
  assert.match(headerList, /type: 'parameter\.write', thread_id: threadId, parameter_id: 'model\.slug'/u)
  assert.doesNotMatch(headerList, /policies\.save|models\.pin|models\.local/u)
})
