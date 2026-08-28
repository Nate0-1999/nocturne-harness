import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

/* eslint-disable react-refresh/only-export-components -- durable event parsers are tested beside their owning Deck */

import type {
  AssistantTranscriptMessage,
  JsonObject,
  SymphonyIntervention,
  SymphonyJudgeCharter,
  SymphonyLaunch,
  UserTranscriptMessage,
} from './protocol'
import { useRackPlugin, useRackSnapshot } from './rack'
import './assets/symphonyDeck.css'

interface DeckAttempt {
  attempt_id: string
  state: 'running' | 'cancelled' | 'completed'
  cancellation: 'none' | 'requested' | 'draining' | 'cancelled'
  follow_ups: string[]
  partial_evidence: string[]
  memories_admitted: false
}

export interface DeckStack {
  symphony_id: string
  state: 'running' | 'blocked' | 'completed'
  execution_kind: 'toy'
  launch: SymphonyLaunch
  attempts: DeckAttempt[]
  timeline: string[]
  forked_from: string | null
  forked_to: string | null
  blocked_reason: string | null
}

export interface ProposedResponseCard {
  thread_id: string
  thread_title: string
  proposal_run_id: string
  primary: string
  alternatives: string[]
  created_at: string
  assistant_text: string
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function stringList(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
    ? value
    : null
}

function parseAttempt(value: unknown): DeckAttempt | null {
  const item = record(value)
  if (
    item === null || typeof item.attempt_id !== 'string' ||
    !['running', 'cancelled', 'completed'].includes(String(item.state)) ||
    !['none', 'requested', 'draining', 'cancelled'].includes(String(item.cancellation)) ||
    item.memories_admitted !== false
  ) return null
  const followUps = stringList(item.follow_ups)
  const partialEvidence = stringList(item.partial_evidence)
  if (followUps === null || partialEvidence === null) return null
  return {
    attempt_id: item.attempt_id,
    state: item.state as DeckAttempt['state'],
    cancellation: item.cancellation as DeckAttempt['cancellation'],
    follow_ups: followUps,
    partial_evidence: partialEvidence,
    memories_admitted: false,
  }
}

export function parseDeckStack(value: JsonObject): DeckStack | null {
  if (value.event_kind !== 'symphony_state' && value.event_kind !== 'symphony_result') return null
  const attempts = Array.isArray(value.attempts) ? value.attempts.map(parseAttempt) : []
  const timeline = stringList(value.timeline)
  if (
    typeof value.symphony_id !== 'string' ||
    !['running', 'blocked', 'completed'].includes(String(value.state)) ||
    value.execution_kind !== 'toy' || record(value.launch) === null ||
    attempts.length === 0 || attempts.some((attempt) => attempt === null) || timeline === null
  ) return null
  return {
    symphony_id: value.symphony_id,
    state: value.state as DeckStack['state'],
    execution_kind: 'toy',
    launch: value.launch as SymphonyLaunch,
    attempts: attempts as DeckAttempt[],
    timeline,
    forked_from: typeof value.forked_from === 'string' ? value.forked_from : null,
    forked_to: typeof value.forked_to === 'string' ? value.forked_to : null,
    blocked_reason: typeof value.blocked_reason === 'string' ? value.blocked_reason : null,
  }
}

export function latestDeckStacks(messages: AssistantTranscriptMessage[]): DeckStack[] {
  const latest = new Map<string, DeckStack>()
  for (const message of messages) {
    for (const event of message.events) {
      const stack = parseDeckStack(event)
      if (stack !== null) latest.set(stack.symphony_id, stack)
    }
  }
  return [...latest.values()].reverse()
}

export function proposedResponseCards(
  snapshot: ReturnType<typeof useRackSnapshot>,
): ProposedResponseCard[] {
  const titles = new Map(snapshot.catalog.map((entry) => [entry.thread_id, entry.title]))
  const latest = new Map(snapshot.catalog.flatMap((entry): [string, ProposedResponseCard][] => {
    const proposal = entry.proposed_response
    if (proposal === null || proposal === undefined) return []
    return [[entry.thread_id, {
      thread_id: entry.thread_id,
      thread_title: entry.title,
      proposal_run_id: proposal.proposal_run_id,
      primary: proposal.primary,
      alternatives: proposal.alternatives,
      created_at: proposal.created_at,
      assistant_text: proposal.assistant_text,
    }]]
  }))
  for (const [threadId, thread] of Object.entries(snapshot.threads)) {
    if (thread.awaitingSnapshot) continue
    latest.delete(threadId)
    const fired = new Set(
      thread.messages
        .filter((message): message is UserTranscriptMessage => (
          message.role === 'user' && message.run_id !== null
        ))
        .map((message) => message.proposed_response?.proposal_run_id)
        .filter((runId): runId is string => typeof runId === 'string'),
    )
    for (const message of thread.messages) {
      if (message.role !== 'assistant' || message.partial) continue
      for (const event of message.events) {
        if (
          event.event_kind !== 'proposed_response' ||
          event.proposal_run_id !== message.run_id ||
          fired.has(message.run_id) ||
          typeof event.primary !== 'string' || !event.primary.trim() ||
          !Array.isArray(event.alternatives) ||
          !event.alternatives.every((alternative) => typeof alternative === 'string') ||
          typeof event.created_at !== 'string' || Number.isNaN(Date.parse(event.created_at))
        ) continue
        latest.set(threadId, {
          thread_id: threadId,
          thread_title: titles.get(threadId) ?? `Thread ${threadId.slice(-6)}`,
          proposal_run_id: message.run_id,
          primary: event.primary.trim(),
          alternatives: event.alternatives.map((alternative) => alternative.trim()),
          created_at: event.created_at,
          assistant_text: message.content,
        })
      }
    }
  }
  return [...latest.values()].sort((left, right) => (
    Date.parse(left.created_at) - Date.parse(right.created_at) ||
    left.proposal_run_id.localeCompare(right.proposal_run_id)
  ))
}

export function SymphonyDeck() {
  const snapshot = useRackSnapshot()
  const { events } = useRackPlugin()
  const selected = snapshot.selectedThreadId === null
    ? null
    : snapshot.threads[snapshot.selectedThreadId]
  const stacks = useMemo(() => latestDeckStacks(
    (selected?.messages ?? []).filter(
      (message): message is AssistantTranscriptMessage => message.role === 'assistant',
    ),
  ), [selected?.messages])
  const cards = useMemo(() => proposedResponseCards(snapshot), [snapshot])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [locallyFired, setLocallyFired] = useState<Set<string>>(() => new Set())
  const [undo, setUndo] = useState<{ card: ProposedResponseCard; text: string } | null>(null)
  const [status, setStatus] = useState('')
  const timer = useRef<number | null>(null)
  const visibleCards = cards.filter((card) => !locallyFired.has(card.proposal_run_id))

  useEffect(() => () => {
    if (timer.current !== null) globalThis.clearTimeout(timer.current)
  }, [])

  function recall() {
    if (undo === null) return
    if (timer.current !== null) globalThis.clearTimeout(timer.current)
    timer.current = null
    setLocallyFired((current) => {
      const next = new Set(current)
      next.delete(undo.card.proposal_run_id)
      return next
    })
    setStatus(`Recalled before sending to ${undo.card.thread_title}.`)
    setUndo(null)
  }

  function fire(card: ProposedResponseCard) {
    const text = (drafts[card.proposal_run_id] ?? card.primary).trim()
    if (!text || undo !== null) return
    void events.dispatch({ type: 'thread.select', thread_id: card.thread_id })
    setLocallyFired((current) => new Set(current).add(card.proposal_run_id))
    setStatus(`Next up: ${visibleCards.find((candidate) => (
      candidate.proposal_run_id !== card.proposal_run_id
    ))?.thread_title ?? 'queue clear'}.`)
    setUndo({ card, text })
    timer.current = globalThis.setTimeout(() => {
      timer.current = null
      void events.dispatch({
        type: 'prompt.submit',
        prompt: text,
        proposed_response: { proposal_run_id: card.proposal_run_id },
      }).then(() => {
        setStatus(`Fired to ${card.thread_title}.`)
        setUndo(null)
      }).catch(() => {
        setLocallyFired((current) => {
          const next = new Set(current)
          next.delete(card.proposal_run_id)
          return next
        })
        setStatus(`Nothing sent to ${card.thread_title}. Check the connection and try again.`)
        setUndo(null)
      })
    }, 6_000)
  }

  return (
    <section className="symphony-deck" data-testid="symphony-deck">
      <header className="symphony-deck__header">
        <div><p>Conductor channel</p><h1>The Deck</h1></div>
        <span>{visibleCards.length} waiting · {stacks.filter((stack) => stack.state === 'running').length} live</span>
      </header>
      <p className="symphony-deck__rule">The longest-waiting reply stays first. Browse freely. You steer the conductor here. Workers are never directly addressable.</p>
      {visibleCards.length === 0 ? (
        <p className="symphony-deck__empty" data-testid="deck-empty">No reply needs you right now.</p>
      ) : (
        <div className="deck-proposal-queue" data-testid="deck-proposal-queue">
          {visibleCards.map((card, index) => (
            <ProposedResponseCardView
              key={card.proposal_run_id}
              card={card}
              primary={index === 0}
              draft={drafts[card.proposal_run_id] ?? card.primary}
              fireDisabled={undo !== null}
              onDraft={(value) => setDrafts((current) => ({
                ...current,
                [card.proposal_run_id]: value,
              }))}
              onFire={() => fire(card)}
            />
          ))}
        </div>
      )}
      {undo !== null && (
        <aside className="deck-undo" role="status" data-testid="deck-undo">
          <span>Firing to {undo.card.thread_title} in 6 seconds.</span>
          <button type="button" onClick={recall}>Undo</button>
        </aside>
      )}
      <p className="deck-status" role="status">{status}</p>
      {snapshot.selectedThreadId === null ? (
        <p className="symphony-deck__empty">Select a conversation to see its Symphony lineages.</p>
      ) : stacks.length > 0 && (
        <div className="symphony-deck__stacks" aria-label="Symphony steering">
          {stacks.map((stack) => <DeckStackCard key={stack.symphony_id} stack={stack} />)}
        </div>
      )}
    </section>
  )
}

function ProposedResponseCardView({
  card,
  primary,
  draft,
  fireDisabled,
  onDraft,
  onFire,
}: {
  card: ProposedResponseCard
  primary: boolean
  draft: string
  fireDisabled: boolean
  onDraft: (value: string) => void
  onFire: () => void
}) {
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    onFire()
  }

