import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import { AssistantMarkdown } from './AssistantMarkdown'
import { SymphonyDeliberationCard, SymphonyResultCard } from './SymphonyCards'
import { MemoryGate } from './MemoryGate'
import { MemoryPanel } from './MemoryPanel'
import { MemoryGraph } from './MemoryGraph'
import { InjectionConsole } from './InjectionConsole'
import { RecipeModule } from './RecipeModule'
import { ModelDevice } from './ModelDevice'
import { VitalsModule } from './VitalsModule'
import { ContextBars } from './ContextBars'
import {
  IMAGE_ACCEPT,
  ImageInputError,
  formatImageBytes,
  prepareImage,
  type PendingImage,
} from './imageInput'
import type {
  AssistantTranscriptMessage,
  ChatMessage,
  ImageAttachmentView,
  ImageMediaType,
  JsonValue,
  UserMessageState,
} from './protocol'
import {
  RackRuntime,
  RACK_MANIFESTS,
  clearRackSelection,
  createHostPluginApi,
  isRackModuleId,
  useRackHostSnapshot,
  useRackHostSelection,
  useRackPlugin,
  useRackSelection,
  useRackSnapshot,
  type RackMemoryPanelState,
  type RackModuleId,
  type RackModuleManifest,
} from './rack'
import {
  RackPluginIframe,
  RackRemoteProvider,
} from './rackBridge'
import { publishRackResize } from './rackEvents'
import {
  FACTORY_STAGE_LAYOUT,
  STAGE_COLUMNS,
  STAGE_FINE_GRID_SIZE,
  STAGE_MAX_ZOOM,
  STAGE_MIN_ZOOM,
  STAGE_MODULE_IDS,
  STAGE_ROWS,
  STAGE_UNIT_HEIGHT,
  STAGE_UNIT_WIDTH,
  activeStageLayer,
  cloneFactoryStageLayout,
  cloneStageLayout,
  createStageLayer,
  fitStageCamera,
  focusStageModule,
  loadSavedStageSet,
  loadStageLayout,
  moduleIsOffscreen,
  moveStageModule,
  persistStageLayout,
  removeStageLayer,
  removeStageModule,
  resizeStageModule,
  restoreStageLayer,
  restoreStageModule,
  saveStageSet,
  selectStageLayer,
  stageLayoutsEqual,
  updateStageCamera,
  type StageCamera,
  type StageLayoutSet,
  type StageModuleId,
  type StageModuleLayout,
} from './stageLayout'
import {
  rackResizeDirections,
  type RackResizeDirection,
} from './rackModuleTemplate'
import { isLegacyFixtureTitle, visibleThreadTitle } from './threadTitles'
import { ProjectSelector } from './ProjectSelector'
import {
  THEMES,
  applyTheme,
  loadTheme,
  type ThemeId,
} from './themes'
import {
  loadColorways,
  pressImage,
  saveColorways,
  type PressedColorway,
  type SeamColorEntry,
} from './platePress.ts'
import seamColorsRaw from './themes/seam-colors.json?raw'
import {
  rackDrawerModule,
  rackModuleSelectionIsOpen,
} from './graphOverlaySelection'
import { ownerConnectionCopy, type PalaceStatus } from './surfaceHonesty'
import { ControlTooltip } from './ControlTooltip'
import { spatialAddresses, type SpatialSelectionContext } from './spatialSelection'

const EMPTY_MESSAGES: ChatMessage[] = []
const SEAM_COLORS = (JSON.parse(seamColorsRaw) as { colors: SeamColorEntry[] }).colors
const EMPTY_MEMORY_PANEL: RackMemoryPanelState = {
  items: [],
  total: 0,
  status: 'idle',
  pending: null,
  lastResponse: null,
  completedEditRequestId: null,
}

const DISMISSIBLE_OVERLAY_CLASSES = {
  thread_end: 'rack-overlay-module--thread-end',
  model_device: 'rack-overlay-module--model-device',
} as const

type DismissibleOverlayModuleId = keyof typeof DISMISSIBLE_OVERLAY_CLASSES

interface TranscriptBackupState {
  enabled: boolean
  state: string
  record_count: number | null
  latest_received_at: string | null
  error: string | null
}

function shortId(value: string): string {
  return value.slice(0, 8).toUpperCase()
}

function resizeDirectionName(direction: RackResizeDirection): string {
  return ({
    n: 'top edge',
    e: 'right edge',
    s: 'bottom edge',
    w: 'left edge',
    ne: 'top-right corner',
    se: 'bottom-right corner',
    sw: 'bottom-left corner',
    nw: 'top-left corner',
  } as const)[direction]
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
  if (state === 'error') {
    const providerRefusal = message.events.find((event) => event.event_kind === 'provider_refusal')
    if (providerRefusal?.classification === 'context_length') {
      return 'Context limit reached'
    }
    if (providerRefusal?.classification === 'provider_refusal') {
      return 'Provider refused'
    }
  }
  return state === undefined ? (message.partial ? 'Partial' : null) : terminalCopy(state)
}

function initialRackLayout(): StageLayoutSet {
  try {
    return loadStageLayout(globalThis.localStorage)
  } catch {
    return cloneFactoryStageLayout()
  }
}

function initialSavedRackSet(): StageLayoutSet | null {
  try {
    return loadSavedStageSet(globalThis.localStorage)
  } catch {
    return null
  }
}

function initialTheme(): ThemeId {
  try {
    return loadTheme(globalThis.localStorage)
  } catch {
    return 'neo-noir'
  }
}

function initialColorways(): PressedColorway[] {
  try {
    return loadColorways(globalThis.localStorage)
  } catch {
    return []
  }
}

function App() {
  const requestedModule = new URLSearchParams(globalThis.location.search).get('rack_module')
  const isRemoteModule = isRackModuleId(requestedModule)
  const isRegressionFixture = useVerifiedRegressionFixture(!isRemoteModule)
  if (isRemoteModule) {
    return (
      <>
        <RackRemoteApp moduleId={requestedModule} />
        <ControlTooltip />
      </>
    )
  }
  if (isRegressionFixture === null) {
    return (
      <main className="fixture-verification" role="status">
        Verifying the isolated regression fixture…
      </main>
    )
  }
  return (
    <>
      <RackRuntime>
        <RackWorkspace isRegressionFixture={isRegressionFixture} />
      </RackRuntime>
      <ControlTooltip />
    </>
  )
}

