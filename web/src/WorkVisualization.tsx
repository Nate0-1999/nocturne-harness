import { useEffect, useMemo, useState } from 'react'
import { Farm } from './Farm'
import { Roots } from './Roots'
import { useRackPlugin, useRackSelection, useRackSnapshot, type RackModuleId } from './rack'
import { VisualizationScene } from './VisualizationScene'
import { agentColor, buildChambers, LEAF, WIDTH, type DetailTier, type VisualizationSnapshot, type WorkAgent } from './visualization'
import './assets/work-visualization.css'
import { Button, Select } from './kit'

/* eslint-disable react-refresh/only-export-components -- the three modules share this feed hook and its toolbar */

export function useVisualization() {
  const { query } = useRackPlugin()
  const selected = useRackSelection()
  const asOf = selected?.as_of ?? null
  const [response, setResponse] = useState<{ data: VisualizationSnapshot; asOf: string | null } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true, pending = false
    const refresh = async () => {
      if (pending) return
      pending = true
      try {
        const value = await query.query({ resource: 'visualization', as_of: asOf ?? 'now' })
        if (active) { setResponse({ data: value.data as unknown as VisualizationSnapshot, asOf }); setError(null) }
      } catch { if (active) setError('The recorded visualization feed is unavailable.') }
      finally { pending = false }
    }
    void refresh()
    const timer = globalThis.setInterval(() => { void refresh() }, 2500)
    return () => { active = false; globalThis.clearInterval(timer) }
  }, [query, asOf])
  return { data: response?.data ?? null, loading: response?.asOf !== asOf, error }
}

export function VisualizationToolbar({ data, moduleId, tier, setTier }: {
  data: VisualizationSnapshot | null; moduleId: RackModuleId; tier: DetailTier; setTier: (tier: DetailTier) => void
}) {
  const { selection, events } = useRackPlugin()
  const selected = useRackSelection()
  const timeline = data?.timeline ?? []
  const oldest = data?.agents.filter((agent) => agent.waiting_since !== null)
    .sort((a, b) => a.waiting_since!.localeCompare(b.waiting_since!))[0]
  const timeOrdered = selected?.time_order ?? false
  useEffect(() => {
    if (!timeOrdered || !oldest || selected?.id === oldest.id) return
    void events.dispatch({ type: 'thread.select', thread_id: oldest.thread_id }).then(() => {
      selection.select({ kind: 'agent', id: oldest.id, thread_id: oldest.thread_id, time_order: true,
        as_of: selected?.as_of ?? null })
    })
  }, [events, selection, oldest, selected?.id, selected?.as_of, timeOrdered])
  const index = selected?.as_of ? Math.max(0, timeline.indexOf(selected.as_of)) : Math.max(0, timeline.length - 1)
  const scrub = (as_of: string | null) => selection.select({ ...(selected ?? { kind: 'module', id: moduleId }), as_of })
  return <div className="work-viz__toolbar">
    <label>Detail<Select aria-label="Visualization detail" data-tooltip-detail="Full draws everything; Efficient is lighter on the machine." value={tier} onChange={(event) => setTier(event.target.value as DetailTier)}>
      <option value="full">Full</option><option value="efficient">Efficient</option>
    </Select></label>
    <Button type="button" data-tooltip-detail="Order the scene by time so the newest work stands out." aria-pressed={timeOrdered} onClick={() => selection.select({ ...(selected ?? { kind: 'module', id: moduleId }), time_order: !timeOrdered })}>Time order</Button>
    <label className="work-viz__scrub">History<input aria-label="Visualization history" data-tooltip-detail="Scrub the scene back to an earlier moment." type="range" min="0" max={Math.max(0, timeline.length - 1)}
      value={index} disabled={!timeline.length} onChange={(event) => scrub(timeline[Number(event.target.value)])} /></label>
    <Button type="button" data-tooltip-detail="Return to the present." aria-pressed={!selected?.as_of} onClick={() => scrub(null)}>Live</Button>
    <time>{data ? new Date(data.as_of).toLocaleTimeString() : 'Waiting for first observation'}</time>
  </div>
}

