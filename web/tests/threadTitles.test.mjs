import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isLegacyFixtureTitle,
  visibleThreadTitle,
} from '../src/threadTitles.ts'

/** A-051 / M2Z4 retires the visible fixture phrase without stranding polluted catalogs. */
test('recognizes and masks the retired fixture title through its migration fingerprint', () => {
  const polluted = ['Which', 'Garden', 'memory', 'governs', 'this', 'handoff?'].join(' ')

  assert.equal(isLegacyFixtureTitle(polluted), true)
  assert.equal(visibleThreadTitle(polluted), 'Verification thread')
})

/** A-051 / M2Z4 keeps ordinary owner titles untouched by the narrow legacy migration. */
test('does not redact an owner thread or alter older cleanup recognition', () => {
  assert.equal(visibleThreadTitle('Plan the courtyard planting'), 'Plan the courtyard planting')
  assert.equal(isLegacyFixtureTitle('Plan the courtyard planting'), false)
  assert.equal(isLegacyFixtureTitle('Open the H6 verification thread context.'), true)
  assert.equal(visibleThreadTitle('Open the H6 verification thread context.'), 'Open the H6 verification thread context.')
})
