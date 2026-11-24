import { useEffect, useRef, useState } from 'react'

import { useRackPlugin, useRackSelection, useRackSnapshot } from './rack'
import type { RunningProfile } from './store'
import { ProfileRunList } from './ProfileRunList'
import { Button, Chip, EmptyState, ModuleHeader } from './kit'
import { MemoryCard } from './MemoryCard'
import './assets/profiler.css'

/** SD-098: the owner's profiler. One row for the kickoff agent, its sub-agents (and a Symphony's
 * workers and judges) beneath it, a bar's width its time, bars colored and named by kind. Times are
 * seconds since the epoch as the daemon recorded them; an open end is still running. */
type StepKind = 'model' | 'tool' | 'skill' | 'memory'
interface Step { kind: StepKind; name: string; start: number; end: number | null }
interface Memory { memory_id: string; label: string; body: string; score?: number | null }
interface Given { task: string; instructions: string | null; tools: string[] | null; memories: Memory[] | null }
interface Agent {
  id: string
  kind: 'kickoff' | 'sub_agent' | 'symphony' | 'round' | 'worker' | 'judge'
  label: string
  model?: string | null
  start: number
  end: number | null
  steps: Step[]
  given: Given | null
  children: Agent[]
}
interface RunEntry { id: string; start: number; end: number | null; task: string }
interface Profile { now: number; runs: RunEntry[]; run: Agent | null }

const KIND_WORDS: Record<StepKind, string> = { model: 'Model wait', tool: 'Tool', skill: 'Skill', memory: 'Memory check' }
const LABEL_CHARACTER_PX = 6.6

function seconds(value: number): string {
  if (value < 10) return `${value.toFixed(value < 1 ? 2 : 1)} s`
  if (value < 120) return `${Math.round(value)} s`
  return `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`
}

function running(agent: Agent): boolean {
  return agent.end === null || agent.children.some(running)
}

function latest(agent: Agent, now: number): number {
  return Math.max(agent.end ?? now, ...agent.steps.map((step) => step.end ?? now), ...agent.children.map((child) => latest(child, now)))
}

/** Steps that overlap in time sit side by side in their own lanes; the rest share the first. */
function lanes<T extends { start: number; end: number | null }>(steps: T[], now: number): T[][] {
  const result: T[][] = []
  for (const step of steps) {
    const lane = result.find((entries) => (entries.at(-1)!.end ?? now) <= step.start)
    if (lane) lane.push(step)
    else result.push([step])
  }
  return result
}

function find(agent: Agent, id: string): Agent | null {
  if (agent.id === id) return agent
  for (const child of agent.children) {
    const found = find(child, id)
    if (found) return found
  }
  return null
}

export function ProfilerModule() {
  const { selectedThreadId, profileRuns } = useRackSnapshot()
  return <ProfileSelection key={selectedThreadId} current={selectedThreadId} runs={profileRuns} />
}

function ProfileSelection({ current, runs }: { current: string | null; runs: RunningProfile[] }) {
  const { selection } = useRackPlugin()
  const global = useRackSelection()
  const [picked, setPicked] = useState<string | null>(null)
  const overlay = global?.kind === 'profile_run'
  const active = runs.find((run) => run.run_id === (overlay ? global.id : picked))
    ?? runs.find((run) => run.thread_id === current) ?? runs[0]
  return <section className="profiler-instrument" aria-label="Agent profiler">
    <ProfileRunList runs={runs} current={current} opened={active?.run_id}
      onOpen={(id) => overlay ? selection.select({ kind: 'profile_run', id }) : setPicked(id)} />
    <Profiler key={active?.run_id ?? current} threadId={active?.thread_id ?? current} liveId={active?.run_id} />
  </section>
}

