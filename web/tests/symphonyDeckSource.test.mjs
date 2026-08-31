import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** ADR-014 and G19-G20 require one current Deck surface for typed steering and exact lineage. */
test('The Deck exposes all three conductor interventions and an owner demand lineage', async () => {
  const [deck, rack, stage, daemon] = await Promise.all([
    readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/stageLayout.ts', import.meta.url), 'utf8'),
    readFile(new URL('../../src/harness/daemon.py', import.meta.url), 'utf8'),
  ])

  assert.match(deck, /You steer the conductor here\. Workers are never directly addressable\./u)
  assert.match(deck, /kind: 'clarification'/u)
  assert.match(deck, /kind: 'cancel_attempt'/u)
  assert.match(deck, /kind: 'charter_change'/u)
  assert.match(deck, /Owner demand/u)
  assert.match(deck, /The signed parent is append-only/u)
  assert.match(deck, /memories not admitted/u)
  assert.match(rack, /id: 'deck'[\s\S]*?law_bound: true, default_scope: 'ATTUNED'/u)
  assert.match(stage, /'palace_queue', 'deck'/u)
  assert.match(daemon, /"recipe",\s*"deck",/u)
})
