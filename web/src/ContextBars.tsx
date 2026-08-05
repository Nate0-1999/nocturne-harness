import { useEffect, useState } from 'react'

import type { JsonValue } from './protocol'
import { useRackPlugin, useRackSnapshot } from './rack'

type Scope = 'GLOBAL' | 'CURRENT'
type Category = 'system' | 'history' | 'memory' | 'tools'

interface Observation {
  model: string
  used_tokens: number
  context_tokens: number
  threshold_tokens: number
  categories: Record<Category, number>
}

const CATEGORY_LABELS: Record<Category, string> = {
  system: 'System', history: 'History', memory: 'Memory', tools: 'Tools',
}
const CATEGORIES: Category[] = ['system', 'history', 'memory', 'tools']
const number = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })

export function ContextBars() {
  const { events, query } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<Scope>('CURRENT')
  const [observation, setObservation] = useState<Observation | null>(null)
  const [failed, setFailed] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [collapsed, setCollapsed] = useState(() => globalThis.innerHeight < 120)

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'context_bars' }).then(setScope)
  }, [events])

  useEffect(() => {
    let active = true
    if (scope === 'CURRENT' && rack.selectedThreadId === null) {
      return () => { active = false }
    }
    const threadId = scope === 'CURRENT' ? rack.selectedThreadId ?? undefined : undefined
    void query.query({ resource: 'context_window', as_of: 'now', thread_id: threadId })
      .then((result) => {
        if (!active) return
        setObservation(parseObservation(result.data))
        setFailed(false)
      })
      .catch(() => {
        if (!active) return
        setFailed(true)
      })
    return () => { active = false }
  }, [query, rack.selectedThreadId, refresh, scope])

  useEffect(() => events.subscribe((event) => {
    if (event.direction === 'inbound' && event.envelope.type === 'run.done') {
      setRefresh((value) => value + 1)
    }
  }), [events])

  useEffect(() => events.subscribeResize((event) => {
    setCollapsed(event.grid_height === 1)
  }), [events])

  function choose(next: Scope) {
    setScope(next)
    void events.dispatch({ type: 'rack.scope.set', module_id: 'context_bars', scope: next })
  }

  const visibleObservation = scope === 'CURRENT' && rack.selectedThreadId === null
    ? null
    : observation
  const usedPercent = visibleObservation === null
    ? 0
    : Math.min(100, visibleObservation.used_tokens / visibleObservation.context_tokens * 100)

  return (
    <section className={`context-bars${collapsed ? ' context-bars--collapsed' : ''}`} aria-label="Context usage">
      <header className="context-bars__header">
        <div>
          <p className="eyebrow">Context</p>
          <strong>{visibleObservation === null ? 'Waiting for a model response' : `${number.format(visibleObservation.used_tokens)} / ${number.format(visibleObservation.context_tokens)}`}</strong>
        </div>
        <div className="scope-switch" aria-label="Context scope">
          <button aria-pressed={scope === 'GLOBAL'} onClick={() => choose('GLOBAL')}>Global</button>
          <button aria-pressed={scope === 'CURRENT'} onClick={() => choose('CURRENT')}>Current</button>
        </div>
      </header>
      {visibleObservation !== null && (
        <>
          <div className="context-bars__track" aria-label={`${usedPercent.toFixed(1)}% of context used`}>
            {CATEGORIES.map((category) => (
              <span
                key={category}
                className={`context-bars__segment context-bars__segment--${category}`}
                style={{ width: `${visibleObservation.categories[category] / visibleObservation.context_tokens * 100}%` }}
              />
            ))}
            <i style={{ left: `${visibleObservation.threshold_tokens / visibleObservation.context_tokens * 100}%` }} title="80% threshold" />
          </div>
          <table className="context-bars__legend">
            <caption>Estimated token breakdown</caption>
            <tbody>{CATEGORIES.map((category) => (
              <tr key={category}><td><i className={`context-bars__key context-bars__key--${category}`} />{CATEGORY_LABELS[category]}</td><td>{number.format(visibleObservation.categories[category])}</td></tr>
            ))}</tbody>
          </table>
          <p className="context-bars__note">Estimated breakdown · 80% line · Compaction is not active</p>
        </>
      )}
      {failed && <button className="context-bars__retry" onClick={() => setRefresh((value) => value + 1)}>Context usage unavailable · retry</button>}
    </section>
  )
}

function parseObservation(value: JsonValue | null): Observation | null {
  if (!isRecord(value) || !isRecord(value.aggregate)) return null
  const item = value.aggregate
  if (
    typeof item.model !== 'string' || typeof item.used_tokens !== 'number' ||
    typeof item.context_tokens !== 'number' || typeof item.threshold_tokens !== 'number' ||
    !isRecord(item.categories)
  ) return null
  const categories = item.categories
  if (!CATEGORIES.every((key) => typeof categories[key] === 'number')) return null
  return {
    model: item.model,
    used_tokens: item.used_tokens,
    context_tokens: item.context_tokens,
    threshold_tokens: item.threshold_tokens,
    categories: categories as unknown as Record<Category, number>,
  }
}

function isRecord(value: unknown): value is Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
