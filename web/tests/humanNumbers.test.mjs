import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  formatHumanCount,
  formatHumanPercent,
  formatHumanQuantity,
  formatHumanUsd,
} from '../src/humanNumbers.ts'

/** PLAN M2ST3 and SPEC P2.4 require human display precision without changing exact accounting inputs. */
test('formats money, percentages, and quantities for a glanceable instrument', () => {
  assert.equal(formatHumanUsd('1200.000000000000'), '$1,200.00')
  assert.equal(formatHumanUsd('-0.084555772000'), '-$0.08')
  assert.equal(formatHumanUsd('0.000084555772'), '$0.0000846')
  assert.equal(formatHumanPercent('11.1111111111111111'), '11.1%')
  assert.equal(formatHumanQuantity('12.345678'), '12.3')
  assert.equal(formatHumanCount(12_345), '12.3K')
})

/** SPEC P2.4 and PLAN M2ST3 keep malformed display inputs loud instead of silently inventing a number. */
test('rejects non-decimal money and non-finite measurements', () => {
  assert.throws(() => formatHumanUsd('1e-8'), /exact decimal string/u)
  assert.throws(() => formatHumanPercent(Number.NaN), /must be finite/u)
})

/** SPEC P2.4 and PLAN M2ST3 make Spend the owner-facing identity of the former Palace Vitals module. */
test('names the owner-facing instrument Spend at the production manifest seam', async () => {
  const rack = await readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8')

  assert.match(rack, /vitals:\s*\{[\s\S]*?name:\s*'Spend'/u)
})
