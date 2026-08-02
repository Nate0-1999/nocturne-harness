import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

/* eslint-disable react-refresh/only-export-components -- this file intentionally exports the rack context hooks beside its provider */

import type {
  GateCommitPayload,
  JsonValue,
  ThreadCatalogEntry,
  Ulid,
} from './protocol'
import {
  subscribeRackEnvelopes,
  subscribeRackResize,
  type RackEnvelopeEvent,
  type RackResizeEvent,
} from './rackEvents'
import { RACK_BOUNDS, type RackBounds } from './rackLayout'
import { harnessClient } from './socket'
import {
  useHarnessStore,
  type ConnectionStatus,
  type HarnessError,
  type MemoryPanelState,
  type ThreadState,
} from './store'

export type RackModuleId = 'header' | 'threads' | 'chat' | 'memory' | 'gate'
export type RackModuleSlot = 'header' | 'panel' | 'overlay'
export type RackMemoryPanelState = MemoryPanelState

export function isRackModuleId(value: unknown): value is RackModuleId {
  return value === 'header' ||
    value === 'threads' ||
    value === 'chat' ||
    value === 'memory' ||
    value === 'gate'
}

export interface RackSnapshot {
  catalog: ThreadCatalogEntry[]
  selectedThreadId: string | null
  threads: Record<string, ThreadState>
  connection: ConnectionStatus
  globalError: HarnessError | null
}

export type RackAction =
  | { type: 'thread.create' }
  | { type: 'thread.select'; thread_id: string }
  | { type: 'prompt.submit'; prompt: string }
  | { type: 'run.cancel'; run_id?: Ulid }
  | { type: 'gate.commit'; decision: GateCommitPayload }
  | { type: 'memory.refresh' }
  | { type: 'memory.remove'; memory_id: string }
  | {
      type: 'memory.edit'
      memory_id: string
      expected_revision: number
      body: string
    }
  | {
      type: 'memory.pin'
      memory_id: string
      expected_revision: number
      pin: boolean
    }

export type RackActionType = RackAction['type']

export interface RackModuleManifest {
  id: RackModuleId
  name: string
  version: '1.0.0'
  class: 'visualizer'
  slot: RackModuleSlot
  streams: readonly string[]
  actions: readonly RackActionType[]
  bounds: RackBounds
  movable: boolean
  law_bound: boolean
}

export interface RackQueryRequest {
  resource: 'catalog' | 'selected_thread' | 'memory_panel'
  as_of?: string | null
}

export interface RackQueryResult {
  status: 'live' | 'historical_unavailable'
  as_of: string | null
  data: JsonValue | null
}

export type RackSelection =
  | { kind: 'thread'; id: string }
  | { kind: 'memory'; id: string }
  | { kind: 'module'; id: RackModuleId }
  | null

export interface RackEventSurface {
  getSnapshot: () => RackSnapshot
  subscribeState: (listener: () => void) => () => void
  subscribe: (listener: (event: RackEnvelopeEvent) => void) => () => void
  subscribeResize: (listener: (event: RackResizeEvent) => void) => () => void
  dispatch: <Action extends RackAction>(action: Action) => Promise<RackActionResult<Action>>
}

export interface RackQuerySurface {
  query: (request: RackQueryRequest) => Promise<RackQueryResult>
}

export interface RackSelectionSurface {
  getSnapshot: () => RackSelection
  subscribe: (listener: () => void) => () => void
  select: (selection: RackSelection) => void
}

export interface RackPluginApi {
  manifest: RackModuleManifest
  events: RackEventSurface
  query: RackQuerySurface
  selection: RackSelectionSurface
}

export type RackActionResult<Action extends RackAction> =
  Action['type'] extends 'thread.create'
    ? string
    : Action['type'] extends 'thread.select'
      ? void
      : Ulid

const commonPanelBounds: RackBounds = {
  min: { w: 1, h: 1 },
  preferred: { w: 1, h: 1 },
  max: { w: 12, h: 12 },
}

