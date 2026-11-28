import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** SPEC B.6 / M8SY item 3: a long worker list must scroll inside the Conversation frame. */
test('the Deck bounds its own scrollable viewport', async () => {
  const css = await readFile(new URL('../src/assets/symphonyDeck.css', import.meta.url), 'utf8')
  const rule = css.match(/\.symphony-deck\s*\{([^}]+)\}/u)?.[1] ?? ''
  assert.match(rule, /(?:^|;)\s*(?:height|max-height|block-size):\s*100%/u)
  assert.match(rule, /overflow(?:-y)?:\s*(?:auto|scroll)/u)
})

/** ADR-021 C4: the winner's card leads to the living queue for explicit review. */
test('a queued attempt opens Memory Ingest, whose count includes pending Symphony lessons', async () => {
  const deck = await readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8')
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const queue = app.slice(app.indexOf('function PalaceQueueModule()'), app.indexOf('function MemoryModule()'))
  assert.match(deck, /selection\.select\(\{\s*kind: 'module', id: 'palace_queue'[\s\S]*?Memories queued for review/u)
  assert.match(queue, /cards\.length[^}]*\} waiting/u)
  assert.match(queue, /setTimeout\(refresh/u)
})

/** ADR-021 C4: a reviewable lesson is the candidate fact, never the Palace resolution payload. */
test('the Deck projects the fact out of each queued lesson', async () => {
  const deck = await readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8')
  const lessons = deck.match(/entry\.queue_cards\.map\(([\s\S]*?)\}\) :/u)?.[1] ?? ''
  assert.match(lessons, /candidate\.body/u)
  assert.doesNotMatch(lessons, /JSON\.stringify|principal_id|evidence_refs/u)
})

/** ADR-012 §3 and B.6: the judge's inputs explain why its memory list is empty. */
test('the Deck explains what judges read beside their memory observation', async () => {
  const context = await readFile(new URL('../src/WorkerContext.tsx', import.meta.url), 'utf8')
  const line = context.match(/worker\.stage === 'judge'\s*\? <p>([^<]+)<\/p>/u)?.[1] ?? ''
  assert.match(line, /judges read the signed charge and the work without Palace memories/iu)
  assert.match(line, /put any memory you want them to weigh in the charge/iu)
})

/** ADR-014 and G19-G20 require one current Deck surface for typed steering and exact lineage. */
test('The Deck exposes all three conductor interventions and an owner demand lineage', async () => {
  const [deck, rack, stage, daemon] = await Promise.all([
    readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/stageLayout.ts', import.meta.url), 'utf8'),
    readFile(new URL('../../src/harness/daemon.py', import.meta.url), 'utf8'),
  ])

  assert.match(deck, /Browse freely; steer the conductor here\. Workers are never directly addressable\./u)
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
