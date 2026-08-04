import {
  useEffect,
  useId,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import { useRackPlugin, useRackSelection, useRackSnapshot } from './rack'
import {
  accountingCopy,
  contiguousPolylineSegments,
  formatExactUsd,
  laneChartPoints,
  latestSpendPoint,
  nearestSpendPoint,
  parseVitalsSnapshot,
  reconciliationCopy,
  spendLaneId,
  unpricedCopy,
  type GaugeStatus,
  type SpendLane,
  type VitalsSnapshot,
} from './vitals'

type LoadPhase = 'loading' | 'live' | 'refreshing' | 'stale' | 'failed'

interface VitalsLoadState {
  snapshot: VitalsSnapshot | null
  phase: LoadPhase
  failed: boolean
}

const METRIC_LABELS: Record<string, string> = {
  created: 'Created',
  reinforced: 'Reinforced',
  superseded: 'Superseded',
  merged: 'Merged',
  quarantined: 'Quarantined',
  tombstoned: 'Tombstoned',
  add_backs: 'Add-backs',
  active_units: 'Active units',
  pinned_units: 'Pinned units',
  candidates_pending: 'Candidates pending',
  edges: 'Edges',
  staged_units: 'Staged units',
  queue_depth: 'Queue depth',
}

const minuteFormatter = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
})

const countFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 3,
})

