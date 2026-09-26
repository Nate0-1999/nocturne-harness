import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { AdditiveBlending, Box3, BufferAttribute, BufferGeometry, CatmullRomCurve3, Color, DataTexture, DataUtils, EquirectangularReflectionMapping, Group, HalfFloatType, LinearFilter, LinearSRGBColorSpace, Mesh, MeshBasicMaterial, NormalBlending, RGBAFormat, type Texture, TubeGeometry, Vector3 } from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { agentColor, buildRootTree, type DetailTier, type Point3, type RootBlush, type RootTube, type VisualizationSnapshot, type WorkAgent } from './visualization'
import { ChromeEnvironment } from './ChromeEnvironment'

export function Roots({ data, agents, selectedId, tier, pick, newest }: {
  data: VisualizationSnapshot; agents: WorkAgent[]; selectedId: string | null
  tier: DetailTier; pick: (agent: WorkAgent) => void; newest: boolean
}) {
  const begin = agents.length ? Math.min(...agents.map((agent) => Date.parse(agent.started_at))) : Date.parse(data.recorded_since)
  const ordered = [...agents].sort((a, b) => a.root.localeCompare(b.root) || a.id.localeCompare(b.id))
  // A cheap signature of every input (recorded data only grows): each agent's identity, state, times, price and event
  // counts, and its trail's length and latest sample. Recorded data arrives as fresh objects on each feed refresh.
  const key = [begin, ...ordered.map((agent) => {
    const trail = data.trails[agent.id] ?? []
    return [agent.id, agent.parent_id, agent.root, agent.state, agent.started_at, agent.updated_at, agent.cost_usd, agent.turns?.length,
      agent.tool_calls?.length, agent.touched_files?.length, trail.length, trail.at(-1)?.ts, trail.at(-1)?.cost_usd].join('|')
  })].join('\n')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const tree = useMemo(() => buildRootTree(ordered, data.trails, begin), [key])
  const owned = useMemo(() => {
    const groups = new Map<string, RootTube[]>()
    for (const tube of tree.tubes) groups.set(tube.agent, [...groups.get(tube.agent) ?? [], tube])
    return groups
  }, [tree])
  const latest = [...agents].sort((a, b) => b.started_at.localeCompare(a.started_at))[0]?.id
  const studio = useMemo(() => liquidStudio(), [])
  useEffect(() => () => studio.dispose(), [studio])
  // Frame what was recorded: centre the drawn river on the camera's target and fit it to the view.
  // When the river grows, the framing eases to its new extent rather than jumping.
  const river = useRef<Group>(null), framing = useRef<{ from: [Vector3, number]; to: [Vector3, number]; start: number } | null>(null)
  const invalidate = useThree((state) => state.invalidate)
  const camera = useThree((state) => state.camera), view = useThree((state) => state.size)
  const extent = JSON.stringify([tree.tubes.length, tree.gauge])
  // The fit waits a frame, until the camera controls have placed the camera for this view.
  const pending = useRef(0)
  useLayoutEffect(() => { pending.current = 2; invalidate() }, [extent, tree, invalidate, camera, view.width, view.height])
  useFrame(({ invalidate: frame }) => {
    const group = river.current
    if (!group) return
    if (pending.current > 1) { pending.current--; frame(); return }
    if (pending.current) {
      pending.current = 0
      const was: [Vector3, number] = [group.position.clone(), group.scale.x]
      group.position.set(0, 0, 0)
      group.scale.setScalar(1)
      const box = new Box3().setFromObject(group), size = box.getSize(new Vector3()), center = box.getCenter(new Vector3())
      // Fit to what the camera actually sees at its distance, with a margin for the readout.
      const fov = 'fov' in camera ? (camera.fov as number) : 42
      const high = 2 * camera.position.length() * Math.tan(fov * Math.PI / 360), wide = high * view.width / Math.max(1, view.height)
      let scale = Math.min(2.5, 0.9 * wide / Math.max(1e-3, size.x), 0.8 * high / Math.max(1e-3, size.y))
      // Depth is time, so later work sits further back and looks smaller: refit on what the camera actually projects.
      camera.updateMatrixWorld()
      for (let pass = 0; pass < 2; pass++) {
        group.scale.setScalar(scale)
        group.position.copy(center).multiplyScalar(-scale)
        group.updateMatrixWorld(true)
        const corner = new Vector3()
        let x = 1e-3, y = 1e-3
        for (const tube of tree.tubes) for (const point of tube.points) {
          corner.set(...point).applyMatrix4(group.matrixWorld).project(camera)
          x = Math.max(x, Math.abs(corner.x)); y = Math.max(y, Math.abs(corner.y))
        }
        // A source's ring reaches past its root's first point.
        for (const { point } of tree.sources) for (const [dx, dy] of [[-1, -1], [1, 1], [-1, 1], [1, -1]]) {
          corner.set(point[0] + dx * tree.gauge, point[1] + dy * tree.gauge, point[2]).applyMatrix4(group.matrixWorld).project(camera)
          x = Math.max(x, Math.abs(corner.x)); y = Math.max(y, Math.abs(corner.y))
        }
        scale *= Math.min(0.94 / x, 0.76 / y)
      }
      // Lifted a little, so the river clears the readout along the bottom of the view.
      const target: [Vector3, number] = [center.multiplyScalar(-scale).add(new Vector3(0, 0.07 * high, 0)), scale]
      const first = was[1] === 1 && was[0].lengthSq() === 0
      group.scale.setScalar(first ? scale : was[1])
      group.position.copy(first ? target[0] : was[0])
      framing.current = first ? null : { from: was, to: target, start: performance.now() }
      frame()
    }
    const move = framing.current
    if (!move) return
    const t = Math.min(1, (performance.now() - move.start) / 600), eased = t * t * (3 - 2 * t)
    group.position.lerpVectors(move.from[0], move.to[0], eased)
    group.scale.setScalar(move.from[1] + (move.to[1] - move.from[1]) * eased)
    if (t >= 1) framing.current = null
    frame()
  })
  return <>
    <ChromeEnvironment />
    <color attach="background" args={[SHEET ? '#ffffff' : '#000000']} />
    <group ref={river}>
      {ordered.map((agent) => <AgentRoots key={agent.id} name={agent.id} tubes={owned.get(agent.id) ?? NONE} studio={studio}
        tier={tier} state={agent.state} joins={LIVE[ordered.find((item) => item.id === agent.parent_id)?.state ?? ''] ? 1 : 0} selected={selectedId === agent.id || newest && latest === agent.id} pick={() => pick(agent)} />)}
      {[...new Set(ordered.map((agent) => agent.root))].map((root) => {
        // A project's trunk is as live as the liveliest root fused into it: dry only when every one has stopped.
        const trunk = owned.get(root)
        return trunk && <AgentRoots key={`trunk:${root}`} name={root} tubes={trunk} studio={studio} tier={tier}
          state={trunkState(ordered.filter((agent) => agent.root === root))} selected={false} pick={() => {}} />
      })}
      {tree.sources.map(({ agent, point }) => {
        const owner = ordered.find((item) => item.id === agent)!, selected = selectedId === agent
        // The plate's source mark: a chrome ring around a chrome bead where a project's root enters.
        return <group key={agent} position={point} onClick={(event) => { event.stopPropagation(); pick(owner) }}>
          <mesh><sphereGeometry args={[tree.gauge * 0.32, tier === 'full' ? 20 : 8, 12]} />
            <meshPhysicalMaterial envMap={studio} color={selected ? agentColor(agent) : PAINT.body} metalness={1} roughness={0.14} clearcoat={1} clearcoatRoughness={0.12} envMapIntensity={2.2} /></mesh>
          <mesh><torusGeometry args={[tree.gauge * 0.75, tree.gauge * 0.05, 8, tier === 'full' ? 40 : 16]} />
            <meshPhysicalMaterial envMap={studio} color={PAINT.ring} metalness={0.6} roughness={0.25} clearcoat={1} clearcoatRoughness={0.15} envMapIntensity={1.6} /></mesh>
        </group>
      })}
    </group>
  </>
}

