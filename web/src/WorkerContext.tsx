import { useEffect, useState } from 'react'
import { ContextBars } from './ContextBars'
import type { JsonValue, MemoryFeatures } from './protocol'
import { useRackPlugin } from './rack'
import { Button } from './kit'
import { failureMessage } from './requestFailure'
import { MemoryCard } from './MemoryCard'

interface Card { memory_id: string; label: string; body: string; score?: number; pin?: boolean; features?: MemoryFeatures | null }
interface Worker {
  worker_id: string
  agent_id: string
  attempt_id: string
  stage: string
  state: string
  observation: JsonValue
  removed: Card[]
  injection: null | { injected: Card[]; near_misses: Card[] }
}

export function WorkerContext({ symphonyId, attemptId }: { symphonyId: string; attemptId: string | null }) {
  const { events } = useRackPlugin()
  const [workers, setWorkers] = useState<Worker[]>([])
  const [status, setStatus] = useState('Waiting for worker context…')
  useEffect(() => {
    let active = true
    const refresh = () => events.dispatch({ type: 'symphony.context', symphony_id: symphonyId })
      .then((value) => {
        if (!active) return
        const data = value as unknown as { workers: Worker[] }
        setWorkers(data.workers.filter((worker) => attemptId === null || worker.attempt_id === attemptId))
        setStatus((current) => current === 'Waiting for worker context…' && data.workers.length
          ? '' : current)
      }).catch((error: unknown) => { if (active) setStatus(failureMessage(error, 'Worker context could not be loaded. Wait for the next refresh or reload.')) })
    void refresh()
    const timer = globalThis.setInterval(() => void refresh(), 2000)
    return () => { active = false; globalThis.clearInterval(timer) }
  }, [events, symphonyId, attemptId])

  async function select(worker: Worker, card: Card, added: boolean) {
    try {
      await events.dispatch({ type: 'symphony.memory', symphony_id: symphonyId,
        worker_id: worker.worker_id, memory_id: card.memory_id, added })
      setStatus(`${card.label}: ${added ? 'add-back' : 'pop-off'} saved for the next model request.`)
    } catch (error) { setStatus(failureMessage(error, 'The context selection was not saved. Try again.')) }
  }

  return <section aria-label="Agent context" className="symphony-card">
    <h3>{attemptId === null ? 'Memories by worker' : `${attemptId} · context`}</h3>
    {status && <p role="status">{status}</p>}
    {workers.map((worker) => <details key={worker.worker_id} open={worker.stage === 'completion'}>
      <summary>{worker.attempt_id} · {worker.stage} · {worker.state} · {worker.agent_id}</summary>
      <ContextBars workerSnapshot={worker.observation} />
      <h4>Injected memories</h4>
      {worker.injection === null ? <p>{worker.stage === 'judge'
        ? 'This judge received no Palace memories.' : 'No injection recorded yet.'}</p>
        : worker.injection.injected.length === 0 && <p>No memories were injected.</p>}
      {worker.injection?.injected.map((card) => <MemoryCard key={card.memory_id} memoryId={card.memory_id} label={card.label}
        body={card.body} score={card.score} pin={card.pin} features={card.features} tone="injected"
        actions={<Button action="remove" iconOnly className="memory-card__remove" type="button" aria-label={`Pop off ${card.label}`}
          data-tooltip="Pop off" data-tooltip-detail="Leave this memory out of the worker's next request."
          disabled={worker.state !== 'running'} onClick={() => void select(worker, card, false)} />} />)}
      {(worker.injection?.near_misses.length || worker.removed.length) > 0 &&
        <h4>Suggestions and removed memories</h4>}
      {[...(worker.injection?.near_misses ?? []), ...worker.removed].map((card) => <MemoryCard key={card.memory_id} memoryId={card.memory_id}
        label={card.label} body={card.body} score={card.score} pin={card.pin} features={card.features} tone="near-miss"
        actions={<Button action="add" iconOnly variant="primary" className="memory-card__add" type="button" aria-label={`Add ${card.label}`}
          data-tooltip="Add" data-tooltip-detail="Bring this memory into the worker's next request."
          disabled={worker.state !== 'running'} onClick={() => void select(worker, card, true)} />} />)}
    </details>)}
  </section>
}