export function VitalsModule() {
  const { events, query, selection: selectionBus } = useRackPlugin()
  const selection = useRackSelection()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL' | 'CURRENT'>('GLOBAL')
  const [requestSequence, setRequestSequence] = useState(0)
  const [load, setLoad] = useState<VitalsLoadState>({
    snapshot: null,
    phase: 'loading',
    failed: false,
  })
  const [collapsed, setCollapsed] = useState(() => globalThis.innerHeight < 120)
  const [hoveredMinute, setHoveredMinute] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void query.query({
      resource: 'vitals', as_of: 'now',
      thread_id: scope === 'CURRENT' ? rack.selectedThreadId ?? undefined : undefined,
    })
      .then((result) => {
        if (result.status !== 'live' || result.data === null) {
          throw new TypeError('Live Palace vitals were not returned')
        }
        const snapshot = parseVitalsSnapshot(result.data)
        if (active) {
          setLoad({ snapshot, phase: 'live', failed: false })
        }
      })
      .catch(() => {
        if (active) {
          setLoad((current) => ({
            ...current,
            phase: current.snapshot === null ? 'failed' : 'stale',
            failed: true,
          }))
        }
      })
    return () => {
      active = false
    }
  }, [query, rack.selectedThreadId, requestSequence, scope])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'vitals' }).then(setScope)
  }, [events])

  useEffect(() => {
    const interval = globalThis.setInterval(() => {
      setRequestSequence((value) => value + 1)
    }, 60_000)
    return () => globalThis.clearInterval(interval)
  }, [])

  useEffect(() => {
    return events.subscribeResize((event) => {
      setCollapsed(event.grid_height === 1)
    })
  }, [events])

  function refresh() {
    setLoad((current) => ({
      ...current,
      phase: current.snapshot === null ? 'loading' : 'refreshing',
      failed: false,
    }))
    setRequestSequence((value) => value + 1)
  }

  if (load.snapshot === null) {
    return (
      <section className="vitals-strip vitals-strip--empty" aria-label="Palace vitals">
        <p className="vitals-strip__notice" role={load.phase === 'failed' ? 'alert' : 'status'}>
          {load.phase === 'failed'
            ? 'Vitals couldn’t refresh. Chat is still available.'
            : 'Reading the Palace vitals…'}
        </p>
        {load.phase === 'failed' && (
          <button className="vitals-refresh" type="button" onClick={refresh}>
            Try again
          </button>
        )}
      </section>
    )
  }

  const snapshot = load.snapshot
  const totalLane = snapshot.spend.lanes.find((lane) => lane.dimension === 'total') ?? null
  const defaultLane = totalLane ?? snapshot.spend.lanes[0] ?? null
  const laneIds = new Set(snapshot.spend.lanes.map(spendLaneId))
  const requestedLaneId = selection?.kind === 'spend_lane' ? selection.id : null
  const focusedLaneId = requestedLaneId !== null && laneIds.has(requestedLaneId)
    ? requestedLaneId
    : defaultLane === null
      ? null
      : spendLaneId(defaultLane)
  const snapshotMinutes = new Set(
    snapshot.spend.lanes.flatMap((lane) => lane.points.map((point) => point.minute)),
  )
  const requestedMinute = selection?.kind === 'spend_lane' ? selection.as_of : null
  const selectedMinute = requestedMinute !== null && snapshotMinutes.has(requestedMinute)
    ? requestedMinute
    : null
  const liveHoveredMinute = hoveredMinute !== null && snapshotMinutes.has(hoveredMinute)
    ? hoveredMinute
    : null
  const sharedMinute = liveHoveredMinute ?? selectedMinute ?? snapshot.spend.latest_minute
  const hasSpend = snapshot.spend.lanes.some((lane) => lane.points.length > 0)

  function focusLane(lane: SpendLane, asOf: string | null) {
    setHoveredMinute(asOf)
    selectionBus.select({
      kind: 'spend_lane',
      id: spendLaneId(lane),
      as_of: asOf,
    })
  }

  function scrub(asOf: string) {
    setHoveredMinute(asOf)
    if (focusedLaneId !== null) {
      selectionBus.select({ kind: 'spend_lane', id: focusedLaneId, as_of: asOf })
    }
  }

  if (collapsed) {
    const totalPoint = totalLane === null ? null : latestSpendPoint(totalLane)
    const partial = totalPoint === null ? null : unpricedCopy(totalPoint.unpriced_lines)
    return (
      <section
        className="vitals-strip vitals-strip--collapsed"
        aria-label="Palace vitals"
        data-failed={load.failed}
      >
        <button
          className="vitals-collapsed-summary"
          type="button"
          disabled={totalLane === null || totalPoint === null}
          onClick={() => {
            if (totalLane !== null && totalPoint !== null) {
              focusLane(totalLane, totalPoint.minute)
            }
          }}
        >
          <span>Spend · latest minute</span>
          <strong>{totalPoint === null ? 'No spend recorded' : formatExactUsd(totalPoint.cost_usd)}</strong>
          {partial !== null && <em>Partial · {partial}</em>}
          <small>
            {totalPoint === null
              ? `Through ${formatMinute(snapshot.as_of)}`
              : `At ${formatMinute(totalPoint.minute)}`}
          </small>
        </button>
        <span
          className={`vitals-reconciliation vitals-reconciliation--${snapshot.reconciliation.status}`}
          title="Palace-wide broker audit"
        >
          {reconciliationCopy(snapshot.reconciliation)}
        </span>
        {snapshot.accounting.status !== 'clear' && (
          <span
            className={`vitals-reconciliation vitals-reconciliation--${snapshot.accounting.status}`}
            title="Owner-local receipt queue"
          >
            {accountingCopy(snapshot.accounting)}
          </span>
        )}
        {load.failed && (
          <span className="vitals-inline-failure" role="alert">
            Vitals couldn’t refresh. Chat is still available.
          </span>
        )}
      </section>
    )
  }

  return (
    <section className="vitals-strip vitals-strip--expanded" aria-label="Palace vitals">
      <header className="vitals-strip__header">
        <p>
          Spend · last hour
          <span>Through {formatMinute(snapshot.as_of)}</span>
        </p>
        <div className="vitals-strip__status" aria-live="polite">
          <div className="scope-switch" aria-label="Vitals scope">
            <button aria-pressed={scope === 'GLOBAL'} onClick={() => { setScope('GLOBAL'); void events.dispatch({ type: 'rack.scope.set', module_id: 'vitals', scope: 'GLOBAL' }) }}>Global</button>
            <button aria-pressed={scope === 'CURRENT'} onClick={() => { setScope('CURRENT'); void events.dispatch({ type: 'rack.scope.set', module_id: 'vitals', scope: 'CURRENT' }) }}>Current</button>
          </div>
          {load.failed && (
            <span role="alert">Vitals couldn’t refresh. Chat is still available.</span>
          )}
          {load.phase === 'refreshing' && <span>Refreshing…</span>}
          <button className="vitals-refresh" type="button" onClick={refresh}>
            Refresh
          </button>
        </div>
      </header>

      <div
        className={`vitals-reconciliation vitals-reconciliation--${snapshot.reconciliation.status}`}
        title="Palace-wide broker audit"
      >
        {reconciliationCopy(snapshot.reconciliation)}
      </div>
      {snapshot.accounting.status !== 'clear' && (
        <div
          className={`vitals-reconciliation vitals-reconciliation--${snapshot.accounting.status}`}
          title="Owner-local receipt queue"
        >
          {accountingCopy(snapshot.accounting)}
        </div>
      )}

      <div className="vitals-gauges" aria-label="Lifecycle and Palace gauges">
        {snapshot.lifecycle_rates.map((gauge) => (
          <Gauge
            key={`rate:${gauge.metric}`}
            metric={gauge.metric}
            status={gauge.status}
            source={gauge.source}
            value={gauge.per_hour}
            suffix="/hr"
          />
        ))}
        {snapshot.palace_counts.map((gauge) => (
          <Gauge
            key={`count:${gauge.metric}`}
            metric={gauge.metric}
            status={gauge.status}
            source={gauge.source}
            value={gauge.count}
          />
        ))}
      </div>

      {!hasSpend ? (
        <p className="vitals-spend-empty">No spend recorded in this window.</p>
      ) : (
        <div
          className={`vitals-lanes${focusedLaneId === null ? '' : ' vitals-lanes--focused'}`}
          aria-label="Server-provided spend lanes"
        >
          {snapshot.spend.lanes.map((lane) => (
            <SpendLaneRow
              key={spendLaneId(lane)}
              lane={lane}
              snapshot={snapshot}
              focused={focusedLaneId === spendLaneId(lane)}
              sharedMinute={sharedMinute}
              onFocus={focusLane}
              onScrub={scrub}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function Gauge({
  metric,
  status,
  source,
  value,
  suffix = '',
}: {
  metric: string
  status: GaugeStatus
  source: string | null
  value: number | null
  suffix?: string
}) {
  const copy = status === 'measured' && value !== null
    ? `${countFormatter.format(value)}${suffix}`
    : status === 'placeholder'
      ? 'Not active yet'
      : 'Not recorded yet'
  return (
    <div
      className={`vitals-gauge vitals-gauge--${status}`}
      data-source={source ?? undefined}
    >
      <span>{METRIC_LABELS[metric] ?? metric.replaceAll('_', ' ')}</span>
      <strong>{copy}</strong>
    </div>
  )
}

function SpendLaneRow({
  lane,
  snapshot,
  focused,
  sharedMinute,
  onFocus,
  onScrub,
}: {
  lane: SpendLane
  snapshot: VitalsSnapshot
  focused: boolean
  sharedMinute: string | null
  onFocus: (lane: SpendLane, asOf: string | null) => void
  onScrub: (asOf: string) => void
}) {
  const descriptionId = useId()
  const chartPoints = laneChartPoints(lane, snapshot.as_of, snapshot.window_minutes)
  const point = sharedMinute === null
    ? latestSpendPoint(lane)
    : lane.points.find((entry) => entry.minute === sharedMinute) ?? null
  const missingSharedBucket = sharedMinute !== null && point === null
  const cursorPoint = point === null
    ? null
    : chartPoints.find((entry) => entry.point.minute === point.minute) ?? null
  const cursorX = sharedMinute === null
    ? cursorPoint?.x ?? null
    : chartX(sharedMinute, snapshot.as_of, snapshot.window_minutes)
  const partial = point === null ? null : unpricedCopy(point.unpriced_lines)
  const segments = contiguousPolylineSegments(chartPoints)
  const accessibleCost = missingSharedBucket
    ? formatExactUsd('0')
    : point === null
      ? 'No samples'
      : formatExactUsd(point.cost_usd)
  const accessibleMinute = missingSharedBucket
    ? formatMinute(sharedMinute ?? snapshot.as_of)
    : point === null
      ? 'this window'
      : formatMinute(point.minute)
  const accessibleReceipts = missingSharedBucket ? 0 : point?.receipt_lines ?? 0

  function scrubFromPointer(event: ReactPointerEvent<HTMLDivElement>) {
    const chart = event.currentTarget.querySelector('svg')
    if (!(chart instanceof SVGSVGElement)) {
      return
    }
    const rect = chart.getBoundingClientRect()
    if (event.clientX < rect.left || event.clientX > rect.right) {
      return
    }
    const nearest = nearestSpendPoint(
      lane.points,
      snapshot.as_of,
      rect.width === 0 ? 1 : (event.clientX - rect.left) / rect.width,
      snapshot.window_minutes,
    )
    if (nearest !== null) {
      onScrub(nearest.minute)
    }
  }

  function scrubFromKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (
      (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') ||
      lane.points.length === 0
    ) {
      return
    }
    event.preventDefault()
    const exactIndex = sharedMinute === null
      ? -1
      : lane.points.findIndex((entry) => entry.minute === sharedMinute)
    const currentIndex = exactIndex < 0 ? lane.points.length - 1 : exactIndex
    const delta = event.key === 'ArrowLeft' ? -1 : 1
    const nextIndex = Math.max(0, Math.min(lane.points.length - 1, currentIndex + delta))
    onScrub(lane.points[nextIndex].minute)
  }

  const sliderMinute = sharedMinute ?? latestSpendPoint(lane)?.minute ?? snapshot.as_of
  const sliderValue = Math.max(
    0,
    Math.min(
      snapshot.window_minutes,
      Math.round(
        (Date.parse(sliderMinute) - (
          Date.parse(snapshot.as_of) - snapshot.window_minutes * 60_000
        )) / 60_000,
      ),
    ),
  )

  return (
    <div
      className={`vitals-lane${focused ? ' vitals-lane--selected' : ''}`}
    >
      <button
        className="vitals-lane__identity"
        type="button"
        aria-pressed={focused}
        aria-label={`${lane.label} spend lane`}
        onClick={() => onFocus(lane, sharedMinute ?? latestSpendPoint(lane)?.minute ?? null)}
      >
        <span>{dimensionLabel(lane.dimension)}</span>
        <strong>{lane.label}</strong>
      </button>
      <div
        className="vitals-lane__scrubber"
        role="slider"
        tabIndex={0}
        aria-label={`${lane.label} spend timeline`}
        aria-describedby={descriptionId}
        aria-valuemin={0}
        aria-valuemax={snapshot.window_minutes}
        aria-valuenow={sliderValue}
        aria-valuetext={`${accessibleCost} at ${accessibleMinute}, ${receiptCopy(accessibleReceipts)}`}
        onKeyDown={scrubFromKeyboard}
        onClick={() => onFocus(lane, sharedMinute ?? latestSpendPoint(lane)?.minute ?? null)}
        onPointerDown={(event) => {
          if (event.pointerType !== 'mouse') {
            event.currentTarget.setPointerCapture(event.pointerId)
          }
          scrubFromPointer(event)
        }}
        onPointerMove={(event) => {
          if (event.pointerType === 'mouse' || event.buttons > 0) {
            scrubFromPointer(event)
          }
        }}
      >
        <svg
          className="vitals-lane__chart"
          viewBox="0 0 100 24"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <line className="vitals-chart__axis" x1="0" y1="21" x2="100" y2="21" />
          {segments.map((segment, index) => (
            <polyline key={index} className="vitals-chart__line" points={segment} />
          ))}
          {chartPoints.map((entry) => entry.y === null ? (
            <path
              key={`unpriced:${entry.point.minute}`}
              className="vitals-chart__unpriced"
              d={`M ${entry.x - 1.3} 18 L ${entry.x} 16.5 L ${entry.x + 1.3} 18 L ${entry.x} 19.5 Z`}
            />
          ) : (
            <circle
              key={`priced:${entry.point.minute}`}
              className="vitals-chart__point"
              cx={entry.x}
              cy={entry.y}
              r="0.9"
            />
          ))}
          {cursorX !== null && (
            <>
              <line
                className="vitals-chart__cursor"
                x1={cursorX}
                y1="1"
                x2={cursorX}
                y2="23"
              />
              {cursorPoint?.y !== null && cursorPoint?.y !== undefined && (
                <circle
                  className="vitals-chart__cursor-point"
                  cx={cursorX}
                  cy={cursorPoint.y}
                  r="1.6"
                />
              )}
            </>
          )}
        </svg>
      </div>
      <div className="vitals-lane__readout" aria-live={focused ? 'polite' : 'off'}>
        <strong>
          {missingSharedBucket
            ? formatExactUsd('0')
            : point === null
              ? 'No samples'
              : formatExactUsd(point.cost_usd)}
        </strong>
        <span>
          {missingSharedBucket
            ? `${formatMinute(sharedMinute ?? snapshot.as_of)} · ${receiptCopy(0)}`
            : point === null
              ? 'This window'
              : `${formatMinute(point.minute)} · ${receiptCopy(point.receipt_lines)}`}
        </span>
        {missingSharedBucket && <em>No spend in this lane</em>}
        {partial !== null && <em>Partial · {partial}</em>}
      </div>
      <span id={descriptionId} className="visually-hidden">
        Use Left and Right Arrow keys to move among minutes with receipts. Missing minutes
        are intentionally not connected. {partial ?? ''}
      </span>
    </div>
  )
}

function chartX(minute: string, asOf: string, windowMinutes: number): number {
  const end = Date.parse(asOf)
  const start = end - windowMinutes * 60_000
  return Math.max(0, Math.min(100, ((Date.parse(minute) - start) / (end - start)) * 100))
}

function dimensionLabel(dimension: SpendLane['dimension']): string {
  switch (dimension) {
    case 'total':
      return 'Total'
    case 'purpose':
      return 'Purpose'
    case 'model':
      return 'Model'
  }
}

function receiptCopy(count: number): string {
  return `${count} ${count === 1 ? 'receipt' : 'receipts'}`
}

function formatMinute(value: string): string {
  return minuteFormatter.format(new Date(value))
}
