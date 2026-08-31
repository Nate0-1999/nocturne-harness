import { Canvas, useFrame, type GLProps } from '@react-three/fiber'
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  InstancedMesh,
  LineBasicMaterial,
  Matrix4,
  Mesh,
  PointsMaterial,
  REVISION,
} from 'three'
import { color as tslColor } from 'three/tsl'
import { MeshStandardNodeMaterial, WebGPURenderer } from 'three/webgpu'
import { useRackPlugin, useRackSnapshot } from './rack'
import {
  buildNebulaBodies,
  buildNebulaCreatureFamilies,
  buildNebulaEvents,
  buildNebulaFilaments,
  NEBULA_BINDINGS,
  NEBULA_EVENT_COLORS,
  type NebulaAxisMode,
  type NebulaBody,
  type NebulaCreatureFamily,
  type NebulaFilament,
  type NebulaHardwareTier,
  type NebulaMemoryEvent,
  type PalaceNebulaSnapshot,
} from './nebulaBindings'
import './assets/palace-nebula.css'

type ScorerSnapshot = {
  active_version?: string
  learning?: {
    eligible_dispositions?: number
    retrain_runs?: unknown[]
    annotations?: { ts?: string }[]
  }
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | {
      kind: 'ready'
      snapshot: PalaceNebulaSnapshot
      bodies: NebulaBody[]
      memoryEvents: NebulaMemoryEvent[]
      filaments: NebulaFilament[]
      families: NebulaCreatureFamily[]
      scorer: ScorerSnapshot | null
    }

type ThreeBackend = 'WebGL2' | 'WebGPU' | 'starting'
type FirstArgument<T> = T extends (argument: infer Argument) => unknown ? Argument : never
type RendererDefaults = FirstArgument<GLProps>

export function PalaceNebula() {
  const { query, events } = useRackPlugin()
  const rack = useRackSnapshot()
  const [axis, setAxis] = useState<NebulaAxisMode>('activity')
  const [tier, setTier] = useState<NebulaHardwareTier>('full')
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' })
  const [fps, setFps] = useState(0)
  const [backend, setBackend] = useState<ThreeBackend>('starting')
  const threadId = scope === 'ATTUNED' ? rack.selectedThreadId ?? undefined : undefined

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'palace_nebula' }).then(setScope)
  }, [events])

  useEffect(() => {
    let active = true
    const graph = query.query({ resource: 'memory_graph', as_of: 'now', thread_id: threadId })
    const scorer = query.query({ resource: 'scorer_console', as_of: 'now', thread_id: threadId })
      .then((result) => result.data as unknown as ScorerSnapshot)
      .catch(() => null)
    void Promise.all([graph, scorer]).then(([graphResult, scorerSnapshot]) => {
      if (!active) return
      const snapshot = graphResult.data as unknown as PalaceNebulaSnapshot
      const bodies = buildNebulaBodies(snapshot, axis)
      const memoryEvents = buildNebulaEvents(snapshot)
      setLoad({
        kind: 'ready',
        snapshot,
        bodies,
        memoryEvents,
        filaments: buildNebulaFilaments(snapshot, bodies),
        families: buildNebulaCreatureFamilies(snapshot, bodies, memoryEvents),
        scorer: scorerSnapshot,
      })
    }).catch(() => {
      if (active) setLoad({ kind: 'error' })
    })
    return () => { active = false }
  }, [axis, query, threadId])

  const bodies = load.kind === 'ready' ? load.bodies : []
  const memoryEvents = load.kind === 'ready' ? load.memoryEvents : []
  const filaments = load.kind === 'ready' ? load.filaments : []
  const families = load.kind === 'ready' ? load.families : []
  const kinds = useMemo(() => (
    load.kind === 'ready' ? [...new Set(load.bodies.map((body) => body.kind))].sort() : []
  ), [load])
  const latestEvent = memoryEvents.at(-1)
  const splitCount = memoryEvents.filter((event) => event.event_class === 'split').length
  const mergeCount = memoryEvents.filter((event) => event.event_class === 'merge').length
  const learning = load.kind === 'ready' ? load.scorer?.learning : undefined
  const contextName = scope === 'GLOBAL' ? 'Whole Palace' : rack.attunement?.name ?? 'Unattuned'

  return <section className="palace-nebula" data-testid="palace-nebula" data-axis={axis} data-tier={tier} data-grammar="torrent-constellation">
    <header className="palace-nebula__header">
      <div className="palace-nebula__title">
        <small>Palace current · {contextName}</small>
        <h1>Living Memory</h1>
        <p>Every point is a recorded memory event. The graph is the instrument.</p>
      </div>
      <div className="palace-nebula__controls">
        <label>Posture<select aria-label="Nebula axes" value={axis} onChange={(event) => { setLoad({ kind: 'loading' }); setAxis(event.target.value as NebulaAxisMode) }}>
          <option value="activity">Activity</option><option value="provenance">Provenance</option>
        </select></label>
        <label>Render<select aria-label="Nebula hardware tier" value={tier} onChange={(event) => { setFps(0); setBackend('starting'); setTier(event.target.value as NebulaHardwareTier) }}>
          <option value="full">Full</option><option value="efficient">Efficient</option>
        </select></label>
      </div>
    </header>
    <div className="palace-nebula__viewport">
      {(bodies.length > 0 || memoryEvents.length > 0) && <ThreeNebula
        bodies={bodies}
        events={memoryEvents}
        families={families}
        filaments={filaments}
        tier={tier}
        reportBackend={setBackend}
        reportFps={setFps}
      />}
      <div className="palace-nebula__readouts" aria-label="Attuned Palace readouts">
        <article><span>Constellation</span><strong>{bodies.length} bodies</strong><small>{filaments.length} real filaments</small></article>
        <article><span>Memory current</span><strong>{memoryEvents.length} events</strong><small>{latestEvent === undefined ? 'No recorded current' : `${latestEvent.event_class} · ${latestEvent.memory_label}`}</small></article>
        <article><span>Creature</span><strong>{families.length} families</strong><small>{splitCount} splits · {mergeCount} merges</small></article>
        <article><span>Optimization</span><strong>{load.kind === 'ready' ? load.scorer?.active_version ?? 'Unavailable' : 'Waiting'}</strong><small>{learning === undefined ? 'Existing learning surface unavailable' : `${learning.eligible_dispositions ?? 0} signals · ${(learning.retrain_runs ?? []).length} runs`}</small></article>
      </div>
      <div className="palace-nebula__event-key" aria-label="Memory event hues">
        {(Object.keys(NEBULA_EVENT_COLORS) as (keyof typeof NEBULA_EVENT_COLORS)[]).map((eventClass) => (
          <span key={eventClass} style={{ '--event-color': rgbCss(NEBULA_EVENT_COLORS[eventClass]) } as CSSProperties}>{eventClass}</span>
        ))}
      </div>
      <div className="palace-nebula__telemetry" aria-live="polite">
        <strong>{fps || '—'} fps</strong>
        <span>Three r{REVISION} · R3F + TSL · {backend} · {tier}</span>
        <span>{load.kind === 'ready' ? load.snapshot.as_of : 'Reading current reality'}</span>
      </div>
      {load.kind === 'loading' && <p role="status" className="palace-nebula__notice">Reading Palace reality…</p>}
      {load.kind === 'error' && <p role="alert" className="palace-nebula__notice">The live Palace current is unavailable.</p>}
      {load.kind === 'ready' && bodies.length === 0 && memoryEvents.length === 0 && <p role="status" className="palace-nebula__notice">No memories or memory events exist in this Palace snapshot.</p>}
    </div>
    <aside className="palace-nebula__legend" aria-label="Living Memory data bindings">
      <section><h2>{axis === 'activity' ? 'Activity posture' : 'Provenance posture'}</h2>{NEBULA_BINDINGS[axis].map((binding) => <p key={binding}>{binding}</p>)}</section>
      <section><h2>Memory current</h2>{NEBULA_BINDINGS.current.map((binding) => <p key={binding}>{binding}</p>)}</section>
      <section><h2>Creature + constellation</h2>{NEBULA_BINDINGS.shared.map((binding) => <p key={binding}>{binding}</p>)}</section>
      <section><h2>Kinds in view</h2><p>{kinds.length === 0 ? 'None' : kinds.join(' · ')}</p><p>Camera alone is interactive; data marks remain still until reality changes.</p></section>
    </aside>
  </section>
}

