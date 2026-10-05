import { useState } from 'react'
import { Button, TextArea } from './kit'
import { useRackPlugin } from './rack'

export function CuratorProposal({ card, onChanged }: {
  card: { item_uid: string; verdict: string; candidate: { label: string; body: string }; proposal_payload?: Record<string, unknown> | null }
  onChanged: () => Promise<void>
}) {
  const { events } = useRackPlugin()
  const [body, setBody] = useState(card.candidate.body)
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const replacement = card.verdict === 'merge' || card.verdict === 'supersede'
  const sources = Array.isArray(card.proposal_payload?.sources) ? card.proposal_payload.sources : []

  async function decide(decision: 'approve' | 'deny') {
    setBusy(true)
    try {
      await events.dispatch({ type: 'queue.decide', item_uid: card.item_uid, decision,
        approval_mode: 'explicit', actor_class: 'human',
        ...(decision === 'approve' && replacement && body !== card.candidate.body ? { amended_body: body } : {}),
      })
      await onChanged()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The proposal could not be decided.')
    } finally { setBusy(false) }
  }

  async function sendFeedback() {
    setBusy(true)
    try {
      await events.dispatch({ type: 'queue.feedback', item_uid: card.item_uid, feedback, actor_class: 'human' })
      setFeedback('')
      setStatus('Feedback recorded for future curator decisions. The proposal is still waiting.')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Feedback could not be recorded.')
    } finally { setBusy(false) }
  }

  return <article data-verdict={card.verdict}>
    <span>{card.verdict.replace('_', ' ')}</span>
    <strong>{card.candidate.label}</strong>
    <p>{typeof card.proposal_payload?.rationale === 'string' ? card.proposal_payload.rationale : 'No rationale supplied.'}</p>
    <section className="curator-comparison">
      <section aria-label="Source memories">
        {sources.map((source, index) => {
          if (typeof source !== 'object' || source === null || !('body' in source) || typeof source.body !== 'string') return null
          return <blockquote key={index}><strong>{'label' in source ? String(source.label) : 'Source memory'}</strong><p>{source.body}</p></blockquote>
        })}
      </section>
      {replacement ? <label>Combined memory
        <TextArea value={body} onChange={(event) => setBody(event.target.value)} disabled={busy} />
        <small>You can amend this text before approving.</small>
      </label> : <p>{card.candidate.body}</p>}
    </section>
    <div>
      <Button type="button" disabled={busy} onClick={() => void decide('deny')}>Keep as is</Button>
      <Button action="confirm" variant="primary" type="button" disabled={busy || !body.trim()} onClick={() => void decide('approve')}>
        {replacement && body !== card.candidate.body ? 'Approve amended repair' : 'Approve repair'}
      </Button>
    </div>
    <label>Feedback for the curator
      <TextArea value={feedback} onChange={(event) => setFeedback(event.target.value)} disabled={busy} />
    </label>
    <Button action="send" type="button" disabled={busy || !feedback.trim()} onClick={() => void sendFeedback()}>Send feedback</Button>
    {status && <p role="status">{status}</p>}
  </article>
}