const SHEET = new URLSearchParams(globalThis.location.search).has('sheet')
const NONE: RootTube[] = []
/** How live an agent's work is: running is full blue, waiting a dimmer blue, stopped or cancelled none. */
const LIVE: Record<string, number> = { running: 1, waiting: 0.55 }
const trunkState = (agents: WorkAgent[]) => ['running', 'waiting'].find((state) => agents.some((agent) => agent.state === state)) ?? 'stopped'
// The plate's palette: a near-black chrome body; blue where work is live, a warm red-pink at junctions and forks
// (a coral glow on the chrome, added over it). Stopped roots fade to a round, softly shaded matte close to the ground
// that keeps a blue trace, never grey and never louder than the live chrome: a pale blue on the white sheet, a deep
// blue on the black stage; their fine hairs a shade further from the ground, so they still read.
const PAINT = {
  body: new Color(SHEET ? '#4a5a80' : '#5d6680'), blue: new Color(SHEET ? '#3a78e0' : '#5a9cff'),
  pink: new Color(SHEET ? '#e8566a' : '#ff6f78'), coral: new Color('#ff7a8a'), dry: new Color(SHEET ? '#1f2a52' : '#1b2146'),
  hair: new Color(SHEET ? '#a7b5e6' : '#2c3768'), ring: new Color(SHEET ? '#5b78d6' : '#7d98ee'),
}