function Profiler({ threadId, liveId }: { threadId: string | null; liveId?: string }) {
  const { events, query } = useRackPlugin()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [opened, setOpened] = useState<string | null>(null)
  const [chosen, setChosen] = useState<string | null>(null)
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set())
  const [failed, setFailed] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [trackWidth, setTrackWidth] = useState(0)
  const chart = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!threadId) return
    let active = true
    void query.query({ resource: 'profile', thread_id: threadId, run_id: liveId ?? opened ?? undefined })
      .then((result) => { if (active) { setProfile(result.data as unknown as Profile); setFailed(false) } })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [query, threadId, liveId, opened, refresh])

  useEffect(() => events.subscribe((event) => {
    if (event.direction !== 'inbound' || event.envelope.thread_id !== threadId) return
    if (event.envelope.type === 'run.started') setOpened(null)
    setRefresh((value) => value + 1)
  }), [events, threadId])

  const run = liveId && profile?.run?.id !== liveId ? null : profile?.run ?? null
  const live = run !== null && running(run)
  useEffect(() => {
    if (!live && !liveId) return
    const timer = globalThis.setTimeout(() => setRefresh((value) => value + 1), 1000)
    return () => globalThis.clearTimeout(timer)
  }, [live, liveId, refresh])

  const shown = run !== null && (live || opened !== null) ? run : null
  const charted = shown !== null
  useEffect(() => {
    const element = chart.current
    if (!element) return
    const observer = new ResizeObserver(() => setTrackWidth(element.querySelector('.profiler-track')?.clientWidth ?? 0))
    observer.observe(element)
    return () => observer.disconnect()
  }, [charted])

  const now = profile?.now ?? 0
  const start = shown?.start ?? 0
  const span = shown ? Math.max(latest(shown, now) - start, 0.001) : 1
  const picked = shown && chosen ? find(shown, chosen) : null

  function bar(step: { start: number; end: number | null }) {
    const width = ((step.end ?? now) - step.start) / span
    return { style: { left: `${((step.start - start) / span) * 100}%`, width: `${width * 100}%` }, px: width * trackWidth }
  }

  function row(agent: Agent, depth: number) {
    const open = !closed.has(agent.id)
    const length = (agent.end ?? now) - agent.start
    const whole = bar(agent)
    const foldable = agent.steps.length > 0 || agent.children.length > 0
    return <li key={agent.id} data-testid="profiler-agent" data-kind={agent.kind} data-running={agent.end === null || undefined}>
      <div className="profiler-row" style={{ ['--depth' as string]: depth }}>
        <div className="profiler-name">
          {foldable && <Button action={open ? 'collapse' : 'expand'} iconOnly variant="bare" type="button" aria-expanded={open}
            data-tooltip={open ? 'Collapse' : 'Expand'} data-tooltip-detail={`${open ? 'Hide' : 'Show'} this agent's steps and the agents beneath it.`}
            onClick={() => setClosed((current) => { const next = new Set(current); if (open) next.add(agent.id); else next.delete(agent.id); return next })} />}
          <Button variant="bare" type="button" className="profiler-agent" data-chosen={chosen === agent.id || undefined} disabled={agent.given === null}
            data-tooltip-detail="Show what this agent was given going in." onClick={() => setChosen(chosen === agent.id ? null : agent.id)}>
            <strong>{agent.label}</strong>
            <span>{seconds(length)}</span>
          </Button>
        </div>
        <div className="profiler-track">
          <span className="profiler-bar" data-kind="agent" style={whole.style}
            title={`${agent.label} · ${seconds(length)}${agent.end === null ? ' · running' : ''}`} />
        </div>
      </div>
      {open && lanes(agent.steps, now).map((lane, index) => <div className="profiler-row" key={index} style={{ ['--depth' as string]: depth }}>
        <div className="profiler-name" />
        <div className="profiler-track">
          {lane.map((step, position) => {
            const placed = bar(step)
            const text = `${step.name} ${seconds((step.end ?? now) - step.start)}`
            return <span key={position} className="profiler-bar" data-testid="profiler-step" data-kind={step.kind} style={placed.style}
              title={`${KIND_WORDS[step.kind]} · ${text}${step.end === null ? ' · running' : ''}`}>
              {placed.px > (text.length + 2) * LABEL_CHARACTER_PX && text}
            </span>
          })}
        </div>
      </div>)}
      {open && agent.children.length > 0 && <ol>{agent.children.map((child) => row(child, depth + 1))}</ol>}
    </li>
  }

  const finished = profile?.runs.filter((entry) => entry.end !== null).slice().reverse() ?? []
  return <>
    <ModuleHeader title="Profiler" detail={shown ? `${live ? 'Running' : 'Finished run'} · ${seconds(span)}` : undefined}>
      {shown && (Object.keys(KIND_WORDS) as StepKind[]).map((kind) => <Chip key={kind} className="profiler-key" data-kind={kind}>{KIND_WORDS[kind]}</Chip>)}
      {shown && !live && <Button action="close" iconOnly type="button" data-tooltip="Close" data-tooltip-detail="Close this run and list the finished runs."
        onClick={() => { setOpened(null); setChosen(null) }} />}
    </ModuleHeader>
    {failed && <p role="alert">The profile could not be loaded. Reload to try again.</p>}
    {shown && <div className="profiler-chart" ref={chart} data-testid="profiler-chart" data-live={live || undefined}>
      <ol>{row(shown, 0)}</ol>
    </div>}
    {picked?.given && <GoingIn agent={picked} onClose={() => setChosen(null)} />}
    {!shown && profile && !liveId && <>
      <EmptyState title={threadId ? 'No agents are running in this conversation.' : 'Select a conversation to profile its agents.'} />
      {finished.length > 0 && <ol className="profiler-runs" aria-label="Finished runs">
        {finished.map((entry) => <li key={entry.id}>
          <Button variant="bare" type="button" data-testid="profiler-run" data-tooltip-detail="Open this finished run's agents and times."
            onClick={() => setOpened(entry.id)}>
            <time>{new Date(entry.start * 1000).toLocaleTimeString()}</time>
            <span>{seconds((entry.end ?? entry.start) - entry.start)}</span>
            <strong>{entry.task || 'Run'}</strong>
          </Button>
        </li>)}
      </ol>}
    </>}
  </>
}

