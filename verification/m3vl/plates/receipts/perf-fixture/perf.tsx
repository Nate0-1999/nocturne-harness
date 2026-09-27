// FIXTURE · M3VL efficient-tier frame rate: the real Roots renderer on a recorded real feed, camera orbit only.
import { useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Canvas, useFrame } from '@react-three/fiber'
import { Roots } from '../src/Roots'
import type { VisualizationSnapshot } from '../src/visualization'

const params = new URLSearchParams(location.search)
const feed = await (await fetch(params.get('feed') ?? '/m3vl-dev/feed-real.json')).json() as VisualizationSnapshot
const tier = (params.get('tier') ?? 'efficient') as 'efficient' | 'full'

function Meter({ report }: { report: (value: string) => void }) {
  const state = useRef({ warm: 0, seconds: 0, frames: 0, samples: [] as number[] })
  useFrame(({ camera }, delta) => {
    const s = state.current
    s.warm += delta
    camera.position.set(Math.sin(s.warm * 0.25) * 10, 2, 14)
    camera.lookAt(0, 0, 0)
    if (s.warm < 2) return
    s.frames++; s.seconds += delta
    if (s.seconds >= 1 && s.samples.length < 12) {
      s.samples.push(Math.round(s.frames / s.seconds)); s.frames = 0; s.seconds = 0
      report(JSON.stringify({ tier, agents: feed.agents.length, fps: s.samples, minimum: Math.min(...s.samples), complete: s.samples.length === 12 }))
    }
  })
  return null
}

function App() {
  const [value, setValue] = useState('warming')
  return <>
    <div style={{ position: 'fixed', top: 0, right: 0, background: '#b00', color: '#fff', font: '12px monospace', padding: '2px 8px' }}>FIXTURE · M3VL roots frame rate</div>
    <pre id="measurement">{value}</pre>
    <div style={{ width: 1230, height: 420 }}>
      <Canvas dpr={1} camera={{ fov: 42, position: [0, 2, 14] }} gl={{ antialias: tier === 'full' }}>
        <ambientLight intensity={0.65} /><directionalLight position={[0, 8, 12]} color="#eff8fa" intensity={4} />
        <directionalLight position={[-8, -4, 6]} color="#436ac5" intensity={3} /><pointLight position={[8, 4, 8]} color="#e8b29f" intensity={45} />
        <Roots data={feed} agents={feed.agents} selectedId={null} tier={tier} pick={() => {}} newest={false} />
        <Meter report={setValue} />
      </Canvas>
    </div>
  </>
}
createRoot(document.getElementById('root')!).render(<App />)