  return (
    <article
      className="deck-proposal"
      data-primary={primary ? 'true' : 'false'}
      data-testid={`deck-proposal-${card.proposal_run_id}`}
    >
      <header>
        <div>
          <span>{primary ? 'Longest waiting' : 'Waiting'}</span>
          <h2>{card.thread_title}</h2>
        </div>
        <time dateTime={card.created_at}>{new Date(card.created_at).toLocaleTimeString()}</time>
      </header>
      <p className="deck-proposal__answer">{card.assistant_text}</p>
      {card.alternatives.length > 0 && (
        <div className="deck-alternatives" aria-label="Alternative replies">
          {card.alternatives.map((alternative) => (
            <button key={alternative} type="button" onClick={() => onDraft(alternative)}>
              {alternative}
            </button>
          ))}
        </div>
      )}
      <label>
        <span>Proposed response · edit freely</span>
        <textarea
          data-testid={`deck-reply-${card.proposal_run_id}`}
          value={draft}
          rows={3}
          maxLength={4_000}
          onChange={(event) => onDraft(event.target.value)}
          onKeyDown={onKeyDown}
        />
      </label>
      <footer>
        <small>Enter fires · Shift+Enter adds a line</small>
        <button type="button" disabled={fireDisabled || !draft.trim()} onClick={onFire}>
          Fire reply
        </button>
      </footer>
    </article>
  )
}

