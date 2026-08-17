import { useMemo, useState } from 'react'

/* eslint-disable react-refresh/only-export-components -- pure event parsers are exported beside their owning cards for protocol tests */

import type {
  JsonObject,
  SymphonyAuthority,
  SymphonyJudgeCharter,
  SymphonyLaunch,
  SymphonyRecipeStep,
} from './protocol'
import { useRackPlugin } from './rack'

type DraftAuthority = Omit<SymphonyAuthority, 'signed'> & { signed: boolean }

interface SymphonyDraft {
  draft_id: string
  objective: string
  motivation: string
  recipe: SymphonyRecipeStep[]
  judge_charters: SymphonyJudgeCharter[]
  authority: DraftAuthority
}

interface SymphonyResult {
  symphony_id: string
  state: 'completed'
  execution_kind: 'toy'
  result: string
  search_step_ids: string[]
  timeline: string[]
  launch: SymphonyLaunch
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function integer(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null
}

function strings(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
    ? value
    : null
}

function parseStep(value: unknown): SymphonyRecipeStep | null {
  const item = record(value)
  if (item === null) return null
  const stepId = text(item.step_id)
  const title = text(item.title)
  const doneWhen = text(item.done_when)
  if (stepId === null || title === null || doneWhen === null || typeof item.search !== 'boolean') {
    return null
  }
  return { step_id: stepId, title, done_when: doneWhen, search: item.search }
}

function parseCharter(value: unknown): SymphonyJudgeCharter | null {
  const item = record(value)
  if (
    item === null ||
    (item.seat !== 'motivation' && item.seat !== 'implementation' && item.seat !== 'performance')
  ) return null
  const rubric = strings(item.rubric)
  const evidence = strings(item.evidence_requirements)
  const metrics = strings(item.metrics)
  if (rubric === null || evidence === null || metrics === null) return null
  return {
    seat: item.seat,
    rubric,
    evidence_requirements: evidence,
    metrics,
  }
}

function parseAuthority(value: unknown): DraftAuthority | null {
  const item = record(value)
  if (item === null) return null
  const attempts = integer(item.attempts)
  const maxRounds = integer(item.max_rounds)
  const depthCap = integer(item.depth_cap)
  const children = integer(item.children_per_attempt)
  const minutes = integer(item.duration_minutes)
  const spend = text(item.spend_wall_usd)
  if (
    attempts === null || maxRounds === null || depthCap === null || children === null ||
    minutes === null || spend === null || typeof item.signed !== 'boolean'
  ) return null
  return {
    attempts,
    spend_wall_usd: spend,
    max_rounds: maxRounds,
    depth_cap: depthCap,
    children_per_attempt: children,
    duration_minutes: minutes,
    signed: item.signed,
  }
}

export function parseSymphonyDraft(value: JsonObject): SymphonyDraft | null {
  if (value.event_kind !== 'symphony_deliberation') return null
  const draftId = text(value.draft_id)
  const objective = text(value.objective)
  const motivation = text(value.motivation)
  const recipe = Array.isArray(value.recipe) ? value.recipe.map(parseStep) : []
  const charters = Array.isArray(value.judge_charters)
    ? value.judge_charters.map(parseCharter)
    : []
  const authority = parseAuthority(value.authority)
  if (
    draftId === null || objective === null || motivation === null || authority === null ||
    recipe.length === 0 || recipe.some((step) => step === null) ||
    charters.length !== 3 || charters.some((charter) => charter === null)
  ) return null
  return {
    draft_id: draftId,
    objective,
    motivation,
    recipe: recipe as SymphonyRecipeStep[],
    judge_charters: charters as SymphonyJudgeCharter[],
    authority,
  }
}

export function parseSymphonyResult(value: JsonObject): SymphonyResult | null {
  if (value.event_kind !== 'symphony_result') return null
  const symphonyId = text(value.symphony_id)
  const result = text(value.result)
  const searchSteps = strings(value.search_step_ids)
  const timeline = strings(value.timeline)
  const launch = record(value.launch)
  if (
    symphonyId === null || result === null || searchSteps === null || timeline === null ||
    value.state !== 'completed' || value.execution_kind !== 'toy' || launch === null
  ) return null
  return {
    symphony_id: symphonyId,
    result,
    search_step_ids: searchSteps,
    timeline,
    state: 'completed',
    execution_kind: 'toy',
    launch: launch as SymphonyLaunch,
  }
}

function replaceAt<T>(items: T[], index: number, value: T): T[] {
  return items.map((item, candidate) => candidate === index ? value : item)
}

export function SymphonyDeliberationCard({ event }: { event: JsonObject }) {
  const draft = useMemo(() => parseSymphonyDraft(event), [event])
  const { events } = useRackPlugin()
  const [objective, setObjective] = useState(draft?.objective ?? '')
  const [motivation, setMotivation] = useState(draft?.motivation ?? '')
  const [recipe, setRecipe] = useState(draft?.recipe ?? [])
  const [charters, setCharters] = useState(draft?.judge_charters ?? [])
  const [authority, setAuthority] = useState<DraftAuthority | null>(draft?.authority ?? null)
  const [status, setStatus] = useState('Nothing launches until you sign.')
  const [busy, setBusy] = useState(false)
  const [holdForSteering, setHoldForSteering] = useState(false)

  if (draft === null || authority === null) return null
  const draftId = draft.draft_id
  const currentAuthority = authority
  const complete = objective.trim() !== '' && motivation.trim() !== '' &&
    recipe.every((step) => step.title.trim() !== '' && step.done_when.trim() !== '') &&
    charters.every((charter) =>
      charter.rubric.every((item) => item.trim() !== '') &&
      charter.evidence_requirements.every((item) => item.trim() !== '') &&
      (charter.seat !== 'performance' || charter.metrics.every((item) => item.trim() !== ''))
    ) && authority.signed

  function updateStep(index: number, update: Partial<SymphonyRecipeStep>) {
    setRecipe((current) => replaceAt(current, index, { ...current[index]!, ...update }))
  }

  function updateCharter(index: number, field: 'rubric' | 'evidence_requirements' | 'metrics', value: string) {
    setCharters((current) => replaceAt(current, index, {
      ...current[index]!,
      [field]: [value],
    }))
  }

  async function launch() {
    if (!complete || busy) return
    setBusy(true)
    setStatus('Launching the separately identified proof stack…')
    const signed: SymphonyLaunch = {
      draft_id: draftId,
      objective: objective.trim(),
      motivation: motivation.trim(),
      recipe: recipe.map((step) => ({
        ...step,
        title: step.title.trim(),
        done_when: step.done_when.trim(),
      })),
      judge_charters: charters.map((charter) => ({
        ...charter,
        rubric: charter.rubric.map((item) => item.trim()),
        evidence_requirements: charter.evidence_requirements.map((item) => item.trim()),
        metrics: charter.metrics.map((item) => item.trim()),
      })),
      authority: { ...currentAuthority, signed: true },
      hold_for_steering: holdForSteering,
    }
    try {
      await events.dispatch({
        type: 'prompt.submit',
        prompt: 'Launch this symphony.',
        symphony: signed,
      })
      setStatus('Signed and launched. This chat remains live.')
    } catch {
      setStatus('Launch did not leave this chat. Review the connection and try again.')
      setBusy(false)
    }
  }

  return (
    <section className="symphony-card" aria-label="Symphony deliberation" data-testid="symphony-deliberation">
      <header className="symphony-card__header">
        <div><span className="symphony-card__eyebrow">Deliberation</span><h3>Compose the work here</h3></div>
        <span>Draft {draft.draft_id.slice(-6)}</span>
      </header>
      <p className="symphony-card__intro">No mode switch. You fix what good means before the conductor can fire.</p>
      <label>Desired outcome<textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="What result should return to this conversation?" /></label>
      <label>Why this deserves a Symphony<textarea value={motivation} onChange={(event) => setMotivation(event.target.value)} placeholder="What is difficult or valuable enough to justify parallel work?" /></label>
      <fieldset><legend>Recipe</legend>
        {recipe.map((step, index) => <div className="symphony-step" key={step.step_id}>
          <label>Step {index + 1}<input value={step.title} onChange={(event) => updateStep(index, { title: event.target.value })} placeholder="What should happen?" /></label>
          <label>Done when<input value={step.done_when} onChange={(event) => updateStep(index, { done_when: event.target.value })} placeholder="Observable acceptance evidence" /></label>
          <label className="symphony-check"><input type="checkbox" checked={step.search} onChange={(event) => updateStep(index, { search: event.target.checked })} /> Search node — spend may occur here</label>
        </div>)}
        <button type="button" className="symphony-card__minor" disabled={recipe.length >= 12} onClick={() => setRecipe((current) => [...current, { step_id: `step-${current.length + 1}`, title: '', done_when: '', search: false }])}>Add recipe step</button>
      </fieldset>
      <fieldset><legend>Fixed judge charters</legend>
        {charters.map((charter, index) => <div className="symphony-judge" key={charter.seat}>
          <strong>{charter.seat}</strong>
          <label>Rubric<input value={charter.rubric[0]} onChange={(event) => updateCharter(index, 'rubric', event.target.value)} /></label>
          <label>Required evidence<input value={charter.evidence_requirements[0]} onChange={(event) => updateCharter(index, 'evidence_requirements', event.target.value)} /></label>
          {charter.seat === 'performance' && <label>Precalculated metric<input value={charter.metrics[0]} onChange={(event) => updateCharter(index, 'metrics', event.target.value)} /></label>}
        </div>)}
      </fieldset>
      <fieldset><legend>T2 AUTHORITY — real walls</legend>
        <div className="symphony-authority">
          <label>Attempts<input type="number" min="1" value={authority.attempts} onChange={(event) => setAuthority({ ...authority, attempts: event.target.valueAsNumber })} /></label>
          <label>Spend USD<input type="number" min="0.01" step="0.01" value={authority.spend_wall_usd} onChange={(event) => setAuthority({ ...authority, spend_wall_usd: event.target.value })} /></label>
          <label>Rounds<input type="number" min="1" value={authority.max_rounds} onChange={(event) => setAuthority({ ...authority, max_rounds: event.target.valueAsNumber })} /></label>
          <label>Depth<input type="number" min="0" value={authority.depth_cap} onChange={(event) => setAuthority({ ...authority, depth_cap: event.target.valueAsNumber })} /></label>
          <label>Children / attempt<input type="number" min="0" value={authority.children_per_attempt} onChange={(event) => setAuthority({ ...authority, children_per_attempt: event.target.valueAsNumber })} /></label>
          <label>Minutes<input type="number" min="1" value={authority.duration_minutes} onChange={(event) => setAuthority({ ...authority, duration_minutes: event.target.valueAsNumber })} /></label>
        </div>
        <label className="symphony-check symphony-sign"><input type="checkbox" checked={authority.signed} onChange={(event) => setAuthority({ ...authority, signed: event.target.checked })} /> I authorize up to {authority.attempts} attempts, ${authority.spend_wall_usd}, {authority.max_rounds} rounds, depth {authority.depth_cap}, {authority.children_per_attempt} children per attempt, and {authority.duration_minutes} minutes.</label>
        <label className="symphony-check"><input type="checkbox" checked={holdForSteering} onChange={(event) => setHoldForSteering(event.target.checked)} /> Hold the toy run live on the Deck so I can exercise steering.</label>
      </fieldset>
      <footer className="symphony-card__footer"><span role="status">{status}</span><button type="button" disabled={!complete || busy} onClick={() => void launch()}>{busy ? 'Launching…' : 'Sign & run toy Symphony'}</button></footer>
    </section>
  )
}

export function SymphonyResultCard({ event }: { event: JsonObject }) {
  const result = useMemo(() => parseSymphonyResult(event), [event])
  if (result === null) return null
  return (
    <section className="symphony-card symphony-result" aria-label="Completed Symphony result" data-testid="symphony-result">
      <header className="symphony-card__header"><div><span className="symphony-card__eyebrow">Returned to chat</span><h3>Toy Symphony complete</h3></div><span>{result.symphony_id.slice(-8)}</span></header>
      <p>{result.result}</p>
      <dl><div><dt>Own stack</dt><dd>{result.symphony_id}</dd></div><div><dt>Outcome</dt><dd>{result.launch.objective}</dd></div><div><dt>Signed wall</dt><dd>${result.launch.authority.spend_wall_usd} · {result.launch.authority.duration_minutes} min · {result.launch.authority.attempts} attempts</dd></div><div><dt>Search nodes</dt><dd>{result.search_step_ids.length}</dd></div></dl>
      <p className="symphony-result__back">You are already back in the live conversation.</p>
    </section>
  )
}
