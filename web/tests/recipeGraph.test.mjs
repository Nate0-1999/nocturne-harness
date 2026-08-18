import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildRecipeCompletionGrid,
  layoutRecipeGraph,
  parseRecipeGraphSnapshot,
} from '../src/recipeGraph.ts'

function graph() {
  return {
    schema_version: 1,
    revision: 4,
    as_of: '2026-08-17T20:00:00Z',
    packet_id: 'ROOT',
    bead_id: 'ng-root',
    nodes: [
      { node_id: 'PREP', label: 'Prepare', kind: 'packet', state: 'passed', bead_id: null, motivation: 'Make the ground honest.' },
      { node_id: 'HARD', label: 'Search', kind: 'search', state: 'ready', bead_id: null, motivation: 'Find the hard answer.' },
      { node_id: 'JUDGE', label: 'Motivation judge', kind: 'judge', state: 'blocked', bead_id: null, motivation: null },
    ],
    edges: [
      { source: 'PREP', target: 'HARD', kind: 'blocks' },
      { source: 'HARD', target: 'JUDGE', kind: 'judged_by' },
    ],
    ready_node_ids: ['HARD'],
  }
}

/** P2.3 requires the living plan to distinguish the ready frontier from dependency order. */
test('recipe graph validates the visible frontier and lays dependencies left to right', () => {
  const snapshot = parseRecipeGraphSnapshot(graph())
  const positions = new Map(layoutRecipeGraph(snapshot).map((item) => [item.node_id, item]))

  assert.equal(snapshot.nodes[1].kind, 'search')
  assert.ok(positions.get('PREP').x < positions.get('HARD').x)
  assert.ok(positions.get('HARD').x < positions.get('JUDGE').x)
})

/** ADR-023 keeps the visualizer read-only, so malformed query truth must fail closed. */
test('recipe graph refuses edges and frontier marks that invent graph truth', () => {
  const dangling = graph()
  dangling.edges[0].source = 'MISSING'
  assert.throws(() => parseRecipeGraphSnapshot(dangling), /identities do not join/)

  const inventedReady = graph()
  inventedReady.ready_node_ids = ['PREP']
  assert.throws(() => parseRecipeGraphSnapshot(inventedReady), /frontier disagrees/)
})

/** SYM13 projects every packet and dependency join into the owner-directed recipe grid. */
test('completion grid keeps packet rows distinct and fuses dependency streams rightward', () => {
  const value = graph()
  value.nodes.splice(1, 0,
    { node_id: 'FRAME', label: 'Build frame', kind: 'packet', state: 'running', bead_id: 'ng-frame', motivation: 'Make the plan visible.' },
  )
  value.nodes.push(
    { node_id: 'SHIP', label: 'Serve result', kind: 'packet', state: 'blocked', bead_id: 'ng-ship', motivation: 'Prove the joined result.' },
  )
  value.edges.push(
    { source: 'FRAME', target: 'SHIP', kind: 'blocks' },
    { source: 'HARD', target: 'SHIP', kind: 'blocks' },
  )
  value.ready_node_ids = ['HARD']

  const snapshot = parseRecipeGraphSnapshot(value)
  const grid = buildRecipeCompletionGrid(snapshot)
  const hard = grid.cells.find((cell) => cell.node_id === 'HARD')
  const ship = grid.cells.find((cell) => cell.node_id === 'SHIP')

  assert.deepEqual(grid.rows.map((node) => node.node_id), ['FRAME', 'PREP', 'HARD', 'SHIP'])
  assert.deepEqual(hard.input_node_ids, ['PREP', 'HARD'])
  assert.equal(hard.row_span, 2)
  assert.deepEqual(hard.judge_node_ids, ['JUDGE'])
  assert.deepEqual(ship.input_node_ids, ['FRAME', 'PREP', 'HARD', 'SHIP'])
  assert.equal(ship.row_span, 4)
  assert.ok(hard.column < ship.column)
  assert.ok(ship.column < grid.milestone_column)
  assert.equal(grid.milestone_state, 'running')
})

/** P2.3 treats a cyclic recipe as corrupt authority rather than drawing a plausible plan. */
test('recipe graph refuses a cycle instead of inventing completion order', () => {
  const cyclic = graph()
  cyclic.edges.push({ source: 'JUDGE', target: 'PREP', kind: 'blocks' })
  assert.throws(() => parseRecipeGraphSnapshot(cyclic), /must remain a DAG/)
})