function DeckStackCard({ stack }: { stack: DeckStack }) {
  const { events } = useRackPlugin()
  const running = stack.attempts.filter((attempt) => attempt.state === 'running')
  const [attemptId, setAttemptId] = useState(running[0]?.attempt_id ?? '')
  const [instruction, setInstruction] = useState('')
  const [seat, setSeat] = useState<SymphonyJudgeCharter['seat']>('motivation')
  const currentCharter = stack.launch.judge_charters.find((charter) => charter.seat === seat)
  const [rubric, setRubric] = useState(currentCharter?.rubric[0] ?? '')
  const [evidence, setEvidence] = useState(currentCharter?.evidence_requirements[0] ?? '')
  const [metric, setMetric] = useState(currentCharter?.metrics[0] ?? '')
  const [signed, setSigned] = useState(false)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  function chooseSeat(next: SymphonyJudgeCharter['seat']) {
    const charter = stack.launch.judge_charters.find((candidate) => candidate.seat === next)
    setSeat(next)
    setRubric(charter?.rubric[0] ?? '')
    setEvidence(charter?.evidence_requirements[0] ?? '')
    setMetric(charter?.metrics[0] ?? '')
    setSigned(false)
  }

  async function intervene(intervention: SymphonyIntervention, success: string) {
    if (busy) return
    setBusy(true)
    setStatus('Sending to the conductor…')
    try {
      await events.dispatch({ type: 'symphony.intervene', intervention })
      setStatus(success)
      setInstruction('')
    } catch {
      setStatus('The intervention stayed local. Check the connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="deck-stack" data-state={stack.state}>
      <header>
        <div><span>{stack.state}</span><h2>{stack.launch.objective}</h2></div>
        <code>{stack.symphony_id}</code>
      </header>
      {(stack.forked_from !== null || stack.forked_to !== null) && (
        <dl className="deck-lineage">
          {stack.forked_from !== null && <div><dt>Forked from</dt><dd>{stack.forked_from}</dd></div>}
          {stack.forked_to !== null && <div><dt>Continue in</dt><dd>{stack.forked_to}</dd></div>}
        </dl>
      )}
      {stack.state === 'blocked' && (
        <aside className="deck-demand" role="alert">
          <strong>Owner demand</strong>
          <p>{stack.blocked_reason}</p>
          <p>The signed parent is append-only. Continue in {stack.forked_to}.</p>
        </aside>
      )}
      <div className="deck-attempts">
        {stack.attempts.map((attempt) => (
          <div className="deck-attempt" key={attempt.attempt_id} data-state={attempt.state}>
            <div><strong>{attempt.attempt_id}</strong><span>{attempt.state}</span></div>
            <small>{attempt.partial_evidence.length} evidence mark(s) · memories not admitted</small>
            {attempt.follow_ups.map((followUp, index) => <p key={index}>Follow-up: {followUp}</p>)}
            {stack.state === 'running' && attempt.state === 'running' && (
              <button type="button" disabled={busy} onClick={() => void intervene({
                kind: 'cancel_attempt', symphony_id: stack.symphony_id,
                attempt_id: attempt.attempt_id,
              }, `${attempt.attempt_id} cancelled after draining.`)}>Cancel attempt</button>
            )}
          </div>
        ))}
      </div>
      {stack.state === 'running' && (
        <div className="deck-controls">
          <fieldset>
            <legend>Clarify inside the signed charge</legend>
            <label>Attempt<select value={attemptId} onChange={(event) => setAttemptId(event.target.value)}>
              {running.map((attempt) => <option key={attempt.attempt_id}>{attempt.attempt_id}</option>)}
            </select></label>
            <label>Follow-up<textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} /></label>
            <button type="button" disabled={busy || attemptId === '' || instruction.trim() === ''} onClick={() => void intervene({
              kind: 'clarification', symphony_id: stack.symphony_id,
              attempt_id: attemptId, instruction: instruction.trim(),
            }, 'Clarification logged without changing the charge.')}>Log clarification</button>
          </fieldset>
          <fieldset>
            <legend>Change a charter by forking</legend>
            <label>Judge seat<select value={seat} onChange={(event) => chooseSeat(event.target.value as SymphonyJudgeCharter['seat'])}>
              <option value="motivation">motivation</option><option value="implementation">implementation</option><option value="performance">performance</option>
            </select></label>
            <label>New rubric<input value={rubric} onChange={(event) => setRubric(event.target.value)} /></label>
            <label>Required evidence<input value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>
            {seat === 'performance' && <label>Metric<input value={metric} onChange={(event) => setMetric(event.target.value)} /></label>}
            <label className="deck-sign"><input type="checkbox" checked={signed} onChange={(event) => setSigned(event.target.checked)} /> Sign a new fork; never rewrite this stack</label>
            <button type="button" disabled={busy || !signed || rubric.trim() === '' || evidence.trim() === '' || (seat === 'performance' && metric.trim() === '')} onClick={() => void intervene({
              kind: 'charter_change', symphony_id: stack.symphony_id, fork_signed: true,
              charter: {
                seat, rubric: [rubric.trim()], evidence_requirements: [evidence.trim()],
                metrics: seat === 'performance' ? [metric.trim()] : [],
              },
            }, 'Fork created. Follow the new lineage card.')}>Sign & fork</button>
          </fieldset>
          <button className="deck-complete" type="button" disabled={busy} onClick={() => void intervene({
            kind: 'complete', symphony_id: stack.symphony_id,
          }, 'Stack completed and returned to chat.')}>Finish surviving attempts</button>
        </div>
      )}
      <p className="deck-status" role="status">{status}</p>
    </article>
  )
}