function ThreeNebula({
  bodies,
  events,
  families,
  filaments,
  tier,
  reportBackend,
  reportFps,
}: {
  bodies: readonly NebulaBody[]
  events: readonly NebulaMemoryEvent[]
  families: readonly NebulaCreatureFamily[]
  filaments: readonly NebulaFilament[]
  tier: NebulaHardwareTier
  reportBackend: (backend: ThreeBackend) => void
  reportFps: (fps: number) => void
}) {
  const createRenderer = useMemo(() => async (defaults: RendererDefaults) => {
    if (!(defaults.canvas instanceof HTMLCanvasElement)) {
      throw new Error('Palace Nebula requires a browser canvas')
    }
    const parameters = { canvas: defaults.canvas, antialias: tier === 'full' }
    const renderer = new WebGPURenderer(parameters)
    await renderer.init()
    return renderer
  }, [tier])

  return <Canvas
    key={tier}
    aria-label={`Living Memory: ${bodies.length} active memories, ${events.length} memory events, ${filaments.length} relationships`}
    camera={{ fov: 48, position: [0, 0.4, 22] }}
    dpr={tier === 'full' ? [1, 2] : 1}
    gl={createRenderer}
    onCreated={({ gl }) => {
      const selected = (gl as unknown as { backend?: { isWebGPUBackend?: boolean } }).backend
      reportBackend(selected?.isWebGPUBackend === true ? 'WebGPU' : 'WebGL2')
    }}
    scene={{ background: new Color(0.004, 0.006, 0.015) }}
  >
    <ambientLight color={new Color(0.1, 0.08, 0.2)} intensity={Math.PI * 0.8} />
    <directionalLight color={new Color(0.96, 0.78, 0.58)} intensity={tier === 'full' ? 2.1 : 1.45} position={[5, 8, 7]} />
    <NebulaEventTorrent events={events} tier={tier} />
    <NebulaFilaments filaments={filaments} />
    {families.map((family) => <NebulaCreatureCluster key={family.id} family={family} tier={tier} />)}
    {bodies.map((body) => <NebulaMemoryBody key={body.id} body={body} tier={tier} />)}
    <FpsMeter reportFps={reportFps} />
  </Canvas>
}