function useVerifiedRegressionFixture(enabled: boolean): boolean | null {
  const requestedFixture = new URLSearchParams(globalThis.location.search).get('fixture')
  const markerRequested = requestedFixture !== null && /^[A-Z][A-Z0-9]* REGRESSION$/.test(requestedFixture)
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
        identity.fixture === requestedFixture &&
        'deterministic' in identity &&
        identity.deterministic === true
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
  const [layout, setLayout] = useState<StageLayoutSet>(initialRackLayout)
  const [savedSet, setSavedSet] = useState<StageLayoutSet | null>(initialSavedRackSet)
  const [theme, setTheme] = useState<ThemeId>(initialTheme)
  const [colorways, setColorways] = useState<PressedColorway[]>(initialColorways)
  const [platePressStatus, setPlatePressStatus] = useState<string | null>(null)
  const [platePressBusy, setPlatePressBusy] = useState(false)
  const plateInputRef = useRef<HTMLInputElement>(null)
  const [appSettingsOpen, setAppSettingsOpen] = useState(false)
  const [transcriptBackup, setTranscriptBackup] = useState<TranscriptBackupState | null>(null)
  const [transcriptBackupBusy, setTranscriptBackupBusy] = useState(false)
  const [pointerActive, setPointerActive] = useState(false)
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 })
  const viewportRef = useRef<HTMLDivElement>(null)
  const layer = activeStageLayer(layout)
  const frameAddresses = useMemo(
    () => spatialAddresses(layer.layer_id, layer.modules),
    [layer.layer_id, layer.modules],
  )
  const selectedThread = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const openGate = selectedThread?.openGate ?? null
  const drawerModule = rackDrawerModule(selection)
  const dismissibleOverlay = drawerModule !== null && drawerModule in DISMISSIBLE_OVERLAY_CLASSES
    ? drawerModule as DismissibleOverlayModuleId
    : null
  const offscreenModules = layer.modules.filter((module) => moduleIsOffscreen(
    module,
    layer.camera,
    viewportSize.width,
    viewportSize.height,
  ))
  const selectedColorway = colorways.find((colorway) => colorway.id === theme) ?? null
  const stageCanvasStyle = {
    width: STAGE_COLUMNS * STAGE_UNIT_WIDTH,
    height: STAGE_ROWS * STAGE_UNIT_HEIGHT,
    transform: `translate(${layer.camera.x}px, ${layer.camera.y}px) scale(${layer.camera.zoom})`,
    '--stage-fine-grid-size': `${STAGE_FINE_GRID_SIZE}px`,
    '--stage-major-grid-width': `${STAGE_UNIT_WIDTH}px`,
    '--stage-major-grid-height': `${STAGE_UNIT_HEIGHT}px`,
  } as CSSProperties

  useEffect(() => {
    if (!appSettingsOpen || transcriptBackup !== null) return
    void globalThis.fetch('/v1/transcripts/settings', { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Transcript backup status is unavailable.')
        setTranscriptBackup(await response.json() as TranscriptBackupState)
      })
      .catch(() => setTranscriptBackup({
        enabled: false,
        state: 'unavailable',
        record_count: null,
        latest_received_at: null,
        error: 'Transcript backup status is unavailable.',
      }))
  }, [appSettingsOpen, transcriptBackup])

  async function changeTranscriptBackup(enabled: boolean) {
    setTranscriptBackupBusy(true)
    try {
      const response = await globalThis.fetch('/v1/transcripts/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      if (!response.ok) throw new Error('The setting could not be saved.')
      setTranscriptBackup(await response.json() as TranscriptBackupState)
    } catch {
      setTranscriptBackup((current) => current === null ? null : {
        ...current,
        error: 'The setting could not be saved. Run nocturne doctor for details.',
      })
    } finally {
      setTranscriptBackupBusy(false)
    }
  }

  useEffect(() => {
    const viewport = viewportRef.current
    if (viewport === null || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      setViewportSize({
        width: Math.round(entry.contentRect.width),
        height: Math.round(entry.contentRect.height),
      })
    })
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const viewport = viewportRef.current
    if (viewport === null) return
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault()
      setLayout((current) => {
        const currentLayer = activeStageLayer(current)
        if (event.ctrlKey || event.metaKey) {
          const rect = viewport.getBoundingClientRect()
          const focusX = event.clientX - rect.left
          const focusY = event.clientY - rect.top
          const zoom = Math.max(
            STAGE_MIN_ZOOM,
            Math.min(STAGE_MAX_ZOOM, currentLayer.camera.zoom * Math.exp(-event.deltaY * 0.004)),
          )
          const ratio = zoom / currentLayer.camera.zoom
          return updateStageCamera(current, {
            x: focusX - (focusX - currentLayer.camera.x) * ratio,
            y: focusY - (focusY - currentLayer.camera.y) * ratio,
            zoom,
          })
        }
        return updateStageCamera(current, {
          ...currentLayer.camera,
          x: currentLayer.camera.x - (event.shiftKey ? event.deltaY : event.deltaX),
          y: currentLayer.camera.y - (event.shiftKey ? 0 : event.deltaY),
        })
      })
    }
    viewport.addEventListener('wheel', handleWheel, { passive: false })
    return () => viewport.removeEventListener('wheel', handleWheel)
  }, [])

  useEffect(() => {
    if (
      selection?.kind !== 'module' ||
      !STAGE_MODULE_IDS.includes(selection.id as StageModuleId)
    ) return
    const timeout = globalThis.setTimeout(() => {
      setLayout((current) => {
        const targetLayer = current.layers.find((candidate) => (
          candidate.modules.some((module) => module.module_id === selection.id)
        ))
        if (targetLayer === undefined) return current
        const selected = selectStageLayer(current, targetLayer.layer_id)
        const module = activeStageLayer(selected).modules.find(
          (candidate) => candidate.module_id === selection.id,
        )
        return module === undefined
          ? selected
          : updateStageCamera(selected, focusStageModule(
              module,
              viewportSize.width,
              viewportSize.height,
              Math.max(activeStageLayer(selected).camera.zoom, 0.72),
            ))
      })
    }, 0)
    return () => globalThis.clearTimeout(timeout)
  }, [selection, viewportSize.height, viewportSize.width])

  useEffect(() => {
    try {
      persistStageLayout(globalThis.localStorage, layout)
    } catch {
      // The rack remains usable when a hardened browser denies local storage.
    }
  }, [layout])

  useEffect(() => {
    try {
      applyTheme(theme, globalThis.localStorage, selectedColorway)
    } catch {
      applyTheme(theme, undefined, selectedColorway)
    }
  }, [selectedColorway, theme])

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
    const copy = cloneStageLayout(layout)
    try {
      saveStageSet(globalThis.localStorage, copy)
    } catch {
      // The visible status remains truthful: no saved set is claimed.
      return
    }
    setSavedSet(copy)
  }, [layout])

  const restoreSavedSet = useCallback(() => {
    if (savedSet !== null) {
      setLayout(cloneStageLayout(savedSet))
    }
  }, [savedSet])

  const resetFactorySet = useCallback(() => {
    setLayout(cloneFactoryStageLayout())
  }, [])

  const changeModuleScope = useCallback((
    moduleId: RackModuleId,
    scope: 'GLOBAL' | 'CURRENT',
  ) => {
    const manifest = RACK_MANIFESTS[moduleId]
    if (!(manifest.actions as readonly string[]).includes('rack.scope.set')) return
    void createHostPluginApi(manifest).events.dispatch({
      type: 'rack.scope.set',
      module_id: moduleId,
      scope,
    }).catch(() => undefined)
  }, [])

  const moveModule = useCallback((moduleId: StageModuleId, x: number, y: number) => {
    setLayout((current) => moveStageModule(current, moduleId, x, y))
  }, [])

  const resizeModule = useCallback((
    moduleId: StageModuleId,
    width: number,
    height: number,
    direction: RackResizeDirection,
  ) => {
    setLayout((current) => resizeStageModule(current, moduleId, width, height, direction))
  }, [])

  const layoutStatus = savedSet !== null && stageLayoutsEqual(layout, savedSet)
    ? 'Saved set'
    : stageLayoutsEqual(layout, FACTORY_STAGE_LAYOUT)
      ? 'Default layout'
      : 'Edited set'

  function changeCamera(camera: StageCamera) {
    setLayout((current) => updateStageCamera(current, camera))
  }

  function zoomAt(nextZoom: number, clientX?: number, clientY?: number) {
    const viewport = viewportRef.current
    if (viewport === null) return
    const rect = viewport.getBoundingClientRect()
    const focusX = clientX === undefined ? rect.width / 2 : clientX - rect.left
    const focusY = clientY === undefined ? rect.height / 2 : clientY - rect.top
    const zoom = Math.max(STAGE_MIN_ZOOM, Math.min(STAGE_MAX_ZOOM, nextZoom))
    const ratio = zoom / layer.camera.zoom
    changeCamera({
      x: focusX - (focusX - layer.camera.x) * ratio,
      y: focusY - (focusY - layer.camera.y) * ratio,
      zoom,
    })
  }

  function beginPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (
      event.button !== 0 ||
      (event.target as HTMLElement).closest('[data-rack-module], button, select, input') !== null
    ) return
    event.preventDefault()
    const handle = event.currentTarget
    const pointerId = event.pointerId
    handle.setPointerCapture(pointerId)
    setPointerActive(true)
    const startX = event.clientX
    const startY = event.clientY
    const startCamera = layer.camera
    const move = (moveEvent: globalThis.PointerEvent) => {
      changeCamera({
        ...startCamera,
        x: startCamera.x + moveEvent.clientX - startX,
        y: startCamera.y + moveEvent.clientY - startY,
      })
    }
    const stop = () => {
      globalThis.removeEventListener('pointermove', move)
      globalThis.removeEventListener('pointerup', stop)
      globalThis.removeEventListener('pointercancel', stop)
      if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId)
      setPointerActive(false)
    }
    globalThis.addEventListener('pointermove', move)
    globalThis.addEventListener('pointerup', stop)
    globalThis.addEventListener('pointercancel', stop)
  }

  function focusModule(module: StageModuleLayout) {
    changeCamera(focusStageModule(
      module,
      viewportSize.width,
      viewportSize.height,
      Math.max(layer.camera.zoom, 0.72),
    ))
  }

  async function pressPlate(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''
    if (file === undefined) return
    setPlatePressBusy(true)
    setPlatePressStatus('Pressing colorway…')
    const result = await pressImage(file, SEAM_COLORS)
    setPlatePressBusy(false)
    if (!result.ok) {
      setPlatePressStatus(result.message)
      return
    }
    const next = [
      ...colorways.filter((colorway) => colorway.id !== result.colorway.id),
      result.colorway,
    ].sort((left, right) => left.id.localeCompare(right.id))
    try {
      saveColorways(globalThis.localStorage, next)
    } catch {
      setPlatePressStatus('This colorway is valid, but the browser could not save it locally.')
      return
    }
    setColorways(next)
    setTheme(result.colorway.id)
    setPlatePressStatus(`${result.colorway.label} is ready.`)
  }

  function removeSelectedColorway() {
    if (selectedColorway === null) return
    const next = colorways.filter((colorway) => colorway.id !== selectedColorway.id)
    try {
      saveColorways(globalThis.localStorage, next)
    } catch {
      setPlatePressStatus('The browser could not remove this colorway from local storage.')
      return
    }
    setColorways(next)
    setTheme('neo-noir')
    setPlatePressStatus(`${selectedColorway.label} removed.`)
  }

  return (
    <div
      className="rack-shell rack-shell--stage"
      data-theme={theme}
      data-testid="rack-shell"
    >
      <div className="rack-ambient" aria-hidden="true" />
      <div className="rack-stage-header" data-rack-module="header">
        <RackPluginIframe
          manifest={RACK_MANIFESTS.header}
          theme={theme}
          isRegressionFixture={isRegressionFixture}
        />
        <button
          className="app-settings-toggle"
          type="button"
          data-testid="app-settings-toggle"
          aria-label="App settings"
          aria-expanded={appSettingsOpen}
          onClick={() => setAppSettingsOpen((open) => !open)}
        >
          <span aria-hidden="true">⚙</span>
        </button>
      </div>
      {appSettingsOpen && (
        <aside className="app-settings-panel" data-testid="app-settings-panel" aria-label="App settings">
          <header>
            <strong>Settings</strong>
            <button type="button" aria-label="Close app settings" onClick={() => setAppSettingsOpen(false)}>×</button>
          </header>
          <section>
            <h2>Appearance</h2>
            <label className="theme-control">
              <span>Theme</span>
              <select
                value={theme}
                data-testid="theme-control"
                onChange={(event) => setTheme(event.currentTarget.value as ThemeId)}
              >
                {THEMES.map((choice) => (
                  <option key={choice.id} value={choice.id}>{choice.label}</option>
                ))}
                {colorways.map((choice) => (
                  <option key={choice.id} value={choice.id}>{choice.label}</option>
                ))}
              </select>
            </label>
            <input
              ref={plateInputRef}
              className="visually-hidden"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              data-testid="plate-press-input"
              onChange={(event) => void pressPlate(event)}
            />
            <div className="app-settings-actions">
              <button
                className="plate-press-button"
                type="button"
                disabled={platePressBusy}
                data-testid="plate-press-button"
                onClick={() => plateInputRef.current?.click()}
              >
                {platePressBusy ? 'Pressing…' : 'Press image'}
              </button>
              {selectedColorway !== null ? (
                <button
                  className="plate-remove-button"
                  type="button"
                  data-testid="plate-remove-button"
                  onClick={removeSelectedColorway}
                >
                  Remove colorway
                </button>
              ) : null}
            </div>
          </section>
          <section>
            <h2>Conversation backup</h2>
            <label className="transcript-backup-control">
              <input
                type="checkbox"
                data-testid="transcript-backup-toggle"
                checked={transcriptBackup?.enabled ?? false}
                disabled={transcriptBackup === null || transcriptBackupBusy}
                onChange={(event) => void changeTranscriptBackup(event.currentTarget.checked)}
              />
              <span>Back up transcripts to your Palace</span>
            </label>
            <p data-testid="transcript-backup-status">
              {transcriptBackup === null
                ? 'Checking Palace backup…'
                : transcriptBackup.error ?? (
                  transcriptBackup.enabled
                    ? `${transcriptBackup.state} · ${transcriptBackup.record_count ?? 0} records`
                    : 'Off · transcripts stay on this machine'
                )}
            </p>
          </section>
          <section>
            <h2>Stage layout</h2>
            <p data-testid="layout-status">{layoutStatus}</p>
            <div className="app-settings-actions">
              <button type="button" data-testid="layout-save" onClick={saveCurrentSet}>Save</button>
              <button
                type="button"
                data-testid="layout-restore"
                disabled={savedSet === null}
                onClick={restoreSavedSet}
              >
                Restore
              </button>
              <button type="button" data-testid="layout-reset" onClick={resetFactorySet}>Reset</button>
            </div>
          </section>
        </aside>
      )}
      <div
        className="stage-toolbar"
        aria-label="Stage controls"
        inert={openGate !== null || dismissibleOverlay !== null || undefined}
      >
        <div className="stage-layers" role="tablist" aria-label="Stage layers">
          {layout.layers.map((candidate) => (
            <div className="stage-layer-tab" key={candidate.layer_id}>
              <button
                type="button"
                role="tab"
                aria-selected={candidate.layer_id === layout.active_layer_id}
                onClick={() => setLayout((current) => selectStageLayer(current, candidate.layer_id))}
              >
                {candidate.name}
              </button>
              <button
                type="button"
                aria-label={`Remove ${candidate.name} layer`}
                onClick={() => setLayout((current) => removeStageLayer(current, candidate.layer_id))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          className="stage-layer-create"
          type="button"
          data-testid="stage-layer-create"
          data-tooltip="Create a layer"
          data-tooltip-detail="Open a new empty layer on this Stage."
          onClick={() => setLayout(createStageLayer)}
        >
          <span aria-hidden="true">＋</span>
          Layer
        </button>
        <div className="stage-camera-controls" aria-label="Stage camera">
          <button type="button" aria-label="Zoom out" onClick={() => zoomAt(layer.camera.zoom - 0.1)}>−</button>
          <output data-testid="stage-zoom">{Math.round(layer.camera.zoom * 100)}%</output>
          <button type="button" aria-label="Zoom in" onClick={() => zoomAt(layer.camera.zoom + 0.1)}>+</button>
          <button
            type="button"
            data-testid="stage-fit"
            onClick={() => changeCamera(fitStageCamera(viewportSize.width, viewportSize.height))}
          >
            Whole stage
          </button>
        </div>
        <button
          className="stage-library-toggle"
          type="button"
          data-testid="stage-library-toggle"
          aria-expanded={libraryOpen}
          onClick={() => setLibraryOpen((open) => !open)}
        >
          Library
        </button>
      </div>
      <output className="plate-press-status" role="status" data-testid="plate-press-status">
        {platePressStatus}
      </output>

      <div
        ref={viewportRef}
        className="stage-viewport"
        data-testid="stage-viewport"
        data-pointer-active={pointerActive ? 'true' : undefined}
        inert={openGate !== null || dismissibleOverlay !== null || undefined}
        onPointerDown={beginPan}
      >
        <div
          className="stage-canvas"
          data-testid="stage-canvas"
          data-stage-columns={STAGE_COLUMNS}
          data-stage-rows={STAGE_ROWS}
          style={stageCanvasStyle}
        >
          {layer.modules.map((module) => {
            const isDrawerOpen = drawerModule === module.module_id
            const isInert = openGate !== null || dismissibleOverlay !== null
            return (
            <RackModuleFrame
              key={module.module_id}
              manifest={RACK_MANIFESTS[module.module_id]}
              x={module.x}
              y={module.y}
              width={module.width}
              height={module.height}
              drawerOpen={isDrawerOpen}
              inert={isInert}
              onMove={moveModule}
              onResize={resizeModule}
              onRemove={(moduleId) => setLayout((current) => removeStageModule(current, moduleId))}
              onPointerActivity={setPointerActive}
              scope={layout.scopes[module.module_id]}
              spatialContext={{
                ...frameAddresses.get(module.module_id)!,
                scope: layout.scopes[module.module_id],
              }}
              onScopeChange={changeModuleScope}
              cameraZoom={layer.camera.zoom}
              isRegressionFixture={isRegressionFixture}
              theme={theme}
            />
            )
          })}
        </div>
        {offscreenModules.length > 0 && (
          <nav className="stage-recall" aria-label="Off-screen modules">
            <span>Off-screen</span>
            {offscreenModules.map((module) => (
              <button key={module.module_id} type="button" onClick={() => focusModule(module)}>
                {RACK_MANIFESTS[module.module_id].name}
              </button>
            ))}
          </nav>
        )}
      </div>

      {libraryOpen && (
        <aside className="stage-library" data-testid="stage-library" aria-label="Stage library">
          <header>
            <strong>Stage library</strong>
            <button type="button" aria-label="Close stage library" onClick={() => setLibraryOpen(false)}>×</button>
          </header>
          <p>Put any instrument back on this layer.</p>
          <ul>
            {STAGE_MODULE_IDS.map((moduleId) => {
              const present = layer.modules.some((module) => module.module_id === moduleId)
              return (
                <li key={moduleId}>
                  <span>{RACK_MANIFESTS[moduleId].name}</span>
                  <button
                    type="button"
                    disabled={present}
                    onClick={() => setLayout((current) => restoreStageModule(current, moduleId))}
                  >
                    {present ? 'On stage' : 'Add'}
                  </button>
                </li>
              )
            })}
          </ul>
          {layout.removed_layers.length > 0 && (
            <>
              <h2>Removed layers</h2>
              <ul>
                {layout.removed_layers.map((removed) => (
                  <li key={removed.layer_id}>
                    <span>{removed.name}</span>
                    <button
                      type="button"
                      onClick={() => setLayout((current) => restoreStageLayer(current, removed.layer_id))}
                    >
                      Restore
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      )}

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
          <RackSettingsControl
            manifest={RACK_MANIFESTS.gate}
            scope={layout.scopes.gate}
          />
          <RackPluginIframe
            manifest={RACK_MANIFESTS.gate}
            theme={theme}
            isRegressionFixture={isRegressionFixture}
          />
        </div>
      )}
      {dismissibleOverlay !== null && openGate === null && (
        <DismissibleRackOverlay
          moduleId={dismissibleOverlay}
          scope={layout.scopes[dismissibleOverlay]}
          onScopeChange={changeModuleScope}
          theme={theme}
          isRegressionFixture={isRegressionFixture}
        />
      )}
      {isRegressionFixture && (
        <RegressionFixtureMarker />
      )}
    </div>
  )
}

function DismissibleRackOverlay({
  moduleId,
  scope,
  onScopeChange,
  theme,
  isRegressionFixture,
}: {
  moduleId: DismissibleOverlayModuleId
  scope: 'GLOBAL' | 'CURRENT'
  onScopeChange: (moduleId: RackModuleId, scope: 'GLOBAL' | 'CURRENT') => void
  theme: ThemeId
  isRegressionFixture: boolean
}) {
  return (
    <div
      className={`rack-overlay-module rack-overlay-module--dismissible ${DISMISSIBLE_OVERLAY_CLASSES[moduleId]}`}
      data-rack-module={moduleId}
      data-stage-return="one-click"
    >
      <button
        className="rack-stage-back"
        type="button"
        data-testid="back-to-stage"
        onClick={clearRackSelection}
      >
        <span aria-hidden="true">←</span>
        Back to stage
      </button>
      <RackSettingsControl
        manifest={RACK_MANIFESTS[moduleId]}
        scope={scope}
        onScopeChange={(value) => onScopeChange(moduleId, value)}
      />
      <RackPluginIframe
        key={`${moduleId}:${scope}`}
        manifest={RACK_MANIFESTS[moduleId]}
        theme={theme}
        isRegressionFixture={isRegressionFixture}
      />
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
  onMove?: (moduleId: StageModuleId, x: number, y: number) => void
  onResize?: (
    moduleId: StageModuleId,
    width: number,
    height: number,
    direction: RackResizeDirection,
  ) => void
  onRemove?: (moduleId: StageModuleId) => void
  onPointerActivity?: (active: boolean) => void
  scope: 'GLOBAL' | 'CURRENT'
  spatialContext: SpatialSelectionContext
  onScopeChange?: (moduleId: StageModuleId, scope: 'GLOBAL' | 'CURRENT') => void
  onCollapseToggle?: () => void
  cameraZoom?: number
  isRegressionFixture?: boolean
  theme: ThemeId
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
  onMove,
  onResize,
  onRemove,
  onPointerActivity,
  scope,
  spatialContext,
  onScopeChange,
  onCollapseToggle,
  cameraZoom = 1,
  isRegressionFixture = false,
  theme,
}: RackModuleFrameProps) {
  const frameRef = useRef<HTMLDivElement>(null)
  const [resizeSequence, setResizeSequence] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const isDocked = manifest.slot === 'panel'
  const isStrip = manifest.slot === 'strip'
  const usesTemplate = isDocked || isStrip
  const moduleId = manifest.id as StageModuleId
  const resizeDirections = rackResizeDirections(manifest)

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

  function dockByKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (!usesTemplate || onMove === undefined || !event.altKey) {
      return
    }
    const deltaX = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
    const deltaY = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0
    if (deltaX === 0 && deltaY === 0) return
    event.preventDefault()
    onMove(moduleId, x + deltaX, y + deltaY)
  }

  function beginMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!usesTemplate || !manifest.movable || onMove === undefined || event.button !== 0) {
      return
    }
    event.preventDefault()
    const handle = event.currentTarget
    const pointerId = event.pointerId
    handle.setPointerCapture(pointerId)
    onPointerActivity?.(true)
    const startX = event.clientX
    const startY = event.clientY
    const startGridX = x
    const startGridY = y
    let moved = false
    setDragging(true)
    const move = (moveEvent: globalThis.PointerEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) >= 4) {
        moved = true
      }
      const deltaX = Math.round(
        (moveEvent.clientX - startX) / (STAGE_UNIT_WIDTH * cameraZoom),
      )
      const deltaY = Math.round(
        (moveEvent.clientY - startY) / (STAGE_UNIT_HEIGHT * cameraZoom),
      )
      onMove(moduleId, startGridX + deltaX, startGridY + deltaY)
    }
    const stop = () => {
      globalThis.removeEventListener('pointermove', move)
      globalThis.removeEventListener('pointerup', stop)
      globalThis.removeEventListener('pointercancel', cancel)
      if (handle.hasPointerCapture(pointerId)) {
        handle.releasePointerCapture(pointerId)
      }
      onPointerActivity?.(false)
      setDragging(false)
      if (!moved) return
    }
    const cancel = () => {
      globalThis.removeEventListener('pointermove', move)
      globalThis.removeEventListener('pointerup', stop)
      globalThis.removeEventListener('pointercancel', cancel)
      if (handle.hasPointerCapture(pointerId)) {
        handle.releasePointerCapture(pointerId)
      }
      onPointerActivity?.(false)
      setDragging(false)
    }
    globalThis.addEventListener('pointermove', move)
    globalThis.addEventListener('pointerup', stop)
    globalThis.addEventListener('pointercancel', cancel)
  }

  function beginResize(
    event: ReactPointerEvent<HTMLButtonElement>,
    direction: RackResizeDirection,
  ) {
    if (!usesTemplate || onResize === undefined) {
      return
    }
    event.preventDefault()
    const handle = event.currentTarget
    const pointerId = event.pointerId
    const viewport = frameRef.current?.closest('.stage-viewport')
    if (!(viewport instanceof HTMLElement)) {
      return
    }
    handle.setPointerCapture(pointerId)
    onPointerActivity?.(true)
    const startX = event.clientX
    const startY = event.clientY
    const startWidth = width
    const startHeight = height
    const unitX = STAGE_UNIT_WIDTH * cameraZoom
    const unitY = STAGE_UNIT_HEIGHT * cameraZoom
    const move = (moveEvent: globalThis.PointerEvent) => {
      const deltaX = Math.round((moveEvent.clientX - startX) / unitX)
      const deltaY = Math.round((moveEvent.clientY - startY) / unitY)
      const nextWidth = direction.includes('e')
        ? startWidth + deltaX
        : direction.includes('w')
          ? startWidth - deltaX
          : startWidth
      const nextHeight = direction.includes('s')
        ? startHeight + deltaY
        : direction.includes('n')
          ? startHeight - deltaY
          : startHeight
      onResize(moduleId, nextWidth, nextHeight, direction)
    }
    const stop = () => {
      globalThis.removeEventListener('pointermove', move)
      globalThis.removeEventListener('pointerup', stop)
      globalThis.removeEventListener('pointercancel', stop)
      if (handle.hasPointerCapture(pointerId)) {
        handle.releasePointerCapture(pointerId)
      }
      onPointerActivity?.(false)
    }
    globalThis.addEventListener('pointermove', move)
    globalThis.addEventListener('pointerup', stop)
    globalThis.addEventListener('pointercancel', stop)
  }

  const style: CSSProperties = {
    left: x * STAGE_UNIT_WIDTH,
    top: y * STAGE_UNIT_HEIGHT,
    width: width * STAGE_UNIT_WIDTH,
    height: height * STAGE_UNIT_HEIGHT,
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
      data-rack-template-module={usesTemplate ? 'true' : undefined}
      data-dragging={usesTemplate ? dragging : undefined}
      data-settings-open={settingsOpen || undefined}
      inert={inert || undefined}
    >
      {usesTemplate && (
        <div className="rack-module__chrome">
          <div
            className="rack-module__drag"
            role="button"
            tabIndex={0}
            aria-label={`Move ${manifest.name}; Alt plus arrow keys also moves it`}
            data-tooltip={`Move ${manifest.name}`}
            data-tooltip-detail="Drag the title or hold Alt and use the arrow keys."
            onKeyDown={dockByKeyboard}
            onPointerDown={beginMove}
          >
            <span aria-hidden="true">⠿</span>
            <strong>{manifest.name}</strong>
          </div>
          <RackSettingsControl
            manifest={manifest}
            scope={scope}
            onScopeChange={(value) => onScopeChange?.(moduleId, value)}
            onOpenChange={setSettingsOpen}
          />
          {onRemove !== undefined && (
            <button
              className="rack-module__remove"
              type="button"
              aria-label={`Remove ${manifest.name}`}
              data-tooltip={`Remove ${manifest.name}`}
              data-tooltip-detail="Remove it from this layer. Restore it later from Library."
              onClick={() => onRemove(moduleId)}
            >
              ×
            </button>
          )}
          {onCollapseToggle !== undefined && (
            <button
              className="rack-module__collapse"
              type="button"
              data-testid="vitals-collapse"
              aria-expanded={!collapsed}
              aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${manifest.name}`}
              onClick={onCollapseToggle}
            >
              <span aria-hidden="true">{collapsed ? '⌃' : '⌄'}</span>
              {collapsed ? 'Expand' : 'Collapse'}
            </button>
          )}
        </div>
      )}
      {resizeDirections.map((direction) => {
        return (
          <button
            key={direction}
            className={`rack-module__resize-handle rack-module__resize-handle--${direction}`}
            type="button"
            data-testid={`rack-resize-${manifest.id}-${direction}`}
            aria-label={`${manifest.name} ${direction} resize handle`}
            data-tooltip={`Resize ${manifest.name} from the ${resizeDirectionName(direction)}`}
            data-tooltip-detail="Drag or use the arrow keys. The Stage grid sets the limit."
            onPointerDown={(event) => beginResize(event, direction)}
            onKeyDown={(event) => {
              if (onResize === undefined) {
                return
              }
              if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault()
                const delta = event.key === 'ArrowRight' ? 1 : -1
                onResize(
                  moduleId,
                  width + (direction.includes('w') ? -delta : delta),
                  height,
                  direction,
                )
              } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                event.preventDefault()
                const delta = event.key === 'ArrowDown' ? 1 : -1
                onResize(
                  moduleId,
                  width,
                  height + (direction.includes('n') ? -delta : delta),
                  direction,
                )
              }
            }}
          />
        )
      })}
      <div className="rack-module__content">
        <RackPluginIframe
          key={`${manifest.id}:${scope}`}
          manifest={manifest}
          spatialContext={spatialContext}
          theme={theme}
          isRegressionFixture={isRegressionFixture}
        />
      </div>
    </div>
  )
}

function RackSettingsControl({
  manifest,
  scope,
  onScopeChange,
  onOpenChange,
}: {
  manifest: RackModuleManifest
  scope: 'GLOBAL' | 'CURRENT'
  onScopeChange?: (scope: 'GLOBAL' | 'CURRENT') => void
  onOpenChange?: (open: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const scopeAdjustable = (manifest.actions as readonly string[]).includes('rack.scope.set')
  const spatial = manifest.id === 'recipe'
  const fixedCopy = manifest.default_scope === 'GLOBAL'
    ? 'This module always shows the whole Palace.'
    : 'This module follows the selected thread.'

  function toggle() {
    const next = !open
    setOpen(next)
    onOpenChange?.(next)
  }

  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setOpen(false)
        onOpenChange?.(false)
      }
    }
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      onOpenChange?.(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', escape)
    }
  }, [onOpenChange, open])

  return (
    <div ref={rootRef} className="rack-module__settings" data-settings-open={open || undefined}>
      <button
        className="rack-module__settings-toggle"
        type="button"
        data-testid={`rack-settings-${manifest.id}`}
        aria-label={`${manifest.name} settings`}
        aria-expanded={open}
        data-tooltip={`${manifest.name} settings`}
        data-tooltip-detail="Open its view and module options."
        onClick={toggle}
      >
        <span aria-hidden="true">⚙</span>
      </button>
      {open && (
        <dialog open className="rack-module__settings-dialog" aria-label={`${manifest.name} settings`}>
          {scopeAdjustable ? (
            <>
              <header>
                <strong>{manifest.name}</strong>
                <button
                  type="button"
                  aria-label={`Close ${manifest.name} settings`}
                  onClick={toggle}
                >
                  ×
                </button>
              </header>
              <p>Choose what this module {spatial ? 'watches' : 'follows'}.</p>
              <div className="rack-module__scope" aria-label={`${manifest.name} view`}>
                {(['GLOBAL', 'CURRENT'] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={scope === value}
                    onClick={() => onScopeChange?.(value)}
                  >
                    {value === 'GLOBAL' ? 'Everything' : spatial ? 'This frame' : 'This thread'}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <p>{fixedCopy}</p>
          )}
        </dialog>
      )}
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
  const label = requested !== null && /^[A-Z][A-Z0-9]* REGRESSION$/.test(requested)
    ? requested
    : 'UNVERIFIED REGRESSION'
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
  const drawerOpen = rackModuleSelectionIsOpen(selection, moduleId)
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
      ) : moduleId === 'context_bars' ? (
        <ContextBars />
      ) : moduleId === 'thread_end' ? (
        <ThreadEndModule />
      ) : moduleId === 'palace_queue' ? (
        <PalaceQueueModule />
      ) : moduleId === 'model_device' ? (
        <ModelDevice />
      ) : moduleId === 'memory_graph' ? (
        <MemoryGraph />
      ) : moduleId === 'injection_console' ? (
        <InjectionConsole />
      ) : moduleId === 'recipe' ? (
        <RecipeModule />
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
  const { query, selection: selectionBus } = useRackPlugin()
  const [palaceStatus, setPalaceStatus] = useState<PalaceStatus>('checking')
  const selectedThread = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const memoryTotal = selectedThread?.memoryPanel.total ?? 0
  const threadsOpen = rackModuleSelectionIsOpen(selection, 'threads')
  const memoriesOpen = rackModuleSelectionIsOpen(selection, 'memory')

  useEffect(() => {
    if (snapshot.connection !== 'connected') return
    let active = true
    const probe = () => {
      void query.query({ resource: 'vitals', as_of: 'now' })
        .then((result) => {
          if (active) setPalaceStatus(result.status === 'live' ? 'ready' : 'unavailable')
        })
        .catch(() => {
          if (active) setPalaceStatus('unavailable')
        })
    }
    queueMicrotask(() => {
      if (active) setPalaceStatus('checking')
    })
    probe()
    const interval = globalThis.setInterval(probe, 60_000)
    return () => {
      active = false
      globalThis.clearInterval(interval)
    }
  }, [query, snapshot.connection])

  function toggleModule(moduleId: 'threads' | 'memory') {
    const alreadyOpen = rackModuleSelectionIsOpen(selection, moduleId)
    selectionBus.select(alreadyOpen ? null : { kind: 'module', id: moduleId })
  }

  return (
    <header className="topbar">
      <div className="brand" aria-label="Nocturne">
        <span className="brand__mark" aria-hidden="true">N</span>
        <span className="brand__word">Nocturne</span>
      </div>
      <span className="app-settings-reserve" aria-hidden="true" />

      <div className="mobile-navigation">
        <button
          className="mobile-threads"
          type="button"
          data-testid="mobile-threads"
          aria-label={`Threads ${snapshot.catalog.length.toString().padStart(2, '0')}`}
          aria-expanded={threadsOpen}
          onClick={() => toggleModule('threads')}
        >
          <span className="mobile-navigation__label">Threads</span>
          <span>{snapshot.catalog.length.toString().padStart(2, '0')}</span>
        </button>
        <button
          className="mobile-memories"
          type="button"
          data-testid="mobile-memories"
          aria-label={`Memory ${memoryTotal}`}
          aria-expanded={memoriesOpen}
          onClick={() => toggleModule('memory')}
        >
          <span className="mobile-navigation__label">Memory</span>
          <span>{memoryTotal}</span>
        </button>
      </div>

      <p
        className={`connection connection--${snapshot.connection} connection--palace-${palaceStatus}`}
        data-testid="connection"
        aria-live="polite"
      >
        <span className="connection__signal" aria-hidden="true" />
        {ownerConnectionCopy(snapshot.connection, palaceStatus)}
      </p>
    </header>
  )
}

function ThreadsModule() {
  const snapshot = useRackSnapshot()
  const { events, selection } = useRackPlugin()
  const [archiveBusyThreadId, setArchiveBusyThreadId] = useState<string | null>(null)
  const [archiveFailure, setArchiveFailure] = useState<string | null>(null)
  const sortedCatalog = useMemo(
    () => [...snapshot.catalog].sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
    [snapshot.catalog],
  )
  const fixtureThreadCount = snapshot.catalog.filter((entry) => isLegacyFixtureTitle(entry.title)).length

  return (
    <aside className="thread-rail" aria-labelledby="thread-rail-title">
      <div className="thread-rail__header">
        <h2 id="thread-rail-title">Threads</h2>
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

      {fixtureThreadCount > 0 && (
        <button
          className="fixture-catalog-cleanup"
          type="button"
          onClick={() => {
            void events.dispatch({ type: 'catalog.cleanup-fixtures' })
          }}
        >
          Remove {fixtureThreadCount} fixture {fixtureThreadCount === 1 ? 'thread' : 'threads'}
        </button>
      )}

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
          const archiveDisabled = archiveBusyThreadId !== null || liveState !== undefined
          return (
            <div
              key={entry.thread_id}
              className={`thread-item${isSelected ? ' thread-item--selected' : ''}`}
              data-thread-id={entry.thread_id}
            >
              <button
                className="thread-item__select"
                type="button"
                aria-current={isSelected ? 'page' : undefined}
                onClick={() => {
                  selection.select({ kind: 'thread', id: entry.thread_id })
                  void events
                    .dispatch({ type: 'thread.select', thread_id: entry.thread_id })
                    .catch(() => undefined)
                }}
              >
                <span className="thread-item__title">{visibleThreadTitle(entry.title)}</span>
                <span className="thread-item__meta">
                  <span>{detail}</span>
                  <span>{shortId(entry.thread_id)}</span>
                </span>
              </button>
              <button
                className="thread-item__archive"
                type="button"
                aria-label={`Archive ${visibleThreadTitle(entry.title)}`}
                data-tooltip={`Archive ${visibleThreadTitle(entry.title)}`}
                data-tooltip-detail="Extract its memories for review, then close the thread."
                disabled={archiveDisabled}
                onClick={() => {
                  setArchiveBusyThreadId(entry.thread_id)
                  setArchiveFailure(null)
                  void events.dispatch({ type: 'thread.archive', thread_id: entry.thread_id })
                    .catch(() => setArchiveFailure('That thread could not be archived. Try again from the thread.'))
                    .finally(() => setArchiveBusyThreadId(null))
                }}
              >
                <span aria-hidden="true">{archiveBusyThreadId === entry.thread_id ? '…' : '⤓'}</span>
              </button>
            </div>
          )
        })}
      </nav>

      {archiveFailure !== null && <p className="thread-archive-error" role="alert">{archiveFailure}</p>}

    </aside>
  )
}

function ChatModule() {
  const snapshot = useRackSnapshot()
  const rackSelection = useRackSelection()
  const { events, selection } = useRackPlugin()
  const selectedThreadId = snapshot.selectedThreadId
  const selectedThread = selectedThreadId === null ? null : snapshot.threads[selectedThreadId]
  const selectedMeta = snapshot.catalog.find((entry) => entry.thread_id === selectedThreadId)
  const [draft, setDraft] = useState('')
  const [pendingImage, setPendingImage] = useState<PendingImage | null>(null)
  const [imageStatus, setImageStatus] = useState('')
  const [imageBusy, setImageBusy] = useState(false)
  const [promptBusy, setPromptBusy] = useState(false)
  const [hasUnread, setHasUnread] = useState(false)
  const [archiveBusy, setArchiveBusy] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const imageReadGeneration = useRef(0)
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
        image: outbound.image_view,
        image_preview_data_url: outbound.image_preview_data_url,
      }))
    return optimistic.length === 0
      ? selectedThread.messages
      : [...selectedThread.messages, ...optimistic]
  }, [selectedThread])
  const activeRun = selectedThread?.activeRun ?? null
  const openGate = selectedThread?.openGate ?? null
  const queuedPrompts = selectedThread?.queuedPrompts ?? []
  const awaitingSnapshot = selectedThread?.awaitingSnapshot ?? true
  const projectSwitching = awaitingSnapshot && rackSelection?.kind === 'project'
  const composerDisabled =
    snapshot.connection !== 'connected' || awaitingSnapshot || openGate !== null
  const canSend =
    !composerDisabled &&
    !imageBusy &&
    !promptBusy &&
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
  const completedSymphonyDraftIds = useMemo(() => {
    const completed = new Set<string>()
    for (const message of messages) {
      if (message.role !== 'assistant') continue
      for (const event of message.events) {
        const launch = event.launch
        if (
          event.event_kind === 'symphony_result' &&
          typeof launch === 'object' && launch !== null && !Array.isArray(launch) &&
          typeof launch.draft_id === 'string'
        ) completed.add(launch.draft_id)
      }
    }
    return completed
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
    const prompt = draft.trim()
    const image = pendingImage
    setPromptBusy(true)
    const action = image === null
      ? { type: 'prompt.submit' as const, prompt }
      : {
          type: 'prompt.submit' as const,
          prompt,
          image: {
            input: image.input,
            view: image.view,
            image_preview_data_url: image.data_url,
          },
        }
    void events.dispatch(action)
      .then(() => {
        imageReadGeneration.current += 1
        setDraft('')
        setPendingImage(null)
        setImageStatus('')
        if (imageInputRef.current !== null) imageInputRef.current.value = ''
      })
      .catch(() => {
        setImageStatus('The prompt was not sent. Check the link and try again.')
      })
      .finally(() => setPromptBusy(false))
    followOutputRef.current = true
    setHasUnread(false)
  }

  async function attachImageFiles(files: readonly File[]) {
    if (files.length === 0) return
    if (files.length !== 1) {
      setImageStatus('Attach one image at a time.')
      return
    }
    if (pendingImage !== null) {
      setImageStatus('Remove the current image before attaching another.')
      return
    }
    const generation = ++imageReadGeneration.current
    setImageBusy(true)
    setImageStatus('Preparing image…')
    try {
      const prepared = await prepareImage(files[0]!)
      if (imageReadGeneration.current !== generation) {
        return
      }
      setPendingImage(prepared)
      setImageStatus(`${prepared.local_filename} attached.`)
    } catch (error) {
      if (imageReadGeneration.current === generation) {
        setImageStatus(
          error instanceof ImageInputError
            ? error.message
            : 'The image could not be read. Choose it again.',
        )
      }
    } finally {
      if (imageReadGeneration.current === generation) setImageBusy(false)
    }
  }

  function onComposerPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.files)
    if (files.length === 0) return
    event.preventDefault()
    void attachImageFiles(files)
  }

  function removePendingImage() {
    imageReadGeneration.current += 1
    setImageBusy(false)
    setPendingImage(null)
    setImageStatus('Image removed.')
    if (imageInputRef.current !== null) imageInputRef.current.value = ''
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
        <h1 id="thread-title">
          {selectedMeta === undefined ? 'Opening thread' : visibleThreadTitle(selectedMeta.title)}
        </h1>
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
        <div className="chat-header__context">
          <ProjectSelector
            selectedThreadId={selectedThreadId}
            currentProjectKey={snapshot.currentProjectKey}
            projectPaths={snapshot.projectPaths}
            awaitingSnapshot={awaitingSnapshot}
            switching={projectSwitching}
            onSelect={(projectKey) => events.dispatch({
              type: 'project.select',
              project_key: projectKey,
            })}
          />
          <button
            type="button"
            className="chat-header__model"
            data-testid="active-model"
            aria-label={`Active model: ${selectedThread?.resolvedModel ?? 'being chosen'}`}
            data-tooltip="Open Model Device"
            data-tooltip-detail="Choose the model and tune this thread’s request controls."
            onClick={() => selection.select({ kind: 'module', id: 'model_device' })}
          >
            <span aria-hidden="true">Model</span>
            <span className="chat-header__model-value">
              {selectedThread?.resolvedModel ?? 'Choosing model'}
            </span>
            <span className="chat-header__model-action" aria-hidden="true">Open ↗</span>
          </button>
        </div>
      </header>

      {(snapshot.globalError !== null || selectedThread?.lastError !== null) && (
        <div className="error-line" role="status" data-testid="error-line">
          <span aria-hidden="true">!</span>
          <span className="error-line__message">
            {selectedThread?.lastError?.message ?? snapshot.globalError?.message}
          </span>
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
              <h2>Restoring thread</h2>
              <p>Loading its latest messages before accepting input.</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="thread-empty" data-testid="thread-empty">
              <h2>New thread</h2>
              <p>Send a prompt when you’re ready. Nothing here demands a response.</p>
            </div>
          ) : (
            <>
              {messages.map((message) => (
                <MessageRow
                  key={message.message_id}
                  message={message}
                  threadId={selectedThreadId ?? ''}
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
                  completedSymphonyDraftIds={completedSymphonyDraftIds}
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
          {pendingImage !== null && (
            <div className="composer-attachment" role="group" aria-label="Attached image">
              <img
                className={pendingImage.input.media_type === 'image/gif' ? 'image-thumbnail--gif' : undefined}
                src={pendingImage.data_url}
                alt=""
              />
              {pendingImage.input.media_type === 'image/gif' && (
                <span className="image-tile image-tile--gif-reduced" aria-hidden="true">GIF</span>
              )}
              <span className="composer-attachment__meta">
                <strong>{pendingImage.local_filename}</strong>
                <small>
                  {imageFormatLabel(pendingImage.input.media_type)} ·{' '}
                  {formatImageBytes(pendingImage.view.byte_count)}
                </small>
              </span>
              <button
                className="composer-attachment__remove"
                type="button"
                aria-label={`Remove ${pendingImage.local_filename}`}
                disabled={promptBusy}
                onClick={removePendingImage}
              >
                Remove
              </button>
            </div>
          )}
          <label className="visually-hidden" htmlFor="prompt-input">
            Message Nocturne
          </label>
          <textarea
            id="prompt-input"
            ref={composerRef}
            data-testid="composer"
            value={draft}
            rows={1}
            placeholder={snapshot.connection === 'connected' ? 'Transmit to Nocturne' : 'Waiting for Nocturne'}
            disabled={composerDisabled || promptBusy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onComposerKeyDown}
            onPaste={onComposerPaste}
          />
          <div className="composer__utility">
            <input
              id="prompt-image-input"
              ref={imageInputRef}
              className="visually-hidden"
              data-testid="image-input"
              type="file"
              accept={IMAGE_ACCEPT}
              tabIndex={-1}
              aria-hidden="true"
              disabled={composerDisabled || imageBusy || promptBusy || pendingImage !== null}
              onChange={(event) => {
                const files = Array.from(event.currentTarget.files ?? [])
                event.currentTarget.value = ''
                void attachImageFiles(files)
              }}
            />
            <button
              className="composer__attach"
              type="button"
              data-testid="attach-image"
              aria-describedby="composer-image-status"
              disabled={composerDisabled || imageBusy || promptBusy || pendingImage !== null}
              onClick={() => imageInputRef.current?.click()}
            >
              {imageBusy ? 'Preparing…' : 'Attach image'}
            </button>
            <p
              id="composer-image-status"
              className="composer__image-status"
              aria-live="polite"
              aria-atomic="true"
            >
              {imageStatus}
            </p>
          </div>
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
              aria-label="Archive this thread"
              data-tooltip="Archive this thread"
              data-tooltip-detail="Extract its memories for review, then close the thread."
              disabled={archiveBusy || openGate !== null}
              onClick={archiveThread}
            >
              <span aria-hidden="true">{archiveBusy ? '…' : '⤓'}</span>
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
  birthplace: 'thread' | 'seed' | 'symphony'
  birthplace_thread_id: string | null
  batch_uid: string | null
  source_name: string | null
  birthplace_run_id?: string | null
  birthplace_origin_agent?: string | null
  judged_context?: {
    verdict: 'unanimous_pass'
    summary: string
    judge_ids: string[]
    evidence_refs: string[]
  } | null
  candidate: { label: string; body: string; keywords: string[] }
  neighbors: Array<{ memory_id: string; label: string }>
}

interface AgentFileOffer {
  batch_uid: string
  relative_path: string
  source_name: string
  markdown: string
  byte_count: number
}

function ThreadEndModule() {
  const snapshot = useRackSnapshot()
  const { events } = useRackPlugin()
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

  return (
    <div className="thread-end-module">
      {cards.length === 0 ? (
        <section className="thread-end-card thread-end-card--empty">
          <h2>Nothing pending</h2>
          <p>Duplicate lessons were folded out, or this thread produced no durable candidates.</p>
        </section>
      ) : (
        <ThreadEndCard
          view={{ final_post: finalPost, cards }}
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
  onDecide,
  onChanged,
}: {
  view: ThreadEndView
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
          <h2>What should survive?</h2>
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

function agentFileOffersFrom(value: JsonValue): { files: AgentFileOffer[]; truncated: boolean } {
  if (!isObject(value) || !Array.isArray(value.files) || typeof value.truncated !== 'boolean') {
    return { files: [], truncated: false }
  }
  const files: AgentFileOffer[] = []
  for (const item of value.files) {
    if (
      isObject(item) &&
      typeof item.batch_uid === 'string' &&
      typeof item.relative_path === 'string' &&
      typeof item.source_name === 'string' &&
      typeof item.markdown === 'string' &&
      typeof item.byte_count === 'number' && Number.isInteger(item.byte_count)
    ) {
      files.push({
        batch_uid: item.batch_uid,
        relative_path: item.relative_path,
        source_name: item.source_name,
        markdown: item.markdown,
        byte_count: item.byte_count,
      })
    }
  }
  return { files, truncated: value.truncated }
}

function isQueueCard(value: unknown): value is ThreadEndQueueCard {
  return isObject(value) && typeof value.item_uid === 'string' &&
    ['new', 'merge', 'supersede', 'contradict'].includes(String(value.verdict)) &&
    (typeof value.birthplace_thread_id === 'string' || value.birthplace_thread_id === null) &&
    (value.birthplace === 'thread' || value.birthplace === 'seed' || value.birthplace === 'symphony') &&
    (typeof value.batch_uid === 'string' || value.batch_uid === null) &&
    (typeof value.source_name === 'string' || value.source_name === null) &&
    (value.birthplace_run_id === undefined || typeof value.birthplace_run_id === 'string' || value.birthplace_run_id === null) &&
    (value.birthplace_origin_agent === undefined || typeof value.birthplace_origin_agent === 'string' || value.birthplace_origin_agent === null) &&
    (value.judged_context === undefined || value.judged_context === null || isObject(value.judged_context)) &&
    isObject(value.candidate) &&
    typeof value.candidate.label === 'string' && typeof value.candidate.body === 'string' &&
    Array.isArray(value.candidate.keywords) && value.candidate.keywords.every((item) => typeof item === 'string') &&
    Array.isArray(value.neighbors)
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function markdownFile(markdown: string): File {
  return new File([markdown], `pasted-${new Date().toISOString().replaceAll(':', '-')}.md`, {
    type: 'text/markdown',
  })
}

function PalaceQueueModule() {
  const { events } = useRackPlugin()
  const seedInputRef = useRef<HTMLInputElement>(null)
  const [cards, setCards] = useState<ThreadEndQueueCard[]>([])
  const [agentFiles, setAgentFiles] = useState<AgentFileOffer[]>([])
  const [agentFilesTruncated, setAgentFilesTruncated] = useState(false)
  const [queuedAgentFiles, setQueuedAgentFiles] = useState(new Set<string>())
  const [statusText, setStatusText] = useState('Add Markdown when you want to grow your Palace.')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)

  const load = useCallback(() => {
    return events.dispatch({ type: 'queue.load' }).then((value) => {
      setCards(queueCardsFrom(value).filter((card) =>
        card.birthplace === 'seed' || card.birthplace === 'symphony'
      ))
    })
  }, [events])

  const loadAgentFiles = useCallback(() => {
    return events.dispatch({ type: 'seed.jump-start.load' }).then((value) => {
      const discovered = agentFileOffersFrom(value)
      setAgentFiles(discovered.files)
      setAgentFilesTruncated(discovered.truncated)
    })
  }, [events])

  useEffect(() => {
    void Promise.all([load(), loadAgentFiles()]).catch(() => {
      setStatusText('Memory Ingest could not load its pending work or agent-file offers.')
    })
  }, [load, loadAgentFiles])

  const batches = useMemo(() => {
    const grouped = new Map<string, ThreadEndQueueCard[]>()
    for (const card of cards) {
      if (card.batch_uid === null) continue
      grouped.set(card.batch_uid, [...(grouped.get(card.batch_uid) ?? []), card])
    }
    return [...grouped.entries()]
  }, [cards])

  async function upload(files: readonly File[]) {
    if (files.length === 0 || busy) return
    setBusy(true)
    try {
      for (const file of files) {
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
      setStatusText('Split complete. Review each document before it enters your Palace.')
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : 'Seed ingestion failed.')
    } finally {
      setBusy(false)
    }
  }

  function queueAgentFile(file: AgentFileOffer) {
    if (busy) return
    setBusy(true)
    setStatusText(`Splitting ${file.relative_path} into reviewable memories…`)
    void events.dispatch({
      type: 'seed.upload',
      batch_uid: file.batch_uid,
      source_name: file.source_name,
      markdown: file.markdown,
    })
      .then(() => load())
      .then(() => {
        setQueuedAgentFiles((current) => new Set(current).add(file.batch_uid))
        setStatusText(`${file.relative_path} is ready for review. Nothing entered your Palace.`)
      })
      .catch((error) => {
        setStatusText(error instanceof Error ? error.message : 'The agent file could not be queued.')
      })
      .finally(() => setBusy(false))
  }

  function dropped(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    setDragging(false)
    if (busy) return
    const files = Array.from(event.dataTransfer.files)
    if (files.length > 0) {
      void upload(files)
      return
    }
    const markdown = event.dataTransfer.getData('text/plain')
    if (markdown.trim()) void upload([markdownFile(markdown)])
  }

  function pasted(event: ClipboardEvent<HTMLElement>) {
    if (busy) return
    const files = Array.from(event.clipboardData.files)
    const markdown = event.clipboardData.getData('text/plain')
    if (files.length === 0 && !markdown.trim()) return
    event.preventDefault()
    void upload(files.length > 0 ? files : [markdownFile(markdown)])
  }

  function decideBatch(batchUid: string, decision: 'approve' | 'deny') {
    if (busy) return
    setBusy(true)
    setStatusText(decision === 'approve' ? 'Approving the batch…' : 'Rejecting the batch…')
    void events.dispatch({ type: 'queue.batch.decide', batch_uid: batchUid, decision })
      .then(() => load())
      .then(() => setStatusText(decision === 'approve' ? 'Batch approved.' : 'Batch rejected.'))
      .catch(() => setStatusText('The document changed before it could be decided.'))
      .finally(() => setBusy(false))
  }

  return (
    <div className="palace-queue-module" data-testid="memory-ingest">
      <section className="palace-queue-card" aria-label="Memory Ingest">
        <header className="palace-queue-card__header">
          <div>
            <h2>Bring knowledge into your Palace</h2>
            <p>Documents become standalone memories for review. Nothing enters until you approve the document.</p>
          </div>
        </header>
        <section className="agent-file-jump-start" aria-labelledby="agent-file-jump-start-title">
          <header>
            <div>
              <h3 id="agent-file-jump-start-title">Start with your agent files</h3>
              <p>These files already guide agents in this workspace. Queue any one to review its memories first.</p>
            </div>
            {agentFilesTruncated ? <span>Showing the first 64 files</span> : null}
          </header>
          {agentFiles.length === 0 ? (
            <p className="agent-file-jump-start__empty">No AGENTS.md or CLAUDE.md files were found here.</p>
          ) : (
            <ul className="agent-file-offers">
              {agentFiles.map((file) => {
                const pending = cards.some((card) => card.batch_uid === file.batch_uid)
                const queued = pending || queuedAgentFiles.has(file.batch_uid)
                return (
                  <li key={`${file.relative_path}:${file.batch_uid}`} data-testid="agent-file-offer">
                    <div>
                      <strong>{file.relative_path}</strong>
                      <span>{file.byte_count.toLocaleString()} bytes</span>
                    </div>
                    <button type="button" disabled={busy || queued} onClick={() => queueAgentFile(file)}>
                      {queued ? 'Waiting for review' : 'Queue for review'}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
        <label
          className={`seed-drop${dragging ? ' seed-drop--active' : ''}`}
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return
            event.preventDefault()
            seedInputRef.current?.click()
          }}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
          }}
          onDrop={dropped}
          onPaste={pasted}
        >
          <span>{busy ? 'Working…' : 'Drop, paste, or choose Markdown'}</span>
          <input
            ref={seedInputRef}
            data-testid="seed-upload"
            type="file"
            accept=".md,.markdown,text/markdown"
            multiple
            tabIndex={-1}
            aria-hidden="true"
            disabled={busy}
            onChange={(event) => void upload(Array.from(event.currentTarget.files ?? []))}
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
                    <span>
                      {batchCards[0]?.birthplace === 'symphony' ? 'Judged Symphony winner' : 'Document'}
                      {' · '}{batchCards.length} memories
                    </span>
                    <h3>{batchCards[0]?.source_name ?? batchCards[0]?.judged_context?.summary ?? 'Untitled document'}</h3>
                    {batchCards[0]?.birthplace === 'symphony' ? (
                      <small>
                        Run {batchCards[0].birthplace_run_id} · {batchCards[0].judged_context?.judge_ids.length ?? 0} judges · explicit consent still required
                      </small>
                    ) : null}
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
  threadId: string
  queuePosition: number
  runState: UserMessageState | undefined
  activeRunId: string | undefined
  activeState: string | undefined
  completedSymphonyDraftIds: ReadonlySet<string>
}

function MessageRow({
  message,
  threadId,
  queuePosition,
  runState,
  activeRunId,
  activeState,
  completedSymphonyDraftIds,
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
        <div className="message__user-body">
          <p className="message__content">{message.content}</p>
          {message.image !== undefined && (
            <UserImage
              key={message.state}
              threadId={threadId}
              messageId={message.message_id}
              image={message.image}
              previewDataUrl={
                'image_preview_data_url' in message
                  ? message.image_preview_data_url
                  : undefined
              }
              available={message.state !== 'submitting'}
            />
          )}
        </div>
      </article>
    )
  }

  const status = messageStatus(message, runState, activeRunId, activeState)
  const tone = runState === 'error'
    ? 'danger'
    : runState === 'budget_exceeded'
      ? 'budget'
      : 'normal'
  const symphonyEvents = message.events.filter((event) =>
    event.event_kind === 'symphony_result' ||
    (
      event.event_kind === 'symphony_deliberation' &&
      typeof event.draft_id === 'string' &&
      !completedSymphonyDraftIds.has(event.draft_id)
    )
  )
  const diagnosticEvents = message.events.filter((event) =>
    typeof event.event_kind !== 'string' || !event.event_kind.startsWith('symphony_')
  )
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
      {symphonyEvents.map((event, index) => event.event_kind === 'symphony_deliberation'
        ? <SymphonyDeliberationCard key={`deliberation-${index}`} event={event} />
        : <SymphonyResultCard key={`result-${index}`} event={event} />
      )}
      {diagnosticEvents.length > 0 && (
        <details className="run-detail">
          <summary>{diagnosticEvents.length} run event{diagnosticEvents.length === 1 ? '' : 's'}</summary>
          <pre>{JSON.stringify(diagnosticEvents, null, 2)}</pre>
        </details>
      )}
    </article>
  )
}

function UserImage({
  threadId,
  messageId,
  image,
  previewDataUrl,
  available,
}: {
  threadId: string
  messageId: string
  image: ImageAttachmentView
  previewDataUrl?: string
  available: boolean
}) {
  const [failed, setFailed] = useState(false)
  const source = available
    ? journalImageSource(threadId, messageId)
    : previewDataUrl
  const useStaticTile = source === undefined || failed
  return (
    <figure className="message-image" data-sha256={image.sha256}>
      {useStaticTile ? (
        <span className="image-tile image-tile--message" aria-hidden="true">
          {imageFormatLabel(image.media_type)}
        </span>
      ) : (
        <img
          className={image.media_type === 'image/gif' ? 'image-thumbnail--gif' : undefined}
          src={source}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
      {!useStaticTile && image.media_type === 'image/gif' && (
        <span className="image-tile image-tile--message image-tile--gif-reduced" aria-hidden="true">
          GIF
        </span>
      )}
      <figcaption>
        Attached {imageFormatLabel(image.media_type)} image ·{' '}
        {formatImageBytes(image.byte_count)}
      </figcaption>
    </figure>
  )
}

function imageFormatLabel(mediaType: ImageMediaType): string {
  if (mediaType === 'image/jpeg') return 'JPEG'
  return mediaType.slice('image/'.length).toUpperCase()
}

function journalImageSource(threadId: string, messageId: string): string {
  return `/v1/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}/image`
}

export default App
