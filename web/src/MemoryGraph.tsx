import { useEffect, useState } from 'react'
import { useRackPlugin, useRackSnapshot } from './rack'
import {
  memoryGraphRequestKey,
  memoryGraphRequestIsQueryable,
  memoryGraphSnapshotForRequest,
  reconcileMemoryGraphSelection,
  type KeyedMemoryGraphSnapshot,
} from './memoryGraphSelection'
import { declutterGraphLabels } from './memoryGraphLabels'
import './assets/honest-display.css'

type Node = { memory: { memory_id: string; label: string; body: string; kind: string; status: string; pin: boolean; revision: number; project_key: string | null; stats: { injections?: number } }; in_current_context: boolean; revisions: unknown[] }
type Edge = { kind: string; from_memory_id: string; to_memory_id: string; similarity?: string; edge_type?: string }
type Snapshot = { as_of: string; graph_edge_sim: number; nodes: Node[]; edges: Edge[]; omitted_memory_ids: string[] }

export function MemoryGraph() {
  const { query, events, selection } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  const [loadedSnapshot, setLoadedSnapshot] = useState<KeyedMemoryGraphSnapshot<Snapshot> | null>(null)
  const [selected, setSelected] = useState<Node | null>(null)
  const [failure, setFailure] = useState<{ requestKey: string; message: string } | null>(null)
  const threadId = scope === 'ATTUNED' ? rack.selectedThreadId : null
  const requestKey = memoryGraphRequestKey(scope, threadId)
  const requestIsQueryable = memoryGraphRequestIsQueryable(scope, threadId)
  const snapshot = memoryGraphSnapshotForRequest(loadedSnapshot, requestKey)
  const visibleFailure = failure?.requestKey === requestKey ? failure.message : null

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'memory_graph' }).then(setScope)
  }, [events])
  useEffect(() => {
    if (!requestIsQueryable) {
      return
    }
    let active = true
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
    })
    return () => { active = false }
  }, [query, requestIsQueryable, requestKey, threadId])

  function inspectNode(node: Node) {
    setSelected(node)
    selection.select({ kind: 'memory', id: node.memory.memory_id })
  }

  const nodes = snapshot?.nodes ?? []
  const positions = new Map(nodes.map((node, index) => [node.memory.memory_id, {
    x: 14 + (index % 5) * 18, y: 18 + Math.floor(index / 5) * 25,
  }]))
  const labels = new Map(declutterGraphLabels(nodes.map((node) => {
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
  return <section className="instrument instrument--graph">
    <header><h1>Memory Graph</h1></header>
    {!requestIsQueryable ? <p role="status">{rack.attunement?.kind === 'stack' ? `${rack.attunement.name} graph is not available yet.` : 'No thread is attuned.'}</p> : visibleFailure !== null ? <p role="alert">{visibleFailure}</p> : snapshot === null ? <p role="status">Loading memory graph…</p> : <div className="graph-stage">
      <svg viewBox="0 0 100 76" role="img" aria-label={`${nodes.length} memories and ${snapshot?.edges.length ?? 0} relationships`}>
        {(snapshot?.edges ?? []).map((edge, index) => { const a = positions.get(edge.from_memory_id); const b = positions.get(edge.to_memory_id); return a && b ? <line key={`${edge.kind}-${index}`} x1={a.x} y1={a.y} x2={b.x + (a === b ? 2 : 0)} y2={b.y + (a === b ? 2 : 0)} data-kind={edge.kind} /> : null })}
        {nodes.map((node) => { const p = positions.get(node.memory.memory_id)!; const r = 3 + Math.min(Number(node.memory.stats.injections ?? 0), 12) / 8; const label = labels.get(node.memory.memory_id); return <g key={node.memory.memory_id}>
          <g className="graph-node" data-status={node.memory.status} data-current={node.in_current_context || undefined} onClick={() => inspectNode(node)} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter') inspectNode(node) }}>
            <title>{node.memory.label}</title>
            {node.memory.pin && <circle className="graph-pin" cx={p.x} cy={p.y} r={r + 2} />}
            <circle cx={p.x} cy={p.y} r={r} data-kind={node.memory.kind} />
            {node.memory.status === 'tombstoned' && <line x1={p.x-r} y1={p.y-r} x2={p.x+r} y2={p.y+r} />}
          </g>
          <text className="graph-node-label" x={label?.x ?? p.x} y={label?.y ?? p.y} data-priority={label?.priority} visibility={label === undefined ? 'hidden' : undefined}>{label?.text ?? ''}</text>
        </g>})}
      </svg>
      <aside>{selected === null ? <p>Select a node to inspect its complete memory.</p> : <><small>{selected.memory.kind} · revision {selected.memory.revision}</small><h2>{selected.memory.label}</h2><p>Project · {selected.memory.project_key ?? 'Palace-wide'}</p><p>{selected.memory.body}</p><p>{selected.revisions.length} recorded revisions</p><em>Edit in Memory Palace</em></>}</aside>
    </div>}
  </section>
}
