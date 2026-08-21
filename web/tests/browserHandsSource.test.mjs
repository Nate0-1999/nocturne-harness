import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')

test('the existing Tools detail exposes the latest browser screenshot', () => {
  assert.match(appSource, /function browserScreenshotDataUrl\(event: JsonObject\)/)
  assert.match(appSource, /part\.tool_name !== 'screenshot'/)
  assert.match(appSource, /Latest browser screenshot/)
  assert.match(appSource, /<details className="run-detail" open=\{latestBrowserScreenshot !== null\}>/)
  assert.doesNotMatch(appSource, /BrowserModule|browser-module/)
})
