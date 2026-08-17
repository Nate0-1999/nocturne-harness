import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  layoutRecipeGraph,
  parseRecipeGraphSnapshot,
  type RecipeGraphNode,
  type RecipeGraphSnapshot,
  type RecipeNodePosition,
} from './recipeGraph'
import { useRackPlugin, useRackSelection } from './rack'
import './assets/recipe.css'

const POLL_INTERVAL_MS = 2_000

export function RecipeModule() {
  const { query, selection } = useRackPlugin()
  const rackSelection = useRackSelection()
  const [snapshot, setSnapshot] = useState<RecipeGraphSnapshot | null>(null)
  const [inspectedNodeId, setInspectedNodeId] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const result = await query.query({ resource: 'recipe_graph', as_of: 'now' })
      if (result.status !== 'live' || result.data === null) {
        throw new Error('current recipe unavailable')
      }
      const next = parseRecipeGraphSnapshot(result.data)
      setSnapshot(next)
      setInspectedNodeId((current) => (
        current !== null && next.nodes.some((node) => node.node_id === current)
          ? current
          : null
      ))
      setFailure(null)
    } catch {
      setFailure('The live recipe is unavailable.')
    }
  }, [query])

  useEffect(() => {
    const initial = globalThis.setTimeout(() => void load(), 0)
    const timer = globalThis.setInterval(() => void load(), POLL_INTERVAL_MS)
    return () => {
      globalThis.clearTimeout(initial)
      globalThis.clearInterval(timer)
    }
  }, [load])

  const selectedNodeId = rackSelection?.kind === 'recipe_node'
    ? rackSelection.id
    : inspectedNodeId

  const positions = useMemo(
    () => snapshot === null ? new Map<string, RecipeNodePosition>() : new Map(
      layoutRecipeGraph(snapshot).map((position) => [position.node_id, position]),
    ),
    [snapshot],
  )
  const selected = snapshot?.nodes.find((node) => node.node_id === selectedNodeId) ?? null

  function inspect(node: RecipeGraphNode) {
    setInspectedNodeId(node.node_id)
    selection.select({ kind: 'recipe_node', id: node.node_id })
  }

  return (
    <section className="recipe-instrument" data-testid="recipe-module">
      <header className="recipe-instrument__header">
        <div>
          <p>Living plan</p>
          <h1>Recipe</h1>
        </div>
        {snapshot !== null && (
          <div className="recipe-instrument__counts" aria-label="Recipe counts">
            <strong>{snapshot.ready_node_ids.length}</strong>
            <span>ready of {snapshot.nodes.length}</span>
          </div>
        )}
      </header>
      {failure !== null ? (
        <p className="recipe-instrument__message" role="alert">{failure}</p>
      ) : snapshot === null ? (
        <p className="recipe-instrument__message" role="status">Finding the live frontier…</p>
      ) : snapshot.nodes.length === 0 ? (
        <p className="recipe-instrument__message" role="status">No recipe is running.</p>
      ) : (
        <div className="recipe-instrument__body">
          <svg
            className="recipe-graph"
            viewBox="0 0 100 72"
            role="img"
            aria-label={`${snapshot.nodes.length} recipe nodes, ${snapshot.edges.length} dependency edges, ${snapshot.ready_node_ids.length} ready now`}
          >
            <defs>
              <marker id="recipe-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            </defs>
            {snapshot.edges.map((edge) => {
              const source = positions.get(edge.source)
              const target = positions.get(edge.target)
              if (source === undefined || target === undefined) return null
              return (
                <line
                  key={`${edge.source}:${edge.target}:${edge.kind}`}
                  className="recipe-edge"
                  data-kind={edge.kind}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  markerEnd="url(#recipe-arrow)"
                />
              )
            })}
            {snapshot.nodes.map((node) => {
              const position = positions.get(node.node_id)
              if (position === undefined) return null
              const active = selectedNodeId === node.node_id
              return (
                <g
                  key={node.node_id}
                  className="recipe-node"
                  data-kind={node.kind}
                  data-state={node.state}
                  data-selected={active || undefined}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.label}, ${node.kind}, ${node.state}`}
                  onClick={() => inspect(node)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      inspect(node)
                    }
                  }}
                >
                  <title>{node.label} · {node.state}</title>
                  {node.kind === 'search' ? (
                    <polygon points={diamond(position)} />
                  ) : node.kind === 'judge' ? (
                    <path d={gate(position)} />
                  ) : (
                    <rect x={position.x - 7} y={position.y - 4} width="14" height="8" rx="2" />
                  )}
                  <text x={position.x} y={position.y + 8}>{shortLabel(node)}</text>
                </g>
              )
            })}
          </svg>
          <aside className="recipe-inspector" aria-live="polite">
            {selected === null ? (
              <>
                <strong>{snapshot.packet_id ?? 'Current recipe'}</strong>
                <p>Select a step to see why it exists.</p>
                <small>{snapshot.bead_id ?? 'Waiting for an authoritative bead identity'}</small>
              </>
            ) : (
              <>
                <span className="recipe-inspector__state" data-state={selected.state}>{selected.state}</span>
                <h2>{selected.label}</h2>
                <p>{selected.motivation ?? kindExplanation(selected)}</p>
                <small>{selected.bead_id ?? selected.node_id}</small>
              </>
            )}
          </aside>
        </div>
      )}
    </section>
  )
}

function diamond(position: RecipeNodePosition): string {
  return `${position.x},${position.y - 5} ${position.x + 7},${position.y} ${position.x},${position.y + 5} ${position.x - 7},${position.y}`
}

function gate(position: RecipeNodePosition): string {
  return `M ${position.x - 5} ${position.y - 4} H ${position.x + 5} M ${position.x - 5} ${position.y + 4} H ${position.x + 5} M ${position.x - 2} ${position.y - 4} V ${position.y + 4} M ${position.x + 2} ${position.y - 4} V ${position.y + 4}`
}

function shortLabel(node: RecipeGraphNode): string {
  const compact = (
    node.kind === 'judge' ? node.label.replace(/ judge$/iu, '') : node.label
  ).trim()
  return compact.length <= 18 ? compact : `${compact.slice(0, 16)}…`
}

function kindExplanation(node: RecipeGraphNode): string {
  if (node.kind === 'search') return 'A deliberation-marked hard step where bounded search may branch.'
  if (node.kind === 'judge') return 'An independently chartered gate that must pass before this search settles.'
  return 'One scoped packet in the current recipe.'
}
