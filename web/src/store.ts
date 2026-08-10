import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import {
  decodeServerEnvelope,
  isUuid,
  type ActiveRunSnapshot,
  type ChatMessage,
  type DecodedServerEvent,
  type Envelope,
  type GateOpenPayload,
  type JsonValue,
  type MemoryPanelItem,
  type MemoryPanelOperation,
  type MemoryPanelServerPayload,
  type PromptQueuedPayload,
  type QueuedPrompt,
  type RunDeltaPayload,
  type RunDonePayload,
  type RunStartedPayload,
  type ThreadCatalogEntry,
  type ThreadSnapshotPayload,
  type Usage,
  type Ulid,
} from './protocol'
import {
  DEFAULT_PROJECT_PATH,
  canonicalProjectPath,
  isCanonicalProjectPath,
} from './projectPath'
import {
  isProjectContextConflict,
  snapshotErrorAfterReconciliation,
  snapshotRequestError,
} from './snapshotBarrier'
import { isLegacyFixtureTitle, normalizedThreadTitle } from './threadTitles'

export const THREAD_CATALOG_STORAGE_KEY = 'harness.thread-catalog.v1'

export type ConnectionStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'

export interface ActiveRunState {
  run_id: Ulid
  prompt_id: Ulid
  state: ActiveRunSnapshot['state']
}

export interface HarnessError {
  message: string
  detail: JsonValue
}

export interface OutboundPrompt {
  prompt_id: Ulid
  prompt: string
}

export interface MemoryPanelPending {
  request_id: Ulid
  operation: MemoryPanelOperation
}

export interface MemoryPanelState {
  items: MemoryPanelItem[]
  total: number
  status: 'idle' | 'loading' | 'ready' | 'error'
  pending: MemoryPanelPending | null
  lastResponse: MemoryPanelServerPayload | null
  completedEditRequestId: Ulid | null
}

export interface ThreadState {
  messages: ChatMessage[]
  outboundPrompts: OutboundPrompt[]
  resolvedModel: string | null
  openGate: GateOpenPayload | null
  activeRun: ActiveRunState | null
  usage: Usage | null
  queuedPrompts: QueuedPrompt[]
  lastError: HarnessError | null
  projectConflictAwaitingSnapshot: boolean
  awaitingSnapshot: boolean
  memoryPanel: MemoryPanelState
}

interface PersistedHarnessState {
  catalog: ThreadCatalogEntry[]
  selectedThreadId: string | null
}

export interface HarnessStoreState extends PersistedHarnessState {
  threads: Record<string, ThreadState>
  connection: ConnectionStatus
  daemonMachineId: string | null
  globalError: HarnessError | null
  createThread: (projectKey?: string | null) => string
  removeFixtureThreads: () => number
  selectThread: (threadId: string) => void
  beginPrompt: (threadId: string, promptId: Ulid, prompt: string) => void
  markCancelling: (threadId: string, runId: Ulid) => void
  markSnapshotPending: (threadId: string) => void
  beginMemoryPanelRequest: (
    threadId: string,
    requestId: Ulid,
    operation: MemoryPanelOperation,
  ) => void
  observeDaemon: (machineId: string) => void
  setConnection: (connection: ConnectionStatus) => void
  setTransportError: (message: string) => void
  clearError: (threadId?: string) => void
  receiveEnvelope: (envelope: Envelope) => boolean
}

function emptyThreadState(): ThreadState {
  return {
    messages: [],
    outboundPrompts: [],
    resolvedModel: null,
    openGate: null,
    activeRun: null,
    usage: null,
    queuedPrompts: [],
    lastError: null,
    projectConflictAwaitingSnapshot: false,
    awaitingSnapshot: false,
    memoryPanel: emptyMemoryPanelState(),
  }
}

function emptyMemoryPanelState(): MemoryPanelState {
  return {
    items: [],
    total: 0,
    status: 'idle',
    pending: null,
    lastResponse: null,
    completedEditRequestId: null,
  }
}

