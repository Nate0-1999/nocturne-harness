import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** F040, ADR-004, and B.6 r12 require a confirmed Edit Save to remain visible
 * until the owner dismisses it instead of silently dropping the editor.
 */
test('keeps the memory editor mounted for its authoritative save result', async () => {
  const source = await readFile(new URL('../src/MemoryPanel.tsx', import.meta.url), 'utf8')

  assert.match(source, /const editing =\s*editor\?\.memoryId === memory\.memory_id/u)
  assert.doesNotMatch(source, /editor\?\.memoryId === memory\.memory_id && !editSaved/u)
  assert.match(source, /Saved\. Per-message scoring refreshes this thread/u)
  assert.match(source, /\{editSaved \? 'Done' : 'Cancel'\}/u)
  assert.match(source, /async function saveEdit\(\)/u)
  assert.match(source, /onClick=\{\(\) => \{ void saveEdit\(\) \}\}/u)
  assert.match(source, /function submitEdit[\s\S]*?void saveEdit\(\)/u)
})

/** M3EX-17 / P1.2.1a: the reason picked in the Memory module's delete dialog is the
 * reason recorded; the module never drops it on the way to the rack action.
 */
test('the Memory module forwards the chosen delete reason', async () => {
  const source = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')

  assert.match(source, /onDelete=\{\(memoryId, expectedRevision, reason\) => events\.dispatch\(\{\s*type: 'memory\.delete', memory_id: memoryId, expected_revision: expectedRevision, reason,/u)
})

/** M3EX-18 / A-072: a deleted memory selected in the Memory Graph offers Restore,
 * which reaches the daemon as the compare-and-set restore request.
 */
test('the Memory Graph restores a deleted memory', async () => {
  const graph = await readFile(new URL('../src/MemoryGraph.tsx', import.meta.url), 'utf8')
  const rack = await readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8')
  const socket = await readFile(new URL('../src/socket.ts', import.meta.url), 'utf8')

  assert.match(graph, /selected\.memory\.status === 'tombstoned' \?[\s\S]*?type: 'memory\.restore', memory_id: selected\.memory\.memory_id, expected_revision: selected\.memory\.revision/u)
  assert.match(rack, /memory_graph: \{[\s\S]*?'memory\.delete', 'memory\.restore'/u)
  assert.match(rack, /case 'memory\.restore':\s*return harnessClient\.restoreMemory\(action\.memory_id, action\.expected_revision\)/u)
  assert.match(socket, /action: 'restore', memory_id: memoryId, expected_revision: expectedRevision/u)
})

/** TASTE-06 / P1.2.1c: the Memory module's card is score, name and memory;
 * revision history sits in the hover panel and opening the origin conversation is a
 * small row action, not a line on the card.
 */
test('the memory card keeps history behind the hover and the link as a row action', async () => {
  const source = await readFile(new URL('../src/MemoryPanel.tsx', import.meta.url), 'utf8')

  assert.match(source, /<Provenance term="History">\s*<ol className="memory-card__history">/u)
  assert.match(source, /<Button action="open" iconOnly className="memory-card__remove"[\s\S]*?Open the conversation<\/Button>\s*\)\}\s*<Button action="delete" iconOnly variant="danger"/u)
  assert.doesNotMatch(source, /Revision history · r/u)
  assert.doesNotMatch(source, /Open the conversation ↗/u)
})
