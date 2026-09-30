import type { JsonObject, JsonValue } from './protocol'

// M3HW (Codex 05): a long turn kept every tool result whole in the page and re-encoded all of
// them on every token. An answer keeps its last 100 stream events, each string at most 2,000
// characters; the conversation journal keeps every event whole.
const STREAM_EVENT_KINDS = new Set([
  'part_start', 'part_delta', 'part_end', 'final_result', 'function_tool_call', 'function_tool_result',
])
export const RETAINED_STREAM_EVENTS = 100
export const RETAINED_EVENT_CHARS = 2_000

function isStreamEvent(event: JsonObject): boolean {
  return STREAM_EVENT_KINDS.has(String(event.event_kind))
}

function trimmedEventValue(value: JsonValue): JsonValue {
  if (typeof value === 'string') {
    return value.length > RETAINED_EVENT_CHARS
      ? `${value.slice(0, RETAINED_EVENT_CHARS)}… ${value.length - RETAINED_EVENT_CHARS} more characters in the journal`
      : value
  }
  if (Array.isArray(value)) return value.map(trimmedEventValue)
  if (value === null || typeof value !== 'object' || value.kind === 'binary') return value // screenshots stay drawable
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, trimmedEventValue(item)]))
}

/** Append arriving events to an answer's retained events (the pure M3HW bound). */
export function retainEvents(events: readonly JsonObject[], arriving: readonly JsonObject[]): JsonObject[] {
  const all = [...events, ...arriving.map((event) => isStreamEvent(event) ? trimmedEventValue(event) as JsonObject : event)]
  const excess = all.filter(isStreamEvent).length - RETAINED_STREAM_EVENTS
  if (excess <= 0) return all
  const earlier = Number(all.find((event) => event.event_kind === 'earlier_stream_events')?.count ?? 0)
  let dropping = excess
  const kept = all.filter((event) => {
    if (event.event_kind === 'earlier_stream_events') return false
    if (dropping > 0 && isStreamEvent(event)) {
      dropping -= 1
      return false
    }
    return true
  })
  return [{ event_kind: 'earlier_stream_events', count: earlier + excess, kept_in: 'the conversation journal' }, ...kept]
}
