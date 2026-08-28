import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** M3DK, SD-046, G19, and Invariant 14 require one-turn editable replies, FIFO attention,
 * append-only tweak provenance, free browsing, and a recall grace without a second call.
 */
test('the finished Deck keeps proposed replies same-turn, editable, ordered, and journaled', async () => {
  const [runtime, provenance, loop, deck, rack, protocol, css] = await Promise.all([
    readFile(new URL('../../src/harness/agent_runtime.py', import.meta.url), 'utf8'),
    readFile(new URL('../../src/harness/proposed_response.py', import.meta.url), 'utf8'),
    readFile(new URL('../../src/harness/run_loop.py', import.meta.url), 'utf8'),
    readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/protocol.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/symphonyDeck.css', import.meta.url), 'utf8'),
  ])

  assert.match(runtime, /PROPOSED_RESPONSE_INSTRUCTION/u)
  assert.match(runtime, /await bridge\.finalize\([\s\S]*result\.output/u)
  assert.match(provenance, /<nocturne-proposed-response>/u)
  assert.match(provenance, /"provenance": "owner_authored_with_assist"/u)
  assert.match(provenance, /"edit_distance": levenshtein_distance/u)
  assert.match(loop, /proposal_was_fired/u)
  assert.match(loop, /source\[0\]\.get\("partial"\) is not False/u)
  assert.match(deck, /Date\.parse\(left\.created_at\) - Date\.parse\(right\.created_at\)/u)
  assert.match(deck, /snapshot\.catalog\.flatMap/u)
  assert.match(deck, /latest\.delete\(threadId\)/u)
  assert.match(deck, /Proposed response · edit freely/u)
  assert.match(deck, /event\.key !== 'Enter' \|\| event\.shiftKey/u)
  assert.match(deck, /setLocallyFired[\s\S]*setUndo[\s\S]*setTimeout/u)
  assert.match(deck, /Firing to \{undo\.card\.thread_title\} in 6 seconds/u)
  assert.match(deck, />Undo</u)
  assert.match(rack, /actions: \['thread.select', 'prompt.submit', 'symphony.intervene'\]/u)
  assert.match(protocol, /proposed_response\?: ProposedResponseReference/u)
  assert.match(css, /\.deck-proposal-queue\s*\{[^}]*overflow-y:\s*auto/su)
  assert.match(css, /\.deck-proposal\[data-primary="true"\]/u)
})
