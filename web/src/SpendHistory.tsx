import { useState, type ReactNode } from 'react'

import { formatHumanPercent, formatHumanQuantity, formatHumanUsd } from './humanNumbers'
import { SPEND_WINDOWS, spendPolylines, spendSeries, type SpendMetrics, type SpendTableSnapshot, type SpendWindow } from './spendTable'
import { useRackPlugin } from './rack'
import { dayDrift, type ReconciliationSnapshot } from './vitals'
import './assets/spend-history.css'
import { Button, Select, TextField } from './kit'

export function InfrastructureInvoiceForm({ onSaved }: { onSaved: () => void }) {
  const { events } = useRackPlugin()
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [invoice, setInvoice] = useState('')
  const [pending, setPending] = useState(false)
  const [status, setStatus] = useState('Enter the cloud bill when it arrives. Recorded invoices cannot be edited.')
  async function save() {
    setPending(true)
    try {
      await events.dispatch({ type: 'spend.invoice', amount_usd: amount, invoice_date: date, invoice_id: invoice.trim() })
      setStatus(`Invoice ${invoice.trim()} recorded. Repeating the same invoice does not add another charge.`)
      onSaved()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Invoice could not be recorded.')
    } finally { setPending(false) }
  }
  return <details className="spend-history">
    <summary>Record a cloud invoice · owner only</summary>
    <form onSubmit={(event) => { event.preventDefault(); void save() }}>
      <label>Amount · USD<TextField aria-label="Invoice amount USD" data-tooltip-detail="The invoice total in US dollars." required type="number" min="0.000000000001" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
      <label>Invoice date · UTC<TextField aria-label="Invoice date" data-tooltip-detail="The date on the invoice, in UTC." required type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      <label>Invoice ID<TextField aria-label="Invoice ID" data-tooltip-detail="The invoice number from your cloud bill." required value={invoice} onChange={(event) => setInvoice(event.target.value)} /></label>
      <Button action="save" variant="primary" type="button" disabled={pending} data-tooltip-detail="Add this invoice to the spend ledger." onClick={(event) => {
        if (event.currentTarget.form?.reportValidity()) void save()
      }}>{pending ? 'Recording…' : 'Record invoice'}</Button>
    </form>
    <p role="status">{status}</p>
  </details>
}