/** One agent's roots: its root, turns, tool calls and file touches, merged into a chrome body and fine tinted tubes. */
function AgentRoots({ name, tubes, studio, tier, state, joins = 0, selected, pick }: {
  name: string; tubes: RootTube[]; studio: Texture; tier: DetailTier; state: string; joins?: number; selected: boolean; pick: () => void
}) {
  const live = LIVE[state] ?? 0, stopped = !live
  const geometry = useMemo(() => {
    const full = tier === 'full'
    // How glossy each point is: live work is chrome; a stopped root is matte, except where its limb leaves a live
    // parent, whose chrome it keeps for one diameter so the join stays one fused body.
    const gloss = (tube: RootTube) => {
      if (live || tube.kind !== 'root' || !joins) return tube.radii.map(() => live ? 1 : 0)
      const collar = 2 * Math.max(...tube.radii.slice(0, 12))
      let walked = 0
      return tube.points.map((point, index) => {
        if (index) walked += Math.hypot(...point.map((value, axis) => value - tube.points[index - 1][axis]))
        return joins * (1 - smooth((walked - collar) / collar))
      })
    }
    // Blue is live work, dimmer while waiting; roots and thick branches are the chrome body. Pink is laid on by tube3.
    const paint = (tube: RootTube, shine: number[], chrome: boolean) => tube.radii.flatMap((radius, index) =>
      (chrome ? PAINT.dry : PAINT.hair).clone().lerp(PAINT.blue.clone().multiplyScalar(live).lerp(PAINT.body, tube.kind === 'root' ? 1 : smooth(radius / 0.8)), shine[index]).toArray())
    const build = (list: RootTube[], chrome: boolean) => {
      const parts = list.map((tube) => {
        const segments = Math.min(chrome ? full ? 160 : 40 : full ? 72 : 28, Math.max(4, Math.round(tube.points.length * (full ? 1.6 : 0.7)))), shine = gloss(tube)
        // Pink marks junctions and forks: the tube's own blush where it leaves, and each child's wash on its side. On
        // the chrome it never tints the dark body: it glows over it (chromeSurface).
        return tube3(tube.points, tube.radii, paint(tube, shine, chrome), segments, chrome ? full ? 16 : 8 : full ? 6 : 4, shine,
          { list: tube.blush, base: tube.pink, pink: PAINT.pink.toArray(), mix: chrome ? 0 : 1 })
      })
      const merged = parts.length ? mergeGeometries(parts) : null
      parts.forEach((part) => part.dispose())
      return merged
    }
    const thick = (tube: RootTube) => tube.kind === 'root' || Math.max(...tube.radii) >= 0.28
    return { chrome: build(tubes.filter(thick), true), fine: build(tubes.filter((tube) => !thick(tube)), false) }
  }, [tubes, tier, live, joins])
  useEffect(() => () => { geometry.chrome?.dispose(); geometry.fine?.dispose() }, [geometry])
  // A tube that appears while you watch grows: light runs from its junction to its tip, then fades.
  const growth = useRef<Group>(null), born = useRef<Set<string> | null>(null)
  const invalidate = useThree((state) => state.invalidate)
  useLayoutEffect(() => {
    const group = growth.current
    if (!group) return
    if (born.current === null) { born.current = new Set(tubes.map((tube) => tube.key)); return }
    for (const tube of tubes) {
      if (born.current.has(tube.key)) continue
      born.current.add(tube.key)
      const light = new Mesh(tube3(tube.points, tube.radii.map((radius) => radius * 1.9 + 0.04), null, 24, 6),
        // White light on the stage's black ground; a cobalt sweep on the sheet's white ground.
        new MeshBasicMaterial({ color: SHEET ? '#2f5bff' : '#dbe7ff', transparent: true, opacity: 0.95,
          blending: SHEET ? NormalBlending : AdditiveBlending, depthWrite: false, toneMapped: false }))
      light.userData.start = performance.now()
      light.geometry.setDrawRange(0, 0)
      group.add(light)
    }
    invalidate()
  }, [tubes, invalidate])
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
  return <group name={`roots:${name}`}>
    <group ref={growth} />
    {/* Liquid chrome: a near-black mirror whose clear coat throws the studio's blue-white streaks, moving with the camera.
        Where it is stopped (gloss 0) it turns a round matte in its own colour: no clear coat, no reflection. */}
    {geometry.chrome && <mesh geometry={geometry.chrome} onClick={click}>
      <meshPhysicalMaterial envMap={studio} vertexColors metalness={1} roughness={0.16} clearcoat={1} clearcoatRoughness={0.16}
        envMapIntensity={selected ? 2.6 : 1.9} toneMapped={!stopped} {...chromeSurface(live)} />
    </mesh>}
    {/* A stopped hair is the same round matte in its own blue tint, never a grey one and never lit into a sheen. */}
    {geometry.fine && <mesh geometry={geometry.fine} onClick={click}>
      {stopped ? <meshPhysicalMaterial vertexColors clearcoat={1} toneMapped={false} {...chromeSurface(0)} />
        : <meshStandardMaterial envMap={studio} vertexColors metalness={0.4} roughness={0.3} envMapIntensity={selected ? 1.8 : 1.2} />}
    </mesh>}
  </group>
}

