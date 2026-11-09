import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

const transpile = (path) => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

/** INCIDENT F193: a steering line sent on a socket that dropped before the daemon read it stayed
 * "Sending" for good. Execute the real socket class: after the reconnect's snapshot, a prompt the
 * snapshot does not hold is sent again under its own id, and one it holds is not. */
test('a prompt lost with a dropped socket is sent again after the reconnect snapshot', () => {
  const sockets = []
  class FakeWebSocket {
    static CONNECTING = 0
    static OPEN = 1
    constructor() { this.readyState = 0; this.sent = []; this.listeners = {}; sockets.push(this) }
    addEventListener(type, listener) { (this.listeners[type] ??= []).push(listener) }
    send(data) { this.sent.push(JSON.parse(data)) }
    close() { this.readyState = 3 }
    fire(type, event = {}) { if (type === 'open') this.readyState = 1; for (const listener of this.listeners[type] ?? []) listener(event) }
    reply(envelope) { this.fire('message', { data: JSON.stringify({ machine_id: 'daemon', ...envelope }) }) }
  }
  const thread = { awaitingSnapshot: false, outboundPrompts: [], memoryPanel: { pending: null } }
  const state = {
    selectedThreadId: 't', daemonMachineId: null, threads: { t: thread },
    catalog: [{ thread_id: 't', project_key: null, project_label: null, workspace_root: null }],
    setConnection() {}, markSnapshotPending() {}, observeDaemon() {}, setTransportError() {}, beginMemoryPanelRequest() {},
    beginPrompt(_threadId, promptId, prompt) { thread.outboundPrompts.push({ prompt_id: promptId, prompt }) },
    receiveEnvelope(envelope) {
      if (envelope.type === 'thread.snapshot') {
        const held = new Set(envelope.payload.messages.map((message) => message.message_id))
        thread.outboundPrompts = thread.outboundPrompts.filter((outbound) => !held.has(outbound.prompt_id))
      }
      return true
    },
  }
  let next = 0
  const modules = {
    './store': { useHarnessStore: { getState: () => state } },
    './protocol': {
      DIRECT_MACHINE_ID: 'direct',
      createBrowserEnvelope: (type, payload, threadId) => ({ v: 1, id: `id-${next++}`, type, payload, thread_id: threadId }),
      parseEnvelope: (data) => JSON.parse(data),
      decodeServerEnvelope: (envelope) => ({ type: envelope.type, payload: envelope.payload }),
    },
    './rackEvents': { publishRackEnvelope() {} },
    './projectPath': {},
  }
  const load = (source, require) => { const exports = {}; vm.runInNewContext(source, { exports, require, WebSocket: FakeWebSocket, location: { host: 'localhost', protocol: 'http:' }, setTimeout: (run) => { run(); return null }, clearTimeout() {} }); return exports }
  modules['./snapshotBarrier'] = load(transpile('../src/snapshotBarrier.ts'), () => ({}))
  const { HarnessSocketClient } = load(transpile('../src/socket.ts'), (name) => modules[name] ?? {})
  const client = new HarnessSocketClient()
  const reconnect = (held) => {
    sockets.at(-1).fire('close')
    const socket = sockets.at(-1)
    socket.fire('open')
    const request = socket.sent.find((envelope) => envelope.type === 'thread.snapshot')
    socket.reply({ type: 'thread.snapshot', thread_id: 't', payload: { request_id: request.id, messages: held } })
    return socket.sent.filter((envelope) => envelope.type === 'prompt.submit')
  }

  client.connect()
  sockets[0].fire('open')
  const first = sockets[0].sent.find((envelope) => envelope.type === 'thread.snapshot')
  sockets[0].reply({ type: 'thread.snapshot', thread_id: 't', payload: { request_id: first.id, messages: [] } })
  const promptId = client.submitPrompt('steer')
  const original = sockets[0].sent.find((envelope) => envelope.type === 'prompt.submit')
  assert.equal(original.id, promptId)

  const resent = reconnect([])
  assert.equal(sockets.length, 2)
  assert.deepEqual(resent, [original])

  assert.deepEqual(reconnect([{ role: 'user', message_id: promptId }]), [])
  assert.deepEqual(thread.outboundPrompts, [])
  assert.deepEqual(reconnect([]), [])
})
