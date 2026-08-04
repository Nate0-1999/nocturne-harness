import assert from 'node:assert/strict'
import test from 'node:test'

import {
  contiguousPolylineSegments,
  formatExactUsd,
  laneChartPoints,
  nearestSpendPoint,
  accountingCopy,
  parseVitalsSnapshot,
  reconciliationCopy,
  spendLaneId,
  unpricedCopy,
} from '../src/vitals.ts'
import { rackBodyRowAllocation } from '../src/rackLayout.ts'

const MINUTE_A = '2026-08-02T12:20:00Z'
const MINUTE_B = '2026-08-02T12:59:00Z'

function snapshot() {
  return {
    as_of: '2026-08-02T13:00:00Z',
    window_minutes: 60,
    spend: {
      source_view: 'v_spend_rate',
      latest_minute: MINUTE_B,
      lanes: [
        {
          dimension: 'total',
          key: null,
          label: 'All spend',
          points: [
            {
              minute: MINUTE_A,
              cost_usd: '0.035000000000',
              receipt_lines: 3,
              unpriced_lines: 0,
            },
            {
              minute: MINUTE_B,
              cost_usd: null,
              receipt_lines: 1,
              unpriced_lines: 1,
            },
          ],
        },
      ],
    },
    reconciliation: {
      status: 'drift',
      checked_at: '2026-08-02T12:59:30Z',
      broker_usage_usd: '10.040000000000',
      ledger_cost_usd: '0.035000000000',
      broker_since_baseline_usd: '0.040000000000',
      ledger_since_baseline_usd: '0.035000000000',
      drift_usd: '-0.005000000000',
      tolerance_usd: '0.000001000000',
      unpriced_lines: 1,
      source: 'openrouter:/api/v1/key',
      error_code: null,
    },
    accounting: {
      status: 'pending',
      pending_lines: 2,
      oldest_queued_at: '2026-08-02T12:58:00Z',
      source: 'harness.receipt_queue',
    },
    lifecycle_rates: [
      {
        metric: 'created',
        status: 'measured',
        per_hour: 3,
        source: 'memory_unit.created_at',
      },
      {
        metric: 'reinforced',
        status: 'not_recorded',
        per_hour: null,
        source: null,
      },
    ],
    palace_counts: [
      {
        metric: 'active_units',
        status: 'measured',
        count: 12,
        source: 'memory_unit.status',
      },
      {
        metric: 'queue_depth',
        status: 'placeholder',
        count: null,
        source: null,
      },
    ],
  }
}

test('parses the exact server-provided vitals shape without re-accounting', () => {
  const parsed = parseVitalsSnapshot(snapshot())

  assert.equal(parsed.spend.lanes[0].points[0].cost_usd, '0.035000000000')
  assert.equal(spendLaneId(parsed.spend.lanes[0]), 'total')
  assert.equal(parsed.palace_counts[1].status, 'placeholder')
  assert.equal(reconciliationCopy(parsed.reconciliation), 'Ledger drift · -$0.005000000000')
  assert.equal(accountingCopy(parsed.accounting), 'Receipt drift · 2 lines pending')
})

test('preserves exact decimal scale and distinguishes an unpriced point', () => {
  assert.equal(formatExactUsd('0.035000000000'), '$0.035000000000')
  assert.equal(formatExactUsd('1200.00'), '$1,200.00')
  assert.equal(formatExactUsd(null), 'Awaiting price')
  assert.equal(unpricedCopy(1), '1 line awaiting a price')
})

test('rejects unavailable gauges masquerading as measured zeroes', () => {
  const payload = snapshot()
  payload.lifecycle_rates[1].per_hour = 0

  assert.throws(
    () => parseVitalsSnapshot(payload),
    /unavailable gauges must not masquerade as zero/,
  )
})

test('finds scrub buckets and uses decimals only for SVG geometry', () => {
  const lane = parseVitalsSnapshot(snapshot()).spend.lanes[0]
  const nearest = nearestSpendPoint(lane.points, '2026-08-02T13:00:00Z', 0.99)
  const chart = laneChartPoints(lane, '2026-08-02T13:00:00Z')

  assert.equal(nearest?.minute, MINUTE_B)
  assert.equal(chart[0].point.cost_usd, '0.035000000000')
  assert.equal(chart[1].y, null)
  assert.ok(chart[0].x >= 0 && chart[0].x <= 100)
})

test('does not invent a trend line across empty or unpriced minute buckets', () => {
  const point = (minute, x, y) => ({
    point: { minute, cost_usd: y === null ? null : '1', receipt_lines: 1, unpriced_lines: 0 },
    x,
    y,
  })
  const segments = contiguousPolylineSegments([
    point('2026-08-02T12:00:00Z', 0, 20),
    point('2026-08-02T12:01:00Z', 10, 10),
    point('2026-08-02T12:03:00Z', 30, 5),
    point('2026-08-02T12:04:00Z', 40, null),
    point('2026-08-02T12:05:00Z', 50, 8),
  ])

  assert.deepEqual(segments, ['0,20 10,10', '30,5', '50,8'])
})

test('collapse reallocates rows instead of overlaying Chat', () => {
  assert.deepEqual(rackBodyRowAllocation(false), {
    panelRows: 7,
    vitalsRows: 4,
    vitalsStart: 9,
  })
  assert.deepEqual(rackBodyRowAllocation(true), {
    panelRows: 10,
    vitalsRows: 1,
    vitalsStart: 12,
  })
})
