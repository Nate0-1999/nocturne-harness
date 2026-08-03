import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import { AssistantMarkdown } from './AssistantMarkdown'
import { MemoryGate } from './MemoryGate'
import { MemoryPanel } from './MemoryPanel'
import { VitalsModule } from './VitalsModule'
import type {
  AssistantTranscriptMessage,
  ChatMessage,
  JsonValue,
  UserMessageState,
} from './protocol'
import {
  RackRuntime,
  RACK_MANIFESTS,
  clearRackSelection,
  isRackModuleId,
  useRackHostSnapshot,
  useRackHostSelection,
  useRackPlugin,
  useRackSelection,
  useRackSnapshot,
  type RackMemoryPanelState,
  type RackModuleManifest,
} from './rack'
import {
  RackPluginIframe,
  RackRemoteProvider,
} from './rackBridge'
import { publishRackResize } from './rackEvents'
import {
  FACTORY_RACK_LAYOUT,
  RACK_COLUMNS,
  cloneFactoryLayout,
  loadRackLayout,
  loadSavedRackSet,
  moduleGridColumn,
  moveRackModule,
  orderedModules,
  persistRackLayout,
  rackBodyRowAllocation,
  rackLayoutsEqual,
  resizeRackModule,
  saveRackSet,
  type DockedModuleId,
  type RackLayoutSet,
} from './rackLayout'

const EMPTY_MESSAGES: ChatMessage[] = []
const EMPTY_MEMORY_PANEL: RackMemoryPanelState = {
  items: [],
  total: 0,
  status: 'idle',
  pending: null,
  lastResponse: null,
  completedEditRequestId: null,
}

function shortId(value: string): string {
  return value.slice(0, 8).toUpperCase()
}

function connectionCopy(connection: string): string {
  switch (connection) {
    case 'connected':
      return 'Link live'
    case 'connecting':
      return 'Connecting'
    case 'reconnecting':
      return 'Resyncing'
    default:
      return 'Offline'
  }
}

function terminalCopy(reason: UserMessageState): string | null {
  switch (reason) {
    case 'cancelled':
      return 'Stopped · partial kept'
    case 'budget_exceeded':
      return 'Budget limit reached · partial kept'
    case 'error':
      return 'Run error · partial kept'
    default:
      return null
  }
}

function messageStatus(
  message: AssistantTranscriptMessage,
  state: UserMessageState | undefined,
  activeRunId: string | undefined,
  activeState: string | undefined,
): string | null {
  if (activeRunId === message.run_id) {
    if (activeState === 'cancelling') {
      return 'Stopping'
    }
    return activeState === 'waiting_gate' ? 'Waiting for memory review' : 'Streaming'
  }
  return state === undefined ? (message.partial ? 'Partial' : null) : terminalCopy(state)
}

function initialRackLayout(): RackLayoutSet {
  try {
    return loadRackLayout(globalThis.localStorage)
  } catch {
    return cloneFactoryLayout()
  }
}

function initialSavedRackSet(): RackLayoutSet | null {
  try {
    return loadSavedRackSet(globalThis.localStorage)
  } catch {
    return null
  }
}

function App() {
  const requestedModule = new URLSearchParams(globalThis.location.search).get('rack_module')
  const isRemoteModule = isRackModuleId(requestedModule)
  const isRegressionFixture = useVerifiedRegressionFixture(!isRemoteModule)
  if (isRemoteModule) {
    return <RackRemoteApp moduleId={requestedModule} />
  }
  if (isRegressionFixture === null) {
    return (
      <main className="fixture-verification" role="status">
        Verifying the isolated regression fixture…
      </main>
    )
  }
  return (
    <RackRuntime>
      <RackWorkspace isRegressionFixture={isRegressionFixture} />
    </RackRuntime>
  )
}

