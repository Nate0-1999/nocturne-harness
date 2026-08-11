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
import { queueDecisionPayload, seedBatchDecisionPayload } from './approvalQueue'
import {
  subscribeRackEnvelopes,
  subscribeRackResize,
  type RackEnvelopeEvent,
  type RackResizeEvent,
} from './rackEvents'
import {
  RACK_BOUNDS,
  VITALS_RACK_BOUNDS,
  loadRackLayout,
  persistRackLayout,
  type RackBounds,
} from './rackLayout'
import { runRackAction } from './rackAction'
import {
  canonicalProjectPath,
  knownProjectPaths,
} from './projectPath'
import { harnessClient } from './socket'
import {
  useHarnessStore,
  type ConnectionStatus,
  type HarnessError,
  type MemoryPanelState,
  type OutboundImage,
  type ThreadState,
} from './store'

export type RackModuleId = 'header' | 'threads' | 'chat' | 'memory' | 'vitals' | 'context_bars' | 'gate' | 'thread_end' | 'palace_queue' | 'model_device' | 'memory_graph' | 'injection_console'
export type RackModuleSlot = 'header' | 'panel' | 'strip' | 'overlay'
export type RackMemoryPanelState = MemoryPanelState

export function isRackModuleId(value: unknown): value is RackModuleId {
  return value === 'header' ||
    value === 'threads' ||
    value === 'chat' ||
    value === 'memory' ||
    value === 'vitals' ||
    value === 'context_bars' ||
    value === 'gate' ||
    value === 'thread_end' ||
    value === 'palace_queue' ||
    value === 'model_device' ||
    value === 'memory_graph' ||
    value === 'injection_console'
}

export interface RackSnapshot {
  catalog: ThreadCatalogEntry[]
  selectedThreadId: string | null
  currentProjectKey: string | null
  projectPaths: string[]
  threads: Record<string, ThreadState>
  connection: ConnectionStatus
  globalError: HarnessError | null
}

export type RackAction =
  | { type: 'thread.create' }
  | { type: 'thread.select'; thread_id: string }
  | { type: 'project.select'; project_key: string }
  | { type: 'catalog.cleanup-fixtures' }
  | { type: 'prompt.submit'; prompt: string; image?: OutboundImage }
  | { type: 'run.cancel'; run_id?: Ulid }
  | { type: 'thread.archive'; thread_id?: string }
  | { type: 'queue.load'; thread_id?: string; birthplace?: 'thread' | 'seed' }
  | { type: 'seed.upload'; batch_uid: string; source_name: string; markdown: string }
  | { type: 'queue.batch.decide'; batch_uid: string; decision: 'approve' | 'deny' }
  | { type: 'rack.scope.get'; module_id: RackModuleId }
  | { type: 'rack.scope.set'; module_id: RackModuleId; scope: 'GLOBAL' | 'CURRENT' }
  | { type: 'parameter.write'; thread_id: string; parameter_id: string; value: string | number | null }
  | { type: 'scorer.simulate'; injection_id?: string; base_version: string; values: JsonValue; slice_parameter_id: string }
  | { type: 'scorer.force'; event_uid: string; base_version: string; values: JsonValue; simulation_digest: string }
  | { type: 'scorer.retrain' }
  | { type: 'scorer.audition'; injection_id: string; proposal_version: string }
  | { type: 'scorer.activate'; event_uid: string; version: string }
  | {
      type: 'queue.decide'
      item_uid: string
      decision: 'approve' | 'deny'
      approval_mode: 'explicit' | 'passive'
      actor_class: 'human' | 'passive'
    }
  | { type: 'gate.commit'; decision: GateCommitPayload }
  | { type: 'memory.refresh' }
  | { type: 'memory.add'; memory_id: string }
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
  class: 'visualizer' | 'control'
  slot: RackModuleSlot
  streams: readonly string[]
  actions: readonly RackActionType[]
  bounds: RackBounds
  movable: boolean
  law_bound: boolean
  default_scope: 'GLOBAL' | 'CURRENT'
  bindings?: readonly string[]
}

