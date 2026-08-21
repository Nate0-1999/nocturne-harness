import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Application,
  Color,
  Entity,
  FILLMODE_NONE,
  RESOLUTION_AUTO,
  StandardMaterial,
  Vec3,
  version as playCanvasVersion,
} from 'playcanvas'
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

export function PalaceNebula() {
  const { query } = useRackPlugin()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [axis, setAxis] = useState<NebulaAxisMode>('activity')
  const [tier, setTier] = useState<NebulaHardwareTier>('full')
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' })
  const [fps, setFps] = useState(0)

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
  useNebulaEngine(canvasRef, bodies, tier, setFps)
  const kinds = useMemo(() => [...new Set(bodies.map((body) => body.kind))].sort(), [bodies])

  return <section className="palace-nebula" data-testid="palace-nebula" data-axis={axis} data-tier={tier}>
    <header className="palace-nebula__header">
      <div><small>Palace · active memory</small><h1>Nebula</h1></div>
      <div className="palace-nebula__controls">
        <label>Axes<select aria-label="Nebula axes" value={axis} onChange={(event) => { setLoad({ kind: 'loading' }); setAxis(event.target.value as NebulaAxisMode) }}>
          <option value="activity">Activity</option><option value="provenance">Provenance</option>
        </select></label>
        <label>Hardware<select aria-label="Nebula hardware tier" value={tier} onChange={(event) => setTier(event.target.value as NebulaHardwareTier)}>
          <option value="full">Full</option><option value="efficient">Efficient</option>
        </select></label>
      </div>
    </header>
    <div className="palace-nebula__viewport">
      <canvas ref={canvasRef} aria-label={`3D nebula of ${bodies.length} active Palace memories`} />
      <div className="palace-nebula__telemetry" aria-live="polite">
        <strong>{bodies.length}</strong> active bodies · <strong>{fps || '—'}</strong> fps
        <span>PlayCanvas {playCanvasVersion} · {tier} · {load.kind === 'ready' ? load.snapshot.as_of : 'waiting'}</span>
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

function useNebulaEngine(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  bodies: readonly NebulaBody[],
  tier: NebulaHardwareTier,
  reportFps: (fps: number) => void,
) {
  useEffect(() => {
    const canvas = canvasRef.current
    if (canvas === null || bodies.length === 0) return
    const app = new Application(canvas, { graphicsDeviceOptions: { antialias: tier === 'full' } })
    app.setCanvasFillMode(FILLMODE_NONE)
    app.graphicsDevice.maxPixelRatio = Math.min(globalThis.devicePixelRatio || 1, tier === 'full' ? 2 : 1)
    app.setCanvasResolution(RESOLUTION_AUTO)
    app.scene.ambientLight = new Color(0.12, 0.14, 0.2)

    const camera = new Entity('nebula-camera')
    camera.addComponent('camera', { clearColor: new Color(0.015, 0.02, 0.045), fov: 52 })
    camera.setLocalPosition(0, 0.6, 22)
    app.root.addChild(camera)

    const light = new Entity('nebula-light')
    light.addComponent('light', { type: 'directional', color: new Color(0.72, 0.78, 1), intensity: tier === 'full' ? 1.8 : 1.25 })
    light.setLocalEulerAngles(35, 25, 0)
    app.root.addChild(light)

    const entities = bodies.map((body) => {
      const material = new StandardMaterial()
      material.diffuse = new Color(...body.color)
      material.emissive = new Color(...body.color).mulScalar(body.pinned || body.in_current_context ? 0.62 : 0.34)
      material.metalness = tier === 'full' ? 0.34 : 0.12
      material.gloss = tier === 'full' ? 0.82 : 0.54
      material.update()
      const entity = new Entity(body.label)
      entity.addComponent('render', { type: 'sphere', material })
      entity.setLocalPosition(...body.position)
      entity.setLocalScale(new Vec3(...body.scale))
      app.root.addChild(entity)
      return { body, entity, phase: (body.position[0] + body.position[2]) * 0.37 }
    })

    let elapsed = 0
    let frameCount = 0
    let sampleSeconds = 0
    app.on('update', (delta: number) => {
      elapsed += delta
      frameCount += 1
      sampleSeconds += delta
      const updateMotion = tier === 'full' || frameCount % 2 === 0
      if (updateMotion) entities.forEach(({ body, entity, phase }) => {
        entity.setLocalPosition(
          body.position[0],
          body.position[1] + Math.sin(elapsed * Math.PI * 2 * body.motion_hz + phase) * body.motion_amplitude,
          body.position[2],
        )
      })
      if (sampleSeconds >= 1) {
        reportFps(Math.round(frameCount / sampleSeconds))
        frameCount = 0
        sampleSeconds = 0
      }
    })

    const resize = () => {
      const bounds = canvas.getBoundingClientRect()
      app.resizeCanvas(Math.max(1, Math.round(bounds.width)), Math.max(1, Math.round(bounds.height)))
    }
    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    resize()
    app.start()
    return () => {
      observer.disconnect()
      app.destroy()
      reportFps(0)
    }
  }, [bodies, canvasRef, reportFps, tier])
}