function useVerifiedRegressionFixture(enabled: boolean): boolean | null {
  const requestedFixture = new URLSearchParams(globalThis.location.search).get('fixture')
  const markerRequested = ['M2C REGRESSION', 'M2G REGRESSION'].includes(
    requestedFixture ?? '',
  )
  const [isVerified, setIsVerified] = useState<boolean | null>(
    enabled && markerRequested ? null : false,
  )

  useEffect(() => {
    if (!enabled || !markerRequested) {
      return
    }
    const controller = new AbortController()
    let active = true
    void globalThis.fetch('/__scenario__/identity', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) {
        if (active) {
          setIsVerified(false)
        }
        return
      }
      const identity: unknown = await response.json()
      const verified = (
        typeof identity === 'object' &&
        identity !== null &&
        'fixture' in identity &&
        identity.fixture === requestedFixture
      )
      if (active) {
        setIsVerified(verified)
      }
    }).catch(() => {
      // Only the isolated regression server owns this opt-in identity route.
      if (active) {
        setIsVerified(false)
      }
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [enabled, markerRequested, requestedFixture])

  return isVerified
}

function RackWorkspace({ isRegressionFixture }: { isRegressionFixture: boolean }) {
  const snapshot = useRackHostSnapshot()
  const selection = useRackHostSelection()
  const [layout, setLayout] = useState<RackLayoutSet>(initialRackLayout)
  const [savedSet, setSavedSet] = useState<RackLayoutSet | null>(initialSavedRackSet)
  const [vitalsCollapsed, setVitalsCollapsed] = useState(
    () => globalThis.matchMedia('(max-width: 47.99rem)').matches,
  )
  const selectedThread = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const openGate = selectedThread?.openGate ?? null
  const drawerModule = selection?.kind === 'module' ? selection.id : null
  const ordered = orderedModules(layout)
  const rowAllocation = rackBodyRowAllocation(vitalsCollapsed)
  useEffect(() => {
    const mobile = globalThis.matchMedia('(max-width: 47.99rem)')
    const collapseOnMobile = (event: MediaQueryListEvent) => {
      if (event.matches) {
        setVitalsCollapsed(true)
      }
    }
    mobile.addEventListener('change', collapseOnMobile)
    return () => mobile.removeEventListener('change', collapseOnMobile)
  }, [])

  useEffect(() => {
    try {
      persistRackLayout(globalThis.localStorage, layout)
    } catch {
      // The rack remains usable when a hardened browser denies local storage.
    }
  }, [layout])

  useEffect(() => {
    const syncScope = (event: Event) => {
      const detail = (event as CustomEvent).detail as { module_id?: string; scope?: string }
      if (detail.module_id === undefined || !['GLOBAL', 'CURRENT'].includes(detail.scope ?? '')) return
      setLayout((current) => ({
        ...current,
        scopes: { ...current.scopes, [detail.module_id!]: detail.scope as 'GLOBAL' | 'CURRENT' },
      }))
    }
    globalThis.addEventListener('nocturne:rack-scope', syncScope)
    return () => globalThis.removeEventListener('nocturne:rack-scope', syncScope)
  }, [])

  const saveCurrentSet = useCallback(() => {
    const copy: RackLayoutSet = {
      version: 1,
      modules: layout.modules.map((module) => ({ ...module })),
      scopes: { ...layout.scopes },
    }
    try {
      saveRackSet(globalThis.localStorage, copy)
    } catch {
      // The visible status remains truthful: no saved set is claimed.
      return
    }
    setSavedSet(copy)
  }, [layout])

  const restoreSavedSet = useCallback(() => {
    if (savedSet !== null) {
      setLayout({
        version: 1,
        modules: savedSet.modules.map((module) => ({ ...module })),
        scopes: { ...savedSet.scopes },
      })
    }
  }, [savedSet])

  const resetFactorySet = useCallback(() => {
    setLayout(cloneFactoryLayout())
  }, [])

  const moveModule = useCallback((source: DockedModuleId, target: DockedModuleId) => {
    setLayout((current) => moveRackModule(current, source, target))
  }, [])

  const resizeModule = useCallback((moduleId: DockedModuleId, width: number) => {
    setLayout((current) => resizeRackModule(current, moduleId, width))
  }, [])

  const layoutStatus = savedSet !== null && rackLayoutsEqual(layout, savedSet)
    ? 'Saved set'
    : rackLayoutsEqual(layout, FACTORY_RACK_LAYOUT)
      ? 'Factory set'
      : 'Edited set'

  return (
    <div
      className={`rack-shell rack-shell--vitals-${vitalsCollapsed ? 'collapsed' : 'expanded'}`}
      data-theme="neo-noir"
      data-testid="rack-shell"
    >
      <div className="rack-ambient" aria-hidden="true" />
      <div className="rack-grid" data-testid="rack-grid">
        <RackModuleFrame
          manifest={RACK_MANIFESTS.header}
          x={1}
          y={1}
          width={RACK_COLUMNS}
          height={1}
          isRegressionFixture={isRegressionFixture}
        />
        <div className="rack-set-controls" aria-label="Rack layout set">
          <span data-testid="layout-status">{layoutStatus}</span>
          <button type="button" data-testid="layout-save" onClick={saveCurrentSet}>
            Save
          </button>
          <button
            type="button"
            data-testid="layout-restore"
            disabled={savedSet === null}
            onClick={restoreSavedSet}
          >
            Restore
          </button>
          <button type="button" data-testid="layout-reset" onClick={resetFactorySet}>
            Factory
          </button>
        </div>

        {ordered.map((module, index) => {
          const geometry = moduleGridColumn(layout, module.module_id)
          const isDrawerOpen = drawerModule === module.module_id
          const otherDrawerOpen = drawerModule !== null && !isDrawerOpen
          const isInert = openGate !== null || otherDrawerOpen
          return (
            <RackModuleFrame
              key={module.module_id}
              manifest={RACK_MANIFESTS[module.module_id]}
              x={geometry.x}
              y={2}
              width={geometry.w}
              height={rowAllocation.panelRows}
              drawerOpen={isDrawerOpen}
              inert={isInert}
              resizeFrom={index === ordered.length - 1 ? 'left' : 'right'}
              onMove={moveModule}
              onResize={resizeModule}
              orderedIds={ordered.map((item) => item.module_id)}
              isRegressionFixture={isRegressionFixture}
            />
          )
        })}
        <RackModuleFrame
          manifest={RACK_MANIFESTS.vitals}
          x={1}
          y={rowAllocation.vitalsStart}
          width={RACK_COLUMNS}
          height={rowAllocation.vitalsRows}
          collapsed={vitalsCollapsed}
          inert={openGate !== null || drawerModule !== null}
          onCollapseToggle={() => setVitalsCollapsed((value) => !value)}
          isRegressionFixture={isRegressionFixture}
        />
      </div>

      {drawerModule !== null && (
        <button
          className="drawer-scrim rack-drawer-scrim"
          type="button"
          tabIndex={-1}
          aria-label="Close open rack module"
          onClick={clearRackSelection}
        />
      )}

      {openGate !== null && (
        <div className="rack-overlay-module" data-rack-module="gate">
          <RackPluginIframe
            manifest={RACK_MANIFESTS.gate}
            isRegressionFixture={isRegressionFixture}
          />
        </div>
      )}
      {drawerModule === 'thread_end' && openGate === null && (
        <div className="rack-overlay-module rack-overlay-module--thread-end" data-rack-module="thread_end">
          <RackPluginIframe
            manifest={RACK_MANIFESTS.thread_end}
            isRegressionFixture={isRegressionFixture}
          />
        </div>
      )}
      {drawerModule === 'palace_queue' && openGate === null && (
        <div className="rack-overlay-module rack-overlay-module--palace-queue" data-rack-module="palace_queue">
          <RackPluginIframe
            manifest={RACK_MANIFESTS.palace_queue}
            isRegressionFixture={isRegressionFixture}
          />
        </div>
      )}
      {isRegressionFixture && (
        <RegressionFixtureMarker />
      )}
    </div>
  )
}

interface RackModuleFrameProps {
  manifest: RackModuleManifest
  x: number
  y: number
  width: number
  height: number
  drawerOpen?: boolean
  collapsed?: boolean
  inert?: boolean
  resizeFrom?: 'left' | 'right'
  orderedIds?: DockedModuleId[]
  onMove?: (source: DockedModuleId, target: DockedModuleId) => void
  onResize?: (moduleId: DockedModuleId, width: number) => void
  onCollapseToggle?: () => void
  isRegressionFixture?: boolean
}

function RackModuleFrame({
  manifest,
  x,
  y,
  width,
  height,
  drawerOpen = false,
  collapsed = false,
  inert = false,
  resizeFrom = 'right',
  orderedIds = [],
  onMove,
  onResize,
  onCollapseToggle,
  isRegressionFixture = false,
}: RackModuleFrameProps) {
  const frameRef = useRef<HTMLDivElement>(null)
  const [resizeSequence, setResizeSequence] = useState(0)
  const isDocked = manifest.slot === 'panel'
  const isStrip = manifest.slot === 'strip'
  const moduleId = manifest.id as DockedModuleId

  useEffect(() => {
    const frame = frameRef.current
    if (frame === null || typeof ResizeObserver === 'undefined') {
      return
    }
    const observer = new ResizeObserver(([entry]) => {
      const rect = entry.contentRect
      publishRackResize({
        module_id: manifest.id,
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        grid_width: width,
        grid_height: height,
      })
      setResizeSequence((value) => value + 1)
    })
    observer.observe(frame)
    return () => observer.disconnect()
  }, [height, manifest.id, width])

  function dropModule(event: DragEvent<HTMLDivElement>) {
    if (!isDocked || onMove === undefined) {
      return
    }
    event.preventDefault()
    const source = event.dataTransfer.getData('application/x-nocturne-module')
    if (source === 'threads' || source === 'chat' || source === 'memory') {
      onMove(source, moduleId)
    }
  }

  function dockByKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (!isDocked || onMove === undefined || !event.altKey) {
      return
    }
    const index = orderedIds.indexOf(moduleId)
    const targetIndex = event.key === 'ArrowLeft'
      ? index - 1
      : event.key === 'ArrowRight'
        ? index + 1
        : index
    const target = orderedIds[targetIndex]
    if (target !== undefined && target !== moduleId) {
      event.preventDefault()
      onMove(moduleId, target)
    }
  }

  function beginResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (!isDocked || onResize === undefined) {
      return
    }
    event.preventDefault()
    const grid = frameRef.current?.closest('.rack-grid')
    if (!(grid instanceof HTMLElement)) {
      return
    }
    const startX = event.clientX
    const startWidth = width
    const unit = grid.getBoundingClientRect().width / RACK_COLUMNS
    const move = (moveEvent: globalThis.PointerEvent) => {
      const delta = Math.round((moveEvent.clientX - startX) / unit)
      onResize(moduleId, startWidth + (resizeFrom === 'left' ? -delta : delta))
    }
    const stop = () => {
      globalThis.removeEventListener('pointermove', move)
      globalThis.removeEventListener('pointerup', stop)
      globalThis.removeEventListener('pointercancel', stop)
    }
    globalThis.addEventListener('pointermove', move)
    globalThis.addEventListener('pointerup', stop)
    globalThis.addEventListener('pointercancel', stop)
  }

  const style: CSSProperties = {
    gridColumn: `${x} / span ${width}`,
    gridRow: `${y} / span ${height}`,
  }
  const className = [
    'rack-module',
    `rack-module--${manifest.slot}`,
    drawerOpen ? 'rack-module--drawer-open' : '',
    manifest.law_bound ? 'rack-module--law-bound' : '',
  ].filter(Boolean).join(' ')

  return (
    <div
      ref={frameRef}
      className={className}
      style={style}
      data-rack-module={manifest.id}
      data-testid={`rack-module-${manifest.id}`}
      data-grid-x={x}
      data-grid-y={y}
      data-grid-width={width}
      data-grid-height={height}
      data-resize-sequence={resizeSequence}
      data-collapsed={isStrip ? collapsed : undefined}
      inert={inert || undefined}
      onDragOver={(event) => {
        if (isDocked) {
          event.preventDefault()
        }
      }}
      onDrop={dropModule}
    >
      {isDocked && (
        <div className="rack-module__chrome">
          <div
            className="rack-module__drag"
            role="button"
            tabIndex={0}
            draggable
            aria-label={`Dock ${manifest.name}; Alt plus arrow keys also moves it`}
            onKeyDown={dockByKeyboard}
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = 'move'
              event.dataTransfer.setData('application/x-nocturne-module', moduleId)
            }}
          >
            <span aria-hidden="true">⠿</span>
            <strong>{manifest.name}</strong>
          </div>
          <span className="rack-module__geometry" aria-label={`${width} grid units wide`}>
            {String(width).padStart(2, '0')}u
          </span>
          <button
            className={`rack-module__resize rack-module__resize--${resizeFrom}`}
            type="button"
            aria-label={`Resize ${manifest.name}`}
            onPointerDown={beginResize}
            onKeyDown={(event) => {
              if (onResize === undefined) {
                return
              }
              if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault()
                const delta = event.key === 'ArrowRight' ? 1 : -1
                onResize(moduleId, width + (resizeFrom === 'left' ? -delta : delta))
              }
            }}
          >
            <span aria-hidden="true">⋮</span>
          </button>
        </div>
      )}
      {isStrip && (
        <div className="rack-module__chrome rack-module__chrome--strip">
          <div className="rack-module__strip-title">
            <span aria-hidden="true">⌁</span>
            <strong>{manifest.name}</strong>
          </div>
          <span className="rack-module__geometry" aria-label={`${height} grid rows high`}>
            12×{String(height).padStart(2, '0')}
          </span>
          <button
            className="rack-module__collapse"
            type="button"
            data-testid="vitals-collapse"
            aria-expanded={!collapsed}
            aria-label={`${collapsed ? 'Expand' : 'Collapse'} Palace Vitals`}
            onClick={onCollapseToggle}
          >
            <span aria-hidden="true">{collapsed ? '⌃' : '⌄'}</span>
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        </div>
      )}
      <div className="rack-module__content">
        <RackPluginIframe
          manifest={manifest}
          isRegressionFixture={isRegressionFixture}
        />
      </div>
    </div>
  )
}

