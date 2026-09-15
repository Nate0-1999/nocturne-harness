import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ATTUNEMENT_PICKS_STORAGE_KEY,
  attunementBadge,
  loadStickyAttunementPicks,
  persistStickyAttunementPicks,
  resolveAttunements,
} from '../src/attunement.ts'
import { loadStageLayout, persistStageLayout, setStageAttunementSource } from '../src/stageLayout.ts'

const threads = [
  { thread_id: 'thread-a', title: 'Alpha Thread' },
  { thread_id: 'thread-b', title: 'Beta Thread' },
]

/** SPEC D.2 / FL-115: named stacks override distance and survive reload. */
test('a named stack remains bound across movement and persisted layout reload', () => {
  let stage = layout([layer('work', [
    module('conversation', 'conversation', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('threads', 'threads', 20, 0),
  ])])
  stage = setStageAttunementSource(stage, 'context_bars', 'threads')
  assert.equal(resolveAttunements(stage, threads, 'thread-a').targets.get('context_bars')?.name, 'Channel Stack')
  stage.layers[0].modules.find((item) => item.instance_id === 'threads').x = 30
  stage.layers[0].modules.find((item) => item.instance_id === 'context_bars').x = 2
  const saved = new Map()
  const storage = { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) }
  persistStageLayout(storage, stage)
  const restored = loadStageLayout(storage)
  assert.equal(resolveAttunements(restored, threads, 'thread-b').targets.get('context_bars')?.source_instance_id, 'threads')
  const nearby = setStageAttunementSource(restored, 'context_bars', null)
  assert.equal(resolveAttunements(nearby, threads, 'thread-b').targets.get('context_bars')?.id, 'thread-a')
})

/** SPEC D.2 / FL-115: deleting a chosen stack must not silently pick another source. */
test('an unavailable named stack stays unattuned and Everything still overrides it', () => {
  const stage = setStageAttunementSource(layout([layer('work', [
    module('conversation', 'conversation', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
  ])]), 'context_bars', 'threads')
  assert.equal(resolveAttunements(stage, threads, 'thread-a').targets.get('context_bars'), null)
  stage.scopes.context_bars = 'GLOBAL'
  assert.equal(attunementBadge('GLOBAL', resolveAttunements(stage, threads, 'thread-a').targets.get('context_bars')), 'Global')
})

function module(instanceId, moduleId, x, y, sourceThreadId, conversationMode = 'focused') {
  return {
    instance_id: instanceId,
    module_id: moduleId,
    ...(sourceThreadId === undefined ? {} : { source_thread_id: sourceThreadId }),
    ...(moduleId === 'conversation' ? { conversation_mode: conversationMode } : {}),
    x,
    y,
    width: 1,
    height: 1,
  }
}

function layout(layers, scopes = {}) {
  return {
    version: 5,
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
    module('conversation', 'conversation', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('context_bars:2', 'context_bars', 9, 0),
    module('conversation:2', 'conversation', 10, 0, 'thread-b'),
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
    module('conversation', 'conversation', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('conversation:2', 'conversation', 10, 0, 'thread-b'),
  ])])
  const moved = structuredClone(before)
  moved.layers[0].modules[1].x = 9

  assert.equal(resolveAttunements(before, threads, null).targets.get('context_bars')?.id, 'thread-a')
  assert.equal(resolveAttunements(moved, threads, null).targets.get('context_bars')?.id, 'thread-b')
})

/** SPEC D.2 139: equal distances emit one sticky, journal-ready random choice. */
test('an exact tie is random once and sticky until the layout changes', () => {
  const stage = layout([layer('work', [
    module('conversation', 'conversation', 0, 0, 'thread-a'),
    module('context_bars', 'context_bars', 1, 0),
    module('conversation:2', 'conversation', 2, 0, 'thread-b'),
  ])])
  const first = resolveAttunements(stage, threads, null, {}, () => 0.99)
  const retained = resolveAttunements(stage, threads, null, first.sticky_picks, () => 0)
  const changed = structuredClone(stage)
  changed.layers.push(layer('later-tab', []))
  const rerolled = resolveAttunements(changed, threads, null, first.sticky_picks, () => 0)

  assert.equal(first.targets.get('context_bars')?.id, 'thread-b')
  assert.equal(first.new_tie_picks.length, 1)
  assert.deepEqual(first.new_tie_picks[0].tied_source_instance_ids, ['conversation', 'conversation:2'])
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
    layer('first', [module('conversation', 'conversation', 0, 0, 'thread-a')]),
    layer('second', [module('conversation:2', 'conversation', 2, 0, 'thread-b')]),
    layer('third', [module('context_bars', 'context_bars', 1, 0)]),
  ])

  const resolved = resolveAttunements(stage, threads, null)
  assert.equal(resolved.targets.get('context_bars')?.id, 'thread-b')
})

/** PLAN M3OM / P2: one conversation instance changes attunement meaning with its posture. */
test('conversation mode switches the same source between one thread and the Deck stack', () => {
  const focused = layout([layer('work', [
    module('conversation', 'conversation', 0, 0, 'thread-a', 'focused'),
  ])])
  const stack = structuredClone(focused)
  stack.layers[0].modules[0].conversation_mode = 'stack'

  assert.deepEqual(resolveAttunements(focused, threads, null).targets.get('conversation'), {
    kind: 'thread', id: 'thread-a', name: 'Alpha Thread', thread_ids: ['thread-a'],
    source_instance_id: 'conversation',
  })
  assert.deepEqual(resolveAttunements(stack, threads, null).targets.get('conversation'), {
    kind: 'stack', id: 'the-deck', name: 'The Deck', thread_ids: ['thread-a', 'thread-b'],
    source_instance_id: 'conversation',
  })
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
