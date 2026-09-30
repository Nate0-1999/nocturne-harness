import { useEffect, useMemo, useState } from 'react'
import { Farm } from './Farm'
import { Roots } from './Roots'
import { useRackPlugin, useRackSelection, useRackSnapshot, type RackModuleId } from './rack'
import { VisualizationScene } from './VisualizationScene'
import { agentColor, parentPath, LEAF, WIDTH, type DetailTier, type VisualizationSnapshot, type WorkAgent } from './visualization'
import { useFarmLayout } from './useFarmLayout'
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
    // A recorded moment never changes, so it is read once; only the present is polled.
    const timer = asOf === null ? globalThis.setInterval(() => { void refresh() }, 2500) : undefined
    return () => { active = false; globalThis.clearInterval(timer) }
  }, [query, asOf])
  // The last state read stays drawn while the next one loads (F155: a scrub never blanks the scene).
  return { data: response?.data ?? null, loading: response?.asOf !== asOf, error }
}

export function VisualizationToolbar({ data, loading, moduleId, tier, setTier }: {
  data: VisualizationSnapshot | null; loading: boolean; moduleId: RackModuleId; tier: DetailTier; setTier: (tier: DetailTier) => void
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
    {loading && data && <span role="status">Loading {selected?.as_of ? new Date(selected.as_of).toLocaleTimeString() : 'the present'}…</span>}
  </div>
}

export function WorkVisualization({ initialView }: { initialView: 'farm' | 'roots' }) {
  const { data, loading, error } = useVisualization()
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
  const [folder, setFolder] = useState({ root: '', path: '.' })
  const [directoryOpen, setDirectoryOpen] = useState(false)
  const [directoryPage, setDirectoryPage] = useState(0)
  const focus = folder.root === project?.root ? folder.path : '.'
  const layout = useFarmLayout(view === 'farm' ? project : undefined, focus)
  const chambers = layout?.chambers ?? []
  const farmProject = useMemo(() => project && ({ ...project,
    root: `${project.root}${focus === '.' ? '' : `/${focus}`}` }), [project, focus])
  const openFolder = (path: string) => {
    setFolder({ root: project!.root, path }); setDirectoryPage(0)
  }
  const expand = (path: string) => {
    openFolder(path === '.' ? focus : `${focus === '.' ? '' : `${focus}/`}${path}`)
    setDirectoryOpen(true)
  }
  const directoryEntries = directoryOpen ? project?.nodes.filter((node) => node.path !== '.' && parentPath(node.path) === focus) ?? [] : []
  const reach = Math.max(0, ...chambers.map((c) => Math.hypot(c.position[0], c.position[1]) + c.radius))
  const distance = view === 'farm' ? Math.max(8, reach * 2.4 + 3.5) : 12
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
      <nav aria-label="Work visualization"><Button variant="bare" aria-pressed={view === 'farm'} onClick={() => setView('farm')}>Farm</Button><Button variant="bare" aria-pressed={view === 'roots'} onClick={() => setView('roots')}>Roots</Button></nav>
    </header>
    <VisualizationToolbar data={data} loading={loading} moduleId={initialView} tier={tier} setTier={setTier} />
    {project && <label className="work-viz__project">Project<Select aria-label="Visualized project" value={project.root} onChange={(event) => setProjectRoot(event.target.value)}>
      {data!.projects.map((p) => <option key={p.root}>{p.root}</option>)}
    </Select></label>}
    {view === 'farm' && project && <div className="work-viz__toolbar">
      <Button action="up" iconOnly disabled={focus === '.'} onClick={() => openFolder(parentPath(focus))}>Up one folder</Button>
      <span>{focus} · {layout ? `showing ${layout.depth} levels` : 'Laying out the tree…'}</span>
      <Button action="open" iconOnly onClick={() => setDirectoryOpen(!directoryOpen)} aria-expanded={directoryOpen}>Browse folder</Button>
    </div>}
    {view === 'farm' && directoryOpen && <div className="work-viz__data">
      <span>{directoryEntries.length} entries in {focus} · {directoryPage * 100 + 1}–{Math.min(directoryEntries.length, (directoryPage + 1) * 100)}</span>
      <Button action="back" iconOnly disabled={!directoryPage} onClick={() => setDirectoryPage(directoryPage - 1)}>Previous entries</Button>
      <Button action="next" iconOnly disabled={(directoryPage + 1) * 100 >= directoryEntries.length} onClick={() => setDirectoryPage(directoryPage + 1)}>Next entries</Button>
      <ul>{directoryEntries.slice(directoryPage * 100, (directoryPage + 1) * 100).map((node) => <li key={node.path}>
        <Button variant="bare" action="open" onClick={() => node.kind === 'directory' ? openFolder(node.path)
          : selection.select({ kind: 'path', id: `${project!.root}/${node.path}`, as_of: selected?.as_of ?? null })}>{node.path}</Button> · {node.kind}
      </li>)}</ul>
    </div>}
    <div className="work-viz__viewport">
      {data && project && <VisualizationScene tier={tier} distance={distance} width={width} label={view === 'farm' ? 'Directory chambers and live agents' : 'Agent roots: thickness is dollars flowing, spacing is time between events'}>
        {view === 'farm' ? layout && <Farm project={farmProject!} chambers={chambers} expand={expand} agents={agents} selectedId={selectedId} selectedPath={selected?.kind === 'path' ? selected.id : null} tier={tier} asOf={data.as_of} pick={pick}
          pickPath={(path) => selection.select({ kind: 'path', id: `${farmProject!.root}${path === '.' ? '' : '/' + path}`, as_of: selected?.as_of ?? null })} />
          : <Roots data={data} agents={agents} selectedId={selectedId} tier={tier} pick={pick} newest={selected?.time_order ?? false} />}
      </VisualizationScene>}
      <aside className="work-viz__readout"><strong>{view === 'farm' ? `${chambers.length} chambers` : `${agents.length - forked} roots · ${forked} forked limbs`}</strong>
        <span>{view === 'farm' ? `${layout?.files ?? 0} files · ${chambers.reduce((sum, chamber) => sum + chamber.hiddenFiles, 0)} in counted chambers`
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
      {view === 'farm' && <span>Chamber = folder · counts = collapsed contents, click to open · size = files it holds · dim = empty · link = parent folder, width = files beneath · cell = file, size = bytes · lit = touched by an agent · ant = agent in its current folder or its counted ancestor · walk = location changed</span>}
      {project?.errors.map((item) => <span key={item.path}>Cannot read {item.path}: {item.error}</span>)}
      {data?.errors.map((item) => <span key={item.feed}>{item.feed} feed unavailable</span>)}
    </footer>
    <details className="work-viz__data" open><summary>Agents and measured work</summary>
      <table><thead><tr><th>Agent</th><th>Where</th><th>State</th><th>Spend</th></tr></thead><tbody>
        {agents.map((agent) => <tr key={agent.id} data-selected={agent.id === selectedId || undefined}>
          <td><Button variant="bare" action="open" onClick={() => pick(agent)} title={agent.label} style={{ color: agentColor(agent.id) }}>{agent.label}</Button></td><td title={agent.location}>{agent.location.startsWith(agent.root) ? `.${agent.location.slice(agent.root.length)}` : agent.location}</td><td>{agent.state}</td>
          <td>{agent.cost_usd === null ? 'Not yet priced' : `$${Number(agent.cost_usd).toFixed(5)}`}</td>
        </tr>)}
      </tbody></table>
    </details>
    {view !== 'farm' && project && <details className="work-viz__data"><summary>Complete directory tree · {project.nodes.length} entries</summary>
      <ul>{project.nodes.map((node) => <li key={node.path}><Button variant="bare" action="open" onClick={() => selection.select({ kind: 'path', id: `${project.root}${node.path === '.' ? '' : '/' + node.path}`, as_of: selected?.as_of ?? null })}>{node.path}</Button> · {node.kind}</li>)}</ul>
    </details>}
  </section>
}
