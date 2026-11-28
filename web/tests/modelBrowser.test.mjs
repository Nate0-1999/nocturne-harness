import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { browseOrder, chipParts, followSubscriptionCheck, modelMark, policyInForce, spendModelLabel, subscriptionGroups, subscriptionState, takesParameter, threadModelMark } from '../src/modelBrowser.ts'

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

/** P2 / SD-115: keep the pinned state visible and the unpinned button reachable by touch or keyboard. */
test('model pins reveal on row hover, keyboard focus and a touch hold', async () => {
  const css = await readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8')
  const pin = String.raw`\.kit-button--pin\[aria-pressed="false"\]`
  assert.match(css, new RegExp(String.raw`\.model-row ${pin} \{\s*opacity: 0; pointer-events: none;\s*\}`))
  for (const row of [String.raw`\.model-row:hover`, String.raw`\.model-row:is\(:has\(:focus-visible\), \[data-show-pin\]\)`]) {
    assert.match(css, new RegExp(String.raw`${row} ${pin} \{\s*opacity: 1;\s*pointer-events: auto;`))
  }
})

/** A-095: an unchecked inventory must fill the open list without another user action. */
test('opening a model list shows checking until each subscription answers', async t => {
  const pending = subscriptionGroups(null)
  assert.deepEqual(pending.map(subscriptionState), ['Checking…', 'Checking…'])
  const browser = { models: [], pins: [], configurations: [], subscriptions: pending }
  const results = [
    browser,
    { ...browser, subscriptions: pending.map((row, i) => ({ ...row, availability: i ? 'missing' : 'available' })) },
  ]
  const displayed = []
  await followSubscriptionCheck(
    async () => results.shift(),
    b => displayed.push(subscriptionGroups(b).map(subscriptionState)),
    () => true,
  )
  assert.deepEqual(displayed, [['Checking…', 'Checking…'], ['Available', 'Not installed']])
  assert.match(subscriptionState(subscriptionGroups(null, true)[0]), /reopen/i)
  let now = Date.now()
  t.mock.method(Date, 'now', () => now)
  await followSubscriptionCheck(
    async () => { now += 90_000; return { ...browser } },
    b => assert.ok(subscriptionGroups(b).every(s => subscriptionState(s).includes('Reopen'))),
    () => true,
  )
})

/** A-095: sorting or searching a broker catalog must preserve the owner's plan choices. */
test('subscription groups and names survive every broker sort and search', () => {
  const codex = 'subscription:codex/ref/astra'
  const claude = 'subscription:claudeAgent/ref/opus'
  const browser = { models: [{ model: codex }, ...models, { model: claude }], subscriptions: [
    { tool: 'codex', availability: 'available' }, { tool: 'claudeAgent', availability: 'available' },
  ], chat_policy: 'elbow', configurations: [] }
  for (const sort of ['rank', 'price', 'context']) {
    assert.deepEqual(browseOrder(browser.models, [], 'absent', sort), [])
    assert.deepEqual(subscriptionGroups(browser).map(s => s.models.map(m => m.model)), [[codex], [claude]])
  }
  assert.equal(modelMark(browser, claude, 'high'), 'Claude Code · opus')
  assert.equal(modelMark(null, codex, 'low'), 'Codex · astra')
  assert.equal(subscriptionState({ tool: 'claudeAgent', availability: 'signed_out' }), 'Signed out · claude auth login')
})

/** P2 / FL-206: restarting can leave a thread with no strategy or a named-route lookup. Spend must
 * agree with its header on the active strategy without relabeling other models on the bill. */
test('expanded Spend matches the strategy in force after restart and preserves other receipt names', () => {
  const model = 'openrouter:vendor/one'
  const billed = 'vendor/one'
  const browser = { chat_policy: 'elbow', configurations: [{ policy: 'elbow', model }] }
  for (const policy of ['elbow', null, 'human_command', 'hydrated_unverified']) {
    assert.equal(spendModelLabel(browser, { model, policy }, billed), 'Elbow · vendor/one')
  }
  assert.equal(spendModelLabel(browser, { model, policy: 'elbow' }, 'embedding'), 'embedding')
  assert.equal(spendModelLabel(browser, undefined, billed), billed)
  assert.equal(spendModelLabel(null, { model, policy: null }, billed), billed)
  assert.equal(spendModelLabel(browser, { model: 'openrouter:vendor/two', policy: 'max' }, 'vendor/two'), 'Max · vendor/two')
  assert.equal(spendModelLabel(browser, { model }, null), 'Model not reported')
})

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

