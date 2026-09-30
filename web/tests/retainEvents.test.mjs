import assert from 'node:assert/strict'
import test from 'node:test'

import { RETAINED_EVENT_CHARS, RETAINED_STREAM_EVENTS, retainEvents } from '../src/storeRetention.ts'

/** M3HW (Codex 05): a long turn kept every tool result whole in the page and re-encoded all of
 * them on every token, freezing the tab for 37 s. An answer keeps its last 100 stream events,
 * each string cut to 2,000 characters, and every control event whole. */
test('an answer retains a bounded tail of stream events and every control event', () => {
  const file = 'x'.repeat(50_000)
  const screenshot = { kind: 'binary', media_type: 'image/png', data: 'A'.repeat(10_000) }
  let events = retainEvents([], [{ event_kind: 'human_interjection', instruction: file }])
  for (let index = 0; index < 250; index += 1) {
    events = retainEvents(events, [{ event_kind: 'function_tool_result', index, result: { content: file }, content: [screenshot] }])
  }
  events = retainEvents(events, [{ event_kind: 'turn_limit', request_limit: 40 }])
  const stream = events.filter((event) => event.event_kind === 'function_tool_result')
  assert.equal(stream.length, RETAINED_STREAM_EVENTS)
  assert.equal(stream[0].index, 150)
  assert.equal(events[0].event_kind, 'earlier_stream_events')
  assert.equal(events[0].count, 150)
  assert.equal(events.filter((event) => event.event_kind === 'earlier_stream_events').length, 1)
  assert.equal(events.find((event) => event.event_kind === 'human_interjection').instruction, file)
  assert.equal(events.at(-1).event_kind, 'turn_limit')
  assert.equal(stream[0].result.content.length < RETAINED_EVENT_CHARS + 60, true)
  assert.match(stream[0].result.content, /48,?000 more characters in the journal$/u)
  assert.deepEqual(stream[0].content, [screenshot])
})
