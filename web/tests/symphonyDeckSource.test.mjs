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
  assert.match(rack, /id: 'conversation'[\s\S]*?law_bound: true,[\s\S]*?default_scope: 'ATTUNED'/u)
  assert.match(stage, /conversation_mode: 'focused'/u)
  assert.match(daemon, /"conversation"/u)
})

/** F140 and Invariant 14 (owner ruling 2026-09-30, "seen clears it"): the Deck keeps only
 * answers still waiting; one read in a Focused conversation, or a closed thread, leaves it.
 */
test('the Deck drops answers already seen in Focused and answers of archived threads', async () => {
  const [deck, seen, app] = await Promise.all([
    readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/deckSeen.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
  ])
  assert.match(deck, /proposedResponseCards\(snapshot\)\.filter\(\(card\) => !seen\.has\(card\.proposal_run_id\)\)/u)
  assert.match(deck, /proposal === undefined \|\| entry\.archived\) return \[\]/u)
  assert.match(deck, /if \(archived\.has\(threadId\)\) continue/u)
  assert.match(seen, /addEventListener\('storage'/u)
  assert.match(app, /<SlashCommandHint \/>\s*<DeckSeenMarker \/>/u)
  assert.match(app, /markProposalSeen\(latest\)/u)
})

/** INCIDENT F193: the Deck said "Clarification logged" when the request left the page, though
 * nothing was recorded; it now says so only once the conductor's record holds the line, and the
 * steering stays on the run card beside the prompt after a later round replaces the attempts. */
test('the Deck calls a clarification logged only when the stack records it', async () => {
  const deck = await readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8')
  const intervene = deck.slice(deck.indexOf('async function intervene('), deck.indexOf('return (', deck.indexOf('async function intervene(')))
  assert.match(intervene, /intervention\.kind === 'clarification'[\s\S]*?setLogging\(\{ instruction: intervention\.instruction, success \}\)/u)
  assert.doesNotMatch(intervene.slice(0, intervene.indexOf("intervention.kind === 'clarification'")), /setStatus\(success\)/u)
  assert.match(deck, /stack\.steering\.includes\(logging\.instruction\) \? logging\.success/u)
  assert.match(deck, /role="status">\{shownStatus\}</u)
  assert.match(deck, /Not logged: the Symphony ended before the conductor read the clarification\./u)
  assert.match(deck, /parsed\?\.kind === 'clarification' && typeof parsed\.instruction === 'string'/u)
  assert.match(deck, /<dt>Steering<\/dt><dd>\{line\}<\/dd>/u)
})
