import { Canvas, useFrame, type GLProps } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Color, Mesh, REVISION } from 'three'
import { color as tslColor } from 'three/tsl'
import { MeshStandardNodeMaterial, WebGPURenderer } from 'three/webgpu'
import { useRackPlugin } from './rack'
import {
  buildNebulaBodies,
  NEBULA_BINDINGS,
  type NebulaAxisMode,
  type NebulaBody,
  type NebulaHardwareTier,
  type PalaceNebulaSnapshot,
} from './nebulaBindings'
import './assets/palace-nebula.css'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; snapshot: PalaceNebulaSnapshot; bodies: NebulaBody[] }

type ThreeBackend = 'WebGL2' | 'WebGPU' | 'starting'
type FirstArgument<T> = T extends (argument: infer Argument) => unknown ? Argument : never
type RendererDefaults = FirstArgument<GLProps>

export function PalaceNebula() {
  const { query } = useRackPlugin()
  const [axis, setAxis] = useState<NebulaAxisMode>('activity')
  const [tier, setTier] = useState<NebulaHardwareTier>('full')
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' })
  const [fps, setFps] = useState(0)
  const [backend, setBackend] = useState<ThreeBackend>('starting')

  useEffect(() => {
    let active = true
    void query.query({ resource: 'memory_graph', as_of: 'now' })
      .then((result) => {
        if (!active) return
        const snapshot = result.data as unknown as PalaceNebulaSnapshot
        setLoad({ kind: 'ready', snapshot, bodies: buildNebulaBodies(snapshot, axis) })
      })
      .catch(() => {
        if (active) setLoad({ kind: 'error' })
      })
    return () => { active = false }
  }, [axis, query])

  const bodies = useMemo(() => load.kind === 'ready' ? load.bodies : [], [load])
  const kinds = useMemo(() => [...new Set(bodies.map((body) => body.kind))].sort(), [bodies])

  return <section className="palace-nebula" data-testid="palace-nebula" data-axis={axis} data-tier={tier}>
    <header className="palace-nebula__header">
      <div><small>Palace · active memory</small><h1>Nebula</h1></div>
      <div className="palace-nebula__controls">
        <label>Axes<select aria-label="Nebula axes" value={axis} onChange={(event) => { setLoad({ kind: 'loading' }); setAxis(event.target.value as NebulaAxisMode) }}>
          <option value="activity">Activity</option><option value="provenance">Provenance</option>
        </select></label>
        <label>Hardware<select aria-label="Nebula hardware tier" value={tier} onChange={(event) => { setFps(0); setBackend('starting'); setTier(event.target.value as NebulaHardwareTier) }}>
          <option value="full">Full</option><option value="efficient">Efficient</option>
        </select></label>
      </div>
    </header>
    <div className="palace-nebula__viewport">
      {bodies.length > 0 && <ThreeNebula bodies={bodies} tier={tier} reportBackend={setBackend} reportFps={setFps} />}
      <div className="palace-nebula__telemetry" aria-live="polite">
        <strong>{bodies.length}</strong> active bodies · <strong>{fps || '—'}</strong> fps
        <span>Three.js r{REVISION} · r3f + TSL · {backend} · {tier} · {load.kind === 'ready' ? load.snapshot.as_of : 'waiting'}</span>
      </div>
      {load.kind === 'loading' && <p role="status" className="palace-nebula__notice">Reading active memories…</p>}
      {load.kind === 'error' && <p role="alert" className="palace-nebula__notice">The live Palace nebula is unavailable.</p>}
      {load.kind === 'ready' && bodies.length === 0 && <p role="status" className="palace-nebula__notice">No active memories in this Palace snapshot.</p>}
    </div>
    <aside className="palace-nebula__legend" aria-label="Nebula data bindings">
      <section><h2>{axis === 'activity' ? 'Activity axes' : 'Provenance axes'}</h2>{NEBULA_BINDINGS[axis].map((binding) => <p key={binding}>{binding}</p>)}</section>
      <section><h2>Shared bindings</h2>{NEBULA_BINDINGS.shared.map((binding) => <p key={binding}>{binding}</p>)}</section>
      <section><h2>Kinds in view</h2><p>{kinds.length === 0 ? 'None' : kinds.join(' · ')}</p></section>
    </aside>
  </section>
}

function ThreeNebula({
  bodies,
  tier,
  reportBackend,
  reportFps,
}: {
  bodies: readonly NebulaBody[]
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
    aria-label={`3D nebula of ${bodies.length} active Palace memories`}
    camera={{ fov: 52, position: [0, 0.6, 22] }}
    dpr={tier === 'full' ? [1, 2] : 1}
    gl={createRenderer}
    onCreated={({ gl }) => {
      const selected = (gl as unknown as { backend?: { isWebGPUBackend?: boolean } }).backend
      reportBackend(selected?.isWebGPUBackend === true ? 'WebGPU' : 'WebGL2')
    }}
    scene={{ background: new Color(0.015, 0.02, 0.045) }}
  >
    <ambientLight color={new Color(0.12, 0.14, 0.2)} intensity={Math.PI} />
    <directionalLight color={new Color(0.72, 0.78, 1)} intensity={tier === 'full' ? 1.8 : 1.25} position={[4, 7, 5]} />
    {bodies.map((body) => <NebulaMemoryBody key={body.id} body={body} tier={tier} />)}
    <FpsMeter reportFps={reportFps} />
  </Canvas>
}

function NebulaMemoryBody({ body, tier }: { body: NebulaBody; tier: NebulaHardwareTier }) {
  const meshRef = useRef<Mesh>(null)
  const frame = useRef(0)
  const phase = (body.position[0] + body.position[2]) * 0.37
  const material = useMemo(() => {
    const base = new Color(...body.color)
    const emissiveStrength = body.pinned || body.in_current_context ? 0.62 : 0.34
    const next = new MeshStandardNodeMaterial({
      metalness: tier === 'full' ? 0.34 : 0.12,
      roughness: tier === 'full' ? 0.18 : 0.46,
    })
    next.colorNode = tslColor(base)
    next.emissiveNode = tslColor(base).mul(emissiveStrength)
    return next
  }, [body.color, body.in_current_context, body.pinned, tier])

  useEffect(() => () => material.dispose(), [material])
  useFrame(({ clock }) => {
    frame.current += 1
    if (tier === 'efficient' && frame.current % 2 !== 0) return
    const mesh = meshRef.current
    if (mesh === null) return
    mesh.position.y = body.position[1] + Math.sin(clock.elapsedTime * Math.PI * 2 * body.motion_hz + phase) * body.motion_amplitude
  })

  return <mesh ref={meshRef} name={body.label} position={body.position} scale={body.scale} material={material}>
    <sphereGeometry args={[1, tier === 'full' ? 24 : 12, tier === 'full' ? 16 : 8]} />
  </mesh>
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
