import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isLegacyFixtureTitle,
  normalizedThreadTitle,
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

/** SPEC B.6 / M2UX1 keeps the secondary thread-list summary bounded without clipping its last word. */
test('shortens a long generated title only at a complete-word boundary', () => {
  assert.equal(
    normalizedThreadTitle(
      'Explain the mechanical no-overlap and no-clipped-text viewport sweep for the owner.',
    ),
    'Explain the mechanical no-overlap and…',
  )
})

/** P2 / SPEC B.6: a title cut short by the journal ends on a whole word wherever it is shown. */
test('shows a journal title cut mid-word only up to its last whole word', () => {
  const journal = 'Walk the release checklist for the harness and memory packages and their changelo'
  assert.equal(visibleThreadTitle(journal), 'Walk the release checklist for the harness and…')
})
