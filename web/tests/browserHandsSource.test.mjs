import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { browserScreenshotDataUrl, elideBinaryPayload } from '../src/runEventDisplay.ts'

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')

/** F070 / SPEC B.6: the screenshot stays visible while binary diagnostics stay collapsed. */
test('the conversation exposes the screenshot without opening its binary diagnostics', () => {
  assert.match(appSource, /Latest browser screenshot/)
  assert.doesNotMatch(appSource, /open=\{latestBrowserScreenshot !== null\}/)
  assert.match(appSource, /JSON\.stringify\(diagnosticEvents, elideBinaryPayload, 2\)/)
  assert.doesNotMatch(appSource, /BrowserModule|browser-module/)
})

/** F071 / M3B2: real Pydantic screenshot bytes must decode, without leaking into JSON text. */
test('renders URL-safe binary as an image and elides nested diagnostic copies without mutation', () => {
  const binary = { kind: 'binary', media_type: 'image/png', data: '-_8=' }
  const event = { event_kind: 'function_tool_result', part: { tool_name: 'screenshot', content: [binary] }, content: [binary] }
  assert.equal(browserScreenshotDataUrl(event), 'data:image/png;base64,+/8=')
  const displayed = JSON.stringify(event, elideBinaryPayload)
  assert.equal((displayed.match(/image\/png, 1 KB/g) ?? []).length, 2)
  assert.ok(!displayed.includes(binary.data))
  assert.equal(binary.data, '-_8=')
  assert.equal(browserScreenshotDataUrl({ ...event, part: { tool_name: 'bash' } }), null)
})
