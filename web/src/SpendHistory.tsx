import { useState } from 'react'

import { formatHumanQuantity, formatHumanUsd } from './humanNumbers'
import type { SpendRateLane, SpendTableSnapshot } from './spendTable'
import {
  contiguousPolylineSegments, formatSignedUsd, laneChartPoints,
  reconciliationCopy, type ReconciliationSnapshot,
} from './vitals'
import './assets/spend-history.css'

const DIMENSIONS = ['total', 'agent', 'subagent', 'model', 'curation'] as const
const LABELS = { total: 'Total', agent: 'Agents', subagent: 'Sub-agents', model: 'Models', curation: 'Memory curation' }

/** ADR-024 / M3SR: recorded money and tokens; unknown prices never plot as zero. */
export function SpendRates({ snapshot, compact = false }: { snapshot: SpendTableSnapshot; compact?: boolean }) {
  const [dimension, setDimension] = useState<SpendRateLane['dimension']>('total')
  const lanes = snapshot.rates.filter((lane) => lane.dimension === dimension)
  return <section className={`spend-history${compact ? ' spend-history--compact' : ''}`} aria-label="Spend over time">
    <div className="spend-history__controls">
      <strong>Recorded USD / minute</strong>
      <select aria-label="Spend graph grouping" value={dimension} onChange={(event) => setDimension(event.target.value as SpendRateLane['dimension'])}>
        {DIMENSIONS.map((value) => <option key={value} value={value}>{LABELS[value]}</option>)}
      </select>
      <small>Last hour</small>
    </div>
    {lanes.length === 0 ? <p>No {LABELS[dimension].toLowerCase()} receipts in this hour.</p> : lanes.map((lane) => {
      const start = Math.ceil((Date.parse(snapshot.as_of) - 3_600_000) / 60_000) * 60_000
      const recorded = new Map(lane.points.map((point) => [Date.parse(point.minute), point]))
      const points = Array.from({ length: 60 }, (_, i) => recorded.get(start + i * 60_000) ?? {
        minute: new Date(start + i * 60_000).toISOString(), cost_usd: '0', receipt_lines: 0, unpriced_lines: 0,
      })
      const chart = laneChartPoints({ points }, snapshot.as_of)
      const maximum = Math.max(...points.map((point) => Number(point.cost_usd ?? 0)))
      const unpriced = points.reduce((total, point) => total + point.unpriced_lines, 0)
      return <figure key={`${lane.dimension}:${lane.key}`}>
        <figcaption>{lane.label} <small>Peak {formatHumanUsd(String(maximum))} / min{unpriced > 0 ? ` · ${unpriced} lines awaiting price` : ''}</small></figcaption>
        <svg viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label={`${lane.label}, recorded dollars per minute over the last hour`}>
          <line x1="0" y1="21" x2="100" y2="21" className="spend-history__axis" />
          {contiguousPolylineSegments(chart).map((segment, i) => <polyline key={i} points={segment} fill="none" vectorEffect="non-scaling-stroke" />)}
          {chart.filter((point) => point.y !== null && point.point.receipt_lines > 0).map((point) => <circle key={point.point.minute} cx={point.x} cy={point.y!} r="0.5">
            <title>{point.point.minute}: {formatHumanUsd(point.point.cost_usd!)}{point.point.unpriced_lines ? ' (partial price)' : ''}</title>
          </circle>)}
        </svg>
      </figure>
    })}
  </section>
}

export function SpendReconciliation({ value }: { value: ReconciliationSnapshot | null }) {
  return <section className="spend-history" aria-label="Daily broker reconciliation">
    <h3>Daily broker reconciliation</h3>
    {value === null ? <p>Reconciliation unavailable.</p> : <>
      <p>{reconciliationCopy(value)}{value.checked_at && ` · Checked ${new Date(value.checked_at).toLocaleString()}`}</p>
      <dl className="spend-history__totals">
        <div><dt>Model ledger</dt><dd>{money(value.ledger_cost_usd)}</dd></div>
        <div><dt>Broker usage</dt><dd>{money(value.broker_usage_usd)}</dd></div>
        <div><dt>Drift since baseline</dt><dd>{value.drift_usd === null ? 'Not recorded' : formatSignedUsd(value.drift_usd)}</dd></div>
      </dl>
      <small>{value.status === 'not_recorded' ? 'Broker totals require a recorded owner-scope reconciliation.' : 'Cumulative changes from the same baseline; infrastructure bills are outside broker usage.'}</small>
    </>}
  </section>
}

export function SpendDaily({ snapshot }: { snapshot: SpendTableSnapshot }) {
  return <details className="spend-history">
    <summary>Daily spend · UTC</summary>
    {snapshot.days.length === 0 ? <p>No daily spend recorded.</p> : <table><thead><tr><th>Day</th><th>Models</th><th>Infrastructure</th><th>Total</th></tr></thead>
      <tbody>{snapshot.days.map((day) => <tr key={day.day}><th>{day.day.slice(0, 10)}</th><td>{money(day.model_usd)}</td><td>{money(day.infrastructure_usd)}</td><td>{money(day.total_usd)}{day.unpriced_lines > 0 && ' + unpriced receipts'}</td></tr>)}</tbody>
    </table>}
    <small>Infrastructure appears on its ledger date. A missing bill is not zero spend.</small>
  </details>
}

export function CacheHistory({ snapshot, threadNames }: { snapshot: SpendTableSnapshot; threadNames: ReadonlyMap<string, string> }) {
  const [selected, setSelected] = useState('')
  const threads = [...new Set(snapshot.messages.map((message) => message.thread_id))]
  const thread = threads.includes(selected) ? selected : threads[0] ?? ''
  const messages = snapshot.messages.filter((message) => message.thread_id === thread)
  return <section className="spend-history" aria-label="Cache efficiency">
    <h3>Cache efficiency by message</h3>
    {threads.length === 0 ? <p>No message receipts recorded.</p> : <>
      <select aria-label="Cache conversation" value={thread} onChange={(event) => setSelected(event.target.value)}>
        {threads.map((id) => <option key={id} value={id}>{threadNames.get(id) ?? `Conversation ${id.slice(0, 8)}`}</option>)}
      </select>
      <table><thead><tr><th>Message</th><th>Fresh</th><th>Cached</th><th>Cache writes</th><th>Reuse</th></tr></thead>
        <tbody>{messages.map((message, index) => {
          const denominator = Number(message.fresh_tokens) + Number(message.cached_tokens)
          const percent = denominator > 0 ? Number(message.cached_tokens) / denominator * 100 : null
          return <tr key={message.prompt_id ?? 'unattributed'}>
            <th title={message.prompt_id ?? 'Prompt identity not recorded'}>{message.prompt_id === null ? 'Unattributed' : index + 1} · {new Date(message.first_request_at).toLocaleTimeString()}</th>
            <td>{formatHumanQuantity(message.fresh_tokens)}</td><td>{formatHumanQuantity(message.cached_tokens)}</td><td>{formatHumanQuantity(message.cache_write_tokens)}</td>
            <td>{percent === null ? 'No input' : <><meter min="0" max="100" value={percent} aria-label={`Message ${index + 1} cache reuse`} /> {percent.toFixed(1)}%</>}</td>
          </tr>
        })}</tbody>
      </table>
      <small>Reuse = cached / (cached + fresh). Cache writes are shown separately.</small>
    </>}
  </section>
}

function money(value: string | null) { return value === null ? 'Not recorded' : formatHumanUsd(value) }
