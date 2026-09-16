import { useLayoutEffect, useMemo, useRef } from 'react'
import { Color, InstancedMesh, Matrix4 } from 'three'
import { agentColor, buildChambers, identitySeed, type DetailTier, type WorkAgent, type WorkProject } from './visualization'
import { Tube } from './VisualizationScene'

export function Farm({ project, agents, selectedId, selectedPath, tier, pick, pickPath }: {
  project: WorkProject; agents: WorkAgent[]; selectedId: string | null; tier: DetailTier
  selectedPath: string | null
  pick: (agent: WorkAgent) => void; pickPath: (path: string) => void
}) {
  const chambers = useMemo(() => buildChambers(project), [project])
  const cells = useMemo(() => chambers.flatMap((chamber) => chamber.files.map((file, i) => {
    const angle = i * 2.399963, r = Math.sqrt((i + 0.5) / Math.max(1, chamber.files.length)) * chamber.radius * 0.78
    return { file, position: [chamber.position[0] + Math.cos(angle) * r,
      chamber.position[1] + Math.sin(angle) * r, chamber.position[2] + 0.12] as [number, number, number] }
  })), [chambers])
  const mesh = useRef<InstancedMesh>(null)
  const extent = Math.ceil(Math.max(8, ...chambers.flatMap((c) => [Math.abs(c.position[0]) * 2 + 4, Math.abs(c.position[1]) * 2 + 4])))
  useLayoutEffect(() => {
    if (!mesh.current) return
    cells.forEach((cell, index) => {
      mesh.current!.setMatrixAt(index, new Matrix4().makeTranslation(...cell.position))
      mesh.current!.setColorAt(index, new Color(selectedPath === `${project.root}/${cell.file.path}` ? '#ffffff' : cell.file.kind === 'link' ? '#e8b29f' : '#bfcbd5'))
    })
    mesh.current.instanceMatrix.needsUpdate = true
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true
  }, [cells, selectedPath, project.root])
  return <group>
    <gridHelper args={[extent, Math.ceil(extent / 2), '#25303a', '#151d26']} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, -2]} />
    {chambers.map((chamber) => {
      const parent = chambers.find((c) => c.path === chamber.parent)
      const selected = selectedPath === `${project.root}${chamber.path === '.' ? '' : '/' + chamber.path}`
      return <group key={chamber.path}>
        {parent && <Tube points={[parent.position, [parent.position[0], chamber.position[1] + 1.5, chamber.position[2]], chamber.position]}
          radius={0.045} color="#98a1b5" tier={tier} />}
        <mesh position={chamber.position} scale={[1, 0.85, 0.55]}
          onClick={(event) => { event.stopPropagation(); pickPath(chamber.path) }}>
          <sphereGeometry args={[chamber.radius, tier === 'full' ? 32 : 10, tier === 'full' ? 20 : 6]} />
          <meshPhysicalMaterial color="#122039" metalness={0.7} roughness={0.16}
            transparent opacity={0.28} depthWrite={false} side={2} />
        </mesh>
        <mesh position={chamber.position} scale={[1, 0.85, 1]}>
          <torusGeometry args={[chamber.radius, 0.026, tier === 'full' ? 10 : 4, tier === 'full' ? 64 : 18]} />
          <meshStandardMaterial color="#eff8fa" metalness={0.9} roughness={0.12} emissive={selected ? '#ffffff' : '#98a1b5'} emissiveIntensity={selected ? 1.5 : 0.32} />
        </mesh>
      </group>
    })}
    <instancedMesh ref={mesh} args={[undefined, undefined, cells.length]} onClick={(event) => {
      if (event.instanceId !== undefined) { event.stopPropagation(); pickPath(cells[event.instanceId].file.path) }
    }}>
      <sphereGeometry args={[0.055, tier === 'full' ? 12 : 4, tier === 'full' ? 8 : 3]} />
      <meshStandardMaterial metalness={0.6} roughness={0.25} emissive="#bcc2cd" emissiveIntensity={0.24} />
    </instancedMesh>
    {agents.filter((agent) => agent.root === project.root).map((agent) => {
      const relative = agent.location === project.root ? '.' : agent.location.slice(project.root.length + 1)
      const chamber = chambers.find((c) => c.path === relative)
      if (!chamber) return null
      const color = agentColor(agent.id)
      const phase = identitySeed(agent.id) * Math.PI * 2
      return <group key={agent.id} position={[chamber.position[0] + Math.cos(phase) * 0.25,
        chamber.position[1] + Math.sin(phase) * 0.25, chamber.position[2] + 0.52]}
        scale={selectedId === agent.id ? 1.5 : 1} onClick={(event) => { event.stopPropagation(); pick(agent) }}>
        {[-0.15, 0, 0.16].map((x, index) => <mesh key={x} position={[x, 0, 0]} scale={[1, 0.7, 0.8]}>
          <sphereGeometry args={[index === 2 ? 0.12 : 0.09, tier === 'full' ? 16 : 6, 8]} />
          <meshStandardMaterial color={color} metalness={0.4} roughness={0.2} emissive={color} emissiveIntensity={0.7} />
        </mesh>)}
        {[-1, 1].flatMap((side) => [-0.1, 0, 0.1].map((x) => <Tube key={`${side}:${x}`}
          points={[[x, 0, 0], [x - 0.04, side * 0.14, 0.02], [x + 0.07, side * 0.24, -0.05]]}
          radius={0.014} color={color} tier={tier} />))}
      </group>
    })}
  </group>
}
