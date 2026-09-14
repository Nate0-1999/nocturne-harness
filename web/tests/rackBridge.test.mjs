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
