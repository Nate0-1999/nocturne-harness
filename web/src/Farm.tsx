import { useFrame } from '@react-three/fiber'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import {
  AdditiveBlending, BoxGeometry, CatmullRomCurve3, Color, DoubleSide, Group, InstancedMesh, LatheGeometry,
  Matrix4, Quaternion, TorusGeometry, TubeGeometry, Vector2, Vector3,
} from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { ChromeEnvironment } from './ChromeEnvironment'
import { buildChambers, identitySeed, type Chamber, type DetailTier, type Point3, type WorkAgent, type WorkProject } from './visualization'

// The plate's farm: liquid-glass basins with chrome rims on a tilted ground, linked by glass limbs.
const TILT = -1.0
const BASIN_PROFILE = [[0.6, 0.03], [0.82, 0.08], [0.92, 0.2], [0.95, 0.34], [0.99, 0.4], [1.04, 0.38],
  [1.07, 0.3], [1.06, 0.12], [0.98, 0.02], [0.84, -0.05], [0.6, -0.05]].map(([x, y]) => new Vector2(x, y))
const TOUCH_HALF_LIFE_S = 600

type Cell = { path: string; position: Point3; size: number }

export function Farm({ project, agents, selectedId, selectedPath, tier, asOf, pick, pickPath }: {
  project: WorkProject; agents: WorkAgent[]; selectedId: string | null; tier: DetailTier
  selectedPath: string | null; asOf: string
  pick: (agent: WorkAgent) => void; pickPath: (path: string) => void
}) {
  const full = tier === 'full'
  // Each feed refresh is a new object; lay the tree out again only when the tree itself changed (F122).
  const tree = `${project.root}\n${project.nodes.map((node) => `${node.kind}:${node.path}:${node.bytes}`).join('\n')}`
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const chambers = useMemo(() => buildChambers(project), [tree])
  const byPath = useMemo(() => new Map(chambers.map((chamber) => [chamber.path, chamber])), [chambers])
  const cells = useMemo(() => chambers.flatMap((chamber) => {
    const count = chamber.files.length, floor = chamber.radius * 0.62
    const room = Math.sqrt(Math.PI * floor * floor / Math.max(1, count)) * 0.72
    return chamber.files.map((file, i): Cell => {
      const angle = i * 2.399963, r = Math.sqrt((i + 0.5) / Math.max(1, count)) * floor
      // Cell size follows the file's bytes (log scale), never larger than its share of the floor.
      const size = Math.min(room, 0.1 + 0.06 * Math.log10(1 + file.bytes))
      return { path: `${project.root}/${file.path}`, size,
        position: [chamber.position[0] + Math.cos(angle) * r, chamber.position[1] + Math.sin(angle) * r, chamber.position[2] + 0.06 + size / 2] }
    })
  }), [chambers, project.root])
  const lastTouch = useMemo(() => {
    const touches = new Map<string, number>()
    for (const agent of agents) for (const file of agent.touched_files ?? []) {
      const time = Date.parse(file.ts)
      if (time > (touches.get(file.path) ?? 0)) touches.set(file.path, time)
    }
    return touches
  }, [agents])
  const inside = (agent: WorkAgent) => agent.location === project.root || agent.location.startsWith(`${project.root}/`)
  const resident = agents.filter(inside).sort((a, b) => a.id.localeCompare(b.id))
  return <>
    <ChromeEnvironment />
    <group rotation={[TILT, 0, 0]}>
      <gridHelper args={[60, 30, '#141c26', '#0b1119']} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, -1.4]} />
      <Basins chambers={chambers} full={full} selectedPath={selectedPath} root={project.root} pickPath={pickPath} />
      <Links chambers={chambers} byPath={byPath} full={full} />
      <Cells cells={cells} lastTouch={lastTouch} asOf={Date.parse(asOf)} selectedPath={selectedPath} full={full}
        pickPath={(path) => pickPath(path.slice(project.root.length + 1))} />
      {resident.map((agent) => {
        const relative = agent.location === project.root ? '.' : agent.location.slice(project.root.length + 1)
        const peers = resident.filter((peer) => peer.location === agent.location)
        return byPath.has(relative) && <Ant key={agent.id} agent={agent} chamber={relative} byPath={byPath}
          slot={peers.indexOf(agent)} selected={selectedId === agent.id} full={full} pick={() => pick(agent)} />
      })}
    </group>
  </>
}

