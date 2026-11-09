import {
  chartPolyline,
  learningAgreementCopy,
  learningCadenceCopy,
  learningFloorCopy,
  learningHygieneCopy,
  learningTimelineModel,
  learningWeightedTotalsCopy,
  type ScorerAccuracyPoint,
  type ScorerConsoleLearning,
} from './learning'
import {
  formatHumanPercent,
  formatHumanQuantity,
} from './humanNumbers'
import { Canvas } from '@react-three/fiber'
import { useMemo, useState } from 'react'
import { Button, TextField } from './kit'

export type TerrainPoint = { tau: number; share: number; x?: number; y?: number; agreement: number }
export type FitPoint = { phase: string; iteration: number; objective?: number; projects?: number; tau?: number; share?: number; observed_at: string }

export function FitProgress({ points, pending }: { points: FitPoint[]; pending: boolean }) {
  const measured = points.filter((point) => point.objective !== undefined)
  const maximum = Math.max(...measured.map((point) => point.objective!), 0.000001)
  const iterations = Math.max(...measured.map((point) => point.iteration), 1)
  const latest = points.at(-1)
  if (!pending && points.length === 0) return null
  return <section aria-label="Measured optimization progress">
    <h3>{pending ? 'Fitting in progress' : 'Last fit'}</h3>
    <p>{latest ? `${latest.phase} · iteration ${latest.iteration} · observed ${latest.observed_at}` : 'Waiting for the worker’s first measurement.'}</p>
    {measured.length > 0 && <figure className="learning-timeline">
      <svg viewBox="0 0 100 100" role="img" aria-label="Measured training loss by iteration">
        <polyline className="learning-timeline__line learning-timeline__line--live" points={measured.map((point) => `${8 + 84 * point.iteration / iterations},${88 - 76 * point.objective! / maximum}`).join(' ')} />
      </svg>
      <figcaption>Training loss {measured.at(-1)!.objective!.toPrecision(5)} · lower is better · sampled every 100 iterations</figcaption>
    </figure>}
    <p>Observed worker steps; a last observation alone does not prove the worker is still running.</p>
  </section>
}
export type CreationSummary = {
  sources: { source: string; created: number; surviving: number; used: number; survival_rate: number | null }[]
  hygiene_excluded_events: number
  events: { event_key: string; source: string; outcome: string; reason: string; ts: string }[]
  compaction?: {
    last_backtest?: string | null
    active: { id: string; memory_size: number } | null
    generations: { id: string; parent: string | null; instructions: string; memory_size: number;
      date: string; adopted: boolean; verdict?: string;
      scores: { incumbent: { score: number }; candidate: { score: number } } | null }[]
  }
}

export type CompactionBacktestResult = {
  verdict: string; id: string | null; fit: { status: string; reason: string };
  joint_fit: { tau: number; memory_context_share: number; memory_size: number; candidate_memory_size: number;
    proposal_eligible: boolean; size_tuning_active: boolean; resized_memories: number } | null
}

