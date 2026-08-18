import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'

import {
  buildRecipeCompletionGrid,
  parseRecipeGraphSnapshot,
  type RecipeGraphNode,
  type RecipeGraphSnapshot,
  type RecipeNodeState,
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

  const completion = useMemo(
    () => snapshot === null ? null : buildRecipeCompletionGrid(snapshot),
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
        {snapshot !== null && completion !== null && (
          <div className="recipe-instrument__counts" aria-label="Recipe counts">
            <strong>{snapshot.nodes.filter((node) => node.state === 'passed').length}</strong>
            <span>complete · {snapshot.ready_node_ids.length} ready</span>
          </div>
        )}
      </header>
      {failure !== null ? (
        <p className="recipe-instrument__message" role="alert">{failure}</p>
      ) : snapshot === null ? (
        <p className="recipe-instrument__message" role="status">Finding the live frontier…</p>
      ) : snapshot.nodes.length === 0 || completion === null ? (
        <p className="recipe-instrument__message" role="status">No recipe is running.</p>
      ) : (
        <div className="recipe-instrument__body">
          <div
            className="recipe-grid-scroll"
            aria-label={`${completion.rows.length} packet inputs moving left to right through ${completion.milestone_column - 2} stages`}
          >
            <div
              className="recipe-grid"
              role="table"
              style={{
                gridTemplateColumns: `minmax(11rem, 15rem) minmax(8rem, 11rem) repeat(${Math.max(0, completion.milestone_column - 3)}, minmax(7.5rem, 9.5rem)) minmax(9rem, 12rem)`,
                gridTemplateRows: `auto repeat(${completion.rows.length}, minmax(5.5rem, auto))`,
              }}
            >
              {Array.from({ length: completion.milestone_column }, (_, index) => (
                <div
                  key={`heading:${index + 1}`}
                  className="recipe-grid__heading"
                  role="columnheader"
                  style={{ gridColumn: index + 1, gridRow: 1 }}
                >
                  {columnHeading(index + 1, completion.milestone_column)}
                </div>
              ))}
              {completion.rows.map((node, index) => (
                <RecipeCell
                  key={`ingredient:${node.node_id}`}
                  className="recipe-grid__ingredient"
                  node={node}
                  selected={selectedNodeId === node.node_id}
                  style={{ gridColumn: 1, gridRow: index + 2 }}
                  onInspect={inspect}
                >
                  <span>{node.node_id} · 1 {node.kind === 'search' ? 'search packet' : 'packet'}</span>
                  <strong>{node.motivation ?? node.label}</strong>
                </RecipeCell>
              ))}
              {completion.rows.map((node, index) => (
                <RecipeCell
                  key={`prep:${node.node_id}`}
                  className="recipe-grid__prep"
                  node={node}
                  selected={selectedNodeId === node.node_id}
                  style={{ gridColumn: 2, gridRow: index + 2 }}
                  onInspect={inspect}
                >
                  <span>Own work</span>
                  <strong>{node.label}</strong>
                </RecipeCell>
              ))}
              {emptyStageCells(completion).map(({ column, row }) => (
                <div
                  key={`empty:${column}:${row}`}
                  className="recipe-grid__empty"
                  aria-hidden="true"
                  style={{ gridColumn: column, gridRow: row + 1 }}
                />
              ))}
              {completion.cells.map((cell) => {
                const node = snapshot.nodes.find((item) => item.node_id === cell.node_id)!
                const judgeNodes = cell.judge_node_ids.map((nodeId) => (
                  snapshot.nodes.find((item) => item.node_id === nodeId)!
                ))
                return (
                  <div
                    key={`stage:${cell.node_id}`}
                    className="recipe-grid__stage"
                    data-state={node.state}
                    data-progress={progressOf(node.state)}
                    data-selected={selectedNodeId === node.node_id || undefined}
                    style={{
                      gridColumn: cell.column,
                      gridRow: `${cell.row_start + 1} / span ${cell.row_span}`,
                    }}
                  >
                    <button type="button" onClick={() => inspect(node)}>
                      <span>{cell.input_node_ids.length} streams join</span>
                      <strong>{node.label}</strong>
                      <small>After {cell.input_node_ids.filter((nodeId) => nodeId !== node.node_id).join(' + ')}</small>
                    </button>
                    {judgeNodes.length > 0 && (
                      <div className="recipe-grid__judges" aria-label={`${judgeNodes.length} judge gates`}>
                        {judgeNodes.map((judge) => (
                          <button
                            key={judge.node_id}
                            type="button"
                            data-state={judge.state}
                            data-progress={progressOf(judge.state)}
                            data-selected={selectedNodeId === judge.node_id || undefined}
                            onClick={() => inspect(judge)}
                          >
                            {judge.label}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
              <div
                className="recipe-grid__milestone"
                data-state={completion.milestone_state}
                data-progress={progressOf(completion.milestone_state)}
                style={{
                  gridColumn: completion.milestone_column,
                  gridRow: `2 / span ${completion.rows.length}`,
                }}
              >
                <span>Served</span>
                <strong>{snapshot.packet_id ?? 'Current milestone'}</strong>
                <small>{milestoneCopy(completion.milestone_state)}</small>
              </div>
            </div>
          </div>
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

function RecipeCell({
  children,
  className,
  node,
  onInspect,
  selected,
  style,
}: {
  children: ReactNode
  className: string
  node: RecipeGraphNode
  onInspect: (node: RecipeGraphNode) => void
  selected: boolean
  style: CSSProperties
}) {
  return (
    <button
      type="button"
      className={className}
      data-kind={node.kind}
      data-state={node.state}
      data-progress={progressOf(node.state)}
      data-selected={selected || undefined}
      style={style}
      onClick={() => onInspect(node)}
    >
      {children}
    </button>
  )
}

function columnHeading(column: number, milestoneColumn: number): string {
  if (column === 1) return 'Packet / input'
  if (column === 2) return 'Own prep'
  if (column === milestoneColumn) return 'Milestone'
  return `Stage ${column - 2}`
}

function progressOf(state: RecipeNodeState): 'done' | 'current' | 'waiting' | 'failed' {
  if (state === 'passed') return 'done'
  if (state === 'ready' || state === 'running' || state === 'review') return 'current'
  if (state === 'failed') return 'failed'
  return 'waiting'
}

function milestoneCopy(state: RecipeNodeState): string {
  if (state === 'passed') return 'The whole plan is complete.'
  if (state === 'failed') return 'A failed step still needs a new path.'
  if (state === 'running' || state === 'review') return 'The plan is being cooked now.'
  if (state === 'ready') return 'The next work is ready.'
  return 'Every stream arrives here.'
}

function emptyStageCells(completion: ReturnType<typeof buildRecipeCompletionGrid>) {
  const occupied = new Set<string>()
  for (const cell of completion.cells) {
    for (let row = cell.row_start; row < cell.row_start + cell.row_span; row += 1) {
      occupied.add(`${cell.column}:${row}`)
    }
  }
  const result: { column: number, row: number }[] = []
  for (let column = 3; column < completion.milestone_column; column += 1) {
    for (let row = 1; row <= completion.rows.length; row += 1) {
      if (!occupied.has(`${column}:${row}`)) result.push({ column, row })
    }
  }
  return result
}

function kindExplanation(node: RecipeGraphNode): string {
  if (node.kind === 'search') return 'A deliberation-marked hard step where bounded search may branch.'
  if (node.kind === 'judge') return 'An independently chartered gate that must pass before this search settles.'
  return 'One scoped packet in the current recipe.'
}
