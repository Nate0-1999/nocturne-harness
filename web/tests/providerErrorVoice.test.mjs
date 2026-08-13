import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** F034 and v2.52 require the owner surface to distinguish a typed context ceiling from an
 * unknown provider refusal while keeping the ordinary runtime-error fallback honest.
 */
test('provider refusal wire detail and terminal voice stay distinct', async () => {
  const [app, protocol, providerError] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/protocol.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/providerError.ts', import.meta.url), 'utf8'),
  ])

  assert.match(providerError, /classification: 'context_length' \| 'provider_refusal'/u)
  assert.match(protocol, /provider_error\?: ProviderErrorPayload/u)
  assert.match(protocol, /providerError !== undefined && stopReason !== 'error'/u)
  assert.match(app, /return 'Context limit reached'/u)
  assert.match(app, /return 'Provider refused'/u)
  assert.match(app, /return 'Run error · partial kept'/u)
})
