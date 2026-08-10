import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** A-051 keeps the authentic scoreboard legible inside the 226px collapsed Vitals iframe. */
test('narrow collapsed Vitals reserves its full row for learning before lower-priority cells', async () => {
  const css = await readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8')
  const breakpointStart = css.lastIndexOf('@media (max-width: 28rem)')
  const breakpointEnd = css.indexOf('@media (prefers-reduced-motion', breakpointStart)

  assert.ok(breakpointStart >= 0)
  assert.ok(breakpointEnd > breakpointStart)
  const breakpoint = css.slice(breakpointStart, breakpointEnd)
  assert.match(
    breakpoint,
    /\.vitals-strip--collapsed\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/u,
  )
  assert.match(
    breakpoint,
    /\.vitals-strip--collapsed\s*>\s*\.learning-summary--compact\s*\{[^}]*grid-template-columns:\s*repeat\(3, max-content\)[^}]*width:\s*100%/u,
  )
  assert.match(
    breakpoint,
    /\.vitals-strip--collapsed\s*>\s*\.vitals-collapsed-summary\s*,\s*\.vitals-strip--collapsed\s*>\s*\.vitals-reconciliation\s*\{\s*display:\s*none/u,
  )
  assert.doesNotMatch(breakpoint, /overflow-x:\s*auto/u)
})
