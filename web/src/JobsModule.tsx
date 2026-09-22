import { useCallback, useEffect, useRef, useState } from 'react'
import { useRackPlugin, type RackAction } from './rack'
import type { JsonValue } from './protocol'
import './assets/jobs.css'
import { Button } from './kit'

type Definition = { name: string; prompt: string; folder: string; model_policy: string; tools: string; memory_scope: string; budget_usd: string; exit_condition: string; cron: string | null; trigger: string | null; trigger_path: string | null }
type Job = { job_id: string; definition: Definition; revision: number; enabled: boolean; next_run_at: string | null }
type Run = { run_id: string; job_id: string; thread_id: string; started_at: string; finished_at: string | null; state: string; verdict: string | null; spend_usd: string; unpriced_lines: number }
type Snapshot = { jobs: Job[]; runs: Run[]; scheduler_error: string | null }
const time = (value: string | null) => value ? new Date(value).toLocaleString() : '—'
const spend = (runs: Run[]) => `$${runs.reduce((sum, run) => sum + Number(run.spend_usd), 0).toFixed(5)}${runs.some(run => run.unpriced_lines > 0) ? ' + unpriced' : ''}`

export function JobsModule() {
  const { query, events } = useRackPlugin()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [loadFailure, setLoadFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const load = useCallback(async () => {
    try {
      const result = await query.query({ resource: 'jobs', as_of: 'now' })
      if (!result.data || typeof result.data !== 'object' || !('jobs' in result.data) || !('runs' in result.data)) throw new Error('Jobs are unavailable.')
      setSnapshot(result.data as unknown as Snapshot)
      setLoadFailure(null)
    } catch (error) { setLoadFailure(error instanceof Error ? error.message : 'Jobs are unavailable.') }
  }, [query])
  useEffect(() => {
    const initial = setTimeout(() => void load(), 0)
    const timer = setInterval(() => void load(), 2000)
    return () => { clearTimeout(initial); clearInterval(timer) }
  }, [load])
  async function act(action: RackAction) {
    setBusy(true)
    try { await events.dispatch(action); setFailure(null); await load() }
    catch (error) { setFailure(error instanceof Error ? error.message : 'The job action failed.') }
    finally { setBusy(false) }
  }
  const selectedJob = snapshot?.jobs.find(job => job.job_id === selected)
  const runs = snapshot?.runs.filter(run => run.job_id === selected).sort((a, b) => b.started_at.localeCompare(a.started_at)) ?? []
  return <section className="jobs-instrument" aria-label="Jobs monitor">
    <header><h1>Jobs</h1>
      <Button type="button" data-tooltip-detail="Load a saved workflow from a JSON file." disabled={busy} onClick={() => file.current?.click()}>Import recipe</Button>
      <input hidden ref={file} type="file" accept=".json,application/json" onChange={async event => {
        const selectedFile = event.target.files?.[0]
        event.target.value = ''
        if (!selectedFile) return
        try { await act({ type: 'jobs.save', definition: JSON.parse(await selectedFile.text()) as JsonValue, expected_revision: 0, enabled: true }) }
        catch (error) { setFailure(error instanceof Error ? error.message : 'Cannot read this recipe.') }
      }} />
    </header>
    {(failure || loadFailure || snapshot?.scheduler_error) && <p role="alert">{failure || loadFailure || snapshot?.scheduler_error}</p>}
    {!snapshot ? <p role="status">Loading jobs…</p> : snapshot.jobs.length === 0 ? <p>Import a recipe JSON file, or save one with <code>nocturne jobs save recipe.json</code>. A recipe names its prompt, folder, model policy, tools, memory scope, budget and exit check.</p> : <div className="jobs-scroll"><table>
      <thead><tr><th>Workflow</th><th>Next run</th><th>Last run</th><th>State</th><th>Spend</th><th>Exit verdict</th><th>Run</th></tr></thead>
      <tbody>{snapshot.jobs.map(job => {
        const history = snapshot.runs.filter(run => run.job_id === job.job_id).sort((a, b) => b.started_at.localeCompare(a.started_at))
        const last = history[0]
        const active = history.find(run => ['running', 'waiting'].includes(run.state))
        return <tr key={job.job_id} data-selected={job.job_id === selected || undefined}>
          <td><Button type="button" data-tooltip-detail="Show this job's prompt, settings and run history." onClick={() => setSelected(job.job_id)}>{job.definition.name}</Button><small>{job.definition.cron ? `${job.definition.cron} UTC` : job.definition.trigger ? `On ${job.definition.trigger} change` : 'On demand'}{!job.enabled ? ' · paused' : ''}</small></td>
          <td>{time(job.next_run_at)}</td><td>{time(last?.started_at ?? null)}</td>
          <td data-state={last?.state}>{last?.state ?? 'Ready'}</td><td>{spend(history)}</td><td>{last?.verdict ?? '—'}</td>
          <td><Button variant="primary" type="button" data-tooltip-detail="Start this job once, outside its schedule." disabled={busy || !!active} onClick={() => void act({ type: 'jobs.run', job_id: job.job_id })}>Run now</Button></td>
        </tr>
      })}</tbody>
    </table></div>}
    {selectedJob && <aside>
      <header><h2>{selectedJob.definition.name}</h2><Button type="button" data-tooltip-detail="Pause or resume this job's schedule; Run now still works." disabled={busy} onClick={() => void act({ type: 'jobs.save', job_id: selectedJob.job_id, definition: selectedJob.definition, expected_revision: selectedJob.revision, enabled: !selectedJob.enabled })}>{selectedJob.enabled ? 'Pause schedule' : 'Resume schedule'}</Button></header>
      <p>{selectedJob.definition.prompt}</p>
      <dl>{Object.entries({ Folder: selectedJob.definition.folder, Model: selectedJob.definition.model_policy, Tools: selectedJob.definition.tools, Memory: selectedJob.definition.memory_scope, 'Run budget': `$${selectedJob.definition.budget_usd}`, 'Exit check': selectedJob.definition.exit_condition }).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <ol className="jobs-timeline" aria-label="Run history">{runs.map(run => <li key={run.run_id} data-state={run.state}>
        <time>{time(run.started_at)}</time><strong>{run.state}</strong><span>{spend([run])}</span><p>{run.verdict ?? 'In progress'}</p>
        <Button type="button" data-tooltip-detail="Open the conversation this run wrote." onClick={() => void act({ type: 'thread.select', thread_id: run.thread_id })}>Open thread</Button>
        {['running', 'waiting'].includes(run.state) && <Button variant="danger" type="button" data-tooltip-detail="Stop this run now; its work so far is kept." disabled={busy} onClick={() => void act({ type: 'jobs.stop', run_id: run.run_id })}>Stop run</Button>}
      </li>)}</ol>
    </aside>}
  </section>
}
