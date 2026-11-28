import { useEffect, useState } from 'react'
import { ContextBars } from './ContextBars'
import { Select } from './kit'
import type { JsonValue } from './protocol'
import { useRackPlugin, useRackSnapshot } from './rack'
import { latestDeckStacks } from './SymphonyDeck'

interface Worker { worker_id: string; attempt_id: string; stage: string; round_scope?: string; observation: JsonValue }

export function SwarmContextBars() {
  const { selectedThreadId, threads } = useRackSnapshot()
  const [runId, setRunId] = useState('')
  const messages = selectedThreadId ? threads[selectedThreadId]?.messages : undefined
  const runs = latestDeckStacks((messages ?? []).filter(message => message.role === 'assistant'))
  const run = runs.find(entry => entry.symphony_id === runId)
  return <>
    {runs.length > 0 && <Select aria-label="Context run" title="Choose a conversation or Symphony"
      value={run?.symphony_id ?? ''} onChange={event => setRunId(event.target.value)}>
      <option value="">Conversation context</option>
      {runs.map(entry => <option key={entry.symphony_id} value={entry.symphony_id}>
        {entry.symphony_id.slice(-8)} · {entry.launch.objective}
      </option>)}
    </Select>}
    {run ? <WorkerBars key={run.symphony_id} id={run.symphony_id} live={run.state === 'running'} /> : <ContextBars />}
  </>
}

function WorkerBars({ id, live }: { id: string; live: boolean }) {
  const { events } = useRackPlugin()
  const [workers, setWorkers] = useState<Worker[]>([])
  const [chosen, setChosen] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function read() {
      try {
        const data = await events.dispatch({ type: 'symphony.context', symphony_id: id })
        if (active) { setWorkers((data as unknown as { workers: Worker[] }).workers); setFailed(false) }
      } catch { if (active) setFailed(true) }
      if (active && live) timer = setTimeout(read, 2000)
    }
    void read()
    return () => { active = false; clearTimeout(timer) }
  }, [events, id, live])
  const worker = workers.find(item => item.worker_id === chosen) ?? workers[0]
  return <>
    {failed && <p role="alert">Worker context could not be loaded. Reopen this run to retry.</p>}
    {worker ? <>
      <Select aria-label="Context source" title="Choose a worker or judge" value={worker.worker_id}
        onChange={event => setChosen(event.target.value)}>
        {workers.map(item => {
          const round = item.round_scope?.match(/^step-(\d+)-round-(\d+)$/)
          return <option key={item.worker_id} value={item.worker_id}>
            {round && `Step ${round[1]} · Round ${round[2]} · `}{item.attempt_id} · {item.stage}
          </option>
        })}
      </Select>
      <ContextBars workerSnapshot={worker.observation ?? null} />
    </> : !failed && <p>Waiting for the first recorded worker request.</p>}
  </>
}
