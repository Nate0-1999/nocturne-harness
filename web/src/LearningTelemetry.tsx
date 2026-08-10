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

export function LearningSummary({
  learning,
  compact = false,
}: {
  learning: ScorerConsoleLearning
  compact?: boolean
}) {
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
            : `${learning.weighted_agreement_percent}%`}
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
        <small>{learning.weighted_right} weighted</small>
      </div>
      <div className="learning-summary__metric learning-summary__metric--wrong">
        <span>Wrong</span>
        <strong>{learning.wrong}</strong>
        <small>{learning.weighted_wrong} weighted</small>
      </div>
      <div className="learning-summary__metric">
        <span>Weighted agreement</span>
        <strong>
          {learning.weighted_agreement_percent === null
            ? 'Not recorded'
            : `${learning.weighted_agreement_percent}%`}
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
      `Live ${point.percent}% at ${point.timestamp}, scorer ${point.version}`
    )) : []),
    ...model.generations.map((point) => (
      `Generation ${point.version}, ${point.percent}% at ${point.timestamp}`
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
              <title>{point.percent}% live agreement · {point.timestamp}</title>
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
              <title>{point.version} · {point.percent}% held-out agreement</title>
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