export const RACK_MANIFESTS: Record<RackModuleId, RackModuleManifest> = {
  header: {
    id: 'header',
    name: 'Nocturne Header',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'header',
    streams: ['connection', 'thread.snapshot'],
    actions: [],
    bounds: {
      min: { w: 12, h: 1 },
      preferred: { w: 12, h: 1 },
      max: { w: 12, h: 1 },
    },
    movable: false,
    law_bound: false,
  },
  threads: {
    id: 'threads',
    name: 'Channel Stack',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'panel',
    streams: ['thread.snapshot', 'run.started', 'run.done', 'prompt.queued'],
    actions: ['thread.create', 'thread.select'],
    bounds: RACK_BOUNDS.threads,
    movable: true,
    law_bound: false,
  },
  chat: {
    id: 'chat',
    name: 'Active Channel',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'panel',
    streams: ['thread.snapshot', 'run.*', 'error'],
    actions: ['prompt.submit', 'run.cancel'],
    bounds: RACK_BOUNDS.chat,
    movable: true,
    law_bound: false,
  },
  memory: {
    id: 'memory',
    name: 'Memory Palace',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'panel',
    streams: ['thread.snapshot', 'memory.panel.update'],
    actions: ['memory.refresh', 'memory.remove', 'memory.edit', 'memory.pin'],
    bounds: RACK_BOUNDS.memory,
    movable: true,
    law_bound: true,
  },
  gate: {
    id: 'gate',
    name: 'Memory Gate',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'overlay',
    streams: ['gate.open', 'gate.dismiss', 'error'],
    actions: ['gate.commit', 'run.cancel'],
    bounds: commonPanelBounds,
    movable: false,
    law_bound: true,
  },
}

let lastStoreState = useHarnessStore.getState()
let lastRackSnapshot = snapshotFromState(lastStoreState)

export function getRackSnapshot(): RackSnapshot {
  const state = useHarnessStore.getState()
  if (state !== lastStoreState) {
    lastStoreState = state
    lastRackSnapshot = snapshotFromState(state)
  }
  return lastRackSnapshot
}

export function subscribeRackState(listener: () => void): () => void {
  return useHarnessStore.subscribe(() => listener())
}

function snapshotFromState(state: ReturnType<typeof useHarnessStore.getState>): RackSnapshot {
  return {
    catalog: state.catalog,
    selectedThreadId: state.selectedThreadId,
    threads: state.threads,
    connection: state.connection,
    globalError: state.globalError,
  }
}

function dispatchRackAction<Action extends RackAction>(
  action: Action,
): RackActionResult<Action> {
  try {
    switch (action.type) {
      case 'thread.create':
        return harnessClient.createThread() as RackActionResult<Action>
      case 'thread.select':
        harnessClient.selectThread(action.thread_id)
        return undefined as RackActionResult<Action>
      case 'prompt.submit':
        return harnessClient.submitPrompt(action.prompt) as RackActionResult<Action>
      case 'run.cancel':
        return harnessClient.cancelRun(action.run_id) as RackActionResult<Action>
      case 'gate.commit':
        return harnessClient.commitGate(action.decision) as RackActionResult<Action>
      case 'memory.refresh':
        return harnessClient.refreshMemoryPanel() as RackActionResult<Action>
      case 'memory.remove':
        return harnessClient.removeMemoryFromContext(action.memory_id) as RackActionResult<Action>
      case 'memory.edit':
        return harnessClient.editMemoryBody(
          action.memory_id,
          action.expected_revision,
          action.body,
        ) as RackActionResult<Action>
      case 'memory.pin':
        return harnessClient.setMemoryPin(
          action.memory_id,
          action.expected_revision,
          action.pin,
        ) as RackActionResult<Action>
    }
  } catch (error) {
    useHarnessStore
      .getState()
      .setTransportError(error instanceof Error ? error.message : 'Rack action failed')
    throw error
  }
}

export const rackQuerySurface: RackQuerySurface = {
  async query(request) {
    const asOf = request.as_of ?? null
    if (asOf !== null && asOf !== 'now') {
      return {
        status: 'historical_unavailable',
        as_of: asOf,
        data: null,
      }
    }
    const snapshot = getRackSnapshot()
    let data: JsonValue | null = null
    if (request.resource === 'catalog') {
      data = snapshot.catalog as unknown as JsonValue
    } else if (request.resource === 'selected_thread') {
      data = snapshot.selectedThreadId === null
        ? null
        : (snapshot.threads[snapshot.selectedThreadId] as unknown as JsonValue) ?? null
    } else if (request.resource === 'memory_panel') {
      const thread = snapshot.selectedThreadId === null
        ? null
        : snapshot.threads[snapshot.selectedThreadId]
      data = (thread?.memoryPanel as MemoryPanelState | undefined) as unknown as JsonValue ?? null
    }
    return { status: 'live', as_of: null, data }
  },
}