function RackRemoteApp({ moduleId }: { moduleId: RackModuleManifest['id'] }) {
  return (
    <RackRemoteProvider
      moduleId={moduleId}
      regressionFixtureMarker={<RegressionFixtureMarker remote />}
    >
      <RackRemoteSurface moduleId={moduleId} />
    </RackRemoteProvider>
  )
}

function RegressionFixtureMarker({ remote = false }: { remote?: boolean }) {
  const requested = new URLSearchParams(globalThis.location.search).get('fixture')
  const known = new Set(['M2C REGRESSION', 'M2G REGRESSION', 'M2I REGRESSION'])
  const label = requested !== null && known.has(requested) ? requested : 'M2C REGRESSION'
  return (
    <div
      className={`m2c-regression-fixture${remote ? ' m2c-regression-fixture--remote' : ''}`}
      aria-hidden="true"
    >
      <strong>{label} FIXTURE</strong>
      <span>DETERMINISTIC EVIDENCE · NOT THE OWNER APP</span>
    </div>
  )
}

function RackRemoteSurface({ moduleId }: { moduleId: RackModuleManifest['id'] }) {
  const selection = useRackSelection()
  const drawerOpen = selection?.kind === 'module' && selection.id === moduleId
  return (
    <div
      className={`rack-remote rack-remote--${moduleId}`}
      data-rack-remote={moduleId}
      data-drawer-open={drawerOpen || undefined}
    >
      {moduleId === 'header' ? (
        <HeaderModule />
      ) : moduleId === 'threads' ? (
        <ThreadsModule />
      ) : moduleId === 'chat' ? (
        <ChatModuleSlot />
      ) : moduleId === 'memory' ? (
        <MemoryModule />
      ) : moduleId === 'vitals' ? (
        <VitalsModule />
      ) : moduleId === 'thread_end' ? (
        <ThreadEndModule />
      ) : moduleId === 'palace_queue' ? (
        <PalaceQueueModule />
      ) : (
        <GateModule />
      )}
    </div>
  )
}

