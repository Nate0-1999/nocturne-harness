import assert from 'node:assert/strict'
import test from 'node:test'

import { parseProviderError } from '../src/providerError.ts'

/** F039 and D.2 112 are defended by accepting the real provider serialization after a
 * bounded split-planning refusal, so its run reaches one terminal state instead of Streaming.
 */
test('split-planning refusal with null optional provider fields is terminal', () => {
  const decoded = parseProviderError({
    classification: 'provider_refusal',
    message: 'Provider request timed out.',
    model: 'provider/model',
    status_code: null,
    code: null,
    provider_code: null,
  })

  assert.deepEqual(decoded, {
    classification: 'provider_refusal',
    message: 'Provider request timed out.',
    model: 'provider/model',
  })
})

/** F043 and D.2 112 are defended by accepting the exact real Reka ceiling envelope, so the
 * lawful archive remedy is followed by one terminal error rather than a stuck Streaming run.
 */
test('context-limit remedy with null optional provider codes is terminal', () => {
  const decoded = parseProviderError({
    classification: 'context_length',
    message: 'This endpoint has a 16384 token context limit.',
    model: 'rekaai/reka-edge',
    status_code: 400,
    code: null,
    provider_code: null,
  })

  assert.deepEqual(decoded, {
    classification: 'context_length',
    message: 'This endpoint has a 16384 token context limit.',
    model: 'rekaai/reka-edge',
    status_code: 400,
  })
})
