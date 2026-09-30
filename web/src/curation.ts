import type { JsonValue } from './protocol'

export interface CuratorActivityView {
  admitted_writes: number
  trigger_every: number
  writes_until_run: number
  pressure_until_run: number
  pending_cards: number
  latest_run: { status: 'completed' | 'failed'; completed_at: string } | null
  growth: Array<{ at: string; active_units: number; curator_removals: number }>
}

export function curatorActivityFrom(value: JsonValue): CuratorActivityView | null {
  if (!isObject(value) || typeof value.admitted_writes !== 'number' ||
    typeof value.trigger_every !== 'number' || typeof value.writes_until_run !== 'number' ||
    typeof value.pressure_until_run !== 'number' || typeof value.pending_cards !== 'number') return null
  const latest = value.latest_run
  if (latest !== null && (!isObject(latest) ||
    (latest.status !== 'completed' && latest.status !== 'failed') ||
    typeof latest.completed_at !== 'string')) return null
  const normalizedLatest = latest === null ? null : {
    status: latest.status === 'completed' ? 'completed' as const : 'failed' as const,
    completed_at: String(latest.completed_at),
  }
  return {
    admitted_writes: value.admitted_writes,
    trigger_every: value.trigger_every,
    writes_until_run: value.writes_until_run,
    pressure_until_run: value.pressure_until_run,
    pending_cards: value.pending_cards,
    latest_run: normalizedLatest,
    growth: Array.isArray(value.growth) ? value.growth.filter((point) =>
      isObject(point) && typeof point.at === 'string' && typeof point.active_units === 'number' &&
      typeof point.curator_removals === 'number'
    ) as CuratorActivityView['growth'] : [],
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