function ChatModuleSlot() {
  const snapshot = useRackSnapshot()
  return <ChatModule key={snapshot.selectedThreadId ?? 'empty'} />
}

function HeaderModule() {
  const snapshot = useRackSnapshot()
  const selection = useRackSelection()
  const { selection: selectionBus } = useRackPlugin()
  const selectedThread = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const memoryTotal = selectedThread?.memoryPanel.total ?? 0
  const threadsOpen = selection?.kind === 'module' && selection.id === 'threads'
  const memoriesOpen = selection?.kind === 'module' && selection.id === 'memory'
  const queueOpen = selection?.kind === 'module' && selection.id === 'palace_queue'

  function toggleModule(moduleId: 'threads' | 'memory' | 'palace_queue') {
    const alreadyOpen = selection?.kind === 'module' && selection.id === moduleId
    selectionBus.select(alreadyOpen ? null : { kind: 'module', id: moduleId })
  }

  return (
    <header className="topbar">
      <div className="brand" aria-label="Nocturne">
        <span className="brand__mark" aria-hidden="true">N</span>
        <span className="brand__word">Nocturne</span>
        <span className="brand__mode">Rack · local direct</span>
      </div>

      <div className="mobile-navigation">
        <button
          className="mobile-threads"
          type="button"
          data-testid="mobile-threads"
          aria-expanded={threadsOpen}
          onClick={() => toggleModule('threads')}
        >
          Threads
          <span>{snapshot.catalog.length.toString().padStart(2, '0')}</span>
        </button>
        <button
          className="mobile-memories"
          type="button"
          data-testid="mobile-memories"
          aria-expanded={memoriesOpen}
          onClick={() => toggleModule('memory')}
        >
          Memory
          <span>{memoryTotal}</span>
        </button>
      </div>

      <button
        className="palace-queue-launch"
        type="button"
        data-testid="palace-queue-launch"
        aria-expanded={queueOpen}
        onClick={() => toggleModule('palace_queue')}
      >
        Palace queue
      </button>

      <p
        className={`connection connection--${snapshot.connection}`}
        data-testid="connection"
        aria-live="polite"
      >
        <span className="connection__signal" aria-hidden="true" />
        {connectionCopy(snapshot.connection)}
      </p>
    </header>
  )
}

function ThreadsModule() {
  const snapshot = useRackSnapshot()
  const { events, selection } = useRackPlugin()
  const sortedCatalog = useMemo(
    () => [...snapshot.catalog].sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
    [snapshot.catalog],
  )

  return (
    <aside className="thread-rail" aria-labelledby="thread-rail-title">
      <div className="thread-rail__header">
        <div>
          <p className="eyebrow">Local channels</p>
          <h2 id="thread-rail-title">Threads</h2>
        </div>
        <button
          className="rail-close"
          type="button"
          data-testid="mobile-close-threads"
          aria-label="Close threads"
          onClick={() => selection.select(null)}
        >
          Back
        </button>
      </div>

      <button
        className="new-thread"
        type="button"
        data-testid="new-thread"
        onClick={() => {
          void events.dispatch({ type: 'thread.create' }).catch(() => undefined)
        }}
      >
        <span aria-hidden="true">＋</span>
        New thread
      </button>

      <nav className="thread-list" data-testid="thread-list" aria-label="Known threads">
        {sortedCatalog.map((entry) => {
          const runtime = snapshot.threads[entry.thread_id]
          const isSelected = entry.thread_id === snapshot.selectedThreadId
          const liveState = runtime?.activeRun?.state
          const queueCount = runtime?.queuedPrompts.length ?? 0
          const outboundCount = runtime?.outboundPrompts.length ?? 0
          const detail = runtime?.awaitingSnapshot
            ? 'Not loaded'
            : liveState === 'cancelling'
              ? 'Stopping'
              : liveState === 'waiting_gate'
                ? 'Review memory'
                : liveState !== undefined
                  ? 'Live'
                  : outboundCount > 0
                    ? 'Sending'
                    : queueCount > 0
                      ? `${queueCount} queued`
                      : runtime?.messages.length
                        ? `${runtime.messages.length} messages`
                        : 'Empty'
          return (
            <button
              key={entry.thread_id}
              className={`thread-item${isSelected ? ' thread-item--selected' : ''}`}
              type="button"
              data-thread-id={entry.thread_id}
              aria-current={isSelected ? 'page' : undefined}
              onClick={() => {
                selection.select({ kind: 'thread', id: entry.thread_id })
                void events
                  .dispatch({ type: 'thread.select', thread_id: entry.thread_id })
                  .catch(() => undefined)
              }}
            >
              <span className="thread-item__title">{entry.title}</span>
              <span className="thread-item__meta">
                <span>{detail}</span>
                <span>{shortId(entry.thread_id)}</span>
              </span>
            </button>
          )
        })}
      </nav>

      <p className="catalog-note">
        Factory-set navigation. The daemon snapshot remains authoritative.
      </p>
    </aside>
  )
}

