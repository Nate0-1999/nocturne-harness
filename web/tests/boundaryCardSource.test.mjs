import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const deck = readFileSync(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8')
const rack = readFileSync(new URL('../src/rack.tsx', import.meta.url), 'utf8')

/** F198 / ADR-015: a waiting wall card is answered on the Deck with Allow once, Allow for this thread or Deny. */
test('a waiting boundary card carries its three answers and posts them to its run', () => {
  for (const [id, decision, label] of [
    ['boundary-allow-once', 'allowed_once', 'Allow once'],
    ['boundary-allow-thread', 'allowed_thread', 'Allow for this thread'],
    ['boundary-deny', 'denied', 'Deny'],
  ]) {
    assert.match(deck, new RegExp(`data-testid="${id}"[\\s\\S]*?decide\\(card, '${decision}'\\)\\}>${label}<`))
  }
  assert.doesNotMatch(deck, /footer>[\s\S]*owner action required[\s\S]*<\/footer/)
  assert.match(rack, /case 'boundary\.decide'[\s\S]*?\/v1\/threads\/\$\{encodeURIComponent\(threadId\)\}\/boundary/)
})
