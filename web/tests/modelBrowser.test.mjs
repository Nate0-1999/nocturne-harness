import assert from 'node:assert/strict'
import test from 'node:test'

import { browseOrder, chipParts } from '../src/modelBrowser.ts'

const model = (id, score, prompt, context, reasoning = false) => ({
  model: `openrouter:${id}`, name: `Vendor: ${id}`, context_tokens: context,
  prompt_price: prompt, completion_price: prompt === null ? null : String(Number(prompt) * 4),
  score, reasoning,
})
const models = [
  model('mid', '30', '0.2', 1_048_576, true),
  model('top', '57', '4', 200_000),
  model('unscored', null, '0.05', null),
]

/** A-020: rank is a display order the owner can re-sort and pin over, never routing. */
test('pins sit on top, then rank, price or context orders the rest', () => {
  const names = (pins, sort, search = '') => browseOrder(models, pins, search, sort).map((item) => item.model.slice(11))
  assert.deepEqual(names([], 'rank'), ['top', 'mid', 'unscored'])
  assert.deepEqual(names(['openrouter:unscored'], 'rank'), ['unscored', 'top', 'mid'])
  assert.deepEqual(names([], 'price'), ['unscored', 'mid', 'top'])
  assert.deepEqual(names([], 'context'), ['mid', 'top', 'unscored'])
  assert.deepEqual(names([], 'rank', 'TOP'), ['top'])
})

/** P4: the conversation chip reads model · thinking level · context window · price. */
test('the chip names the thinking level only for a model that takes one', () => {
  assert.deepEqual(chipParts('openrouter:mid', models[0], 'high'),
    ['mid', 'high thinking', '1M context', '$0.20/$0.80 per M'])
  assert.deepEqual(chipParts('openrouter:top', models[1], null), ['top', '200K context', '$4.00/$16.00 per M'])
  assert.deepEqual(chipParts('openrouter:unknown/model', undefined, null), ['unknown/model'])
  assert.deepEqual(chipParts(null, undefined, null), ['Choosing model'])
})