function ChatModule() {
  const snapshot = useRackSnapshot()
  const { events } = useRackPlugin()
  const selectedThreadId = snapshot.selectedThreadId
  const selectedThread = selectedThreadId === null ? null : snapshot.threads[selectedThreadId]
  const selectedMeta = snapshot.catalog.find((entry) => entry.thread_id === selectedThreadId)
  const [draft, setDraft] = useState('')
  const [hasUnread, setHasUnread] = useState(false)
  const [archiveBusy, setArchiveBusy] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const followOutputRef = useRef(true)
  const messages = useMemo(() => {
    if (selectedThread === null) {
      return EMPTY_MESSAGES
    }
    const represented = new Set(selectedThread.messages.map((message) => message.message_id))
    const optimistic: ChatMessage[] = selectedThread.outboundPrompts
      .filter((outbound) => !represented.has(outbound.prompt_id))
      .map((outbound) => ({
        message_id: outbound.prompt_id,
        run_id: null,
        role: 'user',
        content: outbound.prompt,
        state: 'submitting',
      }))
    return optimistic.length === 0
      ? selectedThread.messages
      : [...selectedThread.messages, ...optimistic]
  }, [selectedThread])
  const activeRun = selectedThread?.activeRun ?? null
  const openGate = selectedThread?.openGate ?? null
  const queuedPrompts = selectedThread?.queuedPrompts ?? []
  const awaitingSnapshot = selectedThread?.awaitingSnapshot ?? true
  const canSend =
    snapshot.connection === 'connected' &&
    !awaitingSnapshot &&
    openGate === null &&
    draft.trim().length > 0
  const runStates = useMemo(() => {
    const states = new Map<string, UserMessageState>()
    for (const message of messages) {
      if (message.role === 'user' && message.run_id !== null) {
        states.set(message.run_id, message.state)
      }
    }
    return states
  }, [messages])

  useEffect(() => {
    followOutputRef.current = true
    globalThis.requestAnimationFrame(() => {
      const transcript = transcriptRef.current
      if (transcript !== null) {
        transcript.scrollTop = transcript.scrollHeight
      }
    })
  }, [selectedThreadId])

  function archiveThread() {
    if (selectedThreadId === null || archiveBusy) {
      return
    }
    setArchiveBusy(true)
    void events.dispatch({ type: 'thread.archive' })
      .catch(() => undefined)
      .finally(() => setArchiveBusy(false))
  }

  useEffect(() => {
    const transcript = transcriptRef.current
    if (transcript === null || messages.length === 0) {
      return
    }
    if (followOutputRef.current) {
      globalThis.requestAnimationFrame(() => {
        transcript.scrollTop = transcript.scrollHeight
      })
    } else {
      setHasUnread(true)
    }
  }, [messages])

  useEffect(() => {
    const composer = composerRef.current
    if (composer === null) {
      return
    }
    composer.style.height = 'auto'
    composer.style.height = `${Math.min(composer.scrollHeight, 144)}px`
  }, [draft])

  function transmitPrompt() {
    if (!canSend) {
      return
    }
    void events
      .dispatch({ type: 'prompt.submit', prompt: draft.trim() })
      .catch(() => undefined)
    setDraft('')
    followOutputRef.current = true
    setHasUnread(false)
  }

  function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    transmitPrompt()
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      transmitPrompt()
    }
  }

  function onTranscriptScroll() {
    const transcript = transcriptRef.current
    if (transcript === null) {
      return
    }
    const nearBottom =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 96
    followOutputRef.current = nearBottom
    if (nearBottom) {
      setHasUnread(false)
    }
  }

  function scrollToLatest() {
    const transcript = transcriptRef.current
    if (transcript === null) {
      return
    }
    followOutputRef.current = true
    setHasUnread(false)
    transcript.scrollTo({ top: transcript.scrollHeight })
  }

  return (
    <main className="chat-panel" aria-labelledby="thread-title">
      <header className="chat-header">
        <div className="chat-header__identity">
          <p className="eyebrow">Active channel</p>
          <h1 id="thread-title">{selectedMeta?.title ?? 'Opening thread'}</h1>
        </div>
        <div className="run-metrics" aria-label="Run status">
          {activeRun !== null && (
            <span className={`run-state run-state--${activeRun.state}`}>
              {activeRun.state === 'cancelling'
                ? 'Stopping'
                : activeRun.state === 'waiting_gate'
                  ? 'Memory review'
                  : 'Run active'}
            </span>
          )}
          {queuedPrompts.length > 0 && <span>{queuedPrompts.length} queued</span>}
          {selectedThread?.usage !== null && selectedThread?.usage !== undefined && (
            <span data-testid="usage">
              {selectedThread.usage.requests} req · {selectedThread.usage.input_tokens} in ·{' '}
              {selectedThread.usage.output_tokens} out
            </span>
          )}
          {selectedThreadId !== null && <span>{shortId(selectedThreadId)}</span>}
        </div>
        <p
          className="chat-header__model"
          data-testid="active-model"
          aria-label={`Active model: ${selectedThread?.resolvedModel ?? 'awaiting daemon'}`}
        >
          <span aria-hidden="true">Model</span>
          <span className="chat-header__model-value">
            {selectedThread?.resolvedModel ?? 'Awaiting daemon'}
          </span>
        </p>
      </header>

      {(snapshot.globalError !== null || selectedThread?.lastError !== null) && (
        <div className="error-line" role="status" data-testid="error-line">
          <span aria-hidden="true">!</span>
          {selectedThread?.lastError?.message ?? snapshot.globalError?.message}
        </div>
      )}

      <div
        className="transcript"
        ref={transcriptRef}
        data-testid="transcript"
        onScroll={onTranscriptScroll}
      >
        <div className="transcript__inner">
          {awaitingSnapshot ? (
            <div className="thread-empty thread-empty--loading" data-testid="thread-loading">
              <p className="eyebrow">Authoritative state</p>
              <h2>Hydrating channel</h2>
              <p>Waiting for the daemon snapshot before accepting input.</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="thread-empty" data-testid="thread-empty">
              <p className="eyebrow">Channel open</p>
              <h2>New thread</h2>
              <p>Send a prompt when you’re ready. Nothing here demands a response.</p>
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <MessageRow
                  key={message.message_id}
                  message={message}
                  queuePosition={
                    message.role === 'user'
                      ? queuedPrompts.findIndex(
                          (queued) => queued.prompt_id === message.message_id,
                        ) + 1
                      : 0
                  }
                  runState={message.run_id === null ? undefined : runStates.get(message.run_id)}
                  activeRunId={activeRun?.run_id}
                  activeState={activeRun?.state}
                />
              ))}
            </>
          )}
        </div>
      </div>

      {hasUnread && (
        <button className="new-response" type="button" data-testid="new-response" onClick={scrollToLatest}>
          New response ↓
        </button>
      )}

      <form className="composer" onSubmit={submitPrompt} aria-label="Prompt composer">
        <div className="composer__body">
          <label className="visually-hidden" htmlFor="prompt-input">
            Message Nocturne
          </label>
          <textarea
            id="prompt-input"
            ref={composerRef}
            data-testid="composer"
            value={draft}
            rows={1}
            placeholder={snapshot.connection === 'connected' ? 'Transmit to Nocturne' : 'Waiting for link'}
            disabled={snapshot.connection !== 'connected' || awaitingSnapshot || openGate !== null}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onComposerKeyDown}
          />
          <p className="composer__hint">
            {openGate !== null
              ? 'Review memory before the model starts'
              : activeRun === null
                ? 'Enter to transmit'
                : 'New prompts queue at the turn boundary'}
            <span>Shift+Enter for newline</span>
          </p>
        </div>
        <div className="composer__actions">
          {activeRun === null && messages.length > 0 && (
            <button
              className="archive-button"
              type="button"
              data-testid="archive-thread"
              disabled={archiveBusy || openGate !== null}
              onClick={archiveThread}
            >
              {archiveBusy ? 'Extracting' : 'Archive'}
            </button>
          )}
          {activeRun !== null && (
            <button
              className="stop-button"
              type="button"
              data-testid="stop"
              disabled={activeRun.state === 'cancelling'}
              onClick={() => {
                void events
                  .dispatch({ type: 'run.cancel', run_id: activeRun.run_id })
                  .catch(() => undefined)
              }}
            >
              {activeRun.state === 'cancelling' ? 'Stopping' : 'Stop'}
            </button>
          )}
          <button
            className="send-button"
            type="button"
            data-testid="send"
            disabled={!canSend}
            onClick={transmitPrompt}
          >
            {activeRun === null ? 'Transmit' : 'Queue'}
            <span aria-hidden="true">↗</span>
          </button>
        </div>
      </form>
    </main>
  )
}

