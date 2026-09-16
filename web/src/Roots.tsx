import { agentColor, rootCurve, type DetailTier, type VisualizationSnapshot, type WorkAgent } from './visualization'
import { Tube } from './VisualizationScene'

export function Roots({ data, agents, selectedId, tier, pick, newest }: {
  data: VisualizationSnapshot; agents: WorkAgent[]; selectedId: string | null
  tier: DetailTier; pick: (agent: WorkAgent) => void; newest: boolean
}) {
  const begin = Date.parse(data.recorded_since), end = Date.parse(data.as_of)
  const ordered = [...agents].sort((a, b) => a.id.localeCompare(b.id))
  const curves = ordered.map((agent, i) => rootCurve(agent, data.trails[agent.id] ?? [], (i - (ordered.length - 1) / 2) * 1.7, begin, end))
  const latest = [...agents].sort((a, b) => b.started_at.localeCompare(a.started_at))[0]?.id
  return <group>
    {ordered.map((agent, index) => {
      const curve = curves[index], parent = ordered.findIndex((a) => a.id === agent.parent_id)
      const junction = parent < 0 ? null : curves[parent].reduce((closest, point) =>
        Math.abs(point[0] - curve[0][0]) < Math.abs(closest[0] - curve[0][0]) ? point : closest)
      const selected = selectedId === agent.id || newest && latest === agent.id
      const stopped = agent.state === 'stopped' || agent.state === 'cancelled'
      const measured = agent.cost_usd !== null
      const radius = measured ? 0.025 + Math.sqrt(Number(agent.cost_usd)) * 0.65 : 0.018
      const color = selected ? '#eff8fa' : stopped ? '#888d9b' : agentColor(agent.id)
      return <group key={agent.id}>
        {junction && <Tube points={[junction, [curve[0][0] - 0.3, junction[1], curve[0][2]], curve[0]]}
          radius={0.028} color={agentColor(agent.id)} tier={tier} />}
        <Tube points={curve} radius={radius} color={color} tier={tier}
          dim={stopped && !selected} onClick={() => pick(agent)} />
        <mesh position={curve.at(-1)} onClick={(event) => { event.stopPropagation(); pick(agent) }}>
          <sphereGeometry args={[0.09 + radius, tier === 'full' ? 20 : 6, 10]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 1 : 0.3} roughness={stopped ? 0.9 : 0.1} />
        </mesh>
      </group>
    })}
  </group>
}
