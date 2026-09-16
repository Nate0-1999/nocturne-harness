import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { CatmullRomCurve3, Color, Vector3 } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { DetailTier, Point3 } from './visualization'

export function CameraControls({ distance, width = 0 }: { distance: number; width?: number }) {
  const { camera, gl, invalidate, size } = useThree()
  const fit = Math.max(distance, width * 1.5 / (size.width / size.height))
  useEffect(() => {
    camera.position.set(0, fit * 0.12, fit)
    const controls = new OrbitControls(camera, gl.domElement)
    controls.enableDamping = false
    controls.addEventListener('change', () => invalidate())
    gl.domElement.setAttribute('tabindex', '0')
    controls.listenToKeyEvents(gl.domElement)
    const zoom = (event: KeyboardEvent) => {
      if (!['+', '=', '-', '_'].includes(event.key)) return
      event.preventDefault()
      camera.position.sub(controls.target).multiplyScalar(event.key === '+' || event.key === '=' ? 0.85 : 1 / 0.85).add(controls.target)
      controls.update()
      invalidate()
    }
    gl.domElement.addEventListener('keydown', zoom)
    controls.update()
    return () => { gl.domElement.removeEventListener('keydown', zoom); controls.dispose() }
  }, [camera, gl, fit, invalidate])
  return null
}

export function VisualizationScene({ children, tier, distance = 24, width = 0, label }: {
  children: ReactNode; tier: DetailTier; distance?: number; width?: number; label: string
}) {
  const [triangles, setTriangles] = useState(0)
  return <><Canvas aria-label={label} frameloop="demand" dpr={tier === 'full' ? [1, 2] : 1}
    camera={{ position: [0, 5, distance], fov: 42, far: Math.max(2000, distance * 4) }}
    gl={{ antialias: tier === 'full' }} scene={{ background: new Color('#030509') }}>
    <ambientLight intensity={0.65} />
    <directionalLight position={[0, 8, 12]} color="#eff8fa" intensity={4} />
    <directionalLight position={[-8, -4, 6]} color="#436ac5" intensity={3} />
    <pointLight position={[8, 4, 8]} color="#e8b29f" intensity={45} />
    {children}
    <CameraControls distance={distance} width={width} />
    <SceneStatistics report={setTriangles} />
  </Canvas><output className="work-viz__primitives" aria-label="Rendered triangles">{triangles.toLocaleString()} triangles · {tier}</output></>
}

export function SceneStatistics({ report }: { report: (triangles: number) => void }) {
  const { gl } = useThree()
  useFrame(() => { requestAnimationFrame(() => report(gl.info.render.triangles)) })
  return null
}

export function Tube({ points, radius, color, tier, dim = false, onClick }: {
  points: Point3[]; radius: number; color: string; tier: DetailTier; dim?: boolean; onClick?: () => void
}) {
  const curve = useMemo(() => new CatmullRomCurve3(points.map((point) => new Vector3(...point))), [points])
  return <mesh onClick={onClick ? (event) => { event.stopPropagation(); onClick() } : undefined}>
    <tubeGeometry args={[curve, tier === 'full' ? 64 : 16, radius, tier === 'full' ? 12 : 4, false]} />
    <meshStandardMaterial color={color} metalness={0.76} roughness={dim ? 0.85 : 0.16}
      emissive={color} emissiveIntensity={dim ? 0.05 : 0.28} transparent opacity={dim ? 0.4 : 0.96} />
  </mesh>
}