function Basins({ chambers, full, selectedPath, root, pickPath }: {
  chambers: Chamber[]; full: boolean; selectedPath: string | null; root: string; pickPath: (path: string) => void
}) {
  const walls = useRef<InstancedMesh>(null), rims = useRef<InstancedMesh>(null), floors = useRef<InstancedMesh>(null)
  const geometry = useMemo(() => {
    const wall = new LatheGeometry(BASIN_PROFILE, full ? 56 : 22).rotateX(Math.PI / 2)
    const rim = new TorusGeometry(1.0, 0.075, full ? 12 : 5, full ? 72 : 28).translate(0, 0, 0.38)
    const floor = new LatheGeometry([new Vector2(0, 0.035), new Vector2(0.7, 0.035), new Vector2(0.84, 0.07)], full ? 40 : 16).rotateX(Math.PI / 2)
    return { wall, rim, floor }
  }, [full])
  useEffect(() => () => Object.values(geometry).forEach((item) => item.dispose()), [geometry])
  useLayoutEffect(() => {
    const matrix = new Matrix4(), rotation = new Quaternion(), color = new Color()
    chambers.forEach((chamber, index) => {
      // Stable identity shapes each basin (ADR-018); its size is the files it holds.
      const seed = identitySeed(chamber.path), r = chamber.radius
      rotation.setFromAxisAngle(new Vector3(0, 0, 1), seed * Math.PI * 2)
      matrix.compose(new Vector3(...chamber.position), rotation,
        new Vector3(r * (1 + (seed - 0.5) * 0.22), r * (1 - (seed - 0.5) * 0.22), 1.6 + Math.min(r, 1.7) * 0.6))
      const empty = chamber.files.length === 0
      const selected = selectedPath === `${root}${chamber.path === '.' ? '' : `/${chamber.path}`}`
      for (const [mesh, lit, dim] of [[walls, '#dfe8ff', '#4a5060'], [rims, '#f4f7ff', '#4d525e'], [floors, '#08122a', '#020308']] as const) {
        mesh.current?.setMatrixAt(index, matrix)
        mesh.current?.setColorAt(index, color.set(selected ? '#ffffff' : empty ? dim : lit))
      }
    })
    for (const mesh of [walls, rims, floors]) {
      if (!mesh.current) continue
      mesh.current.instanceMatrix.needsUpdate = true
      if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true
      mesh.current.computeBoundingSphere()
    }
  }, [chambers, geometry, selectedPath, root])
  const click = (event: { stopPropagation: () => void; instanceId?: number }) => {
    if (event.instanceId === undefined) return
    event.stopPropagation()
    pickPath(chambers[event.instanceId].path)
  }
  return <>
    <instancedMesh key={`floor:${chambers.length}`} ref={floors} args={[geometry.floor, undefined, chambers.length]}>
      <meshPhysicalMaterial metalness={0.7} roughness={0.22} clearcoat={0.4} envMapIntensity={0.22} />
    </instancedMesh>
    <instancedMesh key={`wall:${chambers.length}`} ref={walls} args={[geometry.wall, undefined, chambers.length]} onClick={click}>
      <meshPhysicalMaterial color={full ? '#ffffff' : '#2a4590'} metalness={0} roughness={0.02} clearcoat={1} clearcoatRoughness={0.02}
        ior={1.5} transmission={full ? 1 : 0} thickness={0.35} attenuationColor="#6f8fff" attenuationDistance={1.2}
        transparent={!full} opacity={full ? 1 : 0.55} envMapIntensity={1.5} side={DoubleSide} depthWrite={full} />
    </instancedMesh>
    <instancedMesh key={`rim:${chambers.length}`} ref={rims} args={[geometry.rim, undefined, chambers.length]} onClick={click}>
      <meshPhysicalMaterial metalness={1} roughness={0.08} clearcoat={1} envMapIntensity={1.7} />
    </instancedMesh>
  </>
}

function Links({ chambers, byPath, full }: { chambers: Chamber[]; byPath: Map<string, Chamber>; full: boolean }) {
  const geometry = useMemo(() => {
    const tubes = chambers.flatMap((chamber) => {
      const parent = chamber.parent === null ? undefined : byPath.get(chamber.parent)
      if (!parent) return []
      const from = new Vector3(...parent.position), to = new Vector3(...chamber.position)
      const direction = to.clone().sub(from).normalize()
      const start = from.clone().addScaledVector(direction, parent.radius * 0.98).setZ(from.z + 0.3)
      const end = to.clone().addScaledVector(direction, -chamber.radius * 0.98).setZ(to.z + 0.3)
      const middle = start.clone().lerp(end, 0.5).setZ((start.z + end.z) / 2 - 0.15)
      // Link width follows the files beneath the child folder (log scale).
      const radius = 0.09 + 0.04 * Math.log2(1 + chamber.beneath)
      // Limbs flare where they meet a rim, like the plate's liquid joins.
      const length = full ? 32 : 12, sides = full ? 12 : 6, curve = new CatmullRomCurve3([start, middle, end])
      const tube = new TubeGeometry(curve, length, radius, sides, false), position = tube.attributes.position
      for (let ring = 0; ring <= length; ring++) {
        const t = ring / length, center = curve.getPointAt(t), flare = 1 + 1.1 * Math.pow(Math.abs(2 * t - 1), 6)
        for (let side = 0; side <= sides; side++) {
          const index = ring * (sides + 1) + side
          const point = new Vector3().fromBufferAttribute(position, index).sub(center).multiplyScalar(flare).add(center)
          position.setXYZ(index, point.x, point.y, point.z)
        }
      }
      tube.computeVertexNormals()
      return [tube]
    })
    const merged = tubes.length ? mergeGeometries(tubes) : null
    tubes.forEach((tube) => tube.dispose())
    return merged
  }, [chambers, byPath, full])
  useEffect(() => () => geometry?.dispose(), [geometry])
  return geometry && <mesh geometry={geometry}>
    <meshPhysicalMaterial color="#dfe8ff" metalness={0.85} roughness={0.08} clearcoat={1} envMapIntensity={1.5} />
  </mesh>
}