/** A-021: the chip names the agent policy only while this conversation runs on its pick. */
test('the chip names the policy in force, never one this conversation left', () => {
  const pinned = { policy: 'pinned:openrouter:top', model: 'openrouter:top', reason: 'keeps this model' }
  const elbow = { policy: 'elbow', model: 'openrouter:mid', reason: 'score 30' }
  const browser = { chat_policy: pinned.policy, configurations: [pinned, elbow] }
  assert.equal(policyInForce(browser, 'openrouter:top'), pinned)
  assert.equal(policyInForce(browser, null), pinned)
  assert.equal(policyInForce({ ...browser, chat_policy: 'elbow' }, 'openrouter:mid'), elbow)
  assert.equal(policyInForce({ ...browser, chat_policy: 'elbow' }, 'openrouter:top'), null)
})

/** A-021 / P2: the browser's Pinned card keeps the open conversation's model, so a pinned policy
 * names its own pick — a thread on it reads Pinned whichever conversation is open. */
test('a pinned policy is in force on its own model while another conversation is open', () => {
  const openOnMid = { policy: 'pinned:openrouter:mid', model: 'openrouter:mid', reason: 'keeps this model' }
  const browser = { chat_policy: 'pinned:openrouter:top', configurations: [openOnMid] }
  assert.equal(policyInForce(browser, 'openrouter:top')?.model, 'openrouter:top')
  assert.equal(policyInForce(browser, null)?.model, 'openrouter:top')
  assert.equal(policyInForce(browser, 'openrouter:mid'), null)
})

/** ADR-023 clause 3: the dialog offers only what the model takes; an unpublished list hides nothing. */
test('the parameter dialog shows only the parameters the model takes', () => {
  const gpt = ['max_tokens', 'temperature', 'top_p']
  assert.equal(takesParameter(gpt, 'model.top_p'), true)
  assert.equal(takesParameter(gpt, 'model.top_k'), false)
  assert.equal(takesParameter(null, 'model.top_k'), true)
  assert.equal(takesParameter(undefined, 'model.top_k'), true)
})

/** P2 / A-021: wherever a thread is named it carries one model mark — the policy in force, the
 * model and its thinking level — and the conversation chip adds the context window and price. */
test('one model mark for the thread list, the Deck and the chip', () => {
  const pinned = { policy: 'pinned:openrouter:mid', model: 'openrouter:mid', reason: 'keeps this model' }
  const browser = { chat_policy: pinned.policy, configurations: [pinned], models, pins: [], current: null }
  assert.equal(modelMark(browser, 'openrouter:mid', 'low'), 'Pinned · mid · low thinking')
  assert.equal(modelMark(browser, null, null), 'Pinned · mid · default thinking')
  assert.equal(modelMark(browser, 'openrouter:top', null), 'top')
  assert.equal(modelMark(browser, 'openrouter:mid', 'low', true),
    'Pinned · mid · low thinking · 1M context · $0.20/$0.80 per M')
  assert.equal(modelMark(null, 'openrouter:vendor/model', 'low'), 'vendor/model')
})

/** P2 / ADR-023: the selected thread's mark follows its live model and the browser's read of its
 * thinking level; every other thread's comes from the catalog. */
test('a listed thread takes its mark from the catalog unless it is the one open', () => {
  const browser = {
    chat_policy: 'elbow', configurations: [], models, pins: [],
    current: { model: 'openrouter:mid', effort: 'high' },
  }
  assert.equal(threadModelMark(browser, { model: 'openrouter:mid', effort: 'low' }, null), 'mid · low thinking')
  assert.equal(threadModelMark(browser, { model: 'openrouter:top', effort: null }, { model: 'openrouter:mid' }),
    'mid · high thinking')
  assert.equal(threadModelMark(browser, {}, null), 'Choosing model')
})
