import assert from 'node:assert/strict'
import test from 'node:test'
import { FARM_CELLS, FARM_CHAMBERS, layoutFarm } from '../src/farmLayout.ts'

const dir = (path) => ({ path, kind: 'directory', bytes: 0 })
const file = (path) => ({ path, kind: 'file', bytes: 8 })

/** F122 / PLAN M3FT: the large-tree frontier must account for every file and empty folder. */
test('depth folding bounds geometry without losing files or folders, including git contents', () => {
  const project = { root: '/repo', nodes: [dir('.'), dir('.git'), dir('.git/objects'), file('.git/objects/hash'),
    ...Array.from({ length: 40 }, (_, n) => [dir(`pkg${n}`), dir(`pkg${n}/empty`),
      ...Array.from({ length: 100 }, (_, f) => file(`pkg${n}/file${f}`))]).flat()], errors: [] }
  const layout = layoutFarm(project)
  assert.ok(layout.chambers.length <= FARM_CHAMBERS)
  assert.ok(layout.chambers.flatMap(c => c.files).length <= FARM_CELLS)
  assert.equal(layout.chambers.reduce((sum, c) => sum + c.files.length + c.hiddenFiles, 0), 4001)
  assert.equal(layout.chambers.reduce((sum, c) => sum + 1 + c.hiddenFolders, 0), 83)
  const expanded = layoutFarm(project, 'pkg0')
  assert.equal(expanded.files, 100)
  assert.equal(expanded.chambers.flatMap(c => c.files).length, 100)
  assert.ok(expanded.chambers.some(c => c.path === 'empty'))
  assert.deepEqual(layoutFarm(structuredClone(project)), layout)
})

/** F122 / PLAN M3FT: even a wide, shallow folder stays truthful; browsing can reach every entry. */
test('a shallow oversized folder collapses to exact counts; a small tree stays fully visible', () => {
  const huge = { root: '/repo', nodes: [dir('.'), ...Array.from({ length: 5000 }, (_, n) => file(`f${n}`))], errors: [] }
  assert.equal(layoutFarm(huge).chambers[0].hiddenFiles, 5000)
  const small = { ...huge, nodes: [dir('.'), dir('src'), dir('empty'), file('src/a.py'), file('b.py')] }
  const layout = layoutFarm(small)
  assert.equal(layout.chambers.length, 3)
  assert.equal(layout.chambers.flatMap(c => c.files).length, 2)
  assert.equal(layout.chambers.reduce((sum, c) => sum + c.hiddenFiles + c.hiddenFolders, 0), 0)
})
