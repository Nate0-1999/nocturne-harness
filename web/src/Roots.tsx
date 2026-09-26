import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { AdditiveBlending, Box3, CatmullRomCurve3, Group, Mesh, MeshBasicMaterial, NormalBlending, TubeGeometry, Vector3 } from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { agentColor, buildRootPaths, buildRootRiver, rootSpendShares, rootWorkTimes, type DetailTier, type Point3, type RootBranch, type VisualizationSnapshot, type WorkAgent } from './visualization'
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
  // Frame what was recorded: centre the drawn river on the camera's target and fit it to the view.
  // When the river grows, the framing eases to its new extent rather than jumping.
  const river = useRef<Group>(null), framing = useRef<{ from: [Vector3, number]; to: [Vector3, number]; start: number } | null>(null)
  const invalidate = useThree((state) => state.invalidate)
  const camera = useThree((state) => state.camera), view = useThree((state) => state.size)
  const extent = JSON.stringify([...curves.values()].map((points) => [points[0], points.at(-1)]))
  useLayoutEffect(() => {
    const group = river.current
    if (group === null) return
    const was: [Vector3, number] = [group.position.clone(), group.scale.x]
    group.position.set(0, 0, 0)
    group.scale.setScalar(1)
    const box = new Box3().setFromObject(group), size = box.getSize(new Vector3()), center = box.getCenter(new Vector3())
    // Fit to what the camera actually sees at its distance, with a margin for the readout.
    const fov = 'fov' in camera ? (camera.fov as number) : 42
    const high = 2 * camera.position.length() * Math.tan(fov * Math.PI / 360), wide = high * view.width / Math.max(1, view.height)
    const scale = Math.min(2.5, 0.88 * wide / Math.max(1e-3, size.x), 0.78 * high / Math.max(1e-3, size.y))
    const target: [Vector3, number] = [center.multiplyScalar(-scale), scale]
    const first = was[1] === 1 && was[0].lengthSq() === 0
    group.scale.setScalar(first ? scale : was[1])
    group.position.copy(first ? target[0] : was[0])
    framing.current = first ? null : { from: was, to: target, start: performance.now() }
    invalidate()
  }, [extent, invalidate, camera, view.width, view.height])
  useFrame(({ invalidate: frame }) => {
    const group = river.current, move = framing.current
    if (!group || !move) return
    const t = Math.min(1, (performance.now() - move.start) / 600), eased = t * t * (3 - 2 * t)
    group.position.lerpVectors(move.from[0], move.to[0], eased)
    group.scale.setScalar(move.from[1] + (move.to[1] - move.from[1]) * eased)
    if (t >= 1) framing.current = null
    frame()
  })
  return <>
    <ChromeEnvironment />
    <color attach="background" args={[SHEET ? '#f5f5f2' : '#030509']} />
    <group ref={river}>
    {ordered.map((agent) => {
      const points = curves.get(agent.id)!
      const selected = selectedId === agent.id || newest && latest === agent.id
      const stopped = agent.state === 'stopped' || agent.state === 'cancelled'
      const measured = agent.cost_usd !== null
      const radius = measured ? 0.05 + Math.sqrt(Number(agent.cost_usd) / spendScale) * 0.48 : 0.03
      const forked = ordered.some((child) => child.parent_id === agent.id)
      return <group key={agent.id}>
        <ChromeRoot points={points} spent={rootSpendShares(agent, data.trails[agent.id] ?? [], points, moments)} radius={radius} tier={tier}
          stopped={stopped} selected={selected} forked={forked} onClick={() => pick(agent)} />
        <RootRiver agent={agent} points={points} moments={moments} begin={begin} end={end} radius={radius}
          spent={rootSpendShares(agent, data.trails[agent.id] ?? [], points, moments)}
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

function RootRiver({ agent, points, moments, begin, end, radius, spent, tier, selected, stopped, pick }: {
  agent: WorkAgent; points: Point3[]; moments: number[]; begin: number; end: number; radius: number; spent: number[]; tier: DetailTier
  selected: boolean; stopped: boolean; pick: () => void
}) {
  const key = JSON.stringify([agent.id, agent.turns, agent.tool_calls, agent.touched_files, points, moments, begin, end, radius, spent, tier])
  const geometry = useMemo(() => {
    const branches = buildRootRiver(agent, points, moments, begin, end)
    const heaviest = Math.max(1, ...branches.filter((branch) => branch.kind === 'turn').map((branch) => branch.weight))
    const full = tier === 'full'
    // Width grows with the work recorded beneath a branch; a turn is at most most of its root's width,
    // and a call or a file touch is finer than the branch it leaves.
    const widths: number[] = []
    for (const branch of branches) {
      widths.push(branch.kind === 'turn' ? radius * (0.12 + 0.33 * Math.sqrt(branch.weight / heaviest))
        : branch.kind === 'tool' ? widths[branch.parent] !== undefined && branch.parent >= 0
          ? Math.min(widths[branch.parent] * 0.6, 0.012 + 0.006 * Math.min(4, branch.weight)) : 0.014
          : 0.0065)
    }
    const shape = { turn: [28, 12, 10, 5, 0.16], tool: [14, 7, 6, 4, 0.12], file: [8, 5, 4, 3, 0.1] } as const
    const tubes = (kinds: RootBranch['kind'][]) => branches.flatMap((branch, index) => {
      if (!kinds.includes(branch.kind)) return []
      const [length, lengthLow, sides, sidesLow, end] = shape[branch.kind]
      return [taperedTube(branch.points, Math.max({ turn: 0.016, tool: 0.009, file: 0.0045 }[branch.kind], widths[index]), full ? length : lengthLow, full ? sides : sidesLow, tip(end))]
    })
    const merged = (parts: TubeGeometry[]) => {
      const geometry = parts.length ? mergeGeometries(parts) : null
      parts.forEach((part) => part.dispose())
      return geometry
    }
    // Stable identity per branch: its kind and its order in time within that kind.
    const seen = { turn: 0, tool: 0, file: 0 }
    const identities = branches.map((branch, index) => ({ key: `${branch.kind}:${seen[branch.kind]++}`, points: branch.points,
      width: Math.max({ turn: 0.016, tool: 0.009, file: 0.0045 }[branch.kind], widths[index]) }))
    return { chrome: merged(tubes(['turn', 'tool'])), capillaries: merged(tubes(['file'])), identities }
    // The key carries every input; recorded data arrives as fresh objects on each feed refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  useEffect(() => () => { geometry.chrome?.dispose(); geometry.capillaries?.dispose() }, [geometry])
  // A branch that appears while you watch grows: light runs from its junction to its tip, then fades.
  const growth = useRef<Group>(null), born = useRef<Set<string> | null>(null)
  const invalidate = useThree((state) => state.invalidate)
  useLayoutEffect(() => {
    const group = growth.current
    if (!group) return
    if (born.current === null) { born.current = new Set(geometry.identities.map((branch) => branch.key)); return }
    for (const branch of geometry.identities) {
      if (born.current.has(branch.key)) continue
      born.current.add(branch.key)
      const light = new Mesh(taperedTube(branch.points, branch.width * 1.9, 24, 6, tip(0.3)),
        // White light on the stage's black ground; a cobalt sweep on the sheet's white ground.
        new MeshBasicMaterial({ color: SHEET ? '#2f5bff' : '#dbe7ff', transparent: true, opacity: 0.95,
          blending: SHEET ? NormalBlending : AdditiveBlending, depthWrite: false, toneMapped: false }))
      light.userData.start = performance.now()
      light.geometry.setDrawRange(0, 0)
      group.add(light)
    }
    invalidate()
  }, [geometry, invalidate])
  useFrame(({ invalidate: frame }) => {
    const group = growth.current
    if (!group?.children.length) return
    for (const light of [...group.children] as Mesh<TubeGeometry, MeshBasicMaterial>[]) {
      const t = (performance.now() - light.userData.start) / 1600
      const count = light.geometry.index!.count
      light.geometry.setDrawRange(0, Math.floor(Math.min(1, t / 0.55) * count / 3) * 3)
      light.material.opacity = 0.95 * Math.min(1, Math.max(0, (1 - t) / 0.45))
      if (t >= 1) { group.remove(light); light.geometry.dispose(); light.material.dispose() }
    }
    frame()
  })
  const click = (event: { stopPropagation: () => void }) => { event.stopPropagation(); pick() }
  return <group name={`river:${agent.id}`}>
    <group ref={growth} />
    {geometry.chrome && <mesh geometry={geometry.chrome} onClick={click}><ChromeMaterial stopped={stopped} selected={selected} /></mesh>}
    {geometry.capillaries && <mesh geometry={geometry.capillaries} onClick={click}>
      <meshPhysicalMaterial color={stopped ? SHEET ? '#5a5f68' : '#8a8f99' : agentColor(agent.id)} metalness={stopped ? 0.2 : 0.85}
        roughness={stopped ? 0.8 : 0.2} envMapIntensity={selected ? 2.2 : 1.5} />
    </mesh>}
  </group>
}

/** Swelling from its junction to full width, then thinning to `end` of that width at the tip. */
const tip = (end: number) => (t: number) => Math.min(1, 0.45 + t * 6) * (end + (1 - end) * Math.pow(1 - t, 0.65))

/** A tube along a curve whose width at each point is `radius × profile(t)`. */
function taperedTube(points: Point3[], radius: number, length: number, sides: number, profile: (t: number) => number): TubeGeometry {
  const curve = new CatmullRomCurve3(points.map((point) => new Vector3(...point)))
  const tube = new TubeGeometry(curve, length, radius, sides, false)
  const positions = tube.attributes.position
  for (let ring = 0; ring <= length; ring++) {
    const t = ring / length, center = curve.getPointAt(t)
    const taper = profile(t)
    for (let side = 0; side <= sides; side++) {
      const index = ring * (sides + 1) + side
      const point = new Vector3().fromBufferAttribute(positions, index)
      point.sub(center).multiplyScalar(taper).add(center)
      positions.setXYZ(index, point.x, point.y, point.z)
    }
  }
  tube.computeVertexNormals()
  return tube
}

const SHEET = new URLSearchParams(globalThis.location.search).has('sheet')

function ChromeMaterial({ stopped, selected }: { stopped: boolean; selected: boolean }) {
  // Live roots are cool blue-white mirror chrome; dried roots are desaturated and matte (dark on the sheet).
  // On the sheet the chrome is the plate's dark mirror: a deep body and bright cool reflections.
  return <meshPhysicalMaterial color={stopped ? SHEET ? '#4c5058' : '#8a8e96' : SHEET ? '#7d8cab' : '#e4ecf8'} metalness={stopped ? 0.35 : 1}
    roughness={stopped ? 0.55 : SHEET ? 0.08 : 0.13} clearcoat={stopped ? 0 : 1} clearcoatRoughness={0.04}
    envMapIntensity={(selected ? 1.6 : 1.2) * (SHEET && !stopped ? 1.5 : 1)} />
}

function ChromeRoot({ points, spent, radius, tier, stopped, selected, forked, onClick }: {
  points: Point3[]; spent: number[]; radius: number; tier: DetailTier
  stopped: boolean; selected: boolean; forked: boolean; onClick: () => void
}) {
  const key = spent.join(',')
  const geometry = useMemo(() => {
    // Width follows recorded spend so far: a fine point at the root's start, full width where it has spent.
    const shares = key.split(',').map(Number)
    const profile = (t: number) => {
      const index = t * (shares.length - 1), low = Math.min(shares.length - 2, Math.floor(index))
      const share = shares[low] + (shares[low + 1] - shares[low]) * (index - low)
      return Math.max(0.3, Math.sqrt(share)) * Math.min(1, t / 0.05 + 0.15) * (t > 0.75 ? 1 - (1 - (forked ? 0.35 : 0.08)) * ((t - 0.75) / 0.25) ** 1.5 : 1)
    }
    return taperedTube(points, radius, tier === 'full' ? 96 : 32, tier === 'full' ? 12 : 6, profile)
  }, [points, key, radius, tier, forked])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} onClick={(event) => { event.stopPropagation(); onClick() }}>
    <ChromeMaterial stopped={stopped} selected={selected} />
  </mesh>
}
