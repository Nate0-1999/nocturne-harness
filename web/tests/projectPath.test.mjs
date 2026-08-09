import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DEFAULT_PROJECT_PATH,
  UNSCOPED_PROJECT_LABEL,
  canonicalProjectPath,
  knownProjectPaths,
  newestProjectThread,
  projectPathEditValue,
  projectPathError,
  projectScopeLabel,
  projectSelectorContextKey,
} from '../src/projectPath.ts'

/** F028 + SPEC C.3/C.4 + B.6 r12 require one canonical project key at every browser contract edge. */
test('accepts relative project paths and plainly rejects ambiguous path shapes', () => {
  assert.equal(canonicalProjectPath('  build-test/agent-ui  '), 'build-test/agent-ui')
  assert.equal(projectPathError('build-test'), null)

  for (const invalid of ['', '   ', '/absolute', 'one\\two', 'one//two', 'one/', '.', '..', 'one/../two']) {
    assert.notEqual(projectPathError(invalid), null, invalid)
  }
  assert.throws(() => canonicalProjectPath('x'.repeat(257)), /256 characters or fewer/)
})

/** ADR-005 and F028 preserve explicit legacy null scope while seeding the first usable project path. */
test('lists known non-null paths without turning legacy null into a silent match', () => {
  assert.deepEqual(knownProjectPaths([
    { thread_id: 'legacy', project_key: null, updated_at: '2026-08-09T10:00:00.000Z' },
    { thread_id: 'nested', project_key: 'build-test/ui', updated_at: '2026-08-09T11:00:00.000Z' },
    { thread_id: 'duplicate', project_key: DEFAULT_PROJECT_PATH, updated_at: '2026-08-09T12:00:00.000Z' },
  ]), ['build-test', 'build-test/ui'])
  assert.equal(projectPathEditValue(null), '')
  assert.equal(projectScopeLabel(null), UNSCOPED_PROJECT_LABEL)
  assert.equal(projectPathEditValue(UNSCOPED_PROJECT_LABEL), UNSCOPED_PROJECT_LABEL)
  assert.equal(projectScopeLabel(UNSCOPED_PROJECT_LABEL), null)
  assert.equal(knownProjectPaths([
    { thread_id: 'legacy', project_key: null, updated_at: '2026-08-09T10:00:00.000Z' },
  ]).includes(UNSCOPED_PROJECT_LABEL), false)
})

/** ADR-010/023 require the editor to follow shared rail and authoritative project changes. */
test('changes project-editor identity when either thread or authoritative project changes', () => {
  const original = projectSelectorContextKey('thread-a', 'build-test')

  assert.notEqual(projectSelectorContextKey('thread-b', 'build-test'), original)
  assert.notEqual(projectSelectorContextKey('thread-a', 'research'), original)
  assert.notEqual(projectSelectorContextKey('thread-a', null), original)
  assert.notEqual(
    projectSelectorContextKey('thread-a', null),
    projectSelectorContextKey('thread-a', 'unscoped'),
  )
})

/** ADR-010/023 make a project jump shared navigation, never permission to rebind an existing thread. */
test('chooses the newest existing thread for a project and no thread from another project', () => {
  const entries = [
    { thread_id: 'older', project_key: 'build-test', updated_at: '2026-08-09T10:00:00.000Z' },
    { thread_id: 'newer', project_key: 'build-test', updated_at: '2026-08-09T12:00:00.000Z' },
    { thread_id: 'other', project_key: 'research', updated_at: '2026-08-09T13:00:00.000Z' },
  ]

  assert.equal(newestProjectThread(entries, 'build-test')?.thread_id, 'newer')
  assert.equal(newestProjectThread(entries, 'missing'), null)
})
