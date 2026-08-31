import { useEffect, useState } from 'react'

import type { JsonValue } from './protocol'
import { useRackPlugin, useRackSnapshot } from './rack'
import { formatHumanCount, formatHumanPercent } from './humanNumbers'
import './assets/honest-display.css'

type Scope = 'GLOBAL' | 'ATTUNED'
type Category = 'system' | 'history' | 'memory' | 'tools'

interface Observation {
  model: string
  used_tokens: number
  context_tokens: number
  threshold_tokens: number
  categories: Record<Category, number>
  memory_allocation: MemoryAllocation | null
}
interface MemoryAllocation {
  memory_context_share: number
  share_tokens: number
  regular_tokens: number
  pinned_tokens: number
  total_tokens: number
  pinned_overflow_tokens: number
  actual_block_tokens: number
  unused_share_tokens: number
}

const CATEGORY_LABELS: Record<Category, string> = {
  system: 'System', history: 'History', memory: 'Memory', tools: 'Tools',
}
const CATEGORIES: Category[] = ['system', 'history', 'memory', 'tools']
export function ContextBars() {
  const { events, query } = useRackPlugin()
  const rack = useRackSnapshot()
  const [scope, setScope] = useState<Scope>('ATTUNED')
  const [observation, setObservation] = useState<Observation | null>(null)
  const [failed, setFailed] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [collapsed, setCollapsed] = useState(() => globalThis.innerHeight < 120)

  useEffect(() => {
    void events.dispatch({ type: 'rack.scope.get', module_id: 'context_bars' }).then(setScope)
  }, [events])

  useEffect(() => {
    let active = true
    if (scope === 'ATTUNED' && rack.selectedThreadId === null) {
      return () => { active = false }
    }
    const threadId = scope === 'ATTUNED' ? rack.selectedThreadId ?? undefined : undefined
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

  const visibleObservation = scope === 'ATTUNED' && rack.selectedThreadId === null
    ? null
    : observation
  const usedPercent = visibleObservation === null
    ? 0
    : Math.min(100, visibleObservation.used_tokens / visibleObservation.context_tokens * 100)

  return (
    <section className={`context-bars${collapsed ? ' context-bars--collapsed' : ''}`} aria-label="Context usage">
      <header className="context-bars__header">
        <div>
          <strong title={visibleObservation === null ? 'Waiting for a model response' : undefined}>
            {visibleObservation === null ? '—' : `${formatHumanCount(visibleObservation.used_tokens)} / ${formatHumanCount(visibleObservation.context_tokens)}`}
          </strong>
        </div>
      </header>
      {visibleObservation !== null && (
        <>
          <div className="context-bars__track" aria-label={`${formatHumanPercent(usedPercent)} of context used`}>
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
            <caption>Token breakdown</caption>
            <tbody>{CATEGORIES.map((category) => (
              <tr key={category}><td><i className={`context-bars__key context-bars__key--${category}`} />{CATEGORY_LABELS[category]}</td><td>{formatHumanCount(visibleObservation.categories[category])}</td></tr>
            ))}</tbody>
          </table>
          {visibleObservation.memory_allocation !== null && (
            <p className="context-bars__memory-room">
              Memory block {formatHumanCount(visibleObservation.memory_allocation.actual_block_tokens)} / {formatHumanCount(visibleObservation.memory_allocation.share_tokens)} share ({formatHumanPercent(visibleObservation.memory_allocation.memory_context_share * 100)})
              {visibleObservation.memory_allocation.pinned_overflow_tokens > 0
                ? ` · Pinned overflow +${formatHumanCount(visibleObservation.memory_allocation.pinned_overflow_tokens)}`
                : ` · ${formatHumanCount(visibleObservation.memory_allocation.unused_share_tokens)} unused returns to chat`}
            </p>
          )}
          <p className="context-bars__note">Tools include measured traffic · other lanes estimated · 80% line · Compaction is not active</p>
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
  const memoryAllocation = parseMemoryAllocation(item.memory_allocation)
  return {
    model: item.model,
    used_tokens: item.used_tokens,
    context_tokens: item.context_tokens,
    threshold_tokens: item.threshold_tokens,
    categories: categories as unknown as Record<Category, number>,
    memory_allocation: memoryAllocation,
  }
}

function parseMemoryAllocation(value: JsonValue | undefined): MemoryAllocation | null {
  if (!isRecord(value)) return null
  const keys = [
    'memory_context_share', 'share_tokens', 'regular_tokens', 'pinned_tokens',
    'total_tokens', 'pinned_overflow_tokens', 'actual_block_tokens', 'unused_share_tokens',
  ] as const
  if (!keys.every((key) => typeof value[key] === 'number')) return null
  return value as unknown as MemoryAllocation
}

function isRecord(value: unknown): value is Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
