import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** M3EX-26 / P2: a hover tip never outlives the pointer — over no control, leaving a
 * module frame, or the window losing focus hides it; only keyboard focus raises one.
 */
test('hover tips hide when the pointer or the window leaves', async () => {
  const source = await readFile(new URL('../src/ControlTooltip.tsx', import.meta.url), 'utf8')

  assert.match(source, /if \(control === null\) hide\(activeControl\)/u)
  assert.match(source, /document\.documentElement\.addEventListener\('pointerleave', onLeave\)/u)
  assert.match(source, /globalThis\.addEventListener\('blur', onLeave\)/u)
  assert.match(source, /control\.matches\(':focus-visible'\)/u)
})
