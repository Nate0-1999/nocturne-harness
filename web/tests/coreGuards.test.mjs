import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

/** SPEC B.6 r14 / H7: execute the real socket class at its two refusal boundaries. */
test('snapshot and connection walls quote their actual error messages', () => {
  const source = readFileSync(new URL('../src/socket.ts', import.meta.url), 'utf8')
  const state = { selectedThreadId: 'thread', threads: { thread: { awaitingSnapshot: true } } }
  const exports = {}
  const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  vm.runInNewContext(javascript, {
    exports,
    WebSocket: { OPEN: 1 },
    require: (name) => name === './store' ? { useHarnessStore: { getState: () => state } } : {},
  })
  const client = new exports.HarnessSocketClient()
  assert.throws(() => client.submitPrompt('hello'), {
    message: 'wait for the authoritative thread snapshot before submitting',
  })
  state.threads.thread.awaitingSnapshot = false
  assert.throws(() => client.submitPrompt('hello'), { message: 'Harness is not connected' })
})

/** ADR-018 / SPEC B.6 r14: a remote module never accepts an external host origin. */
test('module host wall rejects external origins and accepts a local port', () => {
  const text = readFileSync(new URL('../src/rackBridge.tsx', import.meta.url), 'utf8')
  const source = ts.createSourceFile('rackBridge.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const functionNode = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name.text === 'remoteHostOrigin')
  const javascript = ts.transpileModule(functionNode.getText(source), {}).outputText
  const context = vm.createContext({ URL, location: { href: 'http://localhost:4000/?rack_host=https://outside.example' } })
  vm.runInContext(javascript, context)
  assert.throws(() => context.remoteHostOrigin(), {
    message: 'rack frame did not receive a valid local host origin',
  })
  context.location.href = 'http://localhost:4000/?rack_host=http://127.0.0.1:4000'
  assert.equal(context.remoteHostOrigin(), 'http://127.0.0.1:4000')
})
