import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

/** PLAN M3CL2 (M3W5B-18): a gate frame inserted mid-run was never painted by the desktop pane,
 * an invisible layer over "Working…"; the frame stays mounted and opening a gate only shows it.
 * [P1.2.1c] */
test('the first-turn gate frame is always mounted and only its visibility follows the gate', async () => {
  const [app, css] = await Promise.all([source('App.tsx'), source('assets/rack.css')])

  assert.doesNotMatch(app, /\{openGate !== null && \(\s*<div className="rack-overlay-module" data-rack-module="gate"/u)
  assert.match(app, /data-rack-module="gate"\s*data-open=\{openGate !== null \|\| undefined\}/u)
  assert.match(css, /\.rack-overlay-module\[data-rack-module="gate"\]:not\(\[data-open\]\)\s*\{\s*visibility:\s*hidden;/u)
})

/** PLAN M3CL2 (Codex M3W5A-04): Enter advanced the Deck, then "Nothing sent" came back; the
 * card's conversation is opened and ready before the queue advances, and a failure says why.
 * [ADR-008, ADR-014] */
test('the Deck opens the card conversation before advancing and names why nothing was sent', async () => {
  const deck = await source('SymphonyDeck.tsx')
  const fire = deck.slice(deck.indexOf('async function fire('), deck.indexOf('  return (', deck.indexOf('async function fire(')))

  assert.ok(fire.indexOf('await threadReady(card.thread_id)') < fire.indexOf('setLocallyFired((current) => new Set(current).add'))
  assert.match(deck, /Nothing sent to \$\{card\.thread_title\}: \$\{why\(error\)\}\./u)
  assert.doesNotMatch(fire, /Check the connection and try again/u)
})