export function WorkVisualization({ initialView }: { initialView: 'farm' | 'roots' }) {
  const { data: observation, loading, error } = useVisualization()
  const data = loading ? null : observation
  const { selection, events } = useRackPlugin()
  const rack = useRackSnapshot()
  const selected = useRackSelection()
  const [view, setView] = useState(initialView)
  const [tier, setTier] = useState<DetailTier>('full')
  const [projectRoot, setProjectRoot] = useState<string | null>(null)
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  useEffect(() => { void events.dispatch({ type: 'rack.scope.get', module_id: initialView }).then(setScope) }, [events, initialView])
  const agents = (data?.agents ?? []).filter((agent) => scope === 'GLOBAL' || agent.thread_id === rack.selectedThreadId)
  // A top-level agent enters as a ringed root; a forked one leaves its parent as a limb.
  const forked = agents.filter((agent) => agents.some((other) => other.id === agent.parent_id)).length
  const selectedMemory = selected?.kind === 'memory' ? data?.palace?.nodes.find((node) => node.memory.memory_id === selected.id)?.memory : undefined
  const selectedId = selected?.kind === 'agent' || selected?.kind === 'thread' ? selected.id : selectedMemory?.origin_thread_id ?? null
  const focused = agents.find((agent) => agent.id === selectedId)
  const project = data?.projects.find((candidate) => candidate.root === (projectRoot ?? focused?.root)) ?? data?.projects[0]
  const chambers = useMemo(() => project ? buildChambers(project) : [], [project])
  const reach = Math.max(0, ...chambers.map((c) => Math.hypot(c.position[0], c.position[1]) + c.radius))
  const distance = view === 'farm' ? Math.max(8, reach * 1.6 + 3.5) : 12
  const width = view === 'farm' ? (reach + 1) * 2 : 20
  const pick = (agent: WorkAgent) => {
    setProjectRoot(agent.root)
    void events.dispatch({ type: 'thread.select', thread_id: agent.thread_id }).then(() => {
      selection.select({ kind: 'agent', id: agent.id, thread_id: agent.thread_id, as_of: selected?.as_of ?? null, time_order: false })
    })
  }
  return <section className="work-viz" data-testid={`${initialView}-module`} data-tier={tier} data-view={view}
    data-sheet={new URLSearchParams(globalThis.location.search).has('sheet') || undefined}>
    <header className="work-viz__header"><div><small>Work, made visible · {scope === 'GLOBAL' ? 'All projects' : rack.attunement?.name ?? 'Unattuned'}</small>
      <h1>{view === 'farm' ? 'The Farm' : 'The Roots'}</h1></div>
      <nav aria-label="Work visualization"><button aria-pressed={view === 'farm'} onClick={() => setView('farm')}>Farm</button><button aria-pressed={view === 'roots'} onClick={() => setView('roots')}>Roots</button></nav>
    </header>
    <VisualizationToolbar data={observation} moduleId={initialView} tier={tier} setTier={setTier} />
    {project && <label className="work-viz__project">Project<select aria-label="Visualized project" value={project.root} onChange={(event) => setProjectRoot(event.target.value)}>
      {data!.projects.map((p) => <option key={p.root}>{p.root}</option>)}
    </select></label>}
    <div className="work-viz__viewport">
      {data && project && <VisualizationScene tier={tier} distance={distance} width={width} label={view === 'farm' ? 'Directory chambers and live agents' : 'Agent roots: thickness is dollars flowing, spacing is time between events'}>
        {view === 'farm' ? <Farm project={project} agents={agents} selectedId={selectedId} selectedPath={selected?.kind === 'path' ? selected.id : null} tier={tier} asOf={data.as_of} pick={pick}
          pickPath={(path) => selection.select({ kind: 'path', id: `${project.root}${path === '.' ? '' : '/' + path}`, as_of: selected?.as_of ?? null })} />
          : <Roots data={data} agents={agents} selectedId={selectedId} tier={tier} pick={pick} newest={selected?.time_order ?? false} />}
      </VisualizationScene>}
      <aside className="work-viz__readout"><strong>{view === 'farm' ? `${chambers.length} chambers` : `${agents.length - forked} roots · ${forked} forked limbs`}</strong>
        <span>{view === 'farm' ? `${project?.nodes.filter((node) => node.kind !== 'directory').length ?? 0} file cells`
          : `${agents.reduce((count, agent) => count + (agent.touched_files?.length ?? 0), 0)} touched-file capillaries`} · {agents.length} agents</span>
        {view === 'farm' ? <span>Drag or Ctrl+arrows to orbit · scroll or +/− to zoom · pick an ant</span> : <>
          <span title={`radius = hair + ${WIDTH}·√$ (a fork divides its cross-section by dollars; unpriced = hair; a parent whose trail rolled up less than a fork's price is drawn at its own spend plus its forks' prices) · across = ln(1 + gap / 0.5 s)^1.2 (a longer gap is always a longer bare stretch) · leaf = ${LEAF}·(compressed wait)^0.75 (or its own spend window, if longer), so a longer wait is always a longer reach`}>
            width = dollars · across = time between events · blue = live · pink = a branch leaving · matte = stopped</span></>}
        {focused && <span style={{ color: agentColor(focused.id) }}>{focused.label} · {focused.location}</span>}
      </aside>
      {(!data || error) && <p className="work-viz__notice" role="status">{error ?? 'Recording the first real state…'}</p>}
    </div>
    <footer className="work-viz__foot">{data && <>Recorded since {new Date(data.recorded_since).toLocaleString()} · {data.timeline.length} states · {data.live ? 'Live observation' : 'Recorded history'}</>}
      {view === 'roots' && <span>Trunk = project, its agents' roots fused · ringed source = a top-level agent, entering at the left edge in its own lane (the finest hair until it started, then it swells and converges at a shallow angle, fusing into the trunk once their bodies come within one diameter; its dollars move into the trunk as it fuses, so each is drawn once) · branch = turn · twig = tool call · capillary = recorded file touch · limb = forked agent, leaving where it started · a turn (a call, within its turn) leaves the latest earlier one that followed a longer wait than its own, so a burst sub-forks · spacing along every root and branch = time between its events (bare chrome = waiting); finer branches run on a finer time scale (×0.82 per level, a forked limb ×0.6) · a leaf reaches as long as the compressed wait for the agent's next event (a bare leaf: or its own spend window, if longer) · side, angle, curl and meander come from each branch's seed; forked limbs fan on the side away from their parent, and a heavy turn leaves away from the other roots · width = the dollars still to flow through it, on one fixed scale (radius = hair + {WIDTH}·√$; a branch carries the spend recorded in its window, a forked limb its own price), so at a junction the branches' cross-sections above the hair width add up to what the parent loses; four stretches are shaped, not priced: a junction's flare, a root's swell from its hair, a leaf too short for its dollars (never thicker than a twelfth of its length), and every tip, which closes to a point past its last recorded moment (a live tip too: still growing) · blue = live work (full while running, dimmer while waiting) · red-pink = a fine branch leaving: always marked, stronger and reaching further the larger its share of its parent's dollars, and carried into the fine branches that leave within that reach; a thicker branch's fork shows as a coral glow one diameter long on its parent's side; a stopped agent carries none but its fork on a live parent · depth = time · matte = stopped (pale on the sheet, deep blue on the stage; a stopped limb keeps its chrome for one diameter where it leaves a live parent)</span>}
      {view === 'farm' && <span>Chamber = folder · size = files it holds · dim = empty · link = parent folder, width = files beneath · cell = file, size = bytes · lit = touched by an agent, brighter = more recent, flash = new touch · ant = agent in its current folder · walk = location changed</span>}
      {project?.errors.map((item) => <span key={item.path}>Cannot read {item.path}: {item.error}</span>)}
      {data?.errors.map((item) => <span key={item.feed}>{item.feed} feed unavailable</span>)}
    </footer>
    <details className="work-viz__data" open><summary>Agents and measured work</summary>
      <table><thead><tr><th>Agent</th><th>Where</th><th>State</th><th>Spend</th></tr></thead><tbody>
        {agents.map((agent) => <tr key={agent.id} data-selected={agent.id === selectedId || undefined}>
          <td><button onClick={() => pick(agent)} title={agent.label} style={{ color: agentColor(agent.id) }}>{agent.label}</button></td><td title={agent.location}>{agent.location.startsWith(agent.root) ? `.${agent.location.slice(agent.root.length)}` : agent.location}</td><td>{agent.state}</td>
          <td>{agent.cost_usd === null ? 'Not yet priced' : `$${Number(agent.cost_usd).toFixed(5)}`}</td>
        </tr>)}
      </tbody></table>
    </details>
    {project && <details className="work-viz__data"><summary>Complete directory tree · {project.nodes.length} entries</summary>
      <ul>{project.nodes.map((node) => <li key={node.path}><button onClick={() => selection.select({ kind: 'path', id: `${project.root}${node.path === '.' ? '' : '/' + node.path}`, as_of: selected?.as_of ?? null })}>{node.path}</button> · {node.kind}</li>)}</ul>
    </details>}
  </section>
}
