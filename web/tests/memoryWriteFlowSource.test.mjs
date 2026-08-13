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
