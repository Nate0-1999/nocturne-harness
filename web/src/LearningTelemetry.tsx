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

export type TerrainPoint = { tau: number; share: number; agreement: number }
export type CreationSummary = {
  sources: { source: string; created: number; surviving: number; used: number; survival_rate: number | null }[]
  hygiene_excluded_events: number
  events: { event_key: string; source: string; outcome: string; reason: string; ts: string }[]
  compaction?: {
    active: { id: string; memory_size: number } | null
    generations: { id: string; parent: string | null; instructions: string; memory_size: number;
      date: string; adopted: boolean; verdict?: string;
      scores: { incumbent: { score: number }; candidate: { score: number } } | null }[]
  }
}

export function CreationScoreboard({ data }: { data?: CreationSummary }) {
  const [size, setSize] = useState(128)
  const [preview, setPreview] = useState(false)
  const [result, setResult] = useState('')
  const [busy, setBusy] = useState(false)
  async function backtest(instructions = false) {
    setBusy(true)
    try {
      const response = await fetch('/v1/rack/compaction-backtest', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_size: instructions ? null : size, preview }),
      })
      if (!response.ok) throw new Error(`Back-test failed (${response.status}).`)
      const value = await response.json()
      setResult(`${value.verdict.replaceAll('_', ' ')}${value.scores?.candidate
        ? ` · current ${value.scores.incumbent.score} · candidate ${value.scores.candidate.score}` : ''}`)
    } catch (error) { setResult(String(error)) }
    finally { setBusy(false) }
  }
  return <section aria-label="Memory creation outcomes" className="learning-summary">
    <h2>Memory creation</h2>
    <p>Compaction instructions and memory size replay the same recent source spans. Only a higher score is adopted; used facts earn one, removed facts cost one, new facts stay neutral.</p>
    <p>Active memory size: {data?.compaction?.active?.memory_size ?? 128} tokens.</p>
    <label>Memory size (tokens)<TextField aria-label="Memory size (tokens)" type="number" min="16" max="128" value={size} onChange={(event) => setSize(Number(event.target.value))} /></label>
    <label><input type="checkbox" checked={preview} onChange={(event) => setPreview(event.target.checked)} />Preview verification records (never adopted)</label>
    <Button variant="bare" disabled={busy || size < 16 || size > 128} onClick={() => void backtest()}>{busy ? 'Back-testing…' : 'Back-test memory size'}</Button>
    <Button variant="bare" disabled={busy} onClick={() => void backtest(true)}>Back-test new instructions</Button>
    {result && <p role="status">{result}</p>}
    <details><summary>Compaction instruction generations</summary>
      {!data?.compaction?.generations.length ? <p>No compaction generation recorded yet.</p> :
        data.compaction.generations.map((generation) => <article key={generation.id}>
          <h3>{generation.id} · {generation.adopted ? 'adopted' : generation.verdict?.replaceAll('_', ' ')}</h3>
          <p>Parent {generation.parent ?? 'none'} · {generation.date} · {generation.memory_size} tokens</p>
          <p>{generation.scores ? `Current ${generation.scores.incumbent.score} · candidate ${generation.scores.candidate.score}` : 'Baseline; no back-test yet.'}</p>
          <pre>{generation.instructions}</pre>
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

export function ScoreTerrain({ points }: { points: TerrainPoint[] }) {
  const [angle, setAngle] = useState(25)
  const mesh = useMemo(() => {
    const vertices: number[] = [], colors: number[] = []
    const steps = Math.round(Math.sqrt(points.length))
    for (let x = 0; x < steps - 1; x++) for (let y = 0; y < steps - 1; y++) {
      const indices = [x * steps + y, (x + 1) * steps + y, x * steps + y + 1,
        x * steps + y + 1, (x + 1) * steps + y, (x + 1) * steps + y + 1]
      for (const index of indices) {
        const point = points[index]
        vertices.push(point.tau - 0.5, point.agreement / 100, (point.share - 0.01) / 0.49 - 0.5)
        colors.push(0.15 + 0.7 * point.agreement / 100, 0.65, 0.95)
      }
    }
    return { vertices: new Float32Array(vertices), colors: new Float32Array(colors) }
  }, [points])
  return <section aria-label="Replay score terrain">
    <h3>Score terrain</h3>
    <p>Held-out decision agreement across minimum match × memory share. Height is agreement; the surface interpolates measured grid points.</p>
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
      <p>X: minimum match 0–1 · depth: memory share 1–50% · height: agreement 0–100%</p>
      <details><summary>Measured grid values</summary><table><thead><tr><th>Minimum match</th><th>Memory share</th><th>Agreement</th></tr></thead><tbody>
        {points.map((point) => <tr key={`${point.tau}-${point.share}`}><td>{point.tau.toFixed(3)}</td><td>{(point.share * 100).toFixed(2)}%</td><td>{point.agreement.toFixed(1)}%</td></tr>)}
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
        {showLive && <span className="learning-timeline__legend learning-timeline__legend--live">Active live</span>}
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
