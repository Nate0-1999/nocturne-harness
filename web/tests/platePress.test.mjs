/** PLAN M2UX5, SPEC D.2 107-114, and B.6 r12: the press is deterministic data, not code. */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  COLORWAY_STORAGE_KEY,
  deriveColorway,
  loadColorways,
  saveColorways,
} from '../src/platePress.ts'

function pixelsFromHex(colors, repeats = 40) {
  const bytes = []
  for (const color of colors) {
    const channels = [1, 3, 5].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16))
    for (let index = 0; index < repeats; index += 1) bytes.push(...channels, 255)
  }
  return new Uint8ClampedArray(bytes)
}

const LAWFUL_COLORS = [
  '#05060f', '#0a0d1a', '#0d1226', '#141d3a', '#eef4fb', '#9fb0c9',
  '#6b7a99', '#5d8cf2', '#a5c4ff', '#db9969', '#d94048', '#69dfb0',
]

const SEAM = [
  {
    variable: '--seam-ground',
    neo_noir: '#03070c',
    seraph_dressed: '#05060f',
    gold_lines: '#d7e0ee',
  },
  {
    variable: '--seam-accent',
    neo_noir: '#38d7ff',
    seraph_dressed: '#5d8cf2',
    gold_lines: '#1c3fa8',
  },
]

/** PLAN M2UX5 and ADR-018 clause 7 keep intake, selection, removal, and iframe projection on one data path. */
test('the Rack exposes one file press path and projects only the validated record', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const bridge = readFileSync(new URL('../src/rackBridge.tsx', import.meta.url), 'utf8')
  assert.match(app, /data-testid="plate-press-input"/)
  assert.match(app, /accept="image\/png,image\/jpeg,image\/webp"/)
  assert.match(app, /data-testid="plate-remove-button"/)
  assert.match(app, /saveColorways\(globalThis\.localStorage, next\)/)
  assert.match(bridge, /applyColorwayTokens\(document\.documentElement, message\.colorway\)/)
})

/** D.2 107 and 114 require identical pixels and hash to emit byte-identical colorway data. */
test('double press is deterministic and emits only CSS token data', () => {
  const pixels = pixelsFromHex(LAWFUL_COLORS)
  const digest = 'a'.repeat(64)
  const first = deriveColorway(pixels, 24, 20, digest, SEAM)
  const second = deriveColorway(pixels, 24, 20, digest, SEAM)
  assert.deepEqual(second, first)
  assert.equal(first.ok, true)
  if (!first.ok) return
  assert.equal(first.colorway.id, `pressed-${'a'.repeat(16)}`)
  assert.equal(first.colorway.validation.passed, true)
  assert.equal(first.colorway.clusters.length, 12)
  assert.equal(first.colorway.tokens['--seam-ground']?.startsWith('#'), true)
  assert.equal(JSON.stringify(first.colorway).includes('<script'), false)
})

/** D.2 114 requires fail-closed validation with the failing visual pair named plainly. */
test('a low-contrast monochrome plate is refused with a named remedy', () => {
  const grays = Array.from({ length: 12 }, (_, index) => {
    const value = (96 + index).toString(16).padStart(2, '0')
    return `#${value}${value}${value}`
  })
  const result = deriveColorway(pixelsFromHex(grays), 24, 20, 'b'.repeat(64), SEAM)
  assert.equal(result.ok, false)
  if (result.ok) return
  assert.match(result.message, /accent \/ ground pair/i)
  assert.match(result.message, /wider range of color/i)
})

/** ADR-018 clause 7 and D.2 114 require removable local persistence with no code surface. */
test('stored colorways round-trip through the validated local data boundary', () => {
  const result = deriveColorway(pixelsFromHex(LAWFUL_COLORS), 24, 20, 'c'.repeat(64), SEAM)
  assert.equal(result.ok, true)
  if (!result.ok) return
  const values = new Map()
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  }
  saveColorways(storage, [result.colorway])
  assert.equal(values.has(COLORWAY_STORAGE_KEY), true)
  assert.deepEqual(loadColorways(storage), [result.colorway])
  values.set(COLORWAY_STORAGE_KEY, '[{"id":"pressed-evil","tokens":{"--x":"red;display:none"}}]')
  assert.deepEqual(loadColorways(storage), [])
})
