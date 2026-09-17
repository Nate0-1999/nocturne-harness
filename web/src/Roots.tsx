import { useEffect, useMemo } from 'react'
import { CatmullRomCurve3, TubeGeometry, Vector3 } from 'three'
import { agentColor, rootCurve, type DetailTier, type Point3, type VisualizationSnapshot, type WorkAgent } from './visualization'
import { ChromeEnvironment } from './ChromeEnvironment'

export function Roots({ data, agents, selectedId, tier, pick, newest }: {
  data: VisualizationSnapshot; agents: WorkAgent[]; selectedId: string | null
  tier: DetailTier; pick: (agent: WorkAgent) => void; newest: boolean
}) {
  const begin = Date.parse(data.recorded_since), end = Date.parse(data.as_of)
  const ordered = [...agents].sort((a, b) => a.root.localeCompare(b.root) || a.id.localeCompare(b.id))
  const curves = ordered.map((agent, i) => rootCurve(agent, data.trails[agent.id] ?? [], (i - (ordered.length - 1) / 2) * 1.7, begin, end))
  const latest = [...agents].sort((a, b) => b.started_at.localeCompare(a.started_at))[0]?.id
  const spendScale = Math.max(0.01, ...agents.map((agent) => Number(agent.cost_usd ?? 0)))
  return <>
    <ChromeEnvironment />
    <color attach="background" args={[new URLSearchParams(globalThis.location.search).has('sheet') ? '#f5f5f2' : '#030509']} />
    <group>
    {ordered.map((agent, index) => {
      const curve = curves[index], parent = ordered.findIndex((a) => a.id === agent.parent_id)
      const junction = parent < 0 ? null : curves[parent].reduce((closest, point) =>
        Math.abs(point[0] - curve[0][0]) < Math.abs(closest[0] - curve[0][0]) ? point : closest)
      const selected = selectedId === agent.id || newest && latest === agent.id
      const stopped = agent.state === 'stopped' || agent.state === 'cancelled'
      const measured = agent.cost_usd !== null
      const radius = measured ? 0.025 + Math.sqrt(Number(agent.cost_usd) / spendScale) * 0.65 : 0.018
      const color = stopped ? '#888d9b' : '#eff8fa'
      // The child begins on its actual parent's curve: one continuous fork,
      // not an unrelated lane connected by a separate thin stroke.
      const points = junction ? curve.map((point, i): Point3 => {
        if (i === 0) return junction
        const join = Math.pow(1 - i / (curve.length - 1), 2)
        return [point[0], point[1] + (junction[1] - curve[0][1]) * join,
          point[2] + (junction[2] - curve[0][2]) * join]
      }) : curve
      const forked = ordered.some((child) => child.parent_id === agent.id)
      return <group key={agent.id}>
        <ChromeRoot points={points} radius={radius} color={color} tier={tier}
          stopped={stopped} selected={selected} forked={forked} onClick={() => pick(agent)} />
        <mesh position={curve.at(-1)} onClick={(event) => { event.stopPropagation(); pick(agent) }}>
          <sphereGeometry args={[0.045, tier === 'full' ? 20 : 8, 10]} />
          <meshStandardMaterial color={agentColor(agent.id)} emissive={agentColor(agent.id)} emissiveIntensity={selected ? 1 : 0.3} roughness={stopped ? 0.9 : 0.1} />
        </mesh>
      </group>
    })}
    </group>
  </>
}

function ChromeRoot({ points, radius, color, tier, stopped, selected, forked, onClick }: {
  points: Point3[]; radius: number; color: string; tier: DetailTier
  stopped: boolean; selected: boolean; forked: boolean; onClick: () => void
}) {
  const geometry = useMemo(() => {
    const curve = new CatmullRomCurve3(points.map((point) => new Vector3(...point)))
    const length = tier === 'full' ? 96 : 32, sides = tier === 'full' ? 12 : 6
    const tube = new TubeGeometry(curve, length, radius, sides, false)
    const positions = tube.attributes.position
    for (let ring = 0; ring <= length; ring++) {
      const t = ring / length, center = curve.getPointAt(t)
      const end = forked ? 0.35 : 0.035
      const taper = end + (1 - end) * Math.pow(1 - t, 0.65)
      for (let side = 0; side <= sides; side++) {
        const index = ring * (sides + 1) + side
        const point = new Vector3().fromBufferAttribute(positions, index)
        point.sub(center).multiplyScalar(taper).add(center)
        positions.setXYZ(index, point.x, point.y, point.z)
      }
    }
    tube.computeVertexNormals()
    return tube
  }, [points, radius, tier, forked])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} onClick={(event) => { event.stopPropagation(); onClick() }}>
    <meshPhysicalMaterial color={color} metalness={stopped ? 0.12 : 1}
      roughness={stopped ? 0.88 : 0.075} clearcoat={stopped ? 0 : 1}
      clearcoatRoughness={0.04} envMapIntensity={selected ? 2.4 : 1.8} />
  </mesh>
}
