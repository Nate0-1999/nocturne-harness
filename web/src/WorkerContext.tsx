import { useEffect, useState } from 'react'
import { ContextBars } from './ContextBars'
import type { JsonValue } from './protocol'
import { useRackPlugin } from './rack'

interface Card { memory_id: string; label: string; body: string }
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

export function WorkerContext({ symphonyId, attemptId }: { symphonyId: string; attemptId: string }) {
  const { events } = useRackPlugin()
  const [workers, setWorkers] = useState<Worker[]>([])
  const [status, setStatus] = useState('Waiting for worker context…')
  useEffect(() => {
    let active = true
    const refresh = () => events.dispatch({ type: 'symphony.context', symphony_id: symphonyId })
      .then((value) => {
        if (!active) return
        const data = value as unknown as { workers: Worker[] }
        setWorkers(data.workers.filter((worker) => worker.attempt_id === attemptId))
        setStatus((current) => current === 'Waiting for worker context…'
          ? 'Memory changes apply at the next model request.' : current)
      }).catch((error: Error) => { if (active) setStatus(error.message) })
    void refresh()
    const timer = globalThis.setInterval(() => void refresh(), 2000)
    return () => { active = false; globalThis.clearInterval(timer) }
  }, [events, symphonyId, attemptId])

  async function select(worker: Worker, card: Card, added: boolean) {
    try {
      await events.dispatch({ type: 'symphony.memory', symphony_id: symphonyId,
        worker_id: worker.worker_id, memory_id: card.memory_id, added })
      setStatus(`${card.label}: ${added ? 'add-back' : 'pop-off'} saved for the next model request.`)
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Selection was not saved.') }
  }

  return <section aria-label="Agent context" className="symphony-card">
    <h3>{attemptId} · context</h3>
    <p role="status">{status}</p>
    {workers.map((worker) => <details key={worker.worker_id} open={worker.stage === 'completion'}>
      <summary>{worker.stage} · {worker.state} · {worker.agent_id}</summary>
      <ContextBars workerSnapshot={worker.observation} />
      <h4>Injected memories</h4>
      {worker.injection?.injected.map((card) => <article key={card.memory_id}>
        <strong>{card.label}</strong><p>{card.body}</p>
        <button type="button" disabled={worker.state !== 'running'} onClick={() => void select(worker, card, false)}>Pop off {card.label}</button>
      </article>)}
      <h4>Suggestions and removed memories</h4>
      {[...(worker.injection?.near_misses ?? []), ...worker.removed].map((card) => <article key={card.memory_id}>
        <strong>{card.label}</strong><p>{card.body}</p>
        <button type="button" disabled={worker.state !== 'running'} onClick={() => void select(worker, card, true)}>Add {card.label}</button>
      </article>)}
    </details>)}
  </section>
}