function Cells({ cells, lastTouch, asOf, selectedPath, full, pickPath }: {
  cells: Cell[]; lastTouch: Map<string, number>; asOf: number; selectedPath: string | null; full: boolean
  pickPath: (path: string) => void
}) {
  const glass = useRef<InstancedMesh>(null), glow = useRef<InstancedMesh>(null)
  const seen = useRef(new Map<string, number>()), flashes = useRef(new Map<number, number>())
  const box = useMemo(() => new BoxGeometry(1, 1, 1), [])
  useEffect(() => () => box.dispose(), [box])
  const brightness = (index: number, now: number) => {
    const cell = cells[index], touched = lastTouch.get(cell.path)
    if (touched === undefined) return 0
    // A touched file glows, brighter the more recent the touch; a new touch flashes as it arrives.
    const recency = Math.pow(0.5, Math.max(0, asOf - touched) / 1000 / TOUCH_HALF_LIFE_S)
    const flash = flashes.current.get(index)
    return 0.6 + 1.4 * recency + (flash === undefined ? 0 : 2.6 * Math.max(0, 1 - (now - flash) / 1600))
  }
  const paint = (now: number) => {
    const color = new Color()
    cells.forEach((cell, index) => {
      const light = brightness(index, now)
      glow.current?.setColorAt(index, selectedPath === cell.path ? color.set('#ffffff') : color.set('#9cc0ff').multiplyScalar(light))
    })
    if (glow.current?.instanceColor) glow.current.instanceColor.needsUpdate = true
  }
  useLayoutEffect(() => {
    const matrix = new Matrix4(), now = performance.now()
    cells.forEach((cell, index) => {
      matrix.makeScale(cell.size, cell.size, cell.size).setPosition(...cell.position)
      glass.current?.setMatrixAt(index, matrix)
      matrix.makeScale(cell.size * 0.55, cell.size * 0.55, cell.size * 0.55).setPosition(...cell.position)
      glow.current?.setMatrixAt(index, matrix)
      const touched = lastTouch.get(cell.path)
      const previous = seen.current.get(cell.path)
      if (touched !== undefined && previous !== undefined && touched > previous) flashes.current.set(index, now)
      if (touched !== undefined) seen.current.set(cell.path, touched)
      else if (!seen.current.has(cell.path)) seen.current.set(cell.path, 0)
    })
    for (const mesh of [glass, glow]) {
      if (!mesh.current) continue
      mesh.current.instanceMatrix.needsUpdate = true
      mesh.current.computeBoundingSphere()
    }
    paint(now)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cells, lastTouch, asOf, selectedPath])
  useFrame(({ invalidate }) => {
    if (!flashes.current.size) return
    const now = performance.now()
    for (const [index, start] of flashes.current) if (now - start > 1600) flashes.current.delete(index)
    paint(now)
    invalidate()
  })
  return <>
    <instancedMesh key={`glass:${cells.length}`} ref={glass} args={[box, undefined, cells.length]}
      onClick={(event) => { if (event.instanceId !== undefined) { event.stopPropagation(); pickPath(cells[event.instanceId].path) } }}>
      <meshPhysicalMaterial color="#e6eeff" metalness={0} roughness={0.03} clearcoat={1} ior={1.5}
        transmission={full ? 0.9 : 0} thickness={0.3} transparent={!full} opacity={full ? 1 : 0.42} envMapIntensity={1.8} />
    </instancedMesh>
    <instancedMesh key={`glow:${cells.length}`} ref={glow} args={[box, undefined, cells.length]}>
      <meshBasicMaterial toneMapped={false} transparent blending={AdditiveBlending} depthWrite={false} />
    </instancedMesh>
  </>
}