function nextIsoTimestamp(previous: string): string {
  const previousTime = Date.parse(previous)
  const nextTime = Math.max(Date.now(), previousTime + 1)
  return new Date(nextTime).toISOString()
}

function newCatalogEntry(threadId: string, projectKey: string): ThreadCatalogEntry {
  const timestamp = new Date().toISOString()
  return {
    thread_id: threadId,
    title: 'New thread',
    created_at: timestamp,
    updated_at: timestamp,
    project_key: canonicalProjectPath(projectKey),
  }
}

function errorFromPayload(payload: JsonValue): HarnessError {
  let message = 'Harness error'
  if (typeof payload === 'string' && payload.trim()) {
    message = payload
  } else if (
    typeof payload === 'object' &&
    payload !== null &&
    !Array.isArray(payload)
  ) {
    if (typeof payload.message === 'string' && payload.message.trim()) {
      message = payload.message
    } else if (typeof payload.code === 'string' && payload.code.trim()) {
      message = payload.code.replaceAll('_', ' ')
    }
  }
  return { message, detail: payload }
}

function replaceThread(
  threads: Record<string, ThreadState>,
  threadId: string,
  update: (thread: ThreadState) => ThreadState,
): Record<string, ThreadState> {
  return {
    ...threads,
    [threadId]: update(threads[threadId] ?? emptyThreadState()),
  }
}

function assistantForRun(runId: Ulid): Extract<ChatMessage, { role: 'assistant' }> {
  return {
    message_id: runId,
    run_id: runId,
    role: 'assistant',
    content: '',
    thinking: '',
    events: [],
    partial: true,
  }
}