export function CreationScoreboard({ data, onBacktest }: {
  data?: CreationSummary;
  onBacktest?: (size: number, preview: boolean) => Promise<CompactionBacktestResult>
}) {
  const [size, setSize] = useState(data?.compaction?.active?.memory_size ?? 128)
  const [verification, setVerification] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<CompactionBacktestResult | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  async function backtest() {
    if (!onBacktest) return
    setBusy(true)
    setFailure(null)
    try { setResult(await onBacktest(size, verification)) }
    catch { setFailure('The compaction back-test did not complete. Current values remain active.') }
    finally { setBusy(false) }
  }
  return <section aria-label="Memory creation outcomes" className="learning-summary">
    <h2>Memory creation</h2>
    <p>Compaction instructions replay recent source spans. Used facts earn one, removed facts cost one, new facts stay neutral; fewer or smaller facts win an equal score.</p>
    <p>Retraining evaluates instructions and size with minimum match and memory share. The winning proposal uses the existing scorer activation.</p>
    <p>Active memory size: {data?.compaction?.active?.memory_size ?? 128} tokens.</p>
    <label>Memory size to back-test<TextField type="number" min={1} max={128} step={1} value={size}
      onChange={(event) => setSize(Number(event.target.value))} /></label>
    <label><input type="checkbox" checked={verification} onChange={(event) => setVerification(event.target.checked)} />Include verification history in this preview</label>
    <Button disabled={!onBacktest || busy || !Number.isInteger(size) || size < 1 || size > 128}
      onClick={() => void backtest()}>{busy ? 'Back-testing…' : 'Back-test size'}</Button>
    <p>Back-tests save a receipt and leave active values unchanged. Size tuning needs 100 graded signals.</p>
    {failure && <p role="status">{failure}</p>}
    {result && <div role="status">
      <p>Preview only · {result.id
        ? result.fit.status === 'proposed' ? 'The joint replay would propose improved values.' : 'The joint replay kept current values.'
        : result.fit.status === 'insufficient_data' ? result.fit.reason : 'The model replay did not complete. Current values remain active.'}</p>
      {result.joint_fit && <p>Tested size {result.joint_fit.memory_size} tokens · minimum match {result.joint_fit.tau.toPrecision(4)} · memory share {(100 * result.joint_fit.memory_context_share).toFixed(2)}% · {result.joint_fit.resized_memories} matched memories replayed. {result.joint_fit.proposal_eligible ? 'Creation candidate improved.' : 'Current creation policy kept.'}</p>}
    </div>}
    {data?.compaction?.last_backtest === 'failed' && <p role="status">The last instruction back-test did not complete. Current instructions remain active.</p>}
    <details><summary>Compaction instruction generations</summary>
      {!data?.compaction?.generations.length ? <p>No compaction generation recorded yet.</p> :
        data.compaction.generations.map((generation) => <article key={generation.id}>
          <h3>{generation.id} · {generation.adopted ? 'adopted' : generation.verdict?.replaceAll('_', ' ')}</h3>
          <p>Parent {generation.parent ?? 'none'} · {generation.date} · {generation.memory_size} tokens</p>
          <p>{generation.scores ? `Current ${generation.scores.incumbent.score} · candidate ${generation.scores.candidate.score}` : 'Baseline; no back-test yet.'}</p>
          <details><summary>Instructions</summary><pre>{generation.instructions}</pre></details>
        </article>)}
    </details>
    {!data ? <p>Creation history needs the current Palace release.</p> : <>
      <p>{data.hygiene_excluded_events} verification or fixture events excluded.</p>
      {data.sources.length === 0 ? <p>No authentic creation outcomes yet.</p> :
        <table><thead><tr><th>Source</th><th>Created</th><th>Surviving</th><th>Used</th><th>Survival</th></tr></thead>
          <tbody>{data.sources.map((row) => <tr key={row.source}><th>{row.source}</th><td>{row.created}</td><td>{row.surviving}</td><td>{row.used}</td><td>{row.survival_rate === null ? '—' : `${(100 * row.survival_rate).toFixed(1)}%`}</td></tr>)}</tbody>
        </table>}
      <details><summary>Replayable outcomes</summary><table><thead><tr><th>Time</th><th>Source</th><th>Outcome</th><th>Reason</th></tr></thead>
        <tbody>{data.events.map((event) => <tr key={event.event_key}><td>{event.ts}</td><td>{event.source}</td><td>{event.outcome}</td><td>{event.reason}</td></tr>)}</tbody>
      </table></details>
    </>}
  </section>
}

