import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { ownerConnectionCopy } from '../src/surfaceHonesty.ts'
import { scan, violations } from '../../scripts/check_product_terms.mjs'

/** F045 and B.6 rule 12 keep the local app transport distinct from live Palace health. */
test('owner connection copy never claims whole-product health from the socket alone', () => {
  assert.equal(ownerConnectionCopy('connected', 'checking'), 'Checking Palace')
  assert.equal(ownerConnectionCopy('connected', 'ready'), 'Palace ready')
  assert.equal(ownerConnectionCopy('connected', 'unavailable'), 'Palace unavailable')
  assert.equal(ownerConnectionCopy('reconnecting', 'ready'), 'Reconnecting')
  assert.equal(ownerConnectionCopy('disconnected', 'ready'), 'Nocturne offline')
})

/** SPEC D.2 130 and P2 keep retired modes and build vocabulary out of every product surface. */
test('source tree product copy rejects internal words and work identifiers', () => {
  assert.deepEqual(scan(new URL('../src', import.meta.url).pathname), [])
  for (const word of ['ensem' + 'ble', 'garden', 'relay', 'M3' + 'RC']) {
    assert.equal(violations(`const label = '${word}'`, 'sample.ts').length, 1)
  }
  assert.deepEqual(violations("// M3RC citation\nconst label = 'Symphony'", 'sample.ts'), [])
})

/** F045, D.2 095, and NATES_VISION section 18 keep owner copy free of build vocabulary. */
test('owner surfaces state the situation without daemon, factory, or link jargon', async () => {
  const files = await Promise.all([
    'App.tsx',
    'MemoryPanel.tsx',
    'ProjectSelector.tsx',
    'socket.ts',
    'VitalsModule.tsx',
    'PalaceStateModule.tsx',
  ].map((path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')))
  const source = files.join('\n')

  for (const forbidden of [
    'Link live',
    '>Linked<',
    'Factory-set navigation',
    '>Factory<',
    'Awaiting daemon',
    'Waiting for daemon',
    'Daemon memory',
    'Daemon uptime',
    'invalid daemon envelope',
    'Waiting for link',
  ]) {
    assert.doesNotMatch(source, new RegExp(forbidden, 'u'))
  }
})