interface ThreadEndQueueCard {
  item_uid: string
  verdict: 'new' | 'merge' | 'supersede' | 'contradict'
  birthplace: 'thread' | 'seed'
  birthplace_thread_id: string | null
  batch_uid: string | null
  source_name: string | null
  candidate: { label: string; body: string; keywords: string[] }
  neighbors: Array<{ memory_id: string; label: string }>
}

function ThreadEndModule() {
  const snapshot = useRackSnapshot()
  const { events, selection } = useRackPlugin()
  const [scope, setScope] = useState<'CURRENT' | 'GLOBAL'>(
    RACK_MANIFESTS.thread_end.default_scope,
  )
  const [cards, setCards] = useState<ThreadEndQueueCard[]>([])
  const selectedThreadId = snapshot.selectedThreadId
  const selectedThread = selectedThreadId === null ? null : snapshot.threads[selectedThreadId]
  const finalPost = finalAssistantPost(selectedThread?.messages ?? [])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'thread_end' }).then(setScope)
  }, [events])

  useEffect(() => {
    const threadId = scope === 'CURRENT' ? selectedThreadId ?? undefined : undefined
    void events.dispatch({ type: 'queue.load', thread_id: threadId, birthplace: 'thread' }).then((value) => {
      setCards(queueCardsFrom(value))
    }).catch(() => setCards([]))
  }, [events, scope, selectedThreadId])

  function changeScope(value: 'CURRENT' | 'GLOBAL') {
    setScope(value)
    void events.dispatch({
      type: 'rack.scope.set', module_id: 'thread_end', scope: value,
    }).catch(() => undefined)
  }

  return (
    <div className="thread-end-module">
      <button
        className="thread-end-module__close"
        type="button"
        onClick={() => selection.select(null)}
      >Close review</button>
      {cards.length === 0 ? (
        <section className="thread-end-card thread-end-card--empty">
          <p className="eyebrow">Thread end · consent surface</p>
          <h2>Nothing pending</h2>
          <p>Duplicate lessons were folded out, or this thread produced no durable candidates.</p>
        </section>
      ) : (
        <ThreadEndCard
          view={{ final_post: finalPost, cards }}
          scope={scope}
          onScopeChange={changeScope}
          onDecide={(itemUid, decision, mode) => events.dispatch({
            type: 'queue.decide', item_uid: itemUid, decision,
            approval_mode: mode,
            actor_class: mode === 'passive' ? 'passive' : 'human',
          })}
          onChanged={(itemUid) => setCards((current) =>
            current.filter((card) => card.item_uid !== itemUid)
          )}
        />
      )}
    </div>
  )
}

interface ThreadEndView {
  final_post: string
  cards: ThreadEndQueueCard[]
}

function ThreadEndCard({
  view,
  scope,
  onScopeChange,
  onDecide,
  onChanged,
}: {
  view: ThreadEndView
  scope: 'CURRENT' | 'GLOBAL'
  onScopeChange: (scope: 'CURRENT' | 'GLOBAL') => void
  onDecide: (
    itemUid: string,
    decision: 'approve' | 'deny',
    mode: 'explicit' | 'passive',
  ) => Promise<JsonValue>
  onChanged: (itemUid: string) => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const seen = useRef(new Set<string>())
  const [busy, setBusy] = useState(new Set<string>())

  function decide(
    itemUid: string,
    decision: 'approve' | 'deny',
    mode: 'explicit' | 'passive',
  ) {
    setBusy((current) => new Set(current).add(itemUid))
    void onDecide(itemUid, decision, mode).then(() => onChanged(itemUid)).finally(() => {
      setBusy((current) => {
        const next = new Set(current)
        next.delete(itemUid)
        return next
      })
    })
  }

  function resolveVisible() {
    if (collapsed) return
    for (const card of view.cards) {
      if (card.verdict !== 'contradict' && seen.current.has(card.item_uid)) {
        decide(card.item_uid, 'approve', 'passive')
      }
    }
  }

  return (
    <section className="thread-end-card" data-testid="thread-end-card" aria-label="Thread memory review">
      <header className="thread-end-card__header">
        <div>
          <p className="eyebrow">Thread end · consent surface</p>
          <h2>What should survive?</h2>
        </div>
        <div className="scope-toggle" aria-label="Queue scope">
          {(['GLOBAL', 'CURRENT'] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={scope === value}
              onClick={() => onScopeChange(value)}
            >{value}</button>
          ))}
        </div>
      </header>
      <div className="thread-end-card__final">
        <span>Final post</span>
        <p>{view.final_post || 'No final assistant post was captured.'}</p>
      </div>
      <button
        className="thread-end-card__collapse"
        type="button"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((value) => !value)}
      >
        {collapsed ? `Show ${view.cards.length} candidates` : 'Collapse candidates'}
      </button>
      {!collapsed && (
        <div className="thread-end-list">
          {view.cards.map((card) => (
            <VisibleQueueRow
              key={card.item_uid}
              card={card}
              disabled={busy.has(card.item_uid)}
              onSeen={() => seen.current.add(card.item_uid)}
              onApprove={() => decide(card.item_uid, 'approve', 'explicit')}
              onDeny={() => decide(card.item_uid, 'deny', 'explicit')}
            />
          ))}
        </div>
      )}
      <footer>
        <button type="button" onClick={resolveVisible} disabled={collapsed}>
          Resolve visible · keep unseen pending
        </button>
        <span>Contradictions always need a tap.</span>
      </footer>
    </section>
  )
}