export function ScoreTerrain({ points, labels = ['Minimum match', 'Memory share'] }: { points: TerrainPoint[]; labels?: string[] }) {
  const [angle, setAngle] = useState(25)
  const mesh = useMemo(() => {
    const vertices: number[] = [], colors: number[] = []
    const xs = points.map((point) => point.x ?? point.tau)
    const ys = points.map((point) => point.y ?? point.share)
    const minX = Math.min(...xs), minY = Math.min(...ys)
    const rangeX = Math.max(...xs) - minX || 1, rangeY = Math.max(...ys) - minY || 1
    const steps = Math.round(Math.sqrt(points.length))
    for (let x = 0; x < steps - 1; x++) for (let y = 0; y < steps - 1; y++) {
      const indices = [x * steps + y, (x + 1) * steps + y, x * steps + y + 1,
        x * steps + y + 1, (x + 1) * steps + y, (x + 1) * steps + y + 1]
      for (const index of indices) {
        const point = points[index]
        vertices.push((xs[index] - minX) / rangeX - 0.5, point.agreement / 100, (ys[index] - minY) / rangeY - 0.5)
        colors.push(0.15 + 0.7 * point.agreement / 100, 0.65, 0.95)
      }
    }
    return { vertices: new Float32Array(vertices), colors: new Float32Array(colors) }
  }, [points])
  return <section aria-label="Replay score terrain">
    <h3>Score terrain</h3>
    <p>Held-out decision agreement across {labels.join(' × ')}. Height is agreement; the surface interpolates measured grid points.</p>
    {points.length === 0 ? <p>No replayable held-out gates yet.</p> : <>
      <div className="score-terrain">
        <Canvas camera={{ position: [1.8, 1.5, 1.8], fov: 42 }} frameloop="demand">
          <group rotation={[0, angle * Math.PI / 180, 0]} position={[0, -0.4, 0]}>
            <gridHelper args={[1, 8, '#60cfea', '#264455']} />
            <axesHelper args={[1]} />
            <mesh><bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[mesh.vertices, 3]} />
              <bufferAttribute attach="attributes-color" args={[mesh.colors, 3]} />
            </bufferGeometry><meshBasicMaterial vertexColors side={2} transparent opacity={0.72} /></mesh>
            <mesh><bufferGeometry><bufferAttribute attach="attributes-position" args={[mesh.vertices, 3]} /></bufferGeometry><meshBasicMaterial color="#8ed8ef" wireframe /></mesh>
          </group>
        </Canvas>
      </div>
      <label>Rotate terrain<input type="range" min="0" max="360" value={angle} onChange={(event) => setAngle(Number(event.target.value))} /></label>
      <p>X: {labels[0]} · depth: {labels[1]} · height: agreement 0–100%</p>
      <details><summary>Measured grid values</summary><table><thead><tr><th>{labels[0]}</th><th>{labels[1]}</th><th>Agreement</th></tr></thead><tbody>
        {points.map((point, index) => <tr key={index}><td>{(point.x ?? point.tau).toPrecision(4)}</td><td>{(point.y ?? point.share).toPrecision(4)}</td><td>{point.agreement.toFixed(1)}%</td></tr>)}
      </tbody></table></details>
    </>}
  </section>
}

export function LearningSummary({
  learning,
  compact = false,
  scope = 'palace',
}: {
  learning: ScorerConsoleLearning
  compact?: boolean
  scope?: 'principal' | 'palace'
}) {
  if (scope === 'principal') {
    return (
      <section className="learning-summary" aria-label="Your learning signals">
        <span>Your learning signals</span>
        <strong>{learning.eligible_dispositions} authentic · {learning.right} right · {learning.wrong} wrong</strong>
        <small>Palace training history is owner-only.</small>
      </section>
    )
  }
  if (compact) {
    return (
      <div
        className="learning-summary learning-summary--compact"
        aria-label={`Learning. ${learningFloorCopy(learning)}. ${learningAgreementCopy(learning)}.`}
        title={`${learningHygieneCopy(learning)}. ${learningWeightedTotalsCopy(learning)}.`}
      >
        <span>Authentic</span>
        <strong>{learning.eligible_dispositions} / {learning.minimum_dispositions}</strong>
        <span>Right</span>
        <strong>{learning.right}</strong>
        <span>Wrong</span>
        <strong>{learning.wrong}</strong>
        <span>Agreement</span>
        <strong>
          {learning.weighted_agreement_percent === null
            ? 'Not recorded'
            : formatHumanPercent(learning.weighted_agreement_percent)}
        </strong>
      </div>
    )
  }

  return (
    <section className="learning-summary" aria-label="Authentic learning status">
      <div className="learning-summary__metric">
        <span>Authentic signals</span>
        <strong>{learning.eligible_dispositions} / {learning.minimum_dispositions}</strong>
        <small>{learning.floor_met ? 'Floor met' : `${learning.remaining_to_floor} to floor`}</small>
      </div>
      <div className="learning-summary__metric learning-summary__metric--right">
        <span>Right</span>
        <strong>{learning.right}</strong>
        <small>{formatHumanQuantity(learning.weighted_right)} weighted</small>
      </div>
      <div className="learning-summary__metric learning-summary__metric--wrong">
        <span>Wrong</span>
        <strong>{learning.wrong}</strong>
        <small>{formatHumanQuantity(learning.weighted_wrong)} weighted</small>
      </div>
      <div className="learning-summary__metric">
        <span>Weighted agreement</span>
        <strong>
          {learning.weighted_agreement_percent === null
            ? 'Not recorded'
            : formatHumanPercent(learning.weighted_agreement_percent)}
        </strong>
        <small>Active {learning.active_scorer_version}</small>
      </div>
      <p className="learning-summary__cadence">{learningCadenceCopy(learning)}</p>
      <p className="learning-summary__hygiene">{learningHygieneCopy(learning)}</p>
    </section>
  )
}

