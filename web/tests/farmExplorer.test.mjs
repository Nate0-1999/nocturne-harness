import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { explorerPresence, explorerRows } from '../src/explorerTree.ts'

const dir = (path) => ({ path, kind: 'directory', bytes: 0 })
const file = (path) => ({ path, kind: 'file', bytes: 8 })

/** F123 / PLAN M8FX: the familiar tree must preserve roots, ordering and agent locations without crowded rows growing. */
test('Explorer sorts and folds each root, retaining location and touch names behind one line of markers', () => {
  const projects = [
    { root: '/repo', nodes: [dir('.'), file('z.txt'), dir('z'), file('a.txt'), dir('a'), file('a/task.txt')], errors: [] },
    { root: '/worktree', nodes: [dir('.'), file('task.txt')], errors: [] },
  ]
  const paths = (opened) => explorerRows(projects, opened).map((row) => row.id)
  assert.deepEqual(paths({}), ['/repo', '/repo/a', '/repo/z', '/repo/a.txt', '/repo/z.txt', '/worktree', '/worktree/task.txt'])
  assert.deepEqual(paths({ '/repo/a': true }).slice(0, 4), ['/repo', '/repo/a', '/repo/a/task.txt', '/repo/z'])
  assert.deepEqual(paths({ '/repo': false }), ['/repo', '/worktree', '/worktree/task.txt'])
  assert.deepEqual(explorerRows(projects, {}).filter((row) => row.parent === null).map((row) => [row.id, row.level]),
    [['/repo', 1], ['/worktree', 1]])

  const agents = Array.from({ length: 17 }, (_, n) => ({ id: `agent-${n}`, label: `Agent ${n}`, state: 'waiting',
    location: '/worktree', touched_files: [{ path: '/worktree/task.txt' }, { path: '/worktree' }] }))
  const presence = explorerPresence(agents)
  for (const path of ['/worktree', '/worktree/task.txt']) {
    const markers = presence.get(path)
    assert.deepEqual(markers.visible.map(({ agent }) => agent.id), ['agent-0', 'agent-1', 'agent-2'])
    assert.equal(markers.remaining, 14)
    assert.equal(markers.names.split('; ').length, 17)
    for (const agent of agents) assert.ok(markers.names.includes(`${agent.label} ·`))
    assert.ok(markers.visible.every(({ touched }) => touched === (path.endsWith('task.txt'))))
  }
  const css = readFileSync(new URL('../src/assets/farm-explorer.css', import.meta.url), 'utf8')
  const markerStyle = css.match(/\.farm-explorer__agents\{([^}]+)\}/u)[1]
  assert.match(markerStyle, /flex-wrap:nowrap/u)
  assert.match(markerStyle, /height:20px/u)
  assert.match(markerStyle, /flex-shrink:0/u)
  const view = readFileSync(new URL('../src/FarmExplorer.tsx', import.meta.url), 'utf8')
  assert.match(view, /\.visible\.map/u)
  assert.match(view, /agentColor\(agent\.id\)/u)
  assert.match(view, /className="farm-explorer__agents" tabIndex=\{0\}/u)
  assert.match(view, /onMouseEnter=.+showNames/u)
  assert.match(view, /onFocus=.+showNames/u)
  assert.match(view, /role="tooltip" tabIndex=\{0\}>\{badges\.get\(row\.id\)!\.names\}/u)
})
