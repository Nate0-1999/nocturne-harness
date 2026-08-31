import { useEffect, useState } from 'react'

import { LearningSummary, LearningTimeline } from './LearningTelemetry'
import { scorerConsoleTelemetry, type ScorerConsoleTelemetry } from './learning'
import { formatHumanQuantity } from './humanNumbers'
import { useRackPlugin } from './rack'
import {
  accountingCopy,
  formatBytes,
  formatUptime,
  parseVitalsSnapshot,
  reconciliationCopy,
  type GaugeStatus,
  type VitalsSnapshot,
} from './vitals'

const METRIC_LABELS: Record<string, string> = {
  created: 'Created',
  reinforced: 'Reinforced',
  superseded: 'Superseded',
  merged: 'Merged',
  quarantined: 'Quarantined',
  tombstoned: 'Tombstoned',
  add_backs: 'Add-backs',
  active_units: 'Active memories',
  pinned_units: 'Pinned memories',
  candidates_pending: 'Candidates pending',
  edges: 'Memory links',
  staged_units: 'Staged memories',
  queue_depth: 'Queue depth',
}

/** PLAN M3SP: Palace State owns every non-money Vital without becoming a second ledger. */
export function PalaceStateModule() {
  const { events, query } = useRackPlugin()
  const [sequence, setSequence] = useState(0)
  const [snapshot, setSnapshot] = useState<VitalsSnapshot | null>(null)
  const [telemetry, setTelemetry] = useState<ScorerConsoleTelemetry | null>(null)
  const [failed, setFailed] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [collapsed, setCollapsed] = useState(() => globalThis.innerHeight < 120)
  useEffect(() => events.subscribeResize((event) => setCollapsed(event.grid_height === 1)), [events])

  useEffect(() => {
    let active = true
    void Promise.all([
      query.query({ resource: 'vitals', as_of: 'now' }),
      query.query({ resource: 'scorer_console', as_of: 'now' }).catch(() => null),
    ]).then(([vitalsResult, telemetryResult]) => {
      if (vitalsResult.status !== 'live' || vitalsResult.data === null) {
        throw new TypeError('Live Palace state was not returned')
      }
      const next = parseVitalsSnapshot(vitalsResult.data)
      const nextTelemetry = telemetryResult?.status === 'live' && telemetryResult.data !== null
        ? scorerConsoleTelemetry(telemetryResult.data)
        : null
      if (active) {
        setSnapshot(next)
        setTelemetry(nextTelemetry)
        setFailed(false)
        setRefreshing(false)
      }
    }).catch(() => {
      if (active) {
        setFailed(true)
        setRefreshing(false)
      }
    })
    return () => { active = false }
  }, [query, sequence])

  useEffect(() => {
    const interval = globalThis.setInterval(() => setSequence((value) => value + 1), 60_000)
    return () => globalThis.clearInterval(interval)
  }, [])

  function refresh() {
    setRefreshing(true)
    setSequence((value) => value + 1)
  }

  if (snapshot === null) {
    return (
      <section className="palace-state palace-state--notice" aria-label="Palace State">
        <p role={failed ? 'alert' : 'status'}>
          {failed ? 'Palace state couldn’t refresh. Chat is still available.' : 'Reading Palace state…'}
        </p>
        {failed && <button type="button" onClick={refresh}>Try again</button>}
      </section>
    )
  }

  if (collapsed) {
    return (
      <section className="palace-state palace-state--collapsed" aria-label="Palace State">
        <strong>{snapshot.palace_counts.find((item) => item.metric === 'active_units')?.count ?? '—'}</strong>
        <span>active memories</span>
        <small>{snapshot.resources.warning === 'low_disk' ? 'Storage running low' : 'Palace ready'}</small>
        {failed && <em role="alert">Couldn’t refresh</em>}
      </section>
    )
  }

  return (
    <section className="palace-state" aria-label="Palace State">
      <div className="palace-state__toolbar">
        <p>Health, memory and learning <span>Through {formatTime(snapshot.as_of)}</span></p>
        <div aria-live="polite">
          {failed && <span role="alert">Palace state couldn’t refresh.</span>}
          {refreshing && <span>Refreshing…</span>}
          <button type="button" onClick={refresh}>Refresh</button>
        </div>
      </div>

      <div className="palace-state__notices">
        <span className={`vitals-reconciliation vitals-reconciliation--${snapshot.reconciliation.status}`}>
          {reconciliationCopy(snapshot.reconciliation)}
        </span>
        {snapshot.accounting.status !== 'clear' && (
          <span className={`vitals-reconciliation vitals-reconciliation--${snapshot.accounting.status}`}>
            {accountingCopy(snapshot.accounting)}
          </span>
        )}
      </div>

      {telemetry !== null && (
        <div className="palace-state__learning" aria-label="Learning state">
          <LearningSummary learning={telemetry.learning} compact />
          <LearningTimeline learning={telemetry.learning} accuracy={telemetry.accuracy} mode="generations" />
        </div>
      )}

      <div className="palace-state__gauges" aria-label="Palace gauges">
        <StateGauge label="Disk free" value={formatBytes(snapshot.resources.disk_free_bytes)} warning={snapshot.resources.warning === 'low_disk'} />
        <StateGauge label="Database" value={formatBytes(snapshot.resources.database_bytes)} />
        <StateGauge label="Nocturne memory" value={formatBytes(snapshot.resources.daemon_rss_bytes)} />
        <StateGauge label="Nocturne uptime" value={formatUptime(snapshot.resources.daemon_uptime_seconds)} />
        <StateGauge label="Journal" value={formatBytes(snapshot.resources.journal_bytes)} />
        <StateGauge label="Backups" value={formatBytes(snapshot.resources.backup_bytes)} />
        {snapshot.lifecycle_rates.map((gauge) => (
          <MeasuredGauge key={`rate:${gauge.metric}`} metric={gauge.metric} status={gauge.status} value={gauge.per_hour} suffix="/hr" />
        ))}
        {snapshot.palace_counts.map((gauge) => (
          <MeasuredGauge key={`count:${gauge.metric}`} metric={gauge.metric} status={gauge.status} value={gauge.count} />
        ))}
      </div>
    </section>
  )
}

function StateGauge({ label, value, warning = false }: { label: string; value: string; warning?: boolean }) {
  return <div className={`palace-state__gauge${warning ? ' palace-state__gauge--warning' : ''}`}><span>{label}</span><strong>{value}</strong></div>
}

function MeasuredGauge({ metric, status, value, suffix = '' }: { metric: string; status: GaugeStatus; value: number | null; suffix?: string }) {
  const copy = status === 'measured' && value !== null ? `${formatHumanQuantity(value)}${suffix}` : '—'
  const missing = status === 'placeholder' ? 'Not active yet' : 'Not recorded yet'
  return <div className={`palace-state__gauge palace-state__gauge--${status}`} title={status === 'measured' ? undefined : missing}><span>{METRIC_LABELS[metric] ?? metric.replaceAll('_', ' ')}</span><strong>{copy}</strong></div>
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
