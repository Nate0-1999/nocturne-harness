import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { ownerConnectionCopy } from '../src/surfaceHonesty.ts'

/** F045 and B.6 rule 12 keep the local app transport distinct from live Palace health. */
test('owner connection copy never claims whole-product health from the socket alone', () => {
  assert.equal(ownerConnectionCopy('connected', 'checking'), 'Checking Palace')
  assert.equal(ownerConnectionCopy('connected', 'ready'), 'Palace ready')
  assert.equal(ownerConnectionCopy('connected', 'unavailable'), 'Palace unavailable')
  assert.equal(ownerConnectionCopy('reconnecting', 'ready'), 'Reconnecting')
  assert.equal(ownerConnectionCopy('disconnected', 'ready'), 'Nocturne offline')
})

/** F045, D.2 095, and NATES_VISION section 18 keep owner copy free of build vocabulary. */
test('owner surfaces state the situation without daemon, factory, or link jargon', async () => {
  const files = await Promise.all([
    'App.tsx',
    'MemoryPanel.tsx',
    'ProjectSelector.tsx',
    'socket.ts',
    'VitalsModule.tsx',
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