export interface RackQueryRequest {
  resource: 'catalog' | 'selected_thread' | 'memory_panel' | 'vitals' | 'context_window' | 'parameters' | 'memory_graph' | 'scorer_console'
  as_of?: string | null
  thread_id?: string
}

export interface RackQueryResult {
  status: 'live' | 'historical_unavailable'
  as_of: string | null
  data: JsonValue | null
}

export type RackSelection =
  | { kind: 'thread'; id: string }
  | { kind: 'project'; id: string }
  | { kind: 'memory'; id: string }
  | { kind: 'module'; id: RackModuleId }
  | { kind: 'spend_lane'; id: string; as_of: string | null }
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
  Action['type'] extends 'thread.create' | 'project.select'
    ? string
    : Action['type'] extends 'catalog.cleanup-fixtures'
      ? number
    : Action['type'] extends 'thread.select'
      ? void
      : Action['type'] extends 'thread.archive' | 'queue.load' | 'queue.decide' | 'seed.upload' | 'queue.batch.decide' | 'parameter.write' | 'scorer.simulate' | 'scorer.force' | 'scorer.retrain' | 'scorer.audition' | 'scorer.activate'
        ? JsonValue
        : Action['type'] extends 'rack.scope.get' | 'rack.scope.set'
          ? 'GLOBAL' | 'CURRENT'
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
    default_scope: 'GLOBAL',
  },
  threads: {
    id: 'threads',
    name: 'Channel Stack',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'panel',
    streams: ['thread.snapshot', 'run.started', 'run.done', 'prompt.queued'],
    actions: ['thread.create', 'thread.select', 'thread.archive', 'catalog.cleanup-fixtures'],
    bounds: RACK_BOUNDS.threads,
    movable: true,
    law_bound: false,
    default_scope: 'CURRENT',
  },
  chat: {
    id: 'chat',
    name: 'Active Channel',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'panel',
    streams: ['thread.snapshot', 'run.*', 'error'],
    actions: ['project.select', 'prompt.submit', 'run.cancel', 'thread.archive', 'queue.load', 'queue.decide'],
    bounds: RACK_BOUNDS.chat,
    movable: true,
    law_bound: false,
    default_scope: 'CURRENT',
  },
  memory: {
    id: 'memory',
    name: 'Memory Palace',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'panel',
    streams: ['thread.snapshot', 'memory.panel.update'],
    actions: ['memory.refresh', 'memory.add', 'memory.remove', 'memory.edit', 'memory.pin'],
    bounds: RACK_BOUNDS.memory,
    movable: true,
    law_bound: true,
    default_scope: 'CURRENT',
  },
  vitals: {
    id: 'vitals',
    name: 'Palace Vitals',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'strip',
    streams: [],
    actions: ['rack.scope.get', 'rack.scope.set'],
    bounds: VITALS_RACK_BOUNDS,
    movable: false,
    law_bound: false,
    default_scope: 'GLOBAL',
  },
  context_bars: {
    id: 'context_bars', name: 'Context Bars', version: '1.0.0', class: 'visualizer',
    slot: 'strip', streams: ['run.done'], actions: ['rack.scope.get', 'rack.scope.set'],
    bounds: { min: { w: 3, h: 1 }, preferred: { w: 3, h: 4 }, max: { w: 3, h: 4 } },
    movable: false, law_bound: false, default_scope: 'CURRENT',
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
    default_scope: 'CURRENT',
  },
  thread_end: {
    id: 'thread_end',
    name: 'Thread Memory Review',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'overlay',
    streams: ['thread.snapshot'],
    actions: ['queue.load', 'queue.decide', 'rack.scope.get', 'rack.scope.set'],
    bounds: commonPanelBounds,
    movable: false,
    law_bound: true,
    default_scope: 'CURRENT',
  },
  palace_queue: {
    id: 'palace_queue',
    name: 'Palace Queue',
    version: '1.0.0',
    class: 'visualizer',
    slot: 'overlay',
    streams: [],
    actions: ['queue.load', 'seed.upload', 'queue.batch.decide', 'rack.scope.get', 'rack.scope.set'],
    bounds: commonPanelBounds,
    movable: false,
    law_bound: true,
    default_scope: 'GLOBAL',
  },
  model_device: {
    id: 'model_device',
    name: 'Model Device',
    version: '1.0.0',
    class: 'control',
    slot: 'overlay',
    streams: ['parameter.change', 'parameter.refused', 'model.change'],
    actions: ['parameter.write', 'rack.scope.get', 'rack.scope.set'],
    bindings: [
      'model.slug', 'model.temperature', 'model.top_p', 'model.top_k',
      'model.max_tokens', 'model.effort',
    ],
    bounds: commonPanelBounds,
    movable: false,
    law_bound: false,
    default_scope: 'CURRENT',
  },
  memory_graph: {
    id: 'memory_graph', name: 'Memory Graph', version: '1.0.0', class: 'visualizer',
    slot: 'overlay', streams: ['memory.panel.update'],
    actions: ['rack.scope.get', 'rack.scope.set'], bounds: commonPanelBounds,
    movable: false, law_bound: true, default_scope: 'GLOBAL',
  },
  injection_console: {
    id: 'injection_console', name: 'Injection Console', version: '1.0.0', class: 'control',
    slot: 'overlay', streams: ['scorer.change'],
    actions: ['scorer.simulate', 'scorer.force', 'scorer.retrain', 'scorer.audition', 'scorer.activate', 'rack.scope.get', 'rack.scope.set'],
    bindings: [
      'scorer.tau', 'scorer.top_k', 'scorer.budget_tokens',
      'scorer.half_life_time_days', 'scorer.half_life_hist_days',
      'scorer.weight.sem', 'scorer.weight.kw', 'scorer.weight.time',
      'scorer.weight.proj', 'scorer.weight.freq', 'scorer.weight.hist',
    ], bounds: commonPanelBounds, movable: false, law_bound: true, default_scope: 'GLOBAL',
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
  const currentProjectKey = state.selectedThreadId === null
    ? null
    : state.catalog.find((entry) => entry.thread_id === state.selectedThreadId)?.project_key ?? null
  return {
    catalog: state.catalog,
    selectedThreadId: state.selectedThreadId,
    currentProjectKey,
    projectPaths: knownProjectPaths(state.catalog),
    threads: state.threads,
    connection: state.connection,
    globalError: state.globalError,
  }
}

