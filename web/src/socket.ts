import {
  createBrowserEnvelope,
  decodeServerEnvelope,
  DIRECT_MACHINE_ID,
  isUuid,
  parseEnvelope,
  type BrowserMessageType,
  type BrowserPayloadMap,
  type Envelope,
  type GateCommitPayload,
  type MemoryPanelOperation,
  type MemoryPanelRequestPayload,
  type PromptImage,
  type Ulid,
} from './protocol'
import { publishRackEnvelope } from './rackEvents'
import { canonicalProjectPath, newestProjectThread } from './projectPath'
import { snapshotBarrierRoute } from './snapshotBarrier'
import {
  useHarnessStore,
  type HarnessStoreState,
  type OutboundImage,
} from './store'

const INITIAL_RECONNECT_DELAY_MS = 250
const MAX_RECONNECT_DELAY_MS = 4_000

export const SNAPSHOT_RESYNC_CLOSE_CODE = 1013
export const SNAPSHOT_RESYNC_REASON = 'snapshot resync required'

export function webSocketUrl(
  location: Pick<Location, 'host' | 'protocol'> = globalThis.location,
): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${location.host}/ws`
}

function selectedRuntime(state: HarnessStoreState) {
  return state.selectedThreadId === null
    ? null
    : (state.threads[state.selectedThreadId] ?? null)
}

/** Own the one direct browser-to-daemon WebSocket and its snapshot barrier. */
export class HarnessSocketClient {
  private socket: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null
  private reconnectAttempt = 0
  private intentionallyClosed = true
  private generation = 0
  private snapshotBarrierThreadId: string | null = null

  connect(): void {
    this.intentionallyClosed = false
    if (
      this.socket !== null &&
      (this.socket.readyState === WebSocket.CONNECTING ||
        this.socket.readyState === WebSocket.OPEN)
    ) {
      return
    }
    if (this.reconnectTimer !== null) {
      globalThis.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.openSocket(this.reconnectAttempt > 0)
  }

  disconnect(): void {
    this.intentionallyClosed = true
    this.generation += 1
    this.snapshotBarrierThreadId = null
    if (this.reconnectTimer !== null) {
      globalThis.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    const socket = this.socket
    this.socket = null
    if (
      socket !== null &&
      (socket.readyState === WebSocket.CONNECTING ||
        socket.readyState === WebSocket.OPEN)
    ) {
      socket.close(1000, 'client closed')
    }
    useHarnessStore.getState().setConnection('disconnected')
  }

  createThread(projectKey?: string | null): string {
    const threadId = useHarnessStore.getState().createThread(projectKey)
    this.requestSnapshot(threadId)
    return threadId
  }

  selectThread(threadId: string): void {
    useHarnessStore.getState().selectThread(threadId)
    this.requestSnapshot(threadId)
  }

  selectProject(projectPath: string): string {
    const projectKey = canonicalProjectPath(projectPath)
    const existing = newestProjectThread(useHarnessStore.getState().catalog, projectKey)
    if (existing === null) {
      return this.createThread(projectKey)
    }
    this.selectThread(existing.thread_id)
    return existing.thread_id
  }

  requestSnapshot(threadId?: string): Ulid | null {
    const state = useHarnessStore.getState()
    const selectedThreadId = threadId ?? state.selectedThreadId
    if (selectedThreadId === null) {
      return null
    }
    const entry = state.catalog.find((candidate) => candidate.thread_id === selectedThreadId)
    if (entry === undefined) {
      throw new RangeError('thread is not in the local catalog')
    }

    state.markSnapshotPending(selectedThreadId)
    this.snapshotBarrierThreadId = selectedThreadId
    if (!this.isOpen()) {
      this.connect()
      return null
    }
    return this.send(
      'thread.snapshot',
      { request: true, project_key: entry.project_key },
      selectedThreadId,
    ).id
  }

  submitPrompt(prompt: string, image?: OutboundImage): Ulid {
    if (!prompt.trim()) {
      throw new TypeError('prompt must not be blank')
    }
    const state = useHarnessStore.getState()
    const threadId = state.selectedThreadId
    if (threadId === null) {
      throw new Error('create or select a thread before submitting a prompt')
    }
    if (selectedRuntime(state)?.awaitingSnapshot) {
      throw new Error('wait for the authoritative thread snapshot before submitting')
    }
    const payload: { prompt: string; image?: PromptImage } = image === undefined
      ? { prompt }
      : { prompt, image: image.input }
    const envelope = this.send('prompt.submit', payload, threadId)
    useHarnessStore.getState().beginPrompt(threadId, envelope.id, prompt, image)
    return envelope.id
  }

  cancelRun(runId?: Ulid): Ulid {
    const state = useHarnessStore.getState()
    const threadId = state.selectedThreadId
    const activeRun = selectedRuntime(state)?.activeRun
    const selectedRunId = runId ?? activeRun?.run_id
    if (threadId === null || selectedRunId === undefined) {
      throw new Error('there is no active run to cancel')
    }
    const envelope = this.send(
      'run.cancel',
      { run_id: selectedRunId },
      threadId,
    )
    useHarnessStore.getState().markCancelling(threadId, selectedRunId)
    return envelope.id
  }

  commitGate(decision: GateCommitPayload): Ulid {
    const state = useHarnessStore.getState()
    const threadId = state.selectedThreadId
    const openGate = selectedRuntime(state)?.openGate
    if (threadId === null || openGate == null) {
      throw new Error('there is no open memory gate to continue')
    }
    if (
      decision.run_id !== openGate.run_id ||
      decision.injection_id !== openGate.injection_id
    ) {
      throw new Error('the memory decision does not match the open gate')
    }
    return this.send('gate.commit', decision, threadId).id
  }

  refreshMemoryPanel(): Ulid {
    return this.sendMemoryPanelRequest('refresh', { action: 'refresh' })
  }

  removeMemoryFromContext(memoryId: string): Ulid {
    if (!isUuid(memoryId)) {
      throw new TypeError('memory id must be a UUID')
    }
    return this.sendMemoryPanelRequest('remove', {
      action: 'remove',
      memory_id: memoryId,
    })
  }

  addMemoryToContext(memoryId: string): Ulid {
    if (!isUuid(memoryId)) {
      throw new TypeError('memory id must be a UUID')
    }
    return this.sendMemoryPanelRequest('add', {
      action: 'add',
      memory_id: memoryId,
    })
  }

  editMemoryBody(
    memoryId: string,
    expectedRevision: number,
    body: string,
  ): Ulid {
    if (!isUuid(memoryId)) {
      throw new TypeError('memory id must be a UUID')
    }
    if (!Number.isInteger(expectedRevision) || expectedRevision < 1) {
      throw new TypeError('expected revision must be a positive integer')
    }
    if (!body.trim()) {
      throw new TypeError('memory body must not be blank')
    }
    return this.sendMemoryPanelRequest('edit', {
      action: 'edit',
      memory_id: memoryId,
      expected_revision: expectedRevision,
      body,
    })
  }

  setMemoryPin(
    memoryId: string,
    expectedRevision: number,
    pin: boolean,
  ): Ulid {
    if (!isUuid(memoryId)) {
      throw new TypeError('memory id must be a UUID')
    }
    if (!Number.isInteger(expectedRevision) || expectedRevision < 1) {
      throw new TypeError('expected revision must be a positive integer')
    }
    return this.sendMemoryPanelRequest('pin', {
      action: 'pin',
      memory_id: memoryId,
      expected_revision: expectedRevision,
      pin,
    })
  }

  private openSocket(reconnecting: boolean): void {
    const generation = ++this.generation
    useHarnessStore
      .getState()
      .setConnection(reconnecting ? 'reconnecting' : 'connecting')

    let socket: WebSocket
    try {
      socket = new WebSocket(webSocketUrl())
    } catch (error) {
      useHarnessStore
        .getState()
        .setTransportError(
          error instanceof Error ? error.message : 'Unable to open Harness socket',
        )
      this.scheduleReconnect()
      return
    }
    this.socket = socket

    socket.addEventListener('open', () => {
      if (generation !== this.generation || socket !== this.socket) {
        socket.close(1000, 'superseded')
        return
      }
      this.reconnectAttempt = 0
      useHarnessStore.getState().setConnection('connected')
      const threadId = useHarnessStore.getState().selectedThreadId
      if (threadId !== null) {
        this.requestSnapshot(threadId)
      }
    })

    socket.addEventListener('message', (event) => {
      if (
        generation !== this.generation ||
        socket !== this.socket ||
        typeof event.data !== 'string'
      ) {
        return
      }
      const envelope = parseEnvelope(event.data)
      if (envelope === null) {
        useHarnessStore
          .getState()
          .setTransportError('Received an invalid daemon envelope')
        return
      }

      const decoded = decodeServerEnvelope(envelope)
      const store = useHarnessStore.getState()
      store.observeDaemon(envelope.machine_id)
      const barrierRoute = snapshotBarrierRoute(
        this.snapshotBarrierThreadId,
        envelope.thread_id,
        decoded?.type ?? null,
      )
      if (barrierRoute.publish) {
        publishRackEnvelope({ direction: 'inbound', envelope })
      }
      const barrierDisposition = barrierRoute.disposition
      if (barrierDisposition !== 'outside') {
        if (barrierDisposition === 'error') {
          store.receiveEnvelope(envelope)
          return
        }
        if (barrierDisposition === 'drop') {
          return
        }
        if (store.receiveEnvelope(envelope)) {
          this.snapshotBarrierThreadId = null
          this.refreshMemoryPanelIfIdle()
        }
        return
      }
      const acceptedSnapshot = store.receiveEnvelope(envelope)
      if (decoded?.type === 'thread.snapshot' && acceptedSnapshot) {
        this.refreshMemoryPanelIfIdle()
        return
      }
      if (
        decoded?.type !== 'run.done' ||
        envelope.thread_id !== useHarnessStore.getState().selectedThreadId
      ) {
        return
      }
      this.refreshMemoryPanelIfIdle()
    })

    socket.addEventListener('error', () => {
      if (generation === this.generation && socket === this.socket) {
        useHarnessStore
          .getState()
          .setTransportError('Harness connection interrupted')
      }
    })

    socket.addEventListener('close', () => {
      if (generation !== this.generation || socket !== this.socket) {
        return
      }
      this.socket = null
      if (this.intentionallyClosed) {
        useHarnessStore.getState().setConnection('disconnected')
        return
      }
      useHarnessStore.getState().setConnection('reconnecting')
      this.scheduleReconnect()
    })
  }

  private scheduleReconnect(): void {
    if (this.intentionallyClosed || this.reconnectTimer !== null) {
      return
    }
    const delay = Math.min(
      INITIAL_RECONNECT_DELAY_MS * 2 ** this.reconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    )
    this.reconnectAttempt += 1
    this.reconnectTimer = globalThis.setTimeout(() => {
      this.reconnectTimer = null
      this.openSocket(true)
    }, delay)
  }

  private isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN
  }

  private sendMemoryPanelRequest(
    operation: MemoryPanelOperation,
    payload: MemoryPanelRequestPayload,
  ): Ulid {
    const state = useHarnessStore.getState()
    const threadId = state.selectedThreadId
    if (threadId === null) {
      throw new Error('create or select a thread before opening memories')
    }
    if (selectedRuntime(state)?.awaitingSnapshot) {
      throw new Error('wait for the authoritative thread snapshot before opening memories')
    }
    const envelope = this.send('memory.panel.update', payload, threadId)
    useHarnessStore
      .getState()
      .beginMemoryPanelRequest(threadId, envelope.id, operation)
    return envelope.id
  }

  private refreshMemoryPanelIfIdle(): void {
    const runtime = selectedRuntime(useHarnessStore.getState())
    if (
      runtime === null ||
      runtime.awaitingSnapshot ||
      runtime.memoryPanel.pending !== null
    ) {
      return
    }
    try {
      this.refreshMemoryPanel()
    } catch (error) {
      useHarnessStore
        .getState()
        .setTransportError(
          error instanceof Error
            ? error.message
            : 'Memory panel could not be refreshed',
        )
    }
  }

  private send<Type extends BrowserMessageType>(
    type: Type,
    payload: BrowserPayloadMap[Type],
    threadId: string,
  ): Envelope<Type, BrowserPayloadMap[Type]> {
    if (!this.isOpen() || this.socket === null) {
      throw new Error('Harness is not connected')
    }
    const state = useHarnessStore.getState()
    const envelope = createBrowserEnvelope(
      type,
      payload,
      threadId,
      state.daemonMachineId ?? DIRECT_MACHINE_ID,
    )
    this.socket.send(JSON.stringify(envelope))
    publishRackEnvelope({ direction: 'outbound', envelope })
    return envelope
  }
}

export const harnessClient = new HarnessSocketClient()
