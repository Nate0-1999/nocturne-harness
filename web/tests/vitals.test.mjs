import assert from 'node:assert/strict'
import test from 'node:test'

import {
  contiguousPolylineSegments,
  formatExactUsd,
  formatBytes,
  formatUptime,
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
    resources: {
      status: 'measured',
      daemon_rss_bytes: 134217728,
      daemon_uptime_seconds: 3661,
      disk_free_bytes: 107374182400,
      disk_total_bytes: 536870912000,
      database_bytes: 7864320,
      journal_bytes: 2048,
      backup_bytes: 4096,
      warning: null,
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

/** SPEC C.10 requires the client to render the canonical snapshot without creating a second accounting authority. */
test('parses the exact server-provided vitals shape without re-accounting', () => {
  const parsed = parseVitalsSnapshot(snapshot())

  assert.equal(parsed.spend.lanes[0].points[0].cost_usd, '0.035000000000')
  assert.equal(spendLaneId(parsed.spend.lanes[0]), 'total')
  assert.equal(parsed.palace_counts[1].status, 'placeholder')
  assert.equal(reconciliationCopy(parsed.reconciliation), 'Ledger drift · -$0.005')
  assert.equal(accountingCopy(parsed.accounting), 'Receipt drift · 2 lines pending')
  assert.equal(parsed.resources.database_bytes, 7864320)
  assert.equal(formatBytes(parsed.resources.disk_free_bytes), '100.0 GiB')
  assert.equal(formatUptime(parsed.resources.daemon_uptime_seconds), '1h 1m')
})

/** F026 and A-035 require CURRENT spend_event snapshots without widening GLOBAL's canonical source contract. */
test('accepts the exact current Vitals source and rejects unknown accounting sources', () => {
  const current = snapshot()
  current.spend.source_view = 'spend_event'
  assert.equal(parseVitalsSnapshot(current).spend.source_view, 'spend_event')

  const unknown = snapshot()
  unknown.spend.source_view = 'other_view'
  assert.throws(
    () => parseVitalsSnapshot(unknown),
    /must come from v_spend_rate or spend_event/,
  )
})

/** A-044 keeps missing process observations unavailable and preserves the low-disk signal. */
test('parses honest partial resource measurements without inventing zeroes', () => {
  const payload = snapshot()
  payload.resources.status = 'partial'
  payload.resources.daemon_rss_bytes = null
  payload.resources.warning = 'low_disk'

  const parsed = parseVitalsSnapshot(payload)

  assert.equal(formatBytes(parsed.resources.daemon_rss_bytes), 'Unavailable')
  assert.equal(parsed.resources.warning, 'low_disk')
})

/** A-034 preserves exact receipt decimals and visible unpriced state so browser arithmetic cannot hide uncertainty. */
test('preserves exact decimal scale and distinguishes an unpriced point', () => {
  assert.equal(formatExactUsd('0.035000000000'), '$0.035000000000')
  assert.equal(formatExactUsd('1200.00'), '$1,200.00')
  assert.equal(formatExactUsd(null), 'Awaiting price')
  assert.equal(unpricedCopy(1), '1 line awaiting a price')
})

/** SPEC C.10 forbids unavailable lifecycle data from masquerading as a measured zero. */
test('rejects unavailable gauges masquerading as measured zeroes', () => {
  const payload = snapshot()
  payload.lifecycle_rates[1].per_hour = 0

  assert.throws(
    () => parseVitalsSnapshot(payload),
    /unavailable gauges must not masquerade as zero/,
  )
})

/** SPEC C.10 requires scrubbing to retain server-provided values while presentation geometry may use numbers. */
test('finds scrub buckets and uses decimals only for SVG geometry', () => {
  const lane = parseVitalsSnapshot(snapshot()).spend.lanes[0]
  const nearest = nearestSpendPoint(lane.points, '2026-08-02T13:00:00Z', 0.99)
  const chart = laneChartPoints(lane, '2026-08-02T13:00:00Z')

  assert.equal(nearest?.minute, MINUTE_B)
  assert.equal(chart[0].point.cost_usd, '0.035000000000')
  assert.equal(chart[1].y, null)
  assert.ok(chart[0].x >= 0 && chart[0].x <= 100)
})

/** SPEC C.10 makes missing and unpriced buckets discontinuities so the rack cannot invent spend history. */
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

/** SPEC B.6 responsive law requires a collapsed rack to preserve rather than obscure the primary chat surface. */
test('collapse reallocates rows instead of overlaying Chat', () => {
  assert.deepEqual(rackBodyRowAllocation(4), {
    panelRows: 7,
    vitalsRows: 4,
    vitalsStart: 9,
  })
  assert.deepEqual(rackBodyRowAllocation(1), {
    panelRows: 10,
    vitalsRows: 1,
    vitalsStart: 12,
  })
})