const smooth = (u: number) => { const v = Math.min(1, Math.max(0, u)); return v * v * (3 - 2 * v) }
/** The chrome's surface, all in the material and fixed in the river's own space (no time, no randomness: same data,
 * same surface). Each vertex's `gloss` is 1 for the liquid chrome and 0 for the stopped matte (its own colour, shaded
 * round by one fixed light from 0.6 at its edges to 1 facing it, no reflection and no sheen). A faint, long ripple of
 * the normals along the river, from a fixed noise field, lets the studio's strip lights run as long streaks that
 * swell and break as the camera moves; it changes no width. Live chrome (`live` > 0) adds a wide blue sheen where the
 * surface turns from the view: cool across the body on the white sheet, the plate's cobalt rim on the black stage. */
const surfaces = new Map<number, { onBeforeCompile: (shader: { vertexShader: string; fragmentShader: string }) => void; customProgramCacheKey: () => string }>()
function chromeSurface(live: number) {
  const rim = (live * (SHEET ? 0.5 : 1.3)).toFixed(3), falloff = SHEET ? '1.1' : '2.6'
  // Red-pink glows on live chrome where a branch leaves, across the face and brightest at the edges, added over the
  // reflection so the glints still show through it (never on the stopped matte).
  const blushGlow = PAINT.coral.toArray().map((channel) => (channel * (SHEET ? 1.3 : 1.1)).toFixed(3)).join(', ')
  if (!surfaces.has(live)) surfaces.set(live, { customProgramCacheKey: () => `roots-chrome:${rim}`, onBeforeCompile: (shader) => {
    shader.vertexShader = shader.vertexShader.replace('#include <common>', 'attribute float gloss;\nattribute float blush;\nvarying float vGloss;\nvarying float vBlush;\nvarying vec3 vRipple;\n#include <common>')
      .replace('#include <begin_vertex>', 'vGloss = gloss;\nvBlush = blush;\nvRipple = position;\n#include <begin_vertex>')
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `varying float vGloss;
varying float vBlush;
varying vec3 vRipple;
#include <common>
float rippleHash(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float rippleNoise(vec3 x) {
  vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(rippleHash(i), rippleHash(i + vec3(1, 0, 0)), f.x), mix(rippleHash(i + vec3(0, 1, 0)), rippleHash(i + vec3(1, 1, 0)), f.x), f.y),
    mix(mix(rippleHash(i + vec3(0, 0, 1)), rippleHash(i + vec3(1, 0, 1)), f.x), mix(rippleHash(i + vec3(0, 1, 1)), rippleHash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
vec3 rippleField(vec3 p) { return vec3(rippleNoise(p), rippleNoise(p + vec3(19.1, 7.3, 3.7)), rippleNoise(p + vec3(5.9, 31.3, 17.1))) - 0.5; }
vec3 ripple(vec3 n) {
  vec3 p = vRipple * vec3(0.22, 0.35, 0.35);
  // Long along the river and mostly tilting along it, so a strip light's streak runs for several diameters, then
  // swells or breaks, rather than wriggling across the tube.
  return normalize(n + vGloss * mat3(viewMatrix) * (vec3(0.75, 0.3, 0.3) * (rippleField(p) + 0.5 * rippleField(p * 2.3 + 11.0))));
}
// The filmic curve the live chrome is drawn with, for a stopped limb's chrome collar (its matte is drawn untoned).
vec3 collarTone(vec3 x) { return clamp(x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }`)
      .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = mix(0.8, roughnessFactor, vGloss);')
      .replace('#include <metalnessmap_fragment>', '#include <metalnessmap_fragment>\nmetalnessFactor = mix(0.1, metalnessFactor, vGloss);')
      .replace('#include <normal_fragment_maps>', '#include <normal_fragment_maps>\nnormal = ripple(normal);')
      .replace('#include <clearcoat_normal_fragment_maps>', '#include <clearcoat_normal_fragment_maps>\nclearcoatNormal = ripple(clearcoatNormal);')
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
float edge = 1.0 - saturate(dot(nonPerturbedNormal, normalize(vViewPosition)));
totalEmissiveRadiance += vec3(0.16, 0.36, 1.0) * ${rim} * vGloss * pow(edge, ${falloff});
totalEmissiveRadiance += vec3(${blushGlow}) * vBlush * vGloss * (0.22 + 0.7 * pow(edge, 1.6));
totalEmissiveRadiance += (1.0 - vGloss) * (diffuseColor.rgb * (0.28 + 0.9 * max(0.0, dot(nonPerturbedNormal, normalize(vec3(-0.35, 0.6, 0.72)))))
  + vec3(0.42, 0.52, 0.86) * ${SHEET ? '0.55' : '0.16'} * pow(edge, 2.2));`)
      .replace('#include <lights_physical_fragment>', '#include <lights_physical_fragment>\nmaterial.clearcoat *= vGloss;')
      // The stopped matte is its own colour, shaded round (emitted above), with no reflection and no sheen.
      .replace('#include <lights_fragment_end>', '#include <lights_fragment_end>\nreflectedLight.directDiffuse *= vGloss;\nreflectedLight.indirectDiffuse *= vGloss;\nreflectedLight.directSpecular *= vGloss;\nreflectedLight.indirectSpecular *= vGloss;')
      .replace('#include <opaque_fragment>', live ? '#include <opaque_fragment>' : 'outgoingLight = mix(outgoingLight, collarTone(outgoingLight), vGloss);\n#include <opaque_fragment>')
  } })
  return surfaces.get(live)!
}

/** The roots' own studio: a black room with a soft cobalt glow away from the viewer (a blue edge light that stays inside
 * the body on the white sheet), two long cool-white strip lights above and below the river's axis with a blue fringe,
 * and a broad soft box overhead, so the chrome reads near-black with blue depth and long blue-white streaks along
 * both edges of every tube that move with the camera. Lighting only. */
function liquidStudio(): DataTexture {
  const width = 256, height = 128, data = new Uint16Array(width * height * 4)
  // [elevation, azimuth, elevation spread, azimuth spread, power]: facing the viewer; a strip is wide in azimuth, so a
  // tube running across the view catches it as one streak along its length.
  const boxes = [[0.42, 1.57, 0.045, 0.8, 14], [-0.34, 1.57, 0.035, 0.7, 9], [1.15, 1.4, 0.12, 0.5, 3], [0.75, 2.05, 0.06, 0.1, 6]]
  for (let row = 0; row < height; row++) for (let column = 0; column < width; column++) {
    const elevation = ((row + 0.5) / height - 0.5) * Math.PI, azimuth = ((column + 0.5) / width - 0.5) * Math.PI * 2
    const facing = Math.sin(azimuth) * Math.cos(elevation), cobalt = ((1 - Math.max(0, facing)) / 2) ** 2 * (0.4 + 0.6 * Math.cos(elevation)) * (SHEET ? 0.5 : 0.15)
    // A faint cobalt fill all round, so the body between highlights reads deep blue rather than black.
    const color = [0.001 + cobalt * 0.03, 0.003 + cobalt * 0.09, 0.012 + cobalt * 0.55]
    for (const [at, middle, high, wide, power] of boxes) {
      const across = Math.exp(-((Math.atan2(Math.sin(azimuth - middle), Math.cos(azimuth - middle)) / wide) ** 4)), off = (elevation - at) / high
      // A cool-white core (#cfe0ff) inside a softer blue fringe (#6fa3ff).
      const core = Math.exp(-(off ** 4)) * across, fringe = 0.12 * Math.exp(-((off / 2.6) ** 2)) * across
      for (let channel = 0; channel < 3; channel++) color[channel] += power * ([0.81, 0.88, 1][channel] * core + [0.44, 0.64, 1][channel] * fringe)
    }
    const offset = (row * width + column) * 4
    for (let channel = 0; channel < 3; channel++) data[offset + channel] = DataUtils.toHalfFloat(color[channel])
    data[offset + 3] = DataUtils.toHalfFloat(1)
  }
  const texture = new DataTexture(data, width, height, RGBAFormat, HalfFloatType)
  texture.mapping = EquirectangularReflectionMapping
  texture.colorSpace = LinearSRGBColorSpace
  texture.magFilter = texture.minFilter = LinearFilter
  texture.needsUpdate = true
  return texture
}

/** A round tube along `points` whose width at each point is `radii[i]` and colour `colors[3i..]`: it thins to its tips, never flattens.
 * Each child's `blush` washes this tube pink on the side it leaves toward, from just before its junction and fading
 * downstream over the stretch the child takes to clear it, as strong as the child's share of the dollars. */
function tube3(points: Point3[], radii: number[], colors: number[] | null, segments: number, sides: number, gloss: number[] | null = null,
  blush: { list: RootBlush[]; base: number[]; pink: number[]; mix: number } | null = null): BufferGeometry {
  const curve = new CatmullRomCurve3(points.map((point) => new Vector3(...point)), false, 'centripetal')
  const tube = new TubeGeometry(curve, segments, 1, sides, false)
  const positions = tube.attributes.position, normals = tube.attributes.normal, center = new Vector3(), point = new Vector3()
  const tangent = new Vector3(), normal = new Vector3(), toward = new Vector3()
  const paint = colors ? new Float32Array(positions.count * 3) : null, shine = gloss ? new Float32Array(positions.count) : null
  const pinks = blush ? new Float32Array(positions.count) : null
  // Rings sit at equal arc length along the curve, so each reads its width and colour at that same arc length.
  const walked = points.map(() => 0)
  for (let k = 1; k < points.length; k++) walked[k] = walked[k - 1] + Math.hypot(...points[k].map((value, axis) => value - points[k - 1][axis]))
  for (let ring = 0, k = 0; ring <= segments; ring++) {
    curve.getPointAt(ring / segments, center)
    curve.getTangentAt(ring / segments, tangent)
    const along = ring / segments * walked.at(-1)!
    while (k < points.length - 2 && walked[k + 1] < along) k++
    const low = k, u = Math.min(1, Math.max(0, (along - walked[low]) / Math.max(1e-9, walked[low + 1] - walked[low]))), index = low + u
    const radius = radii[low] + (radii[low + 1] - radii[low]) * u
    // The washes near this ring: how strong each is here along the tube, and the way its child leaves across it.
    const washes = (blush?.list ?? []).flatMap(({ at, reach, dir, weight }) => {
      const d = index - at, strength = weight * (d < 0 ? Math.exp(-((d / (0.3 * reach)) ** 2)) : 1 - smooth(d / reach))
      if (strength < 0.01) return []
      toward.set(...dir).addScaledVector(tangent, -toward.dot(tangent))
      return toward.lengthSq() > 1e-8 ? [{ strength, across: toward.clone().normalize() }] : []
    })
    for (let side = 0; side <= sides; side++) {
      const vertex = ring * (sides + 1) + side
      point.fromBufferAttribute(positions, vertex).sub(center).multiplyScalar(radius).add(center)
      positions.setXYZ(vertex, point.x, point.y, point.z)
      if (shine && gloss) shine[vertex] = gloss[low] + (gloss[low + 1] - gloss[low]) * u
      if (paint && colors) {
        normal.fromBufferAttribute(normals, vertex)
        // The tube's own blush all round, and each wash: full on the side its child leaves toward, gone on the far side.
        const pink = blush ? washes.reduce((most, { strength, across }) => Math.max(most, strength * ((1 + normal.dot(across)) / 2) ** 3),
          blush.base[low] + (blush.base[low + 1] - blush.base[low]) * u) : 0
        if (pinks) pinks[vertex] = pink
        for (let channel = 0; channel < 3; channel++) {
          const value = colors[low * 3 + channel] + (colors[(low + 1) * 3 + channel] - colors[low * 3 + channel]) * u
          paint[vertex * 3 + channel] = blush ? value + (blush.pink[channel] - value) * pink * blush.mix : value
        }
      }
    }
  }
  if (paint) tube.setAttribute('color', new BufferAttribute(paint, 3))
  if (shine) tube.setAttribute('gloss', new BufferAttribute(shine, 1))
  if (pinks) tube.setAttribute('blush', new BufferAttribute(pinks, 1))
  return tube
}
