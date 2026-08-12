import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  memoryGraphRequestKey,
  memoryGraphRequestIsQueryable,
  memoryGraphSnapshotForRequest,
  reconcileMemoryGraphSelection,
} from '../src/memoryGraphSelection.ts'
import {
  rackDrawerModule,
  rackModuleSelectionIsOpen,
} from '../src/graphOverlaySelection.ts'

/** F028, ADR-010/023, and B.6 r12 require the Graph inspector to follow the
 * authoritative scope snapshot instead of retaining another project's node.
 */
test('rebinds a selected Graph node to the refreshed snapshot or clears it', () => {
  const selected = { memory: { memory_id: 'memory-a', project_key: 'old-project' } }
  const refreshed = { memory: { memory_id: 'memory-a', project_key: 'build-test' } }

  assert.equal(reconcileMemoryGraphSelection(selected, [refreshed]), refreshed)
  assert.equal(reconcileMemoryGraphSelection(selected, []), null)
  assert.equal(reconcileMemoryGraphSelection(null, [refreshed]), null)
})

/** Decision 029, A-035, ADR-023, PLAN M2ST1, and F028 require a Graph node to
 * publish its shared memory identity without changing the mounted stage layer.
 */
test('Graph node activation publishes memory identity without opening an overlay', async () => {
  const [graphSource, appSource, stageSource] = await Promise.all([
    readFile(new URL('../src/MemoryGraph.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/stageLayout.ts', import.meta.url), 'utf8'),
  ])
  const memorySelection = { kind: 'memory', id: 'memory-a' }

  assert.equal(rackDrawerModule(memorySelection), null)
  assert.equal(rackModuleSelectionIsOpen(memorySelection, 'memory_graph'), false)
  assert.match(graphSource, /function inspectNode\(node: Node\)[^{]*\{\s*setSelected\(node\)\s*selection\.select\(\{ kind: 'memory', id: node\.memory\.memory_id \}\)/u)
  assert.match(appSource, /const drawerModule = rackDrawerModule\(selection\)/u)
  assert.match(stageSource, /name: 'Graph'[\s\S]*DEFAULT_MODULES\.memory_graph/u)
  assert.doesNotMatch(appSource, /memory_graph:\s*'rack-overlay-module--/u)
})

/** SPEC C.3/C.4, ADR-010/023, and F028 prohibit showing one scope's graph under
 * another scope or thread label while its authoritative query is pending.
 */
test('only exposes a Graph snapshot matching the pending scope and thread request', () => {
  const globalKey = memoryGraphRequestKey('GLOBAL', 'ignored-thread')
  const currentAKey = memoryGraphRequestKey('CURRENT', 'thread-a')
  const currentBKey = memoryGraphRequestKey('CURRENT', 'thread-b')
  const loaded = { requestKey: globalKey, data: { marker: 'global truth' } }

  assert.deepEqual(memoryGraphSnapshotForRequest(loaded, globalKey), { marker: 'global truth' })
  assert.equal(memoryGraphSnapshotForRequest(loaded, currentAKey), null)
  assert.notEqual(globalKey, currentAKey)
  assert.notEqual(currentAKey, currentBKey)
})

/** SPEC C.3/C.4, ADR-023, and F028 forbid a CURRENT query without a thread:
 * omitting thread_id is the daemon's GLOBAL contract, not empty CURRENT truth.
 */
test('does not query CURRENT memory until a thread identity exists', async () => {
  const source = await readFile(new URL('../src/MemoryGraph.tsx', import.meta.url), 'utf8')

  assert.equal(memoryGraphRequestIsQueryable('GLOBAL', null), true)
  assert.equal(memoryGraphRequestIsQueryable('CURRENT', 'thread-a'), true)
  assert.equal(memoryGraphRequestIsQueryable('CURRENT', null), false)
  assert.match(source, /if \(!requestIsQueryable\) \{\s*return\s*\}\s*let active = true/u)
  assert.match(source, /!requestIsQueryable \? <p role="status">Select a thread to inspect its current memory\.<\/p>/u)
})