function applyStarted(thread: ThreadState, payload: RunStartedPayload): ThreadState {
  const outbound = thread.outboundPrompts.find(
    (prompt) => prompt.prompt_id === payload.prompt_id,
  )
  let foundUser = false
  let foundAssistant = false
  const messages = thread.messages.map((message): ChatMessage => {
    if (message.role === 'user' && message.message_id === payload.prompt_id) {
      foundUser = true
      return { ...message, run_id: payload.run_id, state: 'running' }
    }
    if (message.role === 'assistant' && message.run_id === payload.run_id) {
      foundAssistant = true
    }
    return message
  })
  if (!foundUser && outbound !== undefined) {
    const userMessage: ChatMessage = {
      message_id: payload.prompt_id,
      run_id: payload.run_id,
      role: 'user',
      content: outbound.prompt,
      state: 'running',
    }
    const assistantIndex = messages.findIndex(
      (message) => message.role === 'assistant' && message.run_id === payload.run_id,
    )
    if (assistantIndex === -1) {
      messages.push(userMessage)
    } else {
      messages.splice(assistantIndex, 0, userMessage)
    }
  }
  if (!foundAssistant) {
    messages.push(assistantForRun(payload.run_id))
  }
  return {
    ...thread,
    messages,
    resolvedModel: payload.resolved_model ?? thread.resolvedModel,
    outboundPrompts: thread.outboundPrompts.filter(
      (prompt) => prompt.prompt_id !== payload.prompt_id,
    ),
    activeRun: {
      run_id: payload.run_id,
      prompt_id: payload.prompt_id,
      state: 'running',
    },
    usage: {
      requests: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
    queuedPrompts: thread.queuedPrompts.filter(
      (prompt) =>
        prompt.run_id !== payload.run_id && prompt.prompt_id !== payload.prompt_id,
    ),
    lastError: null,
    projectConflictAwaitingSnapshot: false,
  }
}

function applyQueued(thread: ThreadState, payload: PromptQueuedPayload): ThreadState {
  const outbound = thread.outboundPrompts.find(
    (prompt) => prompt.prompt_id === payload.prompt_id,
  )
  let prompt = outbound?.prompt ?? ''
  let foundUser = false
  const messages = thread.messages.map((message): ChatMessage => {
    if (message.role === 'user' && message.message_id === payload.prompt_id) {
      foundUser = true
      prompt = message.content
      return { ...message, run_id: payload.run_id, state: 'queued' }
    }
    return message
  })
  if (!foundUser && outbound !== undefined) {
    messages.push({
      message_id: payload.prompt_id,
      run_id: payload.run_id,
      role: 'user',
      content: outbound.prompt,
      state: 'queued',
    })
  }
  const exists = thread.queuedPrompts.some(
    (queued) =>
      queued.run_id === payload.run_id || queued.prompt_id === payload.prompt_id,
  )
  return {
    ...thread,
    messages,
    outboundPrompts: thread.outboundPrompts.filter(
      (item) => item.prompt_id !== payload.prompt_id,
    ),
    queuedPrompts:
      exists || !prompt
        ? thread.queuedPrompts
        : [
            ...thread.queuedPrompts,
            {
              run_id: payload.run_id,
              prompt_id: payload.prompt_id,
              prompt,
            },
          ],
  }
}

function applyDelta(thread: ThreadState, payload: RunDeltaPayload): ThreadState {
  if (thread.activeRun?.run_id !== payload.run_id) {
    return thread
  }
  let found = false
  const messages = thread.messages.map((message): ChatMessage => {
    if (message.role !== 'assistant' || message.run_id !== payload.run_id) {
      return message
    }
    found = true
    if (payload.kind === 'text') {
      return { ...message, content: message.content + payload.text }
    }
    if (payload.kind === 'thinking') {
      return { ...message, thinking: message.thinking + payload.text }
    }
    return { ...message, events: [...message.events, payload.event] }
  })
  if (!found) {
    const assistant = assistantForRun(payload.run_id)
    if (payload.kind === 'text') {
      assistant.content = payload.text
    } else if (payload.kind === 'thinking') {
      assistant.thinking = payload.text
    } else {
      assistant.events = [payload.event]
    }
    messages.push(assistant)
  }
  return {
    ...thread,
    messages,
    resolvedModel:
      payload.kind === 'event' && payload.resolved_model !== undefined
        ? payload.resolved_model
        : thread.resolvedModel,
  }
}

function applyDone(thread: ThreadState, payload: RunDonePayload): ThreadState {
  const messages = thread.messages.map((message): ChatMessage => {
    if (message.run_id !== payload.run_id) {
      return message
    }
    if (message.role === 'user') {
      return { ...message, state: payload.stop_reason }
    }
    return { ...message, partial: payload.partial }
  })
  return {
    ...thread,
    messages,
    activeRun:
      thread.activeRun?.run_id === payload.run_id ? null : thread.activeRun,
  }
}

function replaceFromSnapshot(
  payload: ThreadSnapshotPayload,
  previous: ThreadState,
): ThreadState {
  const active = payload.active_run
  const representedPromptIds = new Set(
    payload.messages
      .filter((message) => message.role === 'user')
      .map((message) => message.message_id),
  )
  return {
    messages: payload.messages,
    outboundPrompts: previous.outboundPrompts.filter(
      (prompt) => !representedPromptIds.has(prompt.prompt_id),
    ),
    resolvedModel: payload.resolved_model,
    openGate: payload.open_gate,
    activeRun:
      active === null
        ? null
        : {
            run_id: active.run_id,
            prompt_id: active.prompt_id,
            state: active.state,
          },
    usage: active?.usage ?? null,
    queuedPrompts: active?.queued ?? [],
    lastError: snapshotErrorAfterReconciliation(
      previous.lastError,
      previous.projectConflictAwaitingSnapshot,
    ),
    projectConflictAwaitingSnapshot: false,
    awaitingSnapshot: false,
    memoryPanel: {
      ...emptyMemoryPanelState(),
      completedEditRequestId: previous.memoryPanel.completedEditRequestId,
    },
  }
}

function applyMemoryPanelUpdate(
  panel: MemoryPanelState,
  payload: MemoryPanelServerPayload,
): MemoryPanelState {
  const pending =
    panel.pending?.request_id === payload.request_id ? null : panel.pending

  if (payload.action === 'state') {
    return {
      items: payload.items,
      total: payload.total,
      status: 'ready',
      pending,
      lastResponse: payload,
      completedEditRequestId:
        payload.result === 'edited'
          ? payload.request_id
          : panel.completedEditRequestId,
    }
  }

  if (payload.action === 'conflict') {
    const existing = panel.items.find(
      (item) => item.memory.memory_id === payload.memory.memory_id,
    )
    const currentItem: MemoryPanelItem = {
      ...(existing ?? {}),
      memory: payload.memory,
      in_context: existing?.in_context ?? false,
      thread_excluded: existing?.thread_excluded ?? false,
    }
    const currentItems =
      existing === undefined
        ? [...panel.items, currentItem]
        : panel.items.map((item) =>
            item.memory.memory_id === payload.memory.memory_id
              ? currentItem
              : item,
          )
    const wasActive = existing?.memory.status === 'active'
    const isActive = payload.memory.status === 'active'
    const totalDelta = wasActive === isActive ? 0 : isActive ? 1 : -1
    return {
      ...panel,
      items: currentItems,
      total: Math.max(0, panel.total + totalDelta),
      status: 'ready',
      pending,
      lastResponse: payload,
    }
  }

  return {
    ...panel,
    status: panel.items.length === 0 ? 'error' : 'ready',
    pending,
    lastResponse: payload,
  }
}

function applyEvent(thread: ThreadState, event: DecodedServerEvent): ThreadState {
  switch (event.type) {
    case 'run.started':
      return applyStarted(thread, event.payload)
    case 'prompt.queued':
      return applyQueued(thread, event.payload)
    case 'run.delta':
      return applyDelta(thread, event.payload)
    case 'run.usage':
      return thread.activeRun?.run_id === event.payload.run_id
        ? {
            ...thread,
            usage: {
              requests: event.payload.requests,
              input_tokens: event.payload.input_tokens,
              output_tokens: event.payload.output_tokens,
              cache_read_tokens: event.payload.cache_read_tokens,
              cache_write_tokens: event.payload.cache_write_tokens,
            },
          }
        : thread
    case 'run.done':
      return applyDone(thread, event.payload)
    case 'gate.open':
      return {
        ...thread,
        openGate: event.payload,
        lastError: null,
        projectConflictAwaitingSnapshot: false,
        activeRun:
          thread.activeRun?.run_id === event.payload.run_id
            ? { ...thread.activeRun, state: 'waiting_gate' }
            : thread.activeRun,
      }
    case 'gate.dismiss': {
      const matchesGate = thread.openGate?.run_id === event.payload.run_id
      return {
        ...thread,
        openGate: matchesGate ? null : thread.openGate,
        activeRun:
          matchesGate &&
          thread.activeRun?.run_id === event.payload.run_id &&
          thread.activeRun.state === 'waiting_gate'
            ? { ...thread.activeRun, state: 'running' }
            : thread.activeRun,
      }
    }
    case 'memory.panel.update':
      return {
        ...thread,
        memoryPanel: applyMemoryPanelUpdate(thread.memoryPanel, event.payload),
      }
    case 'model.change':
      return { ...thread, resolvedModel: event.payload.new_model }
    case 'error':
      {
        const lastError = errorFromPayload(event.payload)
        return {
          ...thread,
          lastError,
          projectConflictAwaitingSnapshot: isProjectContextConflict(lastError),
        }
      }
    default:
      return thread
  }
}

function isIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    !Number.isNaN(Date.parse(value)) &&
    new Date(value).toISOString() === value
  )
}

