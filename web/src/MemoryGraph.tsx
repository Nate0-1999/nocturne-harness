import { useCallback, useEffect, useState } from 'react'
import { useRackPlugin, useRackSnapshot } from './rack'
import {
  memoryGraphRequestKey,
  memoryGraphRequestIsQueryable,
  memoryGraphSnapshotForRequest,
  reconcileMemoryGraphSelection,
  type KeyedMemoryGraphSnapshot,
} from './memoryGraphSelection'
import { declutterGraphLabels } from './memoryGraphLabels'
import { SelectedMemoryPanel } from './MemoryPanel'
import { Button } from './kit'
import './assets/honest-display.css'

type Node = { memory: { memory_id: string; label: string; body: string; kind: string; status: string; pin: boolean; revision: number; project_key: string | null; stats: { injections?: number } }; in_current_context: boolean; revisions: unknown[] }
type Edge = { kind: string; from_memory_id: string; to_memory_id: string; similarity?: string; edge_type?: string }
type Snapshot = { as_of: string; graph_edge_sim: number; nodes: Node[]; edges: Edge[]; omitted_memory_ids: string[] }
const PARAMETER_LABELS: Record<string, string> = {
  tau: 'Minimum match', top_k: 'Display limit', memory_context_share: 'Memory share',
  half_life_time_days: 'Recent-use fade (days)', half_life_hist_days: 'Past-choice fade (days)',
  sem: 'Meaning', kw: 'Keywords', time: 'Recency', proj: 'Project', freq: 'Use count', hist: 'Past choices',
}

