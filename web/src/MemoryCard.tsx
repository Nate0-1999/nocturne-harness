import type { ReactNode } from 'react'
import type { MemoryFeatures } from './protocol'
import { FeatureRadar, HoverReveal } from './FeatureRadar'
import { formatHumanScore } from './humanNumbers'

/** SD-068, the compact memory card: score, name and memory. The relevance
 * spider web and the provenance pop up on hover; the actions are small buttons. */
export function MemoryCard({
  memoryId, label, body, score, pin, features, contributions, provenance,
  status, actions, tone = 'stored', testId = 'memory-card', children,
}: {
  memoryId: string
  label: string
  body: string
  score?: number | null
  pin?: boolean
  features?: MemoryFeatures | null
  contributions?: Record<string, string | null> | null
  provenance?: ReactNode
  status?: ReactNode
  actions?: ReactNode
  tone?: 'injected' | 'removed' | 'near-miss' | 'added' | 'stored' | 'context' | 'unavailable'
  testId?: string
  children?: ReactNode
}) {
  const detail = (features == null && contributions == null && provenance === undefined) ? null : (
    <div className="memory-card__detail">
      {(features != null || contributions != null) && <FeatureRadar features={features} contributions={contributions} />}
      {provenance !== undefined && <dl className="memory-card__provenance">{provenance}</dl>}
    </div>
  )
  return (
    <article className={`memory-card memory-card--${tone}`} data-testid={testId} data-memory-id={memoryId} data-tone={tone}>
      <header className="memory-card__header">
        {detail === null ? (
          <div className="memory-card__title">
            <MemoryScore score={score} />
            <h4>{label}</h4>
            {pin && <span className="memory-card__pin">Pinned</span>}
          </div>
        ) : (
          <HoverReveal className="memory-card__title" panel={detail}>
            <MemoryScore score={score} />
            <h4>{label}</h4>
            {pin && <span className="memory-card__pin">Pinned</span>}
          </HoverReveal>
        )}
        {actions !== undefined && <div className="memory-card__decision">{actions}</div>}
      </header>
      {status !== undefined && <p className="memory-card__status">{status}</p>}
      <p className="memory-card__body">{body}</p>
      {children}
    </article>
  )
}

function MemoryScore({ score }: { score?: number | null }) {
  if (score == null) return null
  return <strong className="memory-card__total" data-testid="memory-total-score">{formatHumanScore(score)}</strong>
}

/** One provenance line inside the hover panel. */
export function Provenance({ term, children }: { term: string; children: ReactNode }) {
  return <><dt>{term}</dt><dd>{children}</dd></>
}