function VisibleQueueRow({
  card,
  disabled,
  onSeen,
  onApprove,
  onDeny,
}: {
  card: ThreadEndQueueCard
  disabled: boolean
  onSeen: () => void
  onApprove: () => void
  onDeny: () => void
}) {
  const rowRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const row = rowRef.current
    if (row === null || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && entry.intersectionRatio === 1) onSeen()
    }, { threshold: 1 })
    observer.observe(row)
    return () => observer.disconnect()
  }, [onSeen])
  return (
    <article ref={rowRef} className="thread-end-row" data-verdict={card.verdict}>
      <div className="thread-end-row__meta">
        <span>{card.verdict}</span>
        <span>{card.candidate.keywords.join(' · ')}</span>
      </div>
      <h3>{card.candidate.label}</h3>
      <p>{card.candidate.body}</p>
      {card.neighbors.length > 0 && (
        <small>Neighbors: {card.neighbors.map((item) => item.label).join(', ')}</small>
      )}
      <div className="thread-end-row__actions">
        <button type="button" disabled={disabled} onClick={onDeny}>Deny</button>
        <button type="button" disabled={disabled} onClick={onApprove}>Approve</button>
      </div>
    </article>
  )
}

function finalAssistantPost(messages: ChatMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role === 'assistant') return message.content
  }
  return ''
}

function queueCardsFrom(value: JsonValue): ThreadEndQueueCard[] {
  if (!isObject(value) || !Array.isArray(value.cards)) return []
  const cards: ThreadEndQueueCard[] = []
  for (const item of value.cards) {
    if (isQueueCard(item)) cards.push(item)
  }
  return cards
}

