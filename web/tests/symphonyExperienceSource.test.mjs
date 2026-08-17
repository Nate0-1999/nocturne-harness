import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** ADR-012 requires deliberation to stay in chat while human-fixed criteria, judges, metrics,
 * and signed T2 authority cross one typed launch boundary and return one result card.
 */
test('Symphony deliberation is human-fixed, signed, separately identified, and returned inline', async () => {
  const [cards, app, protocol, socket, shell] = await Promise.all([
    readFile(new URL('../src/SymphonyCards.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/protocol.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/socket.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/shell.css', import.meta.url), 'utf8'),
  ])

  assert.match(cards, /No mode switch\. You fix what good means/u)
  assert.match(cards, /T2 AUTHORITY — real walls/u)
  assert.match(cards, /seat !== 'performance' \|\| charter\.metrics/u)
  assert.match(cards, /I authorize up to \{authority\.attempts\} attempts/u)
  assert.match(cards, /Sign & run toy Symphony/u)
  assert.match(cards, /You are already back in the live conversation/u)
  assert.match(app, /event\.event_kind === 'symphony_deliberation'/u)
  assert.match(app, /event\.event_kind === 'symphony_result'/u)
  assert.match(app, /!completedSymphonyDraftIds\.has\(event\.draft_id\)/u)
  assert.match(protocol, /judge_charters: SymphonyJudgeCharter\[\]/u)
  assert.match(protocol, /authority: SymphonyAuthority/u)
  assert.match(socket, /\[image, symphony, symphonyIntervention\]/u)
  assert.match(shell, /\.symphony-authority\s*\{[^}]*grid-template-columns:\s*repeat\(3/su)
  assert.match(shell, /@media \(max-width: 42rem\)[\s\S]*?\.symphony-authority\s*\{[^}]*grid-template-columns:\s*1fr/su)
})
