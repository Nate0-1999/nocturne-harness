import { useEffect, useMemo } from 'react'
import { CatmullRomCurve3, TubeGeometry, Vector3 } from 'three'
import { agentColor, buildRootPaths, identitySeed, rootWorkPosition, rootWorkTimes, type DetailTier, type Point3, type VisualizationSnapshot, type WorkAgent } from './visualization'
import { ChromeEnvironment } from './ChromeEnvironment'

export function Roots({ data, agents, selectedId, tier, pick, newest }: {
  data: VisualizationSnapshot; agents: WorkAgent[]; selectedId: string | null
  tier: DetailTier; pick: (agent: WorkAgent) => void; newest: boolean
}) {
  const begin = agents.length ? Math.min(...agents.map((agent) => Date.parse(agent.started_at))) : Date.parse(data.recorded_since)
  const end = Date.parse(data.as_of)
  const ordered = [...agents].sort((a, b) => a.root.localeCompare(b.root) || a.id.localeCompare(b.id))
  const curves = buildRootPaths(ordered, data.trails, begin, end)
  const moments = rootWorkTimes(ordered)
  const latest = [...agents].sort((a, b) => b.started_at.localeCompare(a.started_at))[0]?.id
  const spendScale = Math.max(0.01, ...agents.map((agent) => Number(agent.cost_usd ?? 0)))
  return <>
    <ChromeEnvironment />
    <color attach="background" args={[new URLSearchParams(globalThis.location.search).has('sheet') ? '#f5f5f2' : '#030509']} />
    <group>
    {ordered.map((agent) => {
      const points = curves.get(agent.id)!
      const selected = selectedId === agent.id || newest && latest === agent.id
      const stopped = agent.state === 'stopped' || agent.state === 'cancelled'
      const measured = agent.cost_usd !== null
      const radius = measured ? 0.025 + Math.sqrt(Number(agent.cost_usd) / spendScale) * 0.65 : 0.018
      const color = stopped ? '#888d9b' : '#eff8fa'
      const forked = ordered.some((child) => child.parent_id === agent.id)
      return <group key={agent.id}>
        <ChromeRoot points={points} radius={radius} color={color} tier={tier}
          stopped={stopped} selected={selected} forked={forked} onClick={() => pick(agent)} />
        <FileCapillaries agent={agent} points={points} moments={moments} radius={radius}
          tier={tier} selected={selected} stopped={stopped} pick={() => pick(agent)} />
        <mesh position={points.at(-1)} onClick={(event) => { event.stopPropagation(); pick(agent) }}>
          <sphereGeometry args={[0.045, tier === 'full' ? 20 : 8, 10]} />
          <meshStandardMaterial color={agentColor(agent.id)} emissive={agentColor(agent.id)} emissiveIntensity={selected ? 1 : 0.3} roughness={stopped ? 0.9 : 0.1} />
        </mesh>
      </group>
    })}
    </group>
  </>
}

function FileCapillaries({ agent, points, moments, radius, tier, selected, stopped, pick }: {
  agent: WorkAgent; points: Point3[]; moments: number[]; radius: number; tier: DetailTier
  selected: boolean; stopped: boolean; pick: () => void
}) {
  const curve = new CatmullRomCurve3(points.map((point) => new Vector3(...point)))
  return [...(agent.touched_files ?? [])].sort((a, b) => a.path.localeCompare(b.path)).map((file, index, files) => {
    const timeX = -9 + rootWorkPosition(Date.parse(file.ts), moments) * 18
    const t = Math.max(0, Math.min(1, (timeX - points[0][0]) / Math.max(0.001, points.at(-1)![0] - points[0][0])))
    const start = curve.getPoint(t)
    const side = index % 2 ? -1 : 1, fan = (Math.floor(index / 2) + 0.5) / Math.ceil(files.length / 2)
    const length = 1.2 + identitySeed(file.path) * 1.8
    const tip = start.clone().add(new Vector3(length, side * (1 + fan * 3), (identitySeed(file.path + ':depth') - 0.5) * 1.4))
    const branch: Point3[] = [start.toArray(), start.clone().add(new Vector3(length * 0.45, side * 0.2, 0)).toArray(),
      start.clone().lerp(tip, 0.65).toArray(), tip.toArray()]
    return <group key={file.path} name={`file:${file.path}`}>
      <ChromeRoot points={branch} radius={Math.max(0.012, radius * 0.12)} color={stopped ? '#888d9b' : '#eff8fa'}
        tier={tier} stopped={stopped} selected={selected} forked={false} onClick={pick} fine />
    </group>
  })
}

function ChromeRoot({ points, radius, color, tier, stopped, selected, forked, onClick, fine = false }: {
  points: Point3[]; radius: number; color: string; tier: DetailTier
  stopped: boolean; selected: boolean; forked: boolean; onClick: () => void; fine?: boolean
}) {
  const geometry = useMemo(() => {
    const curve = new CatmullRomCurve3(points.map((point) => new Vector3(...point)))
    const length = fine ? (tier === 'full' ? 24 : 8) : (tier === 'full' ? 96 : 32)
    const sides = fine ? (tier === 'full' ? 8 : 4) : (tier === 'full' ? 12 : 6)
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
  }, [points, radius, tier, forked, fine])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} onClick={(event) => { event.stopPropagation(); onClick() }}>
    <meshPhysicalMaterial color={color} metalness={stopped ? 0.12 : 1}
      roughness={stopped ? 0.88 : 0.075} clearcoat={stopped ? 0 : 1}
      clearcoatRoughness={0.04} envMapIntensity={selected ? 2.4 : 1.8} />
  </mesh>
}