export function MemoryGraph() {
  const { query, events, selection } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  const [loadedSnapshot, setLoadedSnapshot] = useState<KeyedMemoryGraphSnapshot<Snapshot> | null>(null)
  const [selected, setSelected] = useState<Node | null>(null)
  const [search, setSearch] = useState('')
  const [restoring, setRestoring] = useState<string | null>(null)
  const [parameters, setParameters] = useState<Record<string, unknown> | null>(null)
  const [failure, setFailure] = useState<{ requestKey: string; message: string } | null>(null)
  const threadId = scope === 'ATTUNED' ? rack.selectedThreadId : null
  const requestKey = memoryGraphRequestKey(scope, threadId)
  const requestIsQueryable = memoryGraphRequestIsQueryable(scope, threadId)
  const snapshot = memoryGraphSnapshotForRequest(loadedSnapshot, requestKey)
  const visibleFailure = failure?.requestKey === requestKey ? failure.message : null
  const [aspect, setAspect] = useState(2)
  const measure = useCallback((element: HTMLDivElement | null) => {
    if (element === null) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setAspect(width / height)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'memory_graph' }).then(setScope)
    void query.query({ resource: 'scorer_console', as_of: 'now' }).then((result) => {
      const data = result.data as { active_version: string; configurations: { version: string; values: Record<string, unknown> }[] }
      setParameters(data.configurations.find((config) => config.version === data.active_version)?.values ?? null)
    }).catch(() => setParameters(null))
  }, [events, query])
  useEffect(() => {
    if (!requestIsQueryable) {
      return
    }
    let active = true
    let pending = false
    const refresh = () => {
      if (pending) return
      pending = true
      void query.query({
        resource: 'memory_graph',
        as_of: 'now',
        thread_id: threadId ?? undefined,
      })
        .then((result) => {
          if (!active) return
          const next = result.data as unknown as Snapshot
          setLoadedSnapshot({ requestKey, data: next })
          setSelected((current) => reconcileMemoryGraphSelection(current, next.nodes))
          setFailure(null)
        })
        .catch(() => {
          if (active) {
            setFailure({ requestKey, message: 'The live memory graph is unavailable.' })
          }
        }).finally(() => { pending = false })
    }
    refresh()
    const timer = globalThis.setInterval(refresh, 5000)
    return () => { active = false; globalThis.clearInterval(timer) }
  }, [query, requestIsQueryable, requestKey, threadId])

  function inspectNode(node: Node) {
    setSelected(node)
    selection.select({ kind: 'memory', id: node.memory.memory_id })
  }

  const nodes = snapshot?.nodes ?? []
  // M4VW: the drawing holds active memories only; a deleted one is still found by name and restored.
  const drawn = nodes.filter((node) => node.memory.status === 'active')
  const matches = search.trim() ? nodes.filter((node) => node.memory.label.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())) : []
  // M4VW: the grid takes the canvas's shape (18 across, 25 down per node) and is scaled to fit it.
  const columns = Math.max(1, Math.min(drawn.length, Math.round(Math.sqrt(drawn.length * aspect * 25 / 18))))
  const positions = new Map(drawn.map((node, index) => [node.memory.memory_id, {
    x: 14 + (index % columns) * 18, y: 18 + Math.floor(index / columns) * 25,
  }]))
  const labels = new Map(declutterGraphLabels(drawn.map((node) => {
    const position = positions.get(node.memory.memory_id)!
    return {
      id: node.memory.memory_id,
      label: node.memory.label,
      x: position.x,
      y: position.y,
      radius: 3 + Math.min(Number(node.memory.stats.injections ?? 0), 12) / 8,
      selected: selected?.memory.memory_id === node.memory.memory_id,
      current: node.in_current_context,
      pinned: node.memory.pin,
      injections: Number(node.memory.stats.injections ?? 0),
    }
  })).map((label) => [label.id, label]))
  const viewWidth = 10 + columns * 18
  const viewHeight = 18 + Math.ceil(drawn.length / columns) * 25
  return <section className="instrument instrument--graph">
    <header><h1>Memory Graph</h1></header>
    <label className="graph-search">Find a memory by name
      <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Memory name" />
    </label>
    {search.trim() && <ul className="graph-search-results" aria-label="Matching memories">
      {matches.length === 0 ? <li>No matching memories.</li> : matches.map((node) => <li key={node.memory.memory_id}>
        <Button type="button" aria-pressed={selected?.memory.memory_id === node.memory.memory_id} onClick={() => inspectNode(node)}>{node.memory.label}{node.memory.status === 'tombstoned' ? ' · deleted' : node.memory.status === 'active' ? '' : ` · ${node.memory.status}`}</Button>
      </li>)}
    </ul>}
    {!requestIsQueryable ? <p role="status">{rack.attunement?.kind === 'stack' ? `${rack.attunement.name} graph is not available yet.` : 'No thread is attuned.'}</p> : visibleFailure !== null ? <p role="alert">{visibleFailure}</p> : snapshot === null ? <p role="status">Loading memory graph…</p> : <div className="graph-stage">
      <div className="graph-canvas" ref={measure}><svg viewBox={`0 0 ${viewWidth} ${viewHeight}`} role="img" aria-label={`${drawn.length} memories and ${snapshot?.edges.length ?? 0} relationships`}>
        {(snapshot?.edges ?? []).map((edge, index) => { const a = positions.get(edge.from_memory_id); const b = positions.get(edge.to_memory_id); return a && b ? <line key={`${edge.kind}-${index}`} x1={a.x} y1={a.y} x2={b.x + (a === b ? 2 : 0)} y2={b.y + (a === b ? 2 : 0)} data-kind={edge.kind} /> : null })}
        {drawn.map((node) => { const p = positions.get(node.memory.memory_id)!; const r = 3 + Math.min(Number(node.memory.stats.injections ?? 0), 12) / 8; const label = labels.get(node.memory.memory_id); return <g key={node.memory.memory_id}>
          <g className="graph-node" data-status={node.memory.status} data-current={node.in_current_context || undefined} onClick={() => inspectNode(node)} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter') inspectNode(node) }}>
            <title>{node.memory.label}</title>
            {node.memory.pin && <circle className="graph-pin" cx={p.x} cy={p.y} r={r + 2} />}
            <circle cx={p.x} cy={p.y} r={r} data-kind={node.memory.kind} />
          </g>
          <text className="graph-node-label" x={label?.x ?? p.x} y={label?.y ?? p.y} data-priority={label?.priority} visibility={label === undefined ? 'hidden' : undefined}>{label?.text ?? ''}</text>
        </g>})}
      </svg></div>
      <aside>{selected === null ? <p>Select a node to inspect its complete memory.</p> : <>
        {selected.memory.status === 'tombstoned' ? <div data-testid="graph-deleted-memory">
          <p><strong>{selected.memory.label}</strong> · deleted</p>
          <p>{selected.memory.body}</p>
          <Button action="restore" type="button" data-testid="memory-restore" data-tooltip-detail="Make this memory active again."
            disabled={restoring === selected.memory.memory_id}
            onClick={() => { setRestoring(selected.memory.memory_id); void events.dispatch({ type: 'memory.restore', memory_id: selected.memory.memory_id, expected_revision: selected.memory.revision }).finally(() => setRestoring(null)) }}>Restore</Button>
        </div> : <SelectedMemoryPanel memoryId={selected.memory.memory_id} />}
        <h3>Relationships</h3>
        <ul>{snapshot?.edges.filter((edge) => edge.from_memory_id === selected.memory.memory_id || edge.to_memory_id === selected.memory.memory_id).map((edge, index) => <li key={index}>
          {edge.edge_type ?? edge.kind} · {nodes.find((node) => node.memory.memory_id === (edge.from_memory_id === selected.memory.memory_id ? edge.to_memory_id : edge.from_memory_id))?.memory.label ?? 'Unavailable memory'}
        </li>)}</ul>
      </>}</aside>
    </div>}
    <details><summary>Scoring parameters</summary>
      {parameters === null ? <p>Scoring parameters are unavailable.</p> : <dl>
        {Object.entries(parameters).flatMap<[string, unknown]>(([name, value]) =>
          typeof value === 'object' && value !== null ? Object.entries(value) : [[name, value]],
        ).map(([name, value]) => <div key={name}><dt>{PARAMETER_LABELS[name] ?? name.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}
      </dl>}
      <p>Use the Injection Console to simulate changes and force a new set of values.</p>
    </details>
  </section>
}