function dispatchRackAction<Action extends RackAction>(
  action: Action,
): RackActionResult<Action> | Promise<RackActionResult<Action>> {
  switch (action.type) {
      case 'thread.create':
        return harnessClient.createThread() as RackActionResult<Action>
      case 'thread.select':
        harnessClient.selectThread(action.thread_id)
        return undefined as RackActionResult<Action>
      case 'project.select': {
        const projectKey = canonicalProjectPath(action.project_key)
        const threadId = harnessClient.selectProject(projectKey)
        rackSelectionSurface.select({ kind: 'project', id: projectKey })
        return threadId as RackActionResult<Action>
      }
      case 'catalog.cleanup-fixtures':
        return useHarnessStore.getState().removeFixtureThreads() as RackActionResult<Action>
      case 'prompt.submit':
        return harnessClient.submitPrompt(action.prompt, action.image) as RackActionResult<Action>
      case 'run.cancel':
        return harnessClient.cancelRun(action.run_id) as RackActionResult<Action>
      case 'thread.archive': {
        const threadId = action.thread_id ?? getRackSnapshot().selectedThreadId
        if (threadId === null) {
          throw new Error('No selected thread to archive')
        }
        if (threadId !== getRackSnapshot().selectedThreadId) {
          harnessClient.selectThread(threadId)
        }
        return fetchJson(`/v1/threads/${encodeURIComponent(threadId)}/archive`, {
          method: 'POST',
        }).then((result) => {
          rackSelectionSurface.select({ kind: 'module', id: 'thread_end' })
          return result as RackActionResult<Action>
        })
      }
      case 'queue.decide':
        return fetchJson(
          `/v1/approval-queue/${encodeURIComponent(action.item_uid)}/decisions`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(queueDecisionPayload({
              decision: action.decision,
              approval_mode: action.approval_mode,
              actor_class: action.actor_class,
            })),
          },
        ) as Promise<RackActionResult<Action>>
      case 'queue.load': {
        const params = new URLSearchParams()
        if (action.thread_id !== undefined) params.set('thread_id', action.thread_id)
        if (action.birthplace !== undefined) params.set('birthplace', action.birthplace)
        const query = params.size === 0 ? '' : `?${params.toString()}`
        return fetchJson(`/v1/approval-queue${query}`) as Promise<RackActionResult<Action>>
      }
      case 'seed.upload':
        return fetchJson('/v1/seeds', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            batch_uid: action.batch_uid,
            source_name: action.source_name,
            markdown: action.markdown,
          }),
        }) as Promise<RackActionResult<Action>>
      case 'queue.batch.decide':
        return fetchJson(
          `/v1/approval-queue/batches/${encodeURIComponent(action.batch_uid)}/decisions`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(seedBatchDecisionPayload(action.decision)),
          },
        ) as Promise<RackActionResult<Action>>
      case 'rack.scope.get':
        return loadRackLayout(globalThis.localStorage).scopes[action.module_id] as
          RackActionResult<Action>
      case 'rack.scope.set': {
        const layout = loadRackLayout(globalThis.localStorage)
        layout.scopes[action.module_id] = action.scope
        persistRackLayout(globalThis.localStorage, layout)
        globalThis.dispatchEvent(new CustomEvent('nocturne:rack-scope', {
          detail: { module_id: action.module_id, scope: action.scope },
        }))
        return action.scope as RackActionResult<Action>
      }
      case 'parameter.write':
        return fetchJson('/v1/rack/parameters', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            module_id: 'model_device',
            thread_id: action.thread_id,
            parameter_id: action.parameter_id,
            value: action.value,
          }),
        }) as Promise<RackActionResult<Action>>
      case 'scorer.simulate':
        return fetchJson('/v1/rack/scorers/simulate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            injection_id: action.injection_id ?? null,
            base_version: action.base_version,
            values: action.values,
            slice_parameter_id: action.slice_parameter_id,
          }),
        }) as Promise<RackActionResult<Action>>
      case 'scorer.force':
        return fetchJson('/v1/rack/scorers', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            event_uid: action.event_uid, base_version: action.base_version,
            values: action.values, simulation_digest: action.simulation_digest, force: true,
          }),
        }) as Promise<RackActionResult<Action>>
      case 'scorer.retrain':
        return fetchJson('/v1/rack/scorers/retrain', {
          method: 'POST',
        }) as Promise<RackActionResult<Action>>
      case 'scorer.audition': {
        return fetchJson('/v1/rack/scorers/audition', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            injection_id: action.injection_id,
            proposal_version: action.proposal_version,
          }),
        }).then((result) => {
          globalThis.dispatchEvent(new CustomEvent('nocturne:scorer-audition', { detail: result }))
          return result as RackActionResult<Action>
        })
      }
      case 'scorer.activate':
        return fetchJson(`/v1/rack/scorers/${encodeURIComponent(action.version)}/activate`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_uid: action.event_uid }),
        }) as Promise<RackActionResult<Action>>
      case 'gate.commit':
        return harnessClient.commitGate(action.decision) as RackActionResult<Action>
      case 'memory.refresh':
        return harnessClient.refreshMemoryPanel() as RackActionResult<Action>
      case 'memory.remove':
        return harnessClient.removeMemoryFromContext(action.memory_id) as RackActionResult<Action>
      case 'memory.add':
        return harnessClient.addMemoryToContext(action.memory_id) as RackActionResult<Action>
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
}