/** Route along the folder tree: up from one chamber to the common ancestor, then down to the other. */
function route(from: string, to: string, byPath: Map<string, Chamber>): Chamber[] {
  const chain = (path: string) => {
    const out: string[] = []
    for (let at: string | null = path; at !== null && byPath.has(at); at = byPath.get(at)!.parent) out.push(at)
    return out
  }
  const up = chain(from), down = chain(to)
  const common = up.find((path) => down.includes(path)) ?? '.'
  return [...up.slice(0, up.indexOf(common) + 1), ...down.slice(0, down.indexOf(common)).reverse()]
    .map((path) => byPath.get(path)!).filter(Boolean)
}

function Ant({ agent, chamber, byPath, slot, selected, full, pick }: {
  agent: WorkAgent; chamber: string; byPath: Map<string, Chamber>; slot: number; selected: boolean
  full: boolean; pick: () => void
}) {
  const group = useRef<Group>(null), legs = useRef<Group>(null)
  const walk = useRef<{ curve: CatmullRomCurve3; start: number; duration: number } | null>(null)
  const at = useRef<string | null>(null)
  const home = byPath.get(chamber)!
  const angle = identitySeed(agent.id) * Math.PI * 2 + slot * 2.4
  const rest = new Vector3(home.position[0] + Math.cos(angle) * home.radius * 0.45,
    home.position[1] + Math.sin(angle) * home.radius * 0.45, home.position[2] + 0.2)
  const [rx, ry, rz] = rest.toArray()
  useLayoutEffect(() => {
    const node = group.current
    if (!node) return
    const target = new Vector3(rx, ry, rz)
    // The ant walks the links only when its recorded location (WHERE) changes; otherwise it rests.
    if (at.current !== null && at.current !== chamber && byPath.has(at.current)) {
      const stops = route(at.current, chamber, byPath).map((stop) => new Vector3(stop.position[0], stop.position[1], stop.position[2] + 0.45))
      const curve = new CatmullRomCurve3([node.position.clone(), ...stops, target])
      walk.current = { curve, start: performance.now(), duration: Math.max(1600, (stops.length - 1) * 900) }
    } else if (walk.current === null) {
      node.position.copy(target)
      node.rotation.set(0, 0, angle + Math.PI / 2)
    }
    at.current = chamber
  }, [chamber, rx, ry, rz, byPath, angle])
  useFrame(({ invalidate }) => {
    const node = group.current, moving = walk.current
    if (!node || !moving) return
    const t = Math.min(1, (performance.now() - moving.start) / moving.duration)
    const eased = t * t * (3 - 2 * t)
    node.position.copy(moving.curve.getPoint(eased))
    const tangent = moving.curve.getTangent(eased)
    node.rotation.set(0, 0, Math.atan2(tangent.y, tangent.x))
    if (legs.current) legs.current.rotation.x = Math.sin(t * moving.duration / 45) * 0.35
    if (t >= 1) { walk.current = null; if (legs.current) legs.current.rotation.x = 0 }
    invalidate()
  })
  const segments = full ? 18 : 8
  return <group ref={group} scale={selected ? 3.1 : 2.2} onClick={(event) => { event.stopPropagation(); pick() }}>
    {/* The plate's ant: blue head and thorax, pearl-white abdomen, dark legs. */}
    <mesh position={[0.16, 0, 0.05]} scale={[1, 0.85, 0.85]}><sphereGeometry args={[0.07, segments, segments / 2]} />
      <meshPhysicalMaterial color="#2448d8" metalness={0.55} roughness={0.12} clearcoat={1} envMapIntensity={1.6} /></mesh>
    <mesh position={[0.04, 0, 0.05]} scale={[1.1, 0.8, 0.8]}><sphereGeometry args={[0.06, segments, segments / 2]} />
      <meshPhysicalMaterial color="#1d3cc4" metalness={0.55} roughness={0.12} clearcoat={1} envMapIntensity={1.6} /></mesh>
    <mesh position={[-0.13, 0, 0.06]} scale={[1.35, 1, 0.95]}><sphereGeometry args={[0.085, segments, segments / 2]} />
      <meshPhysicalMaterial color="#f3f5fb" metalness={0.1} roughness={0.18} clearcoat={1} envMapIntensity={1.3}
        emissive="#9cc0ff" emissiveIntensity={selected ? 0.8 : 0} /></mesh>
    <group ref={legs}>
      {[-1, 1].flatMap((side) => [-0.02, 0.04, 0.1].map((x) => <mesh key={`${side}:${x}`}
        position={[x, side * 0.09, 0.02]} rotation={[side * 0.9, 0, (x - 0.04) * 6]}>
        <cylinderGeometry args={[0.008, 0.006, 0.17, 4]} />
        <meshStandardMaterial color="#14171f" metalness={0.6} roughness={0.35} />
      </mesh>))}
    </group>
  </group>
}
