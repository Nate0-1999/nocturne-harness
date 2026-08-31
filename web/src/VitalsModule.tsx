import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { formatHumanQuantity, formatHumanUsd } from './humanNumbers'
import { useRackPlugin, useRackSnapshot } from './rack'
import {
  parseSpendTableSnapshot,
  partialSpendCopy,
  type SpendMetrics,
  type SpendTableSnapshot,
} from './spendTable'
import './assets/honest-display.css'

type LoadPhase = 'loading' | 'live' | 'refreshing' | 'failed'

/** PLAN M3SP / P2.4: Spend contains money only, grouped conversation then model. */
export function VitalsModule() {
  const { events, query } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  const [sequence, setSequence] = useState(0)
  const [phase, setPhase] = useState<LoadPhase>('loading')
  const [snapshot, setSnapshot] = useState<SpendTableSnapshot | null>(null)
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
    void query.query({ resource: 'spend_table', as_of: 'now' })
      .then((result) => {
        if (result.status !== 'live' || result.data === null) {
          throw new TypeError('Live spend rows were not returned')
        }
        const next = parseSpendTableSnapshot(result.data)
        if (active) {
          setSnapshot(next)
          setPhase('live')
        }
      })
      .catch(() => {
        if (active) setPhase('failed')
      })
    return () => { active = false }
  }, [attunedWithoutTarget, query, rack.attunement, sequence])

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
          ? 'Detailed spend needs a newer Palace. Chat is still available.'
          : 'Reading spend…'}
        {phase === 'failed' && <button type="button" onClick={refresh}>Try again</button>}
      </SpendNotice>
    )
  }

  const rowCount = snapshot.threads.length + snapshot.purposes.length
  if (collapsed) {
    return (
      <section className="spend-table spend-table--collapsed" aria-label="Spend">
        <strong>Spend</strong>
        <span>{rowCount} {rowCount === 1 ? 'group' : 'groups'}</span>
        <small>Through {formatTime(snapshot.as_of)}</small>
        {phase === 'failed' && <em role="alert">Couldn’t refresh</em>}
      </section>
    )
  }

  return (
    <section className="spend-table" aria-label="Spend">
      <div className="spend-table__toolbar">
        <p>Conversations and model costs <span>Through {formatTime(snapshot.as_of)}</span></p>
        <div aria-live="polite">
          {phase === 'failed' && <span role="alert">Spend couldn’t refresh.</span>}
          {phase === 'refreshing' && <span>Refreshing…</span>}
          <button type="button" onClick={refresh}>Refresh</button>
        </div>
      </div>
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
          <button type="button" aria-expanded={disclosure.expanded} onClick={disclosure.toggle}>
            <span aria-hidden="true">{disclosure.expanded ? '−' : '+'}</span>
            {name}
            <small>{disclosure.count} {disclosure.count === 1 ? 'model' : 'models'}</small>
          </button>
        )}
        {purpose && <small>Other work</small>}
      </th>
      <Metric value={metrics.input_tokens} />
      <Metric value={metrics.kv_cache_tokens} />
      <Metric value={metrics.reasoning_tokens} />
      <Metric value={metrics.output_tokens} />
      <td title={partial ?? undefined}>{money(metrics.total_usd)}</td>
      <td title={partial ?? undefined}>{money(metrics.spend_per_hour_usd)}</td>
    </tr>
  )
}

function Metric({ value }: { value: string }) {
  return <td>{formatHumanQuantity(value)}</td>
}

function money(value: string | null): string {
  return value === null ? 'Awaiting price' : formatHumanUsd(value)
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