async function fetchJson(path: string, init?: RequestInit): Promise<JsonValue> {
  const response = await globalThis.fetch(path, {
    cache: 'no-store',
    credentials: 'same-origin',
    ...init,
  })
  if (!response.ok) {
    throw new Error(`Rack action failed (${response.status})`)
  }
  return await response.json() as JsonValue
}

export const rackQuerySurface: RackQuerySurface = {
  async query(request) {
    const asOf = request.as_of ?? null
    if (request.resource === 'vitals' || request.resource === 'context_window' || request.resource === 'memory_graph' || request.resource === 'scorer_console') {
      if (asOf !== null && asOf !== 'now') {
        return { status: 'historical_unavailable', as_of: asOf, data: null }
      }
      const url = new URL('/v1/rack/query', globalThis.location.origin)
      url.searchParams.set('resource', request.resource)
      url.searchParams.set('as_of', 'now')
      if (request.thread_id !== undefined) url.searchParams.set('thread_id', request.thread_id)
      const response = await globalThis.fetch(url, {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) {
        throw new Error(`Memory instrumentation is unavailable (${response.status})`)
      }
      return parseRackQueryResult(await response.json())
    }
    if (request.resource === 'parameters') {
      if (request.thread_id === undefined) {
        throw new Error('CURRENT parameter query requires a thread')
      }
      const url = new URL('/v1/rack/query', globalThis.location.origin)
      url.searchParams.set('resource', 'parameters')
      url.searchParams.set('thread_id', request.thread_id)
      url.searchParams.set('as_of', asOf ?? 'now')
      const response = await globalThis.fetch(url, {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) throw new Error(`Model controls are unavailable (${response.status})`)
      return parseRackQueryResult(await response.json())
    }
    if (asOf !== null && asOf !== 'now') {
      return { status: 'historical_unavailable', as_of: asOf, data: null }
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
    if (rackSelectionsEqual(selection, currentSelection)) {
      return
    }
    currentSelection = selection
    for (const listener of selectionListeners) {
      listener()
    }
  },
}

export function rackSelectionsEqual(left: RackSelection, right: RackSelection): boolean {
  if (left === null || right === null) {
    return left === right
  }
  if (left.kind !== right.kind || left.id !== right.id) {
    return false
  }
  return left.kind !== 'spend_lane' || (
    right.kind === 'spend_lane' && left.as_of === right.as_of
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseRackQueryResult(value: unknown): RackQueryResult {
  if (
    !isRecord(value) ||
    (value.status !== 'live' && value.status !== 'historical_unavailable') ||
    (value.as_of !== null && typeof value.as_of !== 'string') ||
    !Object.hasOwn(value, 'data') ||
    !isJsonValue(value.data)
  ) {
    throw new TypeError('Rack query returned an invalid response')
  }
  return {
    status: value.status,
    as_of: value.as_of,
    data: value.data,
  }
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  ) {
    return true
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue)
  }
  return isRecord(value) && Object.values(value).every(isJsonValue)
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
        return runRackAction(
          () => dispatchRackAction(action),
          (message) => useHarnessStore.getState().setTransportError(message),
        )
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
  const currentProjectKey = useHarnessStore((state) => state.selectedThreadId === null
    ? null
    : state.catalog.find((entry) => entry.thread_id === state.selectedThreadId)?.project_key ?? null)

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
      const selection = rackSelectionSurface.getSnapshot()
      if (
        selection?.kind !== 'project' ||
        selection.id !== currentProjectKey
      ) {
        rackSelectionSurface.select({ kind: 'thread', id: selectedThreadId })
      }
    }
  }, [currentProjectKey, selectedThreadId])

  return children
}
