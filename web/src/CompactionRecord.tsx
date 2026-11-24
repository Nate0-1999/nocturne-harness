import { useState, useEffect } from 'react'
import { useRackPlugin } from './rack'
import { failureMessage } from './requestFailure'

type SpanEntry = { id: string; text: string; kept: boolean }
type Outcome = { status: string; label?: string; reason?: string; item_uid?: string }
function disposition(fact: DrawnFact) {
  const outcome = fact.outcome
  if (!outcome) return fact.verdict === 'already_known' ? 'already known (model proposal)' : 'proposed'
  switch (outcome.status) {
    case 'admitted': return 'new card · ' + outcome.item_uid
    case 'already_known': return 'already known as ' + outcome.label + ' (model proposal)'
    case 'hard_duplicate': return 'already known as ' + outcome.label
    case 'previously_denied': return 'denied before'
    case 'refused': return 'refused · ' + outcome.reason
    case 'waiting': return 'waiting for the Palace'
    default: return 'unknown outcome'
  }
}
type DrawnFact = { label: string; body: string; source_message_ids: string[]; verdict: string; outcome?: Outcome }
type Record = { run_id: string; span: SpanEntry[]; facts: DrawnFact[] }

// v2.133: the owner's check on extraction quality — a compaction's original span beside the
// facts drawn from it; pointing at a fact lights the messages it came from.
export function CompactionRecord({ threadId, runId }: { threadId: string; runId: string }) {
  const { events } = useRackPlugin()
  const [record, setRecord] = useState<Record | null | undefined>(undefined)
  const [focus, setFocus] = useState<number | null>(null)
  const [status, setStatus] = useState('')
  const [opened, setOpened] = useState(false)
  const waiting = record?.facts.some((fact) => fact.outcome?.status === 'waiting')
  useEffect(() => {
    if (!opened || (record !== undefined && !waiting)) return
    let active = true
    async function load() {
      try {
        const result = await events.dispatch({ type: 'thread.compactions', thread_id: threadId }) as
          { compactions?: Record[] } | null
        if (active) setRecord(result?.compactions?.filter((item) => item.run_id === runId).at(-1) ?? null)
      } catch (error) {
        if (active) setStatus(failureMessage(error, 'The compaction record could not be read. Reload the thread and try again.'))
      }
    }
    if (record === undefined) void load()
    const timer = waiting ? window.setInterval(() => { void load() }, 3000) : undefined
    return () => { active = false; window.clearInterval(timer) }
  }, [events, opened, record, runId, threadId, waiting])
  const sources = new Set(focus === null || !record ? [] : record.facts[focus]?.source_message_ids)
  return (
    <details className="run-detail compaction-record" data-testid="compaction-completed"
      onToggle={(event) => { setOpened(event.currentTarget.open) }}>
      <summary data-tooltip-detail="Open the compacted conversation beside the facts drawn from it.">
        Conversation compacted · full history kept in the journal
      </summary>
      {status && <small role="status">{status}</small>}
      {record === null && <small>Open a newly compacted turn to see its source record.</small>}
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
                <small>{fact.label} · {disposition(fact)}</small>
                <p>{fact.body}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>}
    </details>
  )
}