function restoredState(value: unknown): PersistedHarnessState {
  if (typeof value !== 'object' || value === null) {
    return { catalog: [], selectedThreadId: null }
  }
  const candidate = value as Partial<PersistedHarnessState>
  const seen = new Set<string>()
  const catalog: ThreadCatalogEntry[] = []
  if (Array.isArray(candidate.catalog)) {
    for (const entry of candidate.catalog) {
      if (
        typeof entry !== 'object' ||
        entry === null ||
        !isUuid(entry.thread_id) ||
        seen.has(entry.thread_id) ||
        typeof entry.title !== 'string' ||
        !isIsoTimestamp(entry.created_at) ||
        !isIsoTimestamp(entry.updated_at)
      ) {
        continue
      }
      const projectKey = Object.hasOwn(entry, 'project_key')
        ? entry.project_key
        : null
      if (projectKey !== null && !isCanonicalProjectPath(projectKey)) {
        continue
      }
      seen.add(entry.thread_id)
      catalog.push({
        thread_id: entry.thread_id,
        title: entry.title,
        created_at: entry.created_at,
        updated_at: entry.updated_at,
        project_key: projectKey,
      })
    }
  }
  const selectedThreadId =
    typeof candidate.selectedThreadId === 'string' &&
    seen.has(candidate.selectedThreadId)
      ? candidate.selectedThreadId
      : null
  return { catalog, selectedThreadId }
}

