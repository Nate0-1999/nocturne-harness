import { useState } from 'react'
import { useRackPlugin } from './rack'

type SpanEntry = { id: string; text: string; kept: boolean }
type DrawnFact = { label: string; body: string; source_message_ids: string[]; verdict: string }
type Record = { run_id: string; span: SpanEntry[]; facts: DrawnFact[] }

// v2.133: the owner's check on extraction quality — a compaction's original span beside the
// facts drawn from it; pointing at a fact lights the messages it came from.
export function CompactionRecord({ threadId, runId }: { threadId: string; runId: string }) {
  const { events } = useRackPlugin()
  const [record, setRecord] = useState<Record | null | undefined>(undefined)
  const [focus, setFocus] = useState<number | null>(null)
  const [status, setStatus] = useState('')
  async function load() {
    if (record !== undefined) return
    try {
      const result = await events.dispatch({ type: 'thread.compactions', thread_id: threadId }) as
        { compactions?: Record[] } | null
      setRecord(result?.compactions?.filter((item) => item.run_id === runId).at(-1) ?? null)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The record could not be read.')
    }
  }
  const sources = new Set(focus === null || !record ? [] : record.facts[focus]?.source_message_ids)
  return (
    <details className="run-detail compaction-record" data-testid="compaction-completed"
      onToggle={(event) => { if (event.currentTarget.open) void load() }}>
      <summary data-tooltip-detail="Open the compacted conversation beside the facts drawn from it.">
        Conversation compacted · full history kept in the journal
      </summary>
      {status && <small role="status">{status}</small>}
      {record === null && <small>No record was kept for this compaction.</small>}
      {record && <div className="compaction-record__columns">
        <section aria-label="Compacted conversation">
          <h4>Conversation · {record.span.length}</h4>
          <ol>
            {record.span.map((entry) => (
              <li key={entry.id} data-message-id={entry.id} data-source={sources.has(entry.id) || undefined}>
                <small>{entry.id}{entry.kept ? ' · kept' : ''}</small>
                <p>{entry.text}</p>
              </li>
            ))}
          </ol>
        </section>
        <section aria-label="Facts drawn">
          <h4>Facts · {record.facts.length}</h4>
          <ol>
            {record.facts.map((fact, index) => (
              <li key={index} tabIndex={0} data-fact={index} onMouseEnter={() => setFocus(index)}
                onFocus={() => setFocus(index)}
                title={`From ${fact.source_message_ids.join(', ') || 'no named message'}`}>
                <small>{fact.label} · {fact.verdict === 'already_known' ? 'already known' : 'proposed'}</small>
                <p>{fact.body}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>}
    </details>
  )
}
