import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ATTUNEMENT_PICKS_STORAGE_KEY,
  attunementBadge,
  loadStickyAttunementPicks,
  persistStickyAttunementPicks,
  resolveAttunements,
} from '../src/attunement.ts'

const threads = [
  { thread_id: 'thread-a', title: 'Alpha Thread' },
  { thread_id: 'thread-b', title: 'Beta Thread' },
]

function module(instanceId, moduleId, x, y, sourceThreadId) {
  return {
    instance_id: instanceId,
    module_id: moduleId,
    ...(sourceThreadId === undefined ? {} : { source_thread_id: sourceThreadId }),
    x,
    y,
    width: 1,
    height: 1,
  }
}

function layout(layers, scopes = {}) {
  return {
    version: 4,
    active_layer_id: layers[0].layer_id,
    layers,
    removed_layers: [],
    scopes,
  }
}

function layer(layerId, modules) {
  return {
    layer_id: layerId,
    name: layerId,
    camera: { x: 0, y: 0, zoom: 1 },
    modules,
    removed_modules: [],
  }
}

/** SPEC D.2 r138-139: duplicate consumers bind independently to nearest thread sources. */
test('two Context Bars instances can attune to two different nearby threads', () => {
  const stage = layout([layer('work', [
    module('chat', 'chat', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('context_bars:2', 'context_bars', 9, 0),
    module('chat:2', 'chat', 10, 0, 'thread-b'),
  ])])

  const resolved = resolveAttunements(stage, threads, null)
  assert.equal(resolved.targets.get('context_bars')?.id, 'thread-a')
  assert.equal(resolved.targets.get('context_bars:2')?.id, 'thread-b')
  assert.equal(attunementBadge('ATTUNED', resolved.targets.get('context_bars') ?? null), 'Alpha Thread')
  assert.equal(attunementBadge('ATTUNED', resolved.targets.get('context_bars:2') ?? null), 'Beta Thread')
})

/** SPEC D.2 138-139: moving a consumer changes its live binding without a picker. */
test('drag geometry immediately reattunes a consumer', () => {
  const before = layout([layer('work', [
    module('chat', 'chat', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('chat:2', 'chat', 10, 0, 'thread-b'),
  ])])
  const moved = structuredClone(before)
  moved.layers[0].modules[1].x = 9

  assert.equal(resolveAttunements(before, threads, null).targets.get('context_bars')?.id, 'thread-a')
  assert.equal(resolveAttunements(moved, threads, null).targets.get('context_bars')?.id, 'thread-b')
})

/** SPEC D.2 139: equal distances emit one sticky, journal-ready random choice. */
test('an exact tie is random once and sticky until the layout changes', () => {
  const stage = layout([layer('work', [
    module('chat', 'chat', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('chat:2', 'chat', 2, 0, 'thread-b'),
  ])])
  const first = resolveAttunements(stage, threads, null, {}, () => 0.99)
  const retained = resolveAttunements(stage, threads, null, first.sticky_picks, () => 0)
  const changed = structuredClone(stage)
  changed.layers.push(layer('later-tab', []))
  const rerolled = resolveAttunements(changed, threads, null, first.sticky_picks, () => 0)

  assert.equal(first.targets.get('context_bars')?.id, 'thread-b')
  assert.equal(first.new_tie_picks.length, 1)
  assert.deepEqual(first.new_tie_picks[0].tied_source_instance_ids, ['chat', 'chat:2'])
  assert.equal(retained.targets.get('context_bars')?.id, 'thread-b')
  assert.equal(retained.new_tie_picks.length, 0)
  assert.equal(rerolled.targets.get('context_bars')?.id, 'thread-a')
  assert.equal(rerolled.new_tie_picks.length, 1)
})

/** SPEC D.2 139: sticky ambiguity survives reload but malformed evidence fails closed. */
test('a sticky tie pick survives reload but rejects malformed stored state', () => {
  const storage = memoryStorage()
  const pick = {
    context_bars: { layout_signature: 'same-layout', source_instance_id: 'chat:2' },
  }
  persistStickyAttunementPicks(storage, pick)
  assert.deepEqual(loadStickyAttunementPicks(storage), pick)

  storage.setItem(ATTUNEMENT_PICKS_STORAGE_KEY, '{')
  assert.deepEqual(loadStickyAttunementPicks(storage), {})
})

/** SPEC D.2 139: tab order is the third Euclidean axis at one unit per step. */
test('layer distance participates in proximity with one unit per tab step', () => {
  const stage = layout([
    layer('first', [module('chat', 'chat', 0, 0, 'thread-a')]),
    layer('second', [module('chat:2', 'chat', 2, 0, 'thread-b')]),
    layer('third', [module('context_bars', 'context_bars', 1, 0)]),
  ])

  const resolved = resolveAttunements(stage, threads, null)
  assert.equal(resolved.targets.get('context_bars')?.id, 'thread-b')
})

/** SPEC D.2 138-139: badges expose global and zero-source truth without inference. */
test('GLOBAL and zero-source ATTUNED badges state their exact truth', () => {
  const stage = layout([layer('work', [module('context_bars', 'context_bars', 1, 0)])])
  const resolved = resolveAttunements(stage, [], null)
  assert.equal(resolved.targets.get('context_bars'), null)
  assert.equal(attunementBadge('ATTUNED', null), 'Unattuned')
  assert.equal(attunementBadge('GLOBAL', null), 'Global')
})

function memoryStorage() {
  const values = new Map()
  return {
    getItem(key) { return values.get(key) ?? null },
    setItem(key, value) { values.set(key, value) },
  }
}