/** FL-160 / ADR-024: spend per minute, one graph per series on one shared scale. */
export function SpendLines({ snapshot, window, onWindowChange, lead }: { snapshot: SpendTableSnapshot; window: SpendWindow; onWindowChange: (window: SpendWindow) => void; lead?: ReactNode }) {
  const { minutes, series, peak } = spendSeries(snapshot, window)
  const first = minutes[0]
  const last = minutes.at(-1)!
  return <section className="spend-lines" aria-label="Spend per minute">
    <div className="spend-lines__controls">
      {lead}
      <Select aria-label="Spend window" data-tooltip-detail="How far back the graphs reach; today starts at midnight." value={window} onChange={(event) => onWindowChange(event.target.value as SpendWindow)}>
        {Object.entries(SPEND_WINDOWS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Select>
      <small title="Every graph shares this scale.">Top {formatHumanUsd(peak.toFixed(12))} / min</small>
    </div>
    <div className="spend-lines__graphs">
      {series.map((entry) => <figure key={entry.dimension} data-series={entry.dimension}>
        <figcaption title={entry.lines.length > 1 ? entry.lines.map((item) => item.label).join('\n') : undefined}>
          <span>{entry.label}</span>
          <span>{formatHumanUsd(entry.sum.toFixed(12))}{entry.unpriced > 0 ? ' + unpriced' : ''}</span>
        </figcaption>
        <svg viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label={`${entry.label}, dollars per minute, ${SPEND_WINDOWS[window].toLowerCase()}`}>
          <line x1="0" y1="22" x2="100" y2="22" className="spend-lines__axis" />
          {entry.lines.map((item, index) => <g key={item.key} className={`spend-lines__line spend-lines__line--${index % 4}`}>
            <title>{item.label}</title>
            {spendPolylines(item.values, first, last, peak).map((points, i) => <polyline key={i} points={points} fill="none" vectorEffect="non-scaling-stroke" />)}
          </g>)}
        </svg>
      </figure>)}
    </div>
  </section>
}

export function SpendReconciliation({ value, snapshot }: { value: ReconciliationSnapshot | null; snapshot: SpendTableSnapshot }) {
  function total(rows: SpendMetrics[]) {
    const known = rows.filter((row) => row.total_usd !== null)
    const unpriced = rows.some((row) => row.total_unpriced_lines > 0)
    const amount = known.reduce((sum, row) => sum + Number(row.total_usd), 0)
    return `${known.length === 0 && unpriced ? 'Price not reported' : formatHumanUsd(amount.toFixed(12))}${known.length > 0 && unpriced ? ' + unpriced receipts' : ''}`
  }
  return <section className="spend-history" aria-label="Spend totals">
    <h3>Spend totals</h3>
    <dl className="spend-history__totals">
      <div><dt>Conversations in this view</dt><dd>{total(snapshot.threads)}</dd></div>
      <div><dt>Other work in this view</dt><dd>{total(snapshot.purposes)}</dd></div>
    </dl>
    <DayReconciliation value={value} canCheck={snapshot.can_record_invoice === true} />
  </section>
}

/** FL-156 / A-080: today's ledger beside the broker's bill for today (UTC), checked daily or on demand. */
function DayReconciliation({ value, canCheck }: { value: ReconciliationSnapshot | null; canCheck: boolean }) {
  const { events } = useRackPlugin()
  const [latest, setLatest] = useState<ReconciliationSnapshot | null>(null)
  const [status, setStatus] = useState('')
  const [pending, setPending] = useState(false)
  const shown = latest ?? value
  const day = dayDrift(shown)
  async function check() {
    setPending(true)
    try {
      setLatest(await events.dispatch({ type: 'spend.reconcile' }) as unknown as ReconciliationSnapshot)
      setStatus('')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The bill could not be checked.')
    } finally { setPending(false) }
  }
  return <div className={`spend-reconciliation${day?.drifting ? ' spend-reconciliation--drift' : ''}`} data-testid="spend-reconciliation">
    <dl className="spend-history__totals">
      <div><dt>Ledger today · UTC</dt><dd>{day === null ? 'Not checked' : formatHumanUsd(day.ledger.toFixed(12))}</dd></div>
      <div><dt>OpenRouter bill today</dt><dd>{day === null ? 'Not checked' : formatHumanUsd(day.broker.toFixed(12))}</dd></div>
      <div><dt>Drift</dt><dd>{day === null ? '—' : day.percent === null ? (day.ledger > 0 ? 'No bill yet' : 'None') : `${day.percent > 0 ? '+' : ''}${formatHumanPercent(day.percent)}`}</dd></div>
    </dl>
    <p>
      <small title="The key may also pay for other Palaces and apps, and its bill can trail the ledger by a few minutes.">
        {shown?.checked_at ? `Checked ${new Date(shown.checked_at).toLocaleString()}` : 'Checked once a day'}
        {shown?.status === 'unavailable' && ' · OpenRouter did not answer'}
      </small>
      {canCheck && <Button action="refresh" type="button" disabled={pending} data-tooltip-detail="Read OpenRouter's bill for today now and compare it with the ledger." onClick={() => void check()}>{pending ? 'Checking…' : 'Check now'}</Button>}
    </p>
    {status && <p role="status">{status}</p>}
  </div>
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

export function SpendReceipts({ snapshot }: { snapshot: SpendTableSnapshot }) {
  return <details className="spend-history">
    <summary>Spend receipts · {snapshot.receipts.length} lines</summary>
    <p>Oldest first. Each receipt keeps its original ID and amount.</p>
    {snapshot.receipts.length === 0 ? <p>No receipt lines available.</p> : <div className="spend-table__scroll"><table className="spend-receipts" aria-label="Spend receipts">
      <thead><tr><th>Receipt ID · ULID</th><th>Model / purpose</th><th>Quantity</th><th>USD · basis</th></tr></thead>
      <tbody>{snapshot.receipts.map((receipt) => <tr key={receipt.event_uid} data-receipt-id={receipt.event_uid}>
        <th>{receipt.event_uid}<small>{new Date(receipt.ts).toLocaleString()}</small></th>
        <td title={receipt.ref}>{receipt.model ?? receipt.purpose}<div>{receipt.quantity_type.replaceAll('_', ' ')}</div></td>
        <td>{formatHumanQuantity(receipt.quantity)} {receipt.unit_of_measure}</td>
        <td>{receipt.cost_usd === null ? 'Price not reported' : receipt.cost_usd}<div>{receipt.basis}</div></td>
      </tr>)}</tbody>
    </table></div>}
  </details>
}

export function CacheHistory({ snapshot, threadNames }: { snapshot: SpendTableSnapshot; threadNames: ReadonlyMap<string, string> }) {
  const [selected, setSelected] = useState('')
  const threads = [...new Set(snapshot.messages.map((message) => message.thread_id))]
  const thread = threads.includes(selected) ? selected : threads[0] ?? ''
  const messages = snapshot.messages.filter((message) => message.thread_id === thread)
  const priced = messages.filter((message) => message.saved_usd !== null)
  const saved = priced.reduce((total, message) => total + Number(message.saved_usd), 0)
  return <section className="spend-history" aria-label="Cache efficiency">
    <h3>Cache efficiency by message</h3>
    {priced.length > 0 && <p data-testid="cache-saved"><strong>Saved {formatHumanUsd(saved.toFixed(12))}</strong> <small title="Cached tokens priced at the model's fresh prompt price minus its cache-read price, from today's model list.">by cache reads{priced.length < messages.length ? ` · ${messages.length - priced.length} unpriced` : ''}</small></p>}
    {threads.length === 0 ? <p>No message receipts recorded.</p> : <>
      <Select aria-label="Cache conversation" data-tooltip-detail="Pick the conversation whose cache reads and writes to show." value={thread} onChange={(event) => setSelected(event.target.value)}>
        {threads.map((id) => <option key={id} value={id}>{threadNames.get(id) ?? `Conversation ${id.slice(0, 8)}`}</option>)}
      </Select>
      <table><thead><tr><th>Message</th><th>Fresh</th><th>Cached</th><th>Cache writes</th><th>Reuse</th><th>Saved</th></tr></thead>
        <tbody>{messages.map((message, index) => {
          const denominator = Number(message.fresh_tokens) + Number(message.cached_tokens)
          const percent = denominator > 0 ? Number(message.cached_tokens) / denominator * 100 : null
          return <tr key={`${message.prompt_id ?? 'unattributed'}:${message.model ?? ''}`}>
            <th title={`${message.prompt_id ?? 'Prompt identity not recorded'}${message.model ? ` · ${message.model}` : ''}`}>{message.prompt_id === null ? 'Unattributed' : index + 1} · {new Date(message.first_request_at).toLocaleTimeString()}</th>
            <td>{formatHumanQuantity(message.fresh_tokens)}</td><td>{formatHumanQuantity(message.cached_tokens)}</td><td>{formatHumanQuantity(message.cache_write_tokens)}</td>
            <td>{percent === null ? 'No input' : <><meter min="0" max="100" value={percent} aria-label={`Message ${index + 1} cache reuse`} /> {percent.toFixed(1)}%</>}</td>
            <td>{message.saved_usd === null ? '—' : formatHumanUsd(message.saved_usd)}</td>
          </tr>
        })}</tbody>
      </table>
      <small>Reuse = cached / (cached + fresh). Cache writes are shown separately.</small>
    </>}
  </section>
}

function money(value: string | null) { return value === null ? 'Not recorded' : formatHumanUsd(value) }
