import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { formatHumanQuantity, formatHumanUsd } from './humanNumbers'
import { useRackPlugin, useRackSnapshot } from './rack'
import { CacheHistory, InfrastructureInvoiceForm, SpendDaily, SpendRates, SpendReceipts, SpendReconciliation } from './SpendHistory'
import { parseVitalsSnapshot, type ReconciliationSnapshot } from './vitals'
import {
  parseSpendTableSnapshot,
  partialSpendCopy,
  type SpendMetrics,
  type SpendTableSnapshot,
} from './spendTable'
import './assets/honest-display.css'
import { Button } from './kit'

type LoadPhase = 'loading' | 'live' | 'refreshing' | 'failed'

/** PLAN M3SP / P2.4: Spend contains money only, grouped conversation then model. */
export function VitalsModule() {
  const { events, query } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  const [sequence, setSequence] = useState(0)
  const [phase, setPhase] = useState<LoadPhase>('loading')
  const [failure, setFailure] = useState('')
  const [snapshot, setSnapshot] = useState<SpendTableSnapshot | null>(null)
  const [reconciliation, setReconciliation] = useState<ReconciliationSnapshot | null>(null)
  const [expandedThreads, setExpandedThreads] = useState<ReadonlySet<string>>(new Set())
  const [collapsed, setCollapsed] = useState(() => globalThis.innerHeight < 120)
  const attunedWithoutTarget = scope === 'ATTUNED' && rack.attunement === null

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'vitals' }).then(setScope)
  }, [events])

  useEffect(() => events.subscribeResize((event) => setCollapsed(event.grid_height === 1)), [events])

  useEffect(() => {
    if (attunedWithoutTarget) return
    let active = true
    void Promise.all([
      query.query({ resource: 'spend_table', as_of: 'now' }),
      query.query({ resource: 'vitals', as_of: 'now' }).catch(() => null),
    ]).then(([result, vitals]) => {
        if (result.status !== 'live' || result.data === null) {
          throw new TypeError('Live spend rows were not returned')
        }
        const next = parseSpendTableSnapshot(result.data)
        if (active) {
          setSnapshot(next)
          setReconciliation(vitals?.data ? parseVitalsSnapshot(vitals.data).reconciliation : null)
          setPhase('live')
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setFailure(error instanceof Error ? error.message : 'Spend is unavailable. Try again.')
          setPhase('failed')
        }
      })
    return () => { active = false }
  }, [attunedWithoutTarget, query, rack.attunement, sequence])

  useEffect(() => {
    const timer = globalThis.setInterval(() => setSequence((value) => value + 1), 60_000)
    return () => globalThis.clearInterval(timer)
  }, [])

  const threadNames = useMemo(
    () => new Map(rack.catalog.map((entry) => [entry.thread_id, entry.title])),
    [rack.catalog],
  )

  function refresh() {
    setPhase(snapshot === null ? 'loading' : 'refreshing')
    setSequence((value) => value + 1)
  }

  if (attunedWithoutTarget) {
    return <SpendNotice>No conversation or stack is attuned.</SpendNotice>
  }
  if (snapshot === null) {
    return (
      <SpendNotice alert={phase === 'failed'}>
        {phase === 'failed'
          ? failure
          : 'Reading spend…'}
        {phase === 'failed' && <Button action="refresh" type="button" data-tooltip-detail="Read spend again." onClick={refresh}>Try again</Button>}
      </SpendNotice>
    )
  }

  const rowCount = snapshot.threads.length + snapshot.purposes.length
  if (collapsed) {
    return (
      <section className="spend-table spend-table--collapsed" aria-label="Spend">
        <SpendRates snapshot={snapshot} compact />
        {phase === 'failed' && <em role="alert">Couldn’t refresh</em>}
      </section>
    )
  }

  return (
    <section className="spend-table" aria-label="Spend">
      <div className="spend-table__toolbar">
        <p><span>As of {formatTime(snapshot.as_of)}</span></p>
        <div aria-live="polite">
          {phase === 'failed' && <span role="alert">Spend couldn’t refresh.</span>}
          {phase === 'refreshing' && <span>Refreshing…</span>}
          <Button action="refresh" type="button" data-tooltip-detail="Read the latest spend now." onClick={refresh}>Refresh</Button>
        </div>
      </div>
      <SpendRates snapshot={snapshot} />
      <SpendReconciliation value={reconciliation} snapshot={snapshot} />
      {scope === 'GLOBAL' && snapshot.can_record_invoice && <InfrastructureInvoiceForm onSaved={refresh} />}
      {rowCount === 0 ? (
        <p className="spend-table__empty">
          {scope === 'ATTUNED' ? `No spend for ${rack.attunement?.name ?? 'this view'}.` : 'No spend recorded.'}
        </p>
      ) : (
        <div className="spend-table__scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Conversation / model</th>
                <th scope="col">Input</th>
                <th scope="col">KV cache</th>
                <th scope="col">Reasoning</th>
                <th scope="col">Output</th>
                <th scope="col">Total ($)</th>
                <th scope="col">Spend per hour</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.threads.map((row) => {
                const expanded = expandedThreads.has(row.thread_id)
                const fallback = `Conversation ${row.thread_id.slice(0, 8)}`
                return [
                  <SpendRow
                    key={row.thread_id}
                    name={threadNames.get(row.thread_id) ?? fallback}
                    metrics={row}
                    disclosure={{
                      expanded,
                      count: row.models.length,
                      toggle: () => setExpandedThreads((current) => {
                        const next = new Set(current)
                        if (next.has(row.thread_id)) next.delete(row.thread_id)
                        else next.add(row.thread_id)
                        return next
                      }),
                    }}
                  />,
                  ...(expanded ? row.models.map((model, index) => (
                    <SpendRow
                      key={`${row.thread_id}:${model.model ?? 'unreported'}:${index}`}
                      name={model.model ?? 'Model not reported'}
                      metrics={model}
                      nested
                    />
                  )) : []),
                ]
              })}
              {snapshot.purposes.map((row) => (
                <SpendRow key={`purpose:${row.purpose}`} name={row.label} metrics={row} purpose />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <SpendDaily snapshot={snapshot} />
      <SpendReceipts snapshot={snapshot} />
      <CacheHistory snapshot={snapshot} threadNames={threadNames} />
    </section>
  )
}

function SpendNotice({ children, alert = false }: { children: ReactNode; alert?: boolean }) {
  return <section className="spend-table spend-table--notice" aria-label="Spend" role={alert ? 'alert' : 'status'}>{children}</section>
}

function SpendRow({
  name,
  metrics,
  nested = false,
  purpose = false,
  disclosure,
}: {
  name: string
  metrics: SpendMetrics
  nested?: boolean
  purpose?: boolean
  disclosure?: { expanded: boolean; count: number; toggle: () => void }
}) {
  const partial = partialSpendCopy(metrics)
  return (
    <tr className={nested ? 'spend-table__model' : purpose ? 'spend-table__purpose' : undefined}>
      <th scope="row">
        {disclosure === undefined ? <span>{name}</span> : (
          <Button action={disclosure.expanded ? "collapse" : "expand"} variant="bare" type="button" data-tooltip-detail="Show or hide this conversation's models." aria-expanded={disclosure.expanded} onClick={disclosure.toggle}>
            <span className="spend-table__name" title={name}>{name}</span>
            <small>{disclosure.count} {disclosure.count === 1 ? 'model' : 'models'}</small>
          </Button>
        )}
        {purpose && <small>Other work</small>}
      </th>
      <Metric value={metrics.input_tokens} />
      <Metric value={metrics.kv_cache_tokens} />
      <Metric value={metrics.reasoning_tokens} />
      <Metric value={metrics.output_tokens} />
      <td title={partial ?? undefined}>{money(metrics.total_usd, metrics.total_receipt_lines)}{metrics.total_usd !== null && metrics.total_unpriced_lines > 0 && ' + unpriced'}</td>
      <td title={metrics.hourly_unpriced_lines > 0 ? 'The provider did not report a price. No later price is pending.' : undefined}>{money(metrics.spend_per_hour_usd, metrics.hourly_receipt_lines)}{metrics.spend_per_hour_usd !== null && metrics.hourly_unpriced_lines > 0 && ' + unpriced'}</td>
    </tr>
  )
}

function Metric({ value }: { value: string }) {
  return <td>{formatHumanQuantity(value)}</td>
}

function money(value: string | null, receiptLines: number): string {
  return value === null ? (receiptLines === 0 ? formatHumanUsd('0') : 'Price not reported') : formatHumanUsd(value)
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