function isQueueCard(value: unknown): value is ThreadEndQueueCard {
  return isObject(value) && typeof value.item_uid === 'string' &&
    ['new', 'merge', 'supersede', 'contradict'].includes(String(value.verdict)) &&
    (typeof value.birthplace_thread_id === 'string' || value.birthplace_thread_id === null) &&
    (value.birthplace === 'thread' || value.birthplace === 'seed') &&
    (typeof value.batch_uid === 'string' || value.batch_uid === null) &&
    (typeof value.source_name === 'string' || value.source_name === null) &&
    isObject(value.candidate) &&
    typeof value.candidate.label === 'string' && typeof value.candidate.body === 'string' &&
    Array.isArray(value.candidate.keywords) && value.candidate.keywords.every((item) => typeof item === 'string') &&
    Array.isArray(value.neighbors)
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function PalaceQueueModule() {
  const { events, selection } = useRackPlugin()
  const [scope, setScope] = useState<'CURRENT' | 'GLOBAL'>(
    RACK_MANIFESTS.palace_queue.default_scope,
  )
  const [cards, setCards] = useState<ThreadEndQueueCard[]>([])
  const [statusText, setStatusText] = useState('Choose Markdown files to grow the queue.')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    return events.dispatch({ type: 'queue.load', birthplace: 'seed' }).then((value) => {
      setCards(queueCardsFrom(value).filter((card) => card.birthplace === 'seed'))
    })
  }, [events])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'palace_queue' }).then(setScope)
    void load().catch(() => setStatusText('The Palace queue could not be loaded.'))
  }, [events, load])

  const batches = useMemo(() => {
    const grouped = new Map<string, ThreadEndQueueCard[]>()
    for (const card of cards) {
      if (card.batch_uid === null) continue
      grouped.set(card.batch_uid, [...(grouped.get(card.batch_uid) ?? []), card])
    }
    return [...grouped.entries()]
  }, [cards])

  function changeScope(value: 'CURRENT' | 'GLOBAL') {
    setScope(value)
    void events.dispatch({
      type: 'rack.scope.set', module_id: 'palace_queue', scope: value,
    }).catch(() => undefined)
  }

  async function upload(files: FileList | null) {
    if (files === null || files.length === 0 || busy) return
    setBusy(true)
    try {
      for (const file of Array.from(files)) {
        const lower = file.name.toLowerCase()
        if ((!lower.endsWith('.md') && !lower.endsWith('.markdown')) || file.size > 24 * 1024) {
          throw new Error(`${file.name} must be Markdown and no larger than 24 KiB.`)
        }
        setStatusText(`Splitting ${file.name} without losing its claims…`)
        await events.dispatch({
          type: 'seed.upload',
          batch_uid: globalThis.crypto.randomUUID(),
          source_name: file.name,
          markdown: await file.text(),
        })
      }
      await load()
      setStatusText('Split complete. Review each document as one batch.')
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : 'Seed ingestion failed.')
    } finally {
      setBusy(false)
    }
  }

  function decideBatch(batchUid: string, decision: 'approve' | 'deny') {
    if (busy) return
    setBusy(true)
    setStatusText(decision === 'approve' ? 'Planting the document…' : 'Rejecting the document…')
    void events.dispatch({ type: 'queue.batch.decide', batch_uid: batchUid, decision })
      .then(() => load())
      .then(() => setStatusText(decision === 'approve' ? 'Document planted.' : 'Document rejected.'))
      .catch(() => setStatusText('The batch changed before it could be decided.'))
      .finally(() => setBusy(false))
  }

  return (
    <div className="palace-queue-module">
      <button
        className="thread-end-module__close"
        type="button"
        onClick={() => selection.select(null)}
      >Close queue</button>
      <section className="palace-queue-card" aria-label="Palace seed queue">
        <header className="palace-queue-card__header">
          <div>
            <p className="eyebrow">Corpus door · explicit consent</p>
            <h2>Grow the Palace from Markdown</h2>
            <p>Each document is split into standalone memories. Nothing enters until you approve its batch.</p>
          </div>
          <div className="scope-toggle" aria-label="Palace queue scope">
            {(['GLOBAL', 'CURRENT'] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={scope === value}
                onClick={() => changeScope(value)}
              >{value}</button>
            ))}
          </div>
        </header>
        <label className="seed-drop">
          <span>{busy ? 'Working…' : 'Choose Markdown files'}</span>
          <input
            data-testid="seed-upload"
            type="file"
            accept=".md,.markdown,text/markdown"
            multiple
            disabled={busy}
            onChange={(event) => void upload(event.currentTarget.files)}
          />
        </label>
        <p className="seed-status" aria-live="polite">{statusText}</p>
        {batches.length === 0 ? (
          <div className="palace-queue-empty">
            <h3>The queue is clear</h3>
            <p>Pending seed documents will wait here without expiring or interrupting you.</p>
          </div>
        ) : (
          <div className="seed-batch-list">
            {batches.map(([batchUid, batchCards]) => (
              <article className="seed-batch" key={batchUid} data-batch-uid={batchUid}>
                <header>
                  <div>
                    <span>Markdown seed · {batchCards.length} memories</span>
                    <h3>{batchCards[0]?.source_name ?? 'Untitled document'}</h3>
                  </div>
                  <div className="seed-batch__actions">
                    <button type="button" disabled={busy} onClick={() => decideBatch(batchUid, 'deny')}>Reject batch</button>
                    <button type="button" disabled={busy} onClick={() => decideBatch(batchUid, 'approve')}>Approve batch</button>
                  </div>
                </header>
                <div className="seed-batch__memories">
                  {batchCards.map((card) => (
                    <div key={card.item_uid} className="seed-memory" data-verdict={card.verdict}>
                      <span>{card.verdict} · {card.candidate.keywords.join(' · ')}</span>
                      <strong>{card.candidate.label}</strong>
                      <p>{card.candidate.body}</p>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function MemoryModule() {
  const snapshot = useRackSnapshot()
  const selection = useRackSelection()
  const { events, selection: selectionBus } = useRackPlugin()
  const selectedThread = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const panel = selectedThread?.memoryPanel ?? EMPTY_MEMORY_PANEL
  const mobileOpen = selection?.kind === 'module' && selection.id === 'memory'

  return (
    <MemoryPanel
      panel={panel}
      connected={snapshot.connection === 'connected' && !(selectedThread?.awaitingSnapshot ?? true)}
      removeEnabled={selectedThread?.activeRun === null}
      mobileOpen={mobileOpen}
      inert={false}
      onClose={() => selectionBus.select(null)}
      onRefresh={() => events.dispatch({ type: 'memory.refresh' })}
      onAdd={(memoryId) => events.dispatch({ type: 'memory.add', memory_id: memoryId })}
      onRemove={(memoryId) => events.dispatch({ type: 'memory.remove', memory_id: memoryId })}
      onEdit={(memoryId, expectedRevision, body) =>
        events.dispatch({
          type: 'memory.edit',
          memory_id: memoryId,
          expected_revision: expectedRevision,
          body,
        })
      }
      onPin={(memoryId, expectedRevision, pin) =>
        events.dispatch({
          type: 'memory.pin',
          memory_id: memoryId,
          expected_revision: expectedRevision,
          pin,
        })
      }
    />
  )
}

function GateModule() {
  const snapshot = useRackSnapshot()
  const { events } = useRackPlugin()
  const selectedThread = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const openGate = selectedThread?.openGate ?? null
  const activeRun = selectedThread?.activeRun ?? null
  if (openGate === null) {
    return null
  }
  return (
    <MemoryGate
      key={`${openGate.run_id}:${openGate.injection_id}:${openGate.stage}:${
        openGate.wrong_removed[0]?.memory_id ?? 'review'
      }:${openGate.wrong_removed[0]?.revision ?? 0}`}
      gate={openGate}
      connected={snapshot.connection === 'connected'}
      cancelling={activeRun?.state === 'cancelling'}
      serverError={selectedThread?.lastError?.detail ?? null}
      onCommit={(decision) => {
        void events.dispatch({ type: 'gate.commit', decision }).catch(() => undefined)
      }}
      onStop={() => {
        void events
          .dispatch({ type: 'run.cancel', run_id: activeRun?.run_id })
          .catch(() => undefined)
      }}
    />
  )
}

interface MessageRowProps {
  message: ChatMessage
  queuePosition: number
  runState: UserMessageState | undefined
  activeRunId: string | undefined
  activeState: string | undefined
}

function MessageRow({
  message,
  queuePosition,
  runState,
  activeRunId,
  activeState,
}: MessageRowProps) {
  if (message.role === 'user') {
    const status = message.state === 'submitting'
      ? 'Sending'
      : message.state === 'queued'
        ? `Queued ${Math.max(queuePosition, 1)}`
        : null
    return (
      <article className={`message message--user message--${message.state}`} data-role="user">
        <header className="message__label">
          <span>You</span>
          {status !== null && <span>{status}</span>}
        </header>
        <p className="message__content">{message.content}</p>
      </article>
    )
  }

  const status = messageStatus(message, runState, activeRunId, activeState)
  const tone = runState === 'error'
    ? 'danger'
    : runState === 'budget_exceeded'
      ? 'budget'
      : 'normal'
  return (
    <article className={`message message--assistant message--${tone}`} data-role="assistant">
      <header className="message__label">
        <span>Nocturne</span>
        {status !== null && <span className="message__status">{status}</span>}
      </header>
      {message.content ? (
        <AssistantMarkdown content={message.content} />
      ) : (
        <p className="message__content message__content--quiet">Working…</p>
      )}
      {message.thinking && (
        <details className="run-detail">
          <summary>Process signal</summary>
          <p>{message.thinking}</p>
        </details>
      )}
      {message.events.length > 0 && (
        <details className="run-detail">
          <summary>{message.events.length} run event{message.events.length === 1 ? '' : 's'}</summary>
          <pre>{JSON.stringify(message.events, null, 2)}</pre>
        </details>
      )}
    </article>
  )
}

export default App
