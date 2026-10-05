import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ContributionBars } from './ContributionBars'
import { formatHumanPercent, formatHumanScore } from './humanNumbers.ts'
import { CreationScoreboard, ScoreTerrain, LearningSummary, LearningTimeline, type CreationSummary, type TerrainPoint } from './LearningTelemetry'
import {
  ACTIVATE_LABEL,
  AUDITION_LABEL,
  FORCE_RETRAIN_LABEL,
  FORCE_VALUES_LABEL,
  consoleRefreshResetPolicy,
  generationAccuracyCopy,
  learningNoticeAfterSnapshot,
  type LearningNotice,
  type ReplayScoreView,
  type ScorerAccuracyPoint,
  type ScorerConsoleLearning,
} from './learning'
import { useRackPlugin, useRackSnapshot } from './rack'
import { Button, Select, TextField } from './kit'

type Values = {
  tau: number
  top_k: number
  memory_context_share: number
  half_life_time_days: number
  half_life_hist_days: number
  weights: Record<string, number>
}
type Config = {
  axes?: Record<string, { label: string; inputs: string[]; weight: number; action: string; rationale: string; provenance: Record<string, unknown> }>
  project_offsets?: Record<string, Record<string, number>>
  version: string
  created_at: string
  status: string
  values: Values
  replay: { incumbent: ReplayScoreView; challenger: ReplayScoreView } | null
}
type Point = {
  event_uid: string
  outcome: string | null
  axis_contributions?: Record<string, string>
  injection_id: string
  ts: string
  score: string
  rank: number
  shown_as: string
  contributions: Record<string, string | null>
}
type Candidate = { memory_id: string; label: string; points: Point[] }
type Comparison = {
  memory_id: string
  incumbent_score: string
  preview_score: string
  preview_rank: number
  disposition: 'also_shown' | 'would_add' | 'would_drop' | 'still_out'
}
type Instant = {
  status: 'ready' | 'not_requested' | 'not_replayable'
  candidates: Comparison[]
}
type Slice = {
  parameter_id: string
  points: { value: number; accuracy_percent: string | null }[]
}
type Simulation = {
  terrain?: TerrainPoint[]
  simulation_digest: string
  base_version: string
  values: Values
  holdout_dispositions: number
  accuracy_percent: string | null
  incumbent_accuracy_percent: string | null
  delta_percent: string | null
  instant: Instant
  slice: Slice
}
type Audition = { proposal_version: string; instant: Instant }
type RetrainResponse = {
  status: 'insufficient_data' | 'not_better' | 'proposed'
  incumbent_version: string
  proposal_version: string | null
  eligible_dispositions: number
  training_dispositions: number
  holdout_dispositions: number
  training_pairs: number
  reason: string
}
type Snapshot = {
  trainables?: { parameter: string; loop: string; floor: number | null; status: string }[]
  creation?: CreationSummary
  metrics_scope?: 'principal' | 'palace'
  active_version: string
  configurations: Config[]
  proposed_versions: Config[]
  accuracy: ScorerAccuracyPoint[]
  candidates: Candidate[]
  learning: ScorerConsoleLearning
}

const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
const POLL_INTERVAL_MS = 5_000
const CONTROL_LABELS: Record<string, string> = {
  tau: 'Minimum match',
  memory_context_share: 'Memory share',
  half_life_time_days: 'Recent-use fade (days)',
  half_life_hist_days: 'Past-choice fade (days)',
}
const WEIGHT_LABELS: Record<string, string> = {
  sem: 'Meaning',
  kw: 'Keywords',
  time: 'Recency',
  proj: 'Project',
  freq: 'Use count',
  hist: 'Past choices',
}