let currentSelection: RackSelection = null
const selectionListeners = new Set<() => void>()

export const rackSelectionSurface: RackSelectionSurface = {
  getSnapshot: () => currentSelection,
  subscribe(listener) {
    selectionListeners.add(listener)
    return () => selectionListeners.delete(listener)
  },
  select(selection) {
    if (
      selection?.kind === currentSelection?.kind &&
      selection?.id === currentSelection?.id
    ) {
      return
    }
    currentSelection = selection
    for (const listener of selectionListeners) {
      listener()
    }
  },
}

function streamMatches(declarations: readonly string[], eventType: string): boolean {
  return declarations.some((declaration) =>
    declaration.endsWith('.*')
      ? eventType.startsWith(declaration.slice(0, -1))
      : declaration === eventType,
  )
}

export function createHostPluginApi(manifest: RackModuleManifest): RackPluginApi {
  return {
    manifest,
    events: {
      getSnapshot: getRackSnapshot,
      subscribeState: subscribeRackState,
      subscribe(listener) {
        return subscribeRackEnvelopes((event) => {
          if (streamMatches(manifest.streams, String(event.envelope.type))) {
            listener(event)
          }
        })
      },
      subscribeResize(listener) {
        return subscribeRackResize((event) => {
          if (event.module_id === manifest.id) {
            listener(event)
          }
        })
      },
      async dispatch<Action extends RackAction>(action: Action) {
        if (!(manifest.actions as readonly string[]).includes(action.type)) {
          throw new Error(`${manifest.id} is not permitted to dispatch ${action.type}`)
        }
        return dispatchRackAction(action)
      },
    },
    query: rackQuerySurface,
    selection: rackSelectionSurface,
  }
}

const RackPluginContext = createContext<RackPluginApi | null>(null)

export function RackApiProvider({
  api,
  children,
}: {
  api: RackPluginApi
  children: ReactNode
}) {
  return <RackPluginContext.Provider value={api}>{children}</RackPluginContext.Provider>
}

export function useRackPlugin(): RackPluginApi {
  const api = useContext(RackPluginContext)
  if (api === null) {
    throw new Error('rack module rendered outside its plugin provider')
  }
  return api
}

export function useRackSnapshot(): RackSnapshot {
  const { events } = useRackPlugin()
  return useSyncExternalStore(
    events.subscribeState,
    events.getSnapshot,
    events.getSnapshot,
  )
}

export function useRackHostSnapshot(): RackSnapshot {
  return useSyncExternalStore(subscribeRackState, getRackSnapshot, getRackSnapshot)
}

export function useRackSelection(): RackSelection {
  const { selection } = useRackPlugin()
  return useSyncExternalStore(
    selection.subscribe,
    selection.getSnapshot,
    selection.getSnapshot,
  )
}

export function useRackHostSelection(): RackSelection {
  return useSyncExternalStore(
    rackSelectionSurface.subscribe,
    rackSelectionSurface.getSnapshot,
    rackSelectionSurface.getSnapshot,
  )
}

export function clearRackSelection(): void {
  rackSelectionSurface.select(null)
}

export function RackRuntime({ children }: { children: ReactNode }) {
  const selectedThreadId = useHarnessStore((state) => state.selectedThreadId)

  useEffect(() => {
    harnessClient.connect()
    const state = useHarnessStore.getState()
    if (state.catalog.length === 0) {
      harnessClient.createThread()
    } else if (state.selectedThreadId === null) {
      harnessClient.selectThread(state.catalog[0].thread_id)
    } else {
      harnessClient.requestSnapshot(state.selectedThreadId)
    }
    return () => harnessClient.disconnect()
  }, [])

  useEffect(() => {
    if (selectedThreadId !== null) {
      rackSelectionSurface.select({ kind: 'thread', id: selectedThreadId })
    }
  }, [selectedThreadId])

  return children
}