/** What the agent had going in, read from the record; where the record holds none it says so. */
function GoingIn({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const given = agent.given!
  const judged = agent.kind === 'judge'
  return <aside className="profiler-given" aria-label={`${agent.label}: going in`} data-testid="profiler-given">
    <ModuleHeader title={`${agent.label} · going in`} detail={agent.model ?? undefined}>
      <Button action="close" iconOnly type="button" data-tooltip="Close" data-tooltip-detail="Close what this agent was given." onClick={onClose} />
    </ModuleHeader>
    <dl>
      <dt>Task</dt>
      <dd className="profiler-text">{given.task || 'Not in the record.'}</dd>
      <dt>Memories{given.memories?.length ? ` · ${given.memories.length}` : ''}</dt>
      <dd>{given.memories === null
        ? agent.kind === 'sub_agent' ? 'None: a sub-agent is given no memories.'
          : judged ? 'None: a judge is given no memories.'
            : agent.kind === 'kickoff' ? 'None in the record: this run opened no memory gate.' : 'None in the record.'
        : given.memories.length === 0 ? 'None: no memory was injected.'
          : given.memories.map((memory) => <MemoryCard key={memory.memory_id} memoryId={memory.memory_id} label={memory.label}
            body={memory.body} score={memory.score} tone="injected" />)}</dd>
      <dt>Tools{given.tools ? ` · ${given.tools.length}` : ''}</dt>
      <dd>{given.tools === null ? 'Not in the record.' : given.tools.length === 0 ? 'None.'
        : given.tools.map((tool) => <Chip key={tool}>{tool}</Chip>)}</dd>
      <dt>Instructions</dt>
      <dd className="profiler-text">{given.instructions ?? (agent.end === null && agent.kind !== 'kickoff'
        ? 'Not in the record yet: written when this agent finishes.' : 'Not in the record.')}</dd>
    </dl>
  </aside>
}
