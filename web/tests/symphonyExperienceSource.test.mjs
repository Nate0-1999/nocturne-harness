import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** ADR-012 requires deliberation to stay in chat while human-fixed criteria, judges, metrics,
 * and signed T2 authority cross one typed launch boundary and return one result card.
 */
test('Symphony deliberation is human-fixed, signed, separately identified, and returned inline', async () => {
  const [cards, app, protocol, shell] = await Promise.all([
    readFile(new URL('../src/SymphonyCards.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/protocol.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/shell.css', import.meta.url), 'utf8'),
  ])

  assert.match(cards, /Fix what good means before the conductor can fire/u)
  assert.match(cards, /T2 AUTHORITY — real walls/u)
  assert.match(cards, /seat !== 'performance' \|\| charter\.metrics/u)
  assert.match(cards, /I authorize up to \{counted\(authority\.attempts, 'attempt'\)\}/u)
  assert.match(cards, /Sign & run Symphony/u)
  assert.match(cards, /You are already back in the live conversation/u)
  assert.match(app, /event\.event_kind === 'symphony_deliberation'/u)
  assert.match(app, /event\.event_kind === 'symphony_result'/u)
  assert.match(app, /symphonyLaunches\.get\(event\.draft_id\)\?\.state !== 'completed'/u)
  assert.match(protocol, /judge_charters: SymphonyJudgeCharter\[\]/u)
  assert.match(protocol, /authority: SymphonyAuthority/u)
  assert.match(shell, /\.symphony-authority\s*\{[^}]*grid-template-columns:\s*repeat\(3/su)
  assert.match(shell, /@media \(max-width: 42rem\)[\s\S]*?\.symphony-authority\s*\{[^}]*grid-template-columns:\s*1fr/su)
})

/** M3SF / M3EX-08, -11, -12: the chat and the Deck show the live state; a launched draft
 * re-renders what was signed and cannot be signed again until its run is blocked.
 */
test('Symphony cards show the signed charter and the live state, never a stale running', async () => {
  const [cards, app, deck, shell, runtime] = await Promise.all([
    readFile(new URL('../src/SymphonyCards.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/SymphonyDeck.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/shell.css', import.meta.url), 'utf8'),
    readFile(new URL('../../src/harness/symphony_experience.py', import.meta.url), 'utf8'),
  ])

  assert.match(cards, /useState\(signedLaunch\?\.objective \?\? draft\?\.objective/u)
  assert.match(cards, /<fieldset className="symphony-card__form" disabled=\{locked\}>/u)
  assert.match(cards, /locked \? 'Signed · running'/u)
  assert.match(cards, /'Sign & run again'/u)
  assert.match(cards, /counted\(authority\.max_rounds, 'round'\)/u)
  assert.match(cards, /counted\(authority\.children_per_attempt, 'child', 'children'\)/u)
  assert.match(cards, /<h3>\{blocked \? 'Blocked' : 'Running'\}<\/h3>/u)
  assert.match(app, /<SymphonyStatusCard stack=\{symphonyStack\} \/>/u)
  assert.match(deck, /` · \$\{blockedCount\} blocked`/u)
  assert.match(shell, /\.chat-header > details\[open\] \{\s*grid-column: 1 \/ -1;/u)
  assert.doesNotMatch(runtime, /is running in its own worktrees/u)
})
