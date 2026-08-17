import assert from 'node:assert/strict'
import test from 'node:test'

import {
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
