import { useEffect, useMemo, useState } from 'react'
import { Farm } from './Farm'
import { Roots } from './Roots'
import { useRackPlugin, useRackSelection, useRackSnapshot, type RackModuleId } from './rack'
import { VisualizationScene } from './VisualizationScene'
import { agentColor, buildChambers, type DetailTier, type VisualizationSnapshot, type WorkAgent } from './visualization'
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
  const selectedMemory = selected?.kind === 'memory' ? data?.palace?.nodes.find((node) => node.memory.memory_id === selected.id)?.memory : undefined
  const selectedId = selected?.kind === 'agent' || selected?.kind === 'thread' ? selected.id : selectedMemory?.origin_thread_id ?? null
  const focused = agents.find((agent) => agent.id === selectedId)
  const project = data?.projects.find((candidate) => candidate.root === (projectRoot ?? focused?.root)) ?? data?.projects[0]
  const chambers = useMemo(() => project ? buildChambers(project) : [], [project])
  const distance = view === 'farm' ? Math.max(15, ...chambers.map((c) => (Math.abs(c.position[1]) + 2) * 3)) : Math.max(12, agents.length * 2.8)
  const width = view === 'farm' ? Math.max(10, ...chambers.map((c) => (Math.abs(c.position[0]) + 2) * 2)) : 22
  const pick = (agent: WorkAgent) => {
    setProjectRoot(agent.root)
    void events.dispatch({ type: 'thread.select', thread_id: agent.thread_id }).then(() => {
      selection.select({ kind: 'agent', id: agent.id, thread_id: agent.thread_id, as_of: selected?.as_of ?? null, time_order: false })
    })
  }
  return <section className="work-viz" data-testid={`${initialView}-module`} data-tier={tier} data-view={view}>
    <header className="work-viz__header"><div><small>Work, made visible · {scope === 'GLOBAL' ? 'All projects' : rack.attunement?.name ?? 'Unattuned'}</small>
      <h1>{view === 'farm' ? 'The Farm' : 'The Roots'}</h1></div>
      <nav aria-label="Work visualization"><button aria-pressed={view === 'farm'} onClick={() => setView('farm')}>Farm</button><button aria-pressed={view === 'roots'} onClick={() => setView('roots')}>Roots</button></nav>
    </header>
    <VisualizationToolbar data={observation} moduleId={initialView} tier={tier} setTier={setTier} />
    {project && <label className="work-viz__project">Project<select aria-label="Visualized project" value={project.root} onChange={(event) => setProjectRoot(event.target.value)}>
      {data!.projects.map((p) => <option key={p.root}>{p.root}</option>)}
    </select></label>}
    <div className="work-viz__viewport">
      {data && project && <VisualizationScene tier={tier} distance={distance} width={width} label={view === 'farm' ? 'Directory chambers and live agents' : 'Agent roots: thickness is measured spend, depth is time'}>
        {view === 'farm' ? <Farm project={project} agents={agents} selectedId={selectedId} selectedPath={selected?.kind === 'path' ? selected.id : null} tier={tier} pick={pick}
          pickPath={(path) => selection.select({ kind: 'path', id: `${project.root}${path === '.' ? '' : '/' + path}`, as_of: selected?.as_of ?? null })} />
          : <Roots data={data} agents={agents} selectedId={selectedId} tier={tier} pick={pick} newest={selected?.time_order ?? false} />}
      </VisualizationScene>}
      <aside className="work-viz__readout"><strong>{view === 'farm' ? `${chambers.length} chambers` : `${agents.length} roots`}</strong>
        <span>{project?.nodes.filter((node) => node.kind !== 'directory').length ?? 0} file cells · {agents.length} agents</span>
        <span>{view === 'farm' ? 'Drag or Ctrl+arrows to orbit · scroll or +/− to zoom · pick an ant' : 'Width = dollars · depth = time · junction = fork · dry = stopped'}</span>
        {focused && <span style={{ color: agentColor(focused.id) }}>{focused.label} · {focused.location}</span>}
      </aside>
      {(!data || error) && <p className="work-viz__notice" role="status">{error ?? 'Recording the first real state…'}</p>}
    </div>
    <footer className="work-viz__foot">{data && <>Recorded since {new Date(data.recorded_since).toLocaleString()} · {data.timeline.length} states · {data.live ? 'Live observation' : 'Recorded history'}</>}
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