function ulid(): string {
  let time = Date.now()
  let out = ''
  for (let index = 0; index < 10; index += 1) {
    out = ALPHABET[time % 32] + out
    time = Math.floor(time / 32)
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  for (let index = 0; index < 16; index += 1) {
    out += ALPHABET[bytes[index] % 32]
  }
  return out
}

function latestInjection(candidates: Candidate[]): string | undefined {
  return candidates
    .flatMap((candidate) => candidate.points)
    .sort((left, right) => left.ts.localeCompare(right.ts))
    .at(-1)?.injection_id
}

function previousAccuracy(config: Config, point: ScorerAccuracyPoint | undefined): number | null {
  const previous = config.replay?.incumbent as { weighted_disagreements: string; weighted_share_disagreements?: string } | undefined
  const denominator = Number(point?.weighted_dispositions)
  return previous && denominator > 0
    ? 100 * (1 - (Number(previous.weighted_disagreements) - Number(previous.weighted_share_disagreements ?? 0)) / denominator) : null
}

export function InjectionConsole() {
  const { query, events } = useRackPlugin()
  const rack = useRackSnapshot()
  const contextKey = `nocturne.injection.thread.${rack.attunement?.source_instance_id ?? 'current'}`
  const [contextThreads, setContextThreads] = useState<Record<string, string>>({})
  const contextThread = contextThreads[contextKey] ?? sessionStorage.getItem(contextKey)
  const contextIds = rack.attunement?.thread_ids ?? []
  const consoleThreadId = rack.selectedThreadId ??
    (contextThread !== null && contextIds.includes(contextThread) ? contextThread :
      contextIds.length === 1 ? contextIds[0] : null)
  const selectedLocation = rack.catalog.find(
    (entry) => entry.thread_id === consoleThreadId,
  )?.current_location ?? null
  const [scope, setScope] = useState<'GLOBAL' | 'ATTUNED'>('GLOBAL')
  const [data, setData] = useState<Snapshot | null>(null)
  const dataRef = useRef<Snapshot | null>(null)
  const loadGeneration = useRef(0)
  const [draft, setDraft] = useState<Values | null>(null)
  const [preview, setPreview] = useState<Instant | null>(null)
  const [receipt, setReceipt] = useState<Simulation | null>(null)
  const [audition, setAudition] = useState<Audition | null>(null)
  const [sliceParameter, setSliceParameter] = useState('scorer.tau')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [retrainNotice, setRetrainNotice] = useState<LearningNotice | null>(null)

  const applySnapshot = useCallback((next: Snapshot, explicitReset: boolean) => {
    const resetPolicy = consoleRefreshResetPolicy(
      dataRef.current?.active_version ?? null,
      next.active_version,
      explicitReset || dataRef.current === null,
    )
    dataRef.current = next
    setData(next)
    setRetrainNotice((current) => next.metrics_scope === 'principal' ? current : learningNoticeAfterSnapshot(
      current,
      next.learning.eligible_dispositions,
    ))
    if (resetPolicy.draft) {
      setDraft(next.configurations.find((config) => config.version === next.active_version)?.values ?? null)
    }
    if (resetPolicy.preview) {
      setPreview(null)
    }
    if (resetPolicy.receipt) {
      setReceipt(null)
    }
    if (resetPolicy.audition) {
      setAudition(null)
    }
    setFailure(null)
  }, [])

  const load = useCallback(async (explicitReset = false, generation?: number) => {
    if (scope === 'ATTUNED' && consoleThreadId === null) {
      setData(null)
      return
    }
    try {
      const result = await query.query({
        resource: 'scorer_console',
        as_of: 'now',
        thread_id: scope === 'ATTUNED' ? consoleThreadId ?? undefined : undefined,
      })
      if (generation !== undefined && generation !== loadGeneration.current) {
        return
      }
      applySnapshot(result.data as unknown as Snapshot, explicitReset)
    } catch {
      if (generation === undefined || generation === loadGeneration.current) {
        setFailure('Memory tuning is temporarily unavailable.')
      }
    }
  }, [applySnapshot, query, consoleThreadId, scope])

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'injection_console' }).then(setScope)
  }, [events])

  useEffect(() => {
    const generation = loadGeneration.current + 1
    loadGeneration.current = generation
    void load(true, generation)
    const interval = globalThis.setInterval(() => {
      void load(false, generation)
    }, POLL_INTERVAL_MS)
    return () => {
      globalThis.clearInterval(interval)
      if (loadGeneration.current === generation) {
        loadGeneration.current += 1
      }
    }
  }, [load])

  const weightSum = draft === null
    ? 0
    : Object.values(draft.weights).reduce((sum, value) => sum + value, 0)
  const invalidShare = draft !== null && (!Number.isFinite(draft.memory_context_share) ||
    draft.memory_context_share < 0.01 || draft.memory_context_share > 0.5)
  const valid = draft !== null && Math.abs(weightSum - 1) < 0.000001 && !invalidShare
  const injectionId = useMemo(
    () => scope === 'ATTUNED' && data !== null ? latestInjection(data.candidates) : undefined,
    [data, scope],
  )
  const activeVersion = data?.active_version
  const activeConfig = data?.configurations.find((config) => config.version === activeVersion)
  const activeAccuracy = data?.accuracy.find((point) => point.version === activeVersion)
  const latestRetrain = data?.learning.retrain_runs.at(-1)

  useEffect(() => {
    if (activeVersion === undefined || draft === null || !valid) return
    const timer = globalThis.setTimeout(() => {
      void events.dispatch({
        type: 'scorer.simulate',
        injection_id: injectionId,
        base_version: activeVersion,
        values: draft as unknown as never,
        slice_parameter_id: sliceParameter,
      }).then((result) => {
        setPreview((result as unknown as Simulation).instant)
      }).catch(() => setPreview(null))
    }, 180)
    return () => globalThis.clearTimeout(timer)
  }, [activeVersion, draft, events, injectionId, sliceParameter, valid])

  const clearSimulation = () => {
    setReceipt(null)
    setPreview(null)
  }
  const setNumber = (key: keyof Omit<Values, 'weights'>, value: number) => {
    clearSimulation()
    setDraft((old) => old === null ? old : { ...old, [key]: value })
  }
  const setWeight = (key: string, value: number) => {
    clearSimulation()
    setDraft((old) => old === null
      ? old
      : { ...old, weights: { ...old.weights, [key]: value } })
  }

  async function simulate() {
    if (data === null || draft === null || !valid) return
    setBusy(true)
    try {
      const result = await events.dispatch({
        type: 'scorer.simulate',
        injection_id: injectionId,
        base_version: data.active_version,
        values: draft as unknown as never,
        slice_parameter_id: sliceParameter,
      }) as unknown as Simulation
      setReceipt(result)
      setPreview(result.instant)
      setFailure(null)
    } catch {
      setFailure('The simulation could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  async function enact() {
    if (data === null || draft === null || receipt === null || !valid) return
    setBusy(true)
    try {
      await events.dispatch({
        type: 'scorer.force',
        event_uid: ulid(),
        base_version: data.active_version,
        values: draft as unknown as never,
        simulation_digest: receipt.simulation_digest,
      })
      await load(true)
    } catch {
      setReceipt(null)
      setFailure('Evidence changed. Run DEEP again before forcing these values.')
    } finally {
      setBusy(false)
    }
  }

  async function forceRetrain() {
    setBusy(true)
    setRetrainNotice({ copy: 'Retraining in the background. The current recipe keeps serving.', eligibleDispositions: null })
    try {
      const result = await events.dispatch({ type: 'scorer.retrain' }) as unknown as RetrainResponse
      setFailure(null)
      if (result.status === 'insufficient_data') {
        const minimum = dataRef.current?.learning.minimum_dispositions
        setRetrainNotice({
          copy: minimum === undefined
            ? `Not enough authentic signals yet: ${result.eligible_dispositions} available.`
            : `Not enough authentic signals yet: ${result.eligible_dispositions} / ${minimum} available.`,
          eligibleDispositions: result.eligible_dispositions,
        })
      } else if (result.status === 'not_better') {
        setRetrainNotice({
          copy: 'The current recipe still wins. Current values kept: the candidate did not improve the back-test enough. Compare the results below.',
          eligibleDispositions: result.eligible_dispositions,
        })
      } else {
        setRetrainNotice({
          copy: `Proposal ${result.proposal_version ?? 'ready'} is ready to audition.`,
          eligibleDispositions: result.eligible_dispositions,
        })
      }
      await load(false)
    } catch {
      setRetrainNotice(null)
      setFailure('Retraining could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  async function tryProposal(version: string) {
    if (injectionId === undefined) {
      setFailure('Select a thread with a frozen gate to audition this proposal.')
      return
    }
    try {
      const result = await events.dispatch({
        type: 'scorer.audition',
        injection_id: injectionId,
        proposal_version: version,
      }) as unknown as Audition
      setAudition(result)
      setFailure(null)
    } catch {
      setFailure('This proposal could not be auditioned against the selected gate.')
    }
  }

  async function activateProposal(version: string) {
    setBusy(true)
    try {
      await events.dispatch({ type: 'scorer.activate', event_uid: ulid(), version })
      setRetrainNotice({ copy: `Activated ${version}.`, eligibleDispositions: null })
      await load(true)
    } catch {
      setFailure('This proposal could not be activated.')
    } finally {
      setBusy(false)
    }
  }

  const comparisonByMemory = new Map(
    (audition?.instant.candidates ?? preview?.candidates ?? [])
      .map((row) => [row.memory_id, row]),
  )

  return (
    <section className="instrument instrument--console">
      <header>
        <h1>Injection Console</h1>
        {scope === 'ATTUNED' && rack.attunement?.kind === 'stack' && (
          <label>Conversation for preview
            <Select aria-label="Conversation for preview" data-tooltip-detail="Choose the thread whose gate the console reads." value={consoleThreadId ?? ''} onChange={(event) => {
              sessionStorage.setItem(contextKey, event.target.value)
              setContextThreads((current) => ({ ...current, [contextKey]: event.target.value }))
            }}>
              <option value="">Choose a conversation</option>
              {rack.catalog.filter((entry) => contextIds.includes(entry.thread_id)).map((entry) => (
                <option key={entry.thread_id} value={entry.thread_id}>{entry.title || entry.thread_id}</option>
              ))}
            </Select>
          </label>
        )}
        <p data-testid="injection-current-location">
          WHERE · {selectedLocation ?? 'No attuned thread location'}
        </p>
      </header>
      {failure !== null && <p role="alert">{failure}</p>}
      {data?.learning && (
        <div className="console-learning-overview">
          <div className="console-learning-control">
            <LearningSummary learning={data.learning} scope={data.metrics_scope} />
            {data.metrics_scope === 'principal' ? (
              <p className="console-note">Only the Palace owner can retrain the scorer.</p>
            ) : <Button
              className="retrain-control"
              type="button"
              data-tooltip-detail="Refit the scorer from your gate signals now."
              disabled={busy}
              onClick={() => void forceRetrain()}
            >
              {FORCE_RETRAIN_LABEL}
            </Button>}
            {retrainNotice !== null && (
              <p className="console-note" role="status">{retrainNotice.copy}</p>
            )}
            {latestRetrain?.incumbent && latestRetrain.challenger && <>
              <table aria-label="Latest retrain comparison">
                <caption>{latestRetrain.holdout_dispositions} held-out decisions · {latestRetrain.result === 'not_better' ? 'Current values kept' : 'Candidate proposed'}</caption>
                <thead><tr><th>Back-test</th><th>Previous</th><th>Proposed</th></tr></thead>
                <tbody>
                  <tr><th>Weighted errors</th><td>{latestRetrain.incumbent.weighted_disagreements}</td><td>{latestRetrain.challenger.weighted_disagreements}</td></tr>
                  <tr><th>Memory-share errors</th><td>{latestRetrain.incumbent.weighted_share_disagreements}</td><td>{latestRetrain.challenger.weighted_share_disagreements}</td></tr>
                  <tr><th>Injected tokens</th><td>{latestRetrain.incumbent.injected_tokens}</td><td>{latestRetrain.challenger.injected_tokens}</td></tr>
                </tbody>
              </table>
              <p className="console-note">Both sets use the same held-out decisions. Weighted errors include memory-share errors; fewer is better.</p>
            </>}
          </div>
          {data.metrics_scope !== 'principal' && (
            <LearningTimeline learning={data.learning} accuracy={data.accuracy} />
          )}
        </div>
      )}
      <div className="console-grid">
        <section>
          <p className="console-active">Current recipe <strong>{data?.active_version}</strong></p>
          {activeConfig && activeAccuracy?.status === 'measured' && <p>
            Current {generationAccuracyCopy(activeAccuracy)} · Previous {previousAccuracy(activeConfig, activeAccuracy) === null ? 'not recorded' : formatHumanPercent(previousAccuracy(activeConfig, activeAccuracy)!)} · same held-out decisions
          </p>}
          <details><summary>Trainable parameter registry</summary>
            <table><thead><tr><th>Parameter</th><th>Loop</th><th>Authentic floor</th><th>Status</th></tr></thead><tbody>
              {(data?.trainables ?? []).map((item) => <tr key={item.parameter}><td>{item.parameter}</td><td>{item.loop}</td><td>{item.floor ?? '—'}</td><td>{item.status.replaceAll('_', ' ')}</td></tr>)}
            </tbody></table>
          </details>
          <details><summary>Axes and project offsets</summary>
            {(data?.configurations ?? []).filter((config) => config.status !== 'inactive').map((config) => <article key={config.version}>
              <h3>{config.version} · {config.status}</h3>
              {Object.values(config.axes ?? {}).length === 0 && <p>No curator-grown axes in this generation.</p>}
              {Object.entries(config.axes ?? {}).map(([name, axis]) => <div key={name}><strong>{axis.label}</strong><p>{axis.inputs.join(' × ')} · weight {axis.weight.toFixed(4)} · {axis.action.replaceAll('_', ' ')}</p><p>{axis.rationale}</p><details><summary>Provenance</summary><pre>{JSON.stringify(axis.provenance, null, 2)}</pre></details></div>)}
              <p>Unseen projects start with zero offsets from global weights.</p>
              {Object.keys(config.project_offsets ?? {}).length === 0 ? <p>No project offsets learned yet.</p> :
                <table aria-label={`Project offsets for ${config.version}`}><thead><tr><th>Project</th>{Object.values(WEIGHT_LABELS).map((label) => <th key={label}>{label}</th>)}</tr></thead>
                  <tbody>{Object.entries(config.project_offsets ?? {}).map(([project, offsets]) => <tr key={project}><th>{project}</th>{Object.keys(WEIGHT_LABELS).map((key) => <td key={key}>{(offsets[key] ?? 0).toPrecision(4)}</td>)}</tr>)}</tbody>
                </table>}
            </article>)}
          </details>
          {data?.learning && data.metrics_scope !== 'principal' && (
            <p className="console-note">
              Memory share + injection line {data.learning.share_tuning_active
                ? 'learn with each new generation.'
                : `stay fixed until ${data.learning.share_tuning_minimum} authentic signals · ${data.learning.share_tuning_remaining} to go.`}
            </p>
          )}
          {(data?.proposed_versions ?? []).map((proposal) => {
            const point = data?.accuracy.find((candidate) => candidate.version === proposal.version)
            const previous = previousAccuracy(proposal, point)
            const incumbent = data?.configurations.find((config) => config.version === data.active_version)
            const zeroed = Object.keys(WEIGHT_LABELS).filter((key) => proposal.values.weights[key] === 0 && (incumbent?.values.weights[key] ?? 0) > 0)
            return (
              <article className="proposal-card" key={proposal.version}>
                <header>
                  <div><small>BACKGROUND PROPOSAL</small><h2>{proposal.version}</h2></div>
                  <strong>Proposed {generationAccuracyCopy(point)}</strong>
                </header>
                <p>Previous {previous === null ? 'not recorded' : formatHumanPercent(previous)} · same held-out decisions</p>
                {proposal.replay && <p>
                  Weighted errors: proposed {proposal.replay.challenger.weighted_disagreements} · previous {proposal.replay.incumbent.weighted_disagreements}.
                  {' '}Injected tokens: proposed {proposal.replay.challenger.injected_tokens} · previous {proposal.replay.incumbent.injected_tokens}.
                </p>}
                <p>
                  {point?.weighted_dispositions === null || point?.weighted_dispositions === undefined
                    ? 'Exact held-out weight is not recorded.'
                    : `${point.weighted_dispositions} weighted held-out dispositions.`}
                </p>
                {point?.holdout_dispositions !== null && point?.holdout_dispositions !== undefined &&
                  point.holdout_dispositions < (data?.learning.minimum_dispositions ?? 25) &&
                  <p role="note">Limited evidence: only {point.holdout_dispositions} held-out decisions. Review the audition before activating.</p>}
                {zeroed.length > 0 && <p role="note">This proposal removes the influence of {zeroed.map((key) => WEIGHT_LABELS[key]).join(', ')}.</p>}
                <div className="proposal-actions">
                  <Button variant="bare"
                    className="console-secondary-action"
                    data-tooltip-detail="Shadow this proposal on the selected gate; the current scorer still governs."
                    disabled={injectionId === undefined || busy}
                    onClick={() => void tryProposal(proposal.version)}
                  >
                    {AUDITION_LABEL}
                  </Button>
                  <Button variant="primary"
                    className="enact"
                    data-tooltip-detail="Make this proposal the governing scorer."
                    disabled={busy}
                    onClick={() => void activateProposal(proposal.version)}
                  >
                    {ACTIVATE_LABEL}
                  </Button>
                </div>
                {injectionId === undefined && (
                  <small>Select a thread with a frozen gate to audition. Activation remains available.</small>
                )}
              </article>
            )
          })}
          {draft && (
            <div className="control-bank">
              {(['tau', 'memory_context_share', 'half_life_time_days', 'half_life_hist_days'] as const)
                .map((key) => (
                  <label key={key}>
                    <span>{CONTROL_LABELS[key]}</span>
                    <TextField
                      type="number"
                      data-tooltip-detail="Scorer value; simulate before forcing it."
                      value={draft[key]}
                      min={key === 'tau' ? 0 : key === 'memory_context_share' ? 0.01 : 1}
                      max={key === 'tau' ? 1 : key === 'memory_context_share' ? 0.5 : undefined}
                      step={key === 'tau' || key === 'memory_context_share' ? 0.01 : 1}
                      onChange={(event) => setNumber(key, Number(event.target.value))}
                    />
                  </label>
                ))}
              {Object.entries(draft.weights).map(([key, value]) => (
                <label key={key}>
                  <span>{WEIGHT_LABELS[key] ?? key}</span>
                  <TextField
                    type="number"
                    data-tooltip-detail="Feature weight; all weights sum to one."
                    min="0"
                    max="1"
                    step="0.01"
                    value={value}
                    onChange={(event) => setWeight(key, Number(event.target.value))}
                  />
                </label>
              ))}
              <p className={valid ? 'weight-ok' : 'weight-bad'}>
                Influence total {weightSum.toFixed(2)} / 1.00
              </p>
              {invalidShare && <p role="alert">Memory share must be between 0.01 and 0.50 (1–50% of the context window).</p>}
              <label>
                <span>Accuracy slice</span>
                <Select
                  data-tooltip-detail="Pick the value the accuracy curve sweeps."
                  value={sliceParameter}
                  onChange={(event) => {
                    clearSimulation()
                    setSliceParameter(event.target.value)
                  }}
                >
                  {[
                    'tau',
                    'memory_context_share',
                    'half_life_time_days',
                    'half_life_hist_days',
                    ...Object.keys(draft.weights).map((key) => `weight.${key}`),
                  ].map((key) => (
                    <option key={key} value={`scorer.${key}`}>
                      {CONTROL_LABELS[key] ?? WEIGHT_LABELS[key.replace('weight.', '')] ?? key}
                    </option>
                  ))}
                </Select>
              </label>
              <div className="simulation-actions">
                <Button action="run" variant="bare"
                  className="console-secondary-action"
                  data-tooltip-detail="Back-test these values against your recorded gates."
                  disabled={!valid || busy}
                  onClick={() => void simulate()}
                >
                  Run DEEP simulation
                </Button>
                <Button variant="primary"
                  className="enact"
                  data-tooltip-detail="Apply these values by hand; needs a simulation receipt first."
                  disabled={receipt === null || busy}
                  onClick={() => void enact()}
                >
                  {FORCE_VALUES_LABEL}
                </Button>
              </div>
              {receipt && (
                <div className="simulation-receipt" aria-label="Deep simulation receipt">
                  <strong>{receipt.accuracy_percent === null ? 'Not scored' : `${formatHumanPercent(receipt.accuracy_percent)} accuracy`}</strong>
                  <span>
                    {receipt.delta_percent === null
                      ? 'No held-out comparison'
                      : `${Number(receipt.delta_percent) >= 0 ? '+' : ''}${formatHumanScore(receipt.delta_percent)} points vs current`}
                  </span>
                  <small>
                    {receipt.holdout_dispositions} held-out dispositions · {receipt.simulation_digest.slice(0, 12)}
                  </small>
                  <AccuracyCurve slice={receipt.slice} />
                  <ScoreTerrain points={receipt.terrain ?? []} />
                </div>
              )}
              {scope === 'GLOBAL' && (
                <p className="console-note">Global simulation has no fabricated gate preview.</p>
              )}
              {preview?.status === 'not_replayable' && (
                <p className="console-note">This older gate lacks exact replay inputs.</p>
              )}
            </div>
          )}
        </section>
        <section className="candidate-ledger">
          <h2>{audition ? `Auditioning ${audition.proposal_version}` : 'Why memories surfaced'}</h2>
          {(data?.candidates ?? []).map((candidate) => {
            const point = candidate.points.at(-1)
            const comparison = comparisonByMemory.get(candidate.memory_id)
            return (
              <article key={candidate.memory_id}>
                <header>
                  <strong>{candidate.label}</strong>
                  <span>
                    {comparison
                      ? `Current ${formatHumanScore(comparison.incumbent_score)} · Proposed ${formatHumanScore(comparison.preview_score)} · #${comparison.preview_rank} ${comparison.disposition.replaceAll('_', ' ')}`
                      : point
                        ? `${formatHumanScore(point.score)} · #${point.rank} ${point.shown_as}`
                        : 'Not measured yet'}
                  </span>
                </header>
                <ContributionBars values={point ? { ...point.contributions, ...point.axis_contributions } : undefined} />
              </article>
            )
          })}
          {data?.candidates.length === 0 && <p>Nothing measured yet.</p>}
        </section>
      </div>
      <section aria-label="Injection back-test history">
        <h3>Injection back-test history</h3>
        <table aria-label="Injection back-test history"><thead><tr><th>Time</th><th>Memory</th><th>Decision</th><th>Score</th></tr></thead>
          <tbody>{(data?.candidates ?? []).flatMap((candidate) => candidate.points.filter((point) => point.outcome !== null).map((point) => ({ ...point, label: candidate.label })))
            .sort((left, right) => left.ts.localeCompare(right.ts) || left.event_uid.localeCompare(right.event_uid)).map((point) =>
              <tr key={point.event_uid}><td>{point.ts}</td><th>{point.label}</th><td>{point.outcome?.replaceAll('_', ' ').replace(':', ' · ')}</td><td>{formatHumanScore(point.score)}</td></tr>)}</tbody>
        </table>
      </section>
      {data && <CreationScoreboard data={data.creation?.sources ? data.creation : undefined} />}
    </section>
  )
}

function AccuracyCurve({ slice }: { slice: Slice }) {
  const measured = slice.points.filter(
    (point): point is { value: number; accuracy_percent: string } =>
      point.accuracy_percent !== null,
  )
  if (measured.length === 0) {
    return <p className="console-note">No held-out accuracy is available yet.</p>
  }
  const values = measured.map((point) => point.value)
  const scores = measured.map((point) => Number(point.accuracy_percent))
  const minX = Math.min(...values)
  const maxX = Math.max(...values)
  const minY = Math.min(...scores)
  const maxY = Math.max(...scores)
  const points = measured.map((point) => (
    `${10 + 80 * (point.value - minX) / Math.max(maxX - minX, 1)},${90 - 80 * (Number(point.accuracy_percent) - minY) / Math.max(maxY - minY, 1)}`
  )).join(' ')
  return (
    <figure className="accuracy-curve">
      <svg role="img" aria-label={`Accuracy by ${slice.parameter_id}`} viewBox="0 0 100 100">
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <figcaption>{slice.parameter_id} · {minY.toFixed(1)}–{maxY.toFixed(1)}%</figcaption>
    </figure>
  )
}