export function LearningTimeline({
  learning,
  accuracy,
  mode = 'both',
}: {
  learning: ScorerConsoleLearning
  accuracy: readonly ScorerAccuracyPoint[]
  mode?: 'both' | 'generations'
}) {
  const model = learningTimelineModel(learning, accuracy)
  const showLive = mode === 'both'
  const hasPoints = model.generations.length > 0 || (showLive && model.live.length > 0)
  const accessiblePoints = [
    ...(showLive ? model.live.map((point) => (
      `Live ${formatHumanPercent(point.percent)} at ${point.timestamp}, scorer ${point.version}`
    )) : []),
    ...model.generations.map((point) => (
      `Generation ${point.version}, ${formatHumanPercent(point.percent)} at ${point.timestamp}`
    )),
  ]

  return (
    <figure
      className={`learning-timeline learning-timeline--${mode}`}
      aria-label={mode === 'both'
        ? 'Active agreement and held-out generation accuracy'
        : 'Held-out accuracy by scorer generation'}
    >
      {!hasPoints ? (
        <p className="learning-timeline__empty">No measured learning scores yet.</p>
      ) : (
        <svg viewBox="0 0 100 100" role="img" aria-label="Learning score timeline">
          <line className="learning-timeline__grid" x1="8" y1="12" x2="92" y2="12" />
          <line className="learning-timeline__grid" x1="8" y1="50" x2="92" y2="50" />
          <line className="learning-timeline__grid" x1="8" y1="88" x2="92" y2="88" />
          {mode === 'both' && model.annotations.map((annotation) => (
            <line
              key={annotation.event_uid}
              className={`learning-timeline__annotation learning-timeline__annotation--${annotation.kind}`}
              x1={annotation.x}
              y1="7"
              x2={annotation.x}
              y2="92"
            >
              <title>{annotation.label} at {annotation.ts}</title>
            </line>
          ))}
          {showLive && model.live.length > 1 && (
            <polyline
              className="learning-timeline__line learning-timeline__line--live"
              points={chartPolyline(model.live)}
            />
          )}
          {showLive && model.live.map((point) => (
            <circle
              key={point.id}
              className="learning-timeline__point learning-timeline__point--live"
              cx={point.x}
              cy={point.y}
              r="1.4"
            >
              <title>{formatHumanPercent(point.percent)} live agreement · {point.timestamp}</title>
            </circle>
          ))}
          {model.generations.length > 1 && (
            <polyline
              className="learning-timeline__line learning-timeline__line--generation"
              points={chartPolyline(model.generations)}
            />
          )}
          {model.generations.map((point) => (
            <circle
              key={point.id}
              className="learning-timeline__point learning-timeline__point--generation"
              cx={point.x}
              cy={point.y}
              r="2"
            >
              <title>{point.version} · {formatHumanPercent(point.percent)} held-out agreement</title>
            </circle>
          ))}
        </svg>
      )}
      <figcaption>
        {showLive && <span className="learning-timeline__legend learning-timeline__legend--live">Live agreement history</span>}
        <span className="learning-timeline__legend learning-timeline__legend--generation">Held-out generations</span>
        {model.unmeasuredGenerations > 0 && (
          <small>{model.unmeasuredGenerations} legacy {model.unmeasuredGenerations === 1 ? 'generation' : 'generations'} not recorded</small>
        )}
      </figcaption>
      <ol className="visually-hidden">
        {accessiblePoints.map((copy) => <li key={copy}>{copy}</li>)}
        {mode === 'both' && model.annotations.map((annotation) => (
          <li key={`annotation:${annotation.event_uid}`}>{annotation.label} at {annotation.ts}</li>
        ))}
      </ol>
      {mode === 'both' && model.annotations.length > 0 && (
        <div className="learning-timeline__annotations" aria-hidden="true">
          {model.annotations.map((annotation) => (
            <span key={annotation.event_uid}>{annotation.label}</span>
          ))}
        </div>
      )}
    </figure>
  )
}
