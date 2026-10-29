import { useEffect, useState } from 'react'

import { formatHumanPercent } from './humanNumbers'
import { useRackPlugin } from './rack'
import { SpendLines } from './SpendHistory'
import { parseSpendTableSnapshot, spendSeries, type SpendTableSnapshot, type SpendWindow } from './spendTable'
import { dayDrift, formatDayUsd, parseVitalsSnapshot, type ReconciliationSnapshot } from './vitals'
import './assets/spend-history.css'

/** FL-160: the bottom strip — spend per minute for agents, sub-agents, models, memory curation and total. */
export function SpendStrip() {
  const { query } = useRackPlugin()
  const [snapshot, setSnapshot] = useState<SpendTableSnapshot | null>(null)
  const [reconciliation, setReconciliation] = useState<ReconciliationSnapshot | null>(null)
  const [failed, setFailed] = useState(false)
  const [window, setWindow] = useState<SpendWindow>('1h')
  const [compact, setCompact] = useState(() => globalThis.innerHeight < 64)

  useEffect(() => {
    const resize = () => setCompact(globalThis.innerHeight < 64)
    globalThis.addEventListener('resize', resize)
    return () => globalThis.removeEventListener('resize', resize)
  }, [])

  useEffect(() => {
    let active = true
    const read = () => void Promise.all([
      query.query({ resource: 'spend_table', as_of: 'now' }),
      query.query({ resource: 'vitals', as_of: 'now' }).catch(() => null),
    ]).then(([table, vitals]) => {
      if (!active || table.status !== 'live' || table.data === null) return
      setSnapshot(parseSpendTableSnapshot(table.data))
      setReconciliation(vitals?.data ? parseVitalsSnapshot(vitals.data).reconciliation : null)
      setFailed(false)
    }).catch(() => { if (active) setFailed(true) })
    read()
    const timer = globalThis.setInterval(read, 30_000)
    return () => { active = false; globalThis.clearInterval(timer) }
  }, [query])

  const day = dayDrift(reconciliation)
  const today = snapshot === null ? null : spendSeries(snapshot, 'today').series.find((entry) => entry.dimension === 'total')
  const latest = snapshot === null ? null : spendSeries(snapshot, '10m').series.find((entry) => entry.dimension === 'total')?.lines[0].values.at(-2)
  const summary = <>
    <strong>Spend</strong>
    {snapshot === null
      ? <span>{failed ? 'Spend is unavailable.' : 'Reading spend…'}</span>
      : <>
        <span title="Recorded spend since local midnight.">Today {formatDayUsd(today?.sum ?? 0)}</span>
        <span title="The last full minute's recorded spend.">Last minute {latest?.cost == null ? '—' : formatDayUsd(latest.cost)}</span>
      </>}
    {day?.drifting && <span className="spend-strip__drift" role="status" data-testid="spend-drift-banner"
      title="Today's ledger (UTC) against OpenRouter's bill for the key. The key may also pay for other Palaces and apps.">
      Ledger {formatDayUsd(day.ledger)} vs bill {formatDayUsd(day.broker)} today
      {day.percent === null ? ' · no bill yet' : ` · ${day.percent > 0 ? '+' : ''}${formatHumanPercent(day.percent)} drift`}
    </span>}
  </>
  return <section className={`spend-strip${compact ? ' spend-strip--compact' : ''}`} aria-label="Spend strip">
    {compact || snapshot === null
      ? <header className="spend-strip__summary">{summary}</header>
      : <SpendLines snapshot={snapshot} window={window} onWindowChange={setWindow} lead={<span className="spend-strip__summary">{summary}</span>} />}
  </section>
}
