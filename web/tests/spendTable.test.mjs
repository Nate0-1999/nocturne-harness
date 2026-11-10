import assert from 'node:assert/strict'
import test from 'node:test'

import { parseSpendTableSnapshot, partialSpendCopy, spendPolylines, spendSeries } from '../src/spendTable.ts'

const metrics = (overrides = {}) => ({
  input_tokens: '1200.5',
  kv_cache_tokens: '400',
  reasoning_tokens: '72',
  output_tokens: '180',
  total_usd: '0.042500000000',
  total_receipt_lines: 4,
  total_unpriced_lines: 0,
  spend_per_hour_usd: '0.012500000000',
  hourly_receipt_lines: 2,
  hourly_unpriced_lines: 0,
  ...overrides,
})

const snapshot = () => ({
  as_of: '2026-08-31T17:00:00Z',
  window_minutes: 60,
  threads: [{
    thread_id: '22345678-1234-5678-1234-567812345678',
    models: [
      { model: 'openai/gpt-5.4', ...metrics() },
      { model: 'openai/gpt-5.4-mini', ...metrics({ reasoning_tokens: '0' }) },
    ],
    ...metrics({ total_usd: '0.085000000000', total_receipt_lines: 8 }),
  }],
  purposes: [{ purpose: 'embedding', label: 'Embeddings', ...metrics() }],
})

/** ADR-024 keeps exact server-authored token buckets and nested model rows at the browser seam. */
test('parses conversation, model, reasoning, cache, and purpose rows without re-accounting', () => {
  const parsed = parseSpendTableSnapshot(snapshot())

  assert.equal(parsed.threads[0].models.length, 2)
  assert.equal(parsed.threads[0].models[0].reasoning_tokens, '72')
  assert.equal(parsed.threads[0].models[0].kv_cache_tokens, '400')
  assert.equal(parsed.purposes[0].label, 'Embeddings')
})

/** ADR-024 requires partial pricing to remain visible rather than silently becoming zero. */
test('keeps partial pricing explicit and rejects impossible receipt counts', () => {
  const payload = snapshot()
  payload.purposes[0] = {
    purpose: 'curation',
    label: 'Memory keeping',
    ...metrics({
      total_usd: '0.010000000000',
      total_unpriced_lines: 1,
      spend_per_hour_usd: null,
      hourly_receipt_lines: 1,
      hourly_unpriced_lines: 1,
    }),
  }
  const row = parseSpendTableSnapshot(payload).purposes[0]
  assert.equal(partialSpendCopy(row), '1 line has no provider-reported price. No later price is pending.')

  payload.purposes[0].total_unpriced_lines = 5
  assert.throws(() => parseSpendTableSnapshot(payload), /impossible unpriced receipt counts/u)
})

/** ADR-024 ATTUNED projections may truthfully contain no rows, but never duplicate a grouping. */
test('accepts an empty attuned slice and rejects duplicate conversation rows', () => {
  assert.deepEqual(
    parseSpendTableSnapshot({ ...snapshot(), threads: [], purposes: [] }).threads,
    [],
  )
  const payload = snapshot()
  payload.threads.push(structuredClone(payload.threads[0]))
  assert.throws(() => parseSpendTableSnapshot(payload), /thread rows must be unique/u)
})

/** SPEC C.10 / ADR-024: an unpriced minute is a gap, never a zero, so the strip cannot invent spend history. */
test('the strip breaks a line at an unpriced minute and shares one scale', () => {
  const point = (minute, cost, unpriced = 0) => ({ minute: `2026-08-31T16:${minute}:00Z`, cost_usd: cost, receipt_lines: 1, unpriced_lines: unpriced })
  const lane = (dimension, key, points) => ({ dimension, key, label: dimension, points })
  const { series, peak, minutes } = spendSeries({
    ...parseSpendTableSnapshot(snapshot()),
    rates: [
      lane('total', null, [point('51', '0.004'), point('53', null, 1), point('55', '0.002')]),
      lane('curation', 'curation', [point('55', '0.001')]),
    ],
  }, '10m')
  const total = series.find((entry) => entry.dimension === 'total')
  assert.equal(minutes.length, 10)
  assert.equal(peak, 0.004)
  assert.equal(total.unpriced, 1)
  assert.equal(spendPolylines(total.lines[0].values, minutes[0], minutes.at(-1), peak).length, 2)
})