function runtimeForCatalog(catalog: ThreadCatalogEntry[]): Record<string, ThreadState> {
  return Object.fromEntries(
    catalog.map((entry) => [
      entry.thread_id,
      { ...emptyThreadState(), awaitingSnapshot: true },
    ]),
  )
}

export const useHarnessStore = create<HarnessStoreState>()(
  persist<HarnessStoreState, [], [], PersistedHarnessState>(
    (set, get) => ({
      catalog: [],
      selectedThreadId: null,
      threads: {},
      connection: 'disconnected',
      daemonMachineId: null,
      globalError: null,

      createThread: (requestedProjectKey) => {
        const current = get()
        const selectedProjectKey = current.selectedThreadId === null
          ? null
          : current.catalog.find((entry) => entry.thread_id === current.selectedThreadId)
            ?.project_key ?? null
        const projectKey = canonicalProjectPath(
          requestedProjectKey ?? selectedProjectKey ?? DEFAULT_PROJECT_PATH,
        )
        let threadId = globalThis.crypto.randomUUID()
        while (get().catalog.some((entry) => entry.thread_id === threadId)) {
          threadId = globalThis.crypto.randomUUID()
        }
        const entry = newCatalogEntry(threadId, projectKey)
        set((state) => ({
          catalog: [...state.catalog, entry],
          selectedThreadId: threadId,
          threads: {
            ...state.threads,
            [threadId]: emptyThreadState(),
          },
          globalError: null,
        }))
        return threadId
      },

      removeFixtureThreads: () => {
        const fixtureIds = new Set(
          get().catalog
            .filter((entry) => isLegacyFixtureTitle(entry.title))
            .map((entry) => entry.thread_id),
        )
        if (fixtureIds.size === 0) {
          return 0
        }
        set((state) => {
          const catalog = state.catalog.filter((entry) => !fixtureIds.has(entry.thread_id))
          const threads = Object.fromEntries(
            Object.entries(state.threads).filter(([threadId]) => !fixtureIds.has(threadId)),
          )
          return {
            catalog,
            threads,
            selectedThreadId: state.selectedThreadId !== null && fixtureIds.has(state.selectedThreadId)
              ? catalog[0]?.thread_id ?? null
              : state.selectedThreadId,
          }
        })
        return fixtureIds.size
      },

      selectThread: (threadId) => {
        if (!get().catalog.some((entry) => entry.thread_id === threadId)) {
          throw new RangeError('thread is not in the local catalog')
        }
        set((state) => ({
          selectedThreadId: threadId,
          threads: replaceThread(state.threads, threadId, (thread) => ({
            ...thread,
            lastError: snapshotRequestError(
              thread.lastError,
              thread.projectConflictAwaitingSnapshot,
            ),
          })),
          globalError: null,
        }))
      },

      beginPrompt: (threadId, promptId, prompt) => {
        const title = normalizedThreadTitle(prompt)
        if (!title) {
          throw new TypeError('prompt must not be blank')
        }
        set((state) => ({
          catalog: state.catalog.map((entry) => {
            if (entry.thread_id !== threadId) {
              return entry
            }
            const firstPrompt = entry.created_at === entry.updated_at
            return {
              ...entry,
              title: firstPrompt ? title : entry.title,
              updated_at: nextIsoTimestamp(entry.updated_at),
            }
          }),
          threads: replaceThread(state.threads, threadId, (thread) => ({
            ...thread,
            outboundPrompts: [
              ...thread.outboundPrompts.filter(
                (outbound) => outbound.prompt_id !== promptId,
              ),
              { prompt_id: promptId, prompt },
            ],
            lastError: null,
            projectConflictAwaitingSnapshot: false,
          })),
        }))
      },

      markCancelling: (threadId, runId) => {
        set((state) => ({
          threads: replaceThread(state.threads, threadId, (thread) => ({
            ...thread,
            activeRun:
              thread.activeRun?.run_id === runId
                ? { ...thread.activeRun, state: 'cancelling' }
                : thread.activeRun,
          })),
        }))
      },

      markSnapshotPending: (threadId) => {
        set((state) => ({
          threads: replaceThread(state.threads, threadId, (thread) => ({
            ...thread,
            lastError: snapshotRequestError(
              thread.lastError,
              thread.projectConflictAwaitingSnapshot,
            ),
            awaitingSnapshot: true,
            memoryPanel: {
              ...thread.memoryPanel,
              status: 'loading',
              pending: null,
            },
          })),
        }))
      },

      beginMemoryPanelRequest: (threadId, requestId, operation) => {
        set((state) => ({
          threads: replaceThread(state.threads, threadId, (thread) => ({
            ...thread,
            memoryPanel: {
              ...thread.memoryPanel,
              status:
                operation === 'refresh' && thread.memoryPanel.items.length === 0
                  ? 'loading'
                  : thread.memoryPanel.status,
              pending: { request_id: requestId, operation },
            },
          })),
        }))
      },

      observeDaemon: (machineId) => {
        if (machineId.trim()) {
          set({ daemonMachineId: machineId })
        }
      },

      setConnection: (connection) => set({ connection }),

      setTransportError: (message) => {
        set({
          globalError: { message, detail: message },
        })
      },

      clearError: (threadId) => {
        if (threadId === undefined) {
          set({ globalError: null })
          return
        }
        set((state) => ({
          threads: replaceThread(state.threads, threadId, (thread) => ({
            ...thread,
            lastError: null,
            projectConflictAwaitingSnapshot: false,
          })),
        }))
      },

      receiveEnvelope: (envelope) => {
        get().observeDaemon(envelope.machine_id)
        const event = decodeServerEnvelope(envelope)
        if (event === null || event.type === 'unknown') {
          return false
        }

        const selectedThreadId = get().selectedThreadId
        if (event.type === 'error' && envelope.thread_id === undefined) {
          set({ globalError: errorFromPayload(event.payload) })
          return false
        }
        if (
          selectedThreadId === null ||
          envelope.thread_id !== selectedThreadId
        ) {
          return false
        }

        if (event.type === 'thread.snapshot') {
          set((state) => ({
            catalog: state.catalog.map((entry) => entry.thread_id === selectedThreadId
              ? { ...entry, project_key: event.payload.project_key }
              : entry),
            threads: {
              ...state.threads,
              [selectedThreadId]: replaceFromSnapshot(
                event.payload,
                state.threads[selectedThreadId] ?? emptyThreadState(),
              ),
            },
            globalError: null,
          }))
          return true
        }

        set((state) => ({
          threads: replaceThread(state.threads, selectedThreadId, (thread) =>
            applyEvent(thread, event),
          ),
        }))
        return false
      },
    }),
    {
      name: THREAD_CATALOG_STORAGE_KEY,
      partialize: (state) => ({
        catalog: state.catalog,
        selectedThreadId: state.selectedThreadId,
      }),
      merge: (persisted, current) => {
        const restored = restoredState(persisted)
        return {
          ...current,
          ...restored,
          threads: runtimeForCatalog(restored.catalog),
        }
      },
    },
  ),
)
