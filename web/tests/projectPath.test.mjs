import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DEFAULT_PROJECT_PATH,
  UNSCOPED_PROJECT_LABEL,
  authoritativeProjectPath,
  canonicalProjectPath,
  initialProjectControlState,
  knownProjectPaths,
  newestProjectThread,
  projectPathEditValue,
  projectPathError,
  projectScopeLabel,
  projectSelectorContextKey,
  reconcileProjectControlState,
} from '../src/projectPath.ts'

/** F041, ADR-005, and B.6 r12 require a requested project to remain a draft
 * until the daemon snapshot acknowledges the binding.
 */
test('renders a project path only after authoritative snapshot acknowledgement', () => {
  assert.equal(authoritativeProjectPath('requested-project', true), null)
  assert.equal(authoritativeProjectPath('accepted-project', false), 'accepted-project')
  assert.equal(authoritativeProjectPath(null, false), null)
})

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

/** F035, ADR-023 clause 5, and B.6 r12 require the daemon-owned project binding to
 * replace a submitted browser draft after acceptance, refusal, reload, and thread switch.
 */
test('re-renders project control from authoritative context at every reconciliation boundary', () => {
  const editing = {
    ...initialProjectControlState('thread-a', 'build-test'),
    edit: 'm2xs-build-test',
    submitted: true,
  }

  assert.deepEqual(
    reconcileProjectControlState(editing, 'thread-b', 'm2xs-build-test', false),
    initialProjectControlState('thread-b', 'm2xs-build-test'),
    'accepted project jump follows the acknowledged thread and project',
  )
  assert.deepEqual(
    reconcileProjectControlState(editing, 'thread-a', 'build-test', false),
    {
      ...initialProjectControlState('thread-a', 'build-test'),
      feedback: 'Project m2xs-build-test was not bound. This thread remains in build-test.',
    },
    'refused project jump restores and explains the unchanged daemon binding',
  )
  assert.deepEqual(
    reconcileProjectControlState(
      initialProjectControlState('thread-a', 'build-test'),
      'thread-a',
      'build-test',
      false,
    ),
    initialProjectControlState('thread-a', 'build-test'),
    'reload starts from daemon-hydrated context without a local draft',
  )
  assert.deepEqual(
    reconcileProjectControlState(editing, 'thread-c', 'research', true),
    {
      ...editing,
      contextKey: projectSelectorContextKey('thread-c', 'research'),
    },
    'a submitted draft survives only until the new thread hydration resolves it',
  )
  const switched = reconcileProjectControlState(editing, 'thread-c', 'research', true)
  const refused = reconcileProjectControlState(switched, 'thread-a', 'build-test', false)
  assert.equal(refused.edit, null)
  assert.equal(refused.submitted, false)
  assert.match(refused.feedback ?? '', /was not bound/u)
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