function NebulaMemoryBody({ body, tier }: { body: NebulaBody; tier: NebulaHardwareTier }) {
  const meshRef = useRef<Mesh>(null)
  const material = useMemo(() => {
    const base = new Color(...body.color)
    const contextLight = body.pinned || body.in_current_context ? 0.42 : 0.16
    const next = new MeshStandardNodeMaterial({
      metalness: tier === 'full' ? 0.48 : 0.2,
      roughness: tier === 'full' ? 0.14 : 0.38,
    })
    next.colorNode = tslColor(base)
    next.emissiveNode = tslColor(base).mul(contextLight + body.recency_glow * 0.38)
    return next
  }, [body.color, body.in_current_context, body.pinned, body.recency_glow, tier])

  useEffect(() => () => material.dispose(), [material])
  return <mesh ref={meshRef} name={body.label} position={body.position} scale={body.scale} material={material}>
    <sphereGeometry args={[1, tier === 'full' ? 32 : 14, tier === 'full' ? 22 : 9]} />
  </mesh>
}

function NebulaEventTorrent({ events, tier }: { events: readonly NebulaMemoryEvent[]; tier: NebulaHardwareTier }) {
  const meshRef = useRef<InstancedMesh>(null)
  useLayoutEffect(() => {
    const mesh = meshRef.current
    if (mesh === null) return
    const matrix = new Matrix4()
    events.forEach((event, index) => {
      matrix.makeTranslation(...event.position)
      mesh.setMatrixAt(index, matrix)
      mesh.setColorAt(index, new Color(...event.color))
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor !== null) mesh.instanceColor.needsUpdate = true
  }, [events])
  return <instancedMesh
    ref={meshRef}
    name="memory-event-current"
    renderOrder={3}
    args={[undefined, undefined, events.length]}
  >
    <octahedronGeometry args={[tier === 'full' ? 0.09 : 0.065, 0]} />
    <meshBasicMaterial transparent opacity={0.96} depthTest={false} depthWrite={false} toneMapped={false} />
  </instancedMesh>
}

function NebulaFilaments({ filaments }: { filaments: readonly NebulaFilament[] }) {
  const geometry = useMemo(() => {
    const next = new BufferGeometry()
    next.setAttribute('position', new Float32BufferAttribute(filaments.flatMap((filament) => [...filament.from, ...filament.to]), 3))
    next.setAttribute('color', new Float32BufferAttribute(filaments.flatMap((filament) => [...filament.color, ...filament.color]), 3))
    return next
  }, [filaments])
  const material = useMemo(() => new LineBasicMaterial({ transparent: true, opacity: 0.46, vertexColors: true }), [])
  useEffect(() => () => { geometry.dispose(); material.dispose() }, [geometry, material])
  return <lineSegments name="memory-relationships" geometry={geometry} material={material} />
}

function NebulaCreatureCluster({ family, tier }: { family: NebulaCreatureFamily; tier: NebulaHardwareTier }) {
  const geometry = useMemo(() => {
    const positions: [number, number, number][] = []
    const colors: [number, number, number][] = []
    const count = tier === 'full' ? family.stipple_count : Math.ceil(family.stipple_count / 2)
    const radius = 0.72 + family.memory_ids.length * 0.16
    for (let index = 0; index < count; index += 1) {
      const y = 1 - ((index + 0.5) / count) * 2
      const ring = Math.sqrt(Math.max(0, 1 - y * y))
      const theta = family.phase + index * 2.399963229728653
      positions.push([
        family.center[0] + Math.cos(theta) * ring * radius,
        family.center[1] + y * radius,
        family.center[2] + Math.sin(theta) * ring * radius,
      ])
      colors.push([0.9, 0.94, 1])
    }
    return pointGeometry(positions, colors)
  }, [family, tier])
  const material = useMemo(() => new PointsMaterial({ size: 1.2, sizeAttenuation: false, transparent: true, opacity: 0.52, vertexColors: true }), [])
  useEffect(() => () => { geometry.dispose(); material.dispose() }, [geometry, material])
  return <points name={`duplicate-family-${family.id}`} geometry={geometry} material={material} />
}

function pointGeometry(
  positions: readonly (readonly [number, number, number])[],
  colors: readonly (readonly [number, number, number])[],
): BufferGeometry {
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(positions.flatMap((position) => [...position]), 3))
  geometry.setAttribute('color', new Float32BufferAttribute(colors.flatMap((color) => [...color]), 3))
  return geometry
}

function FpsMeter({ reportFps }: { reportFps: (fps: number) => void }) {
  const frames = useRef(0)
  const sampleSeconds = useRef(0)
  useEffect(() => () => reportFps(0), [reportFps])
  useFrame((_state, delta) => {
    frames.current += 1
    sampleSeconds.current += delta
    if (sampleSeconds.current < 1) return
    reportFps(Math.round(frames.current / sampleSeconds.current))
    frames.current = 0
    sampleSeconds.current = 0
  })
  return null
}

function rgbCss(color: readonly [number, number, number]): string {
  return `rgb(${color.map((channel) => Math.round(channel * 255)).join(' ')})`
}
