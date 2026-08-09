import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** F028, ADR-023, and B.6 r12 require the plain project-conflict remedy to remain
 * readable when an artificial path reaches its 256-code-point bound on a narrow rack.
 */
test('the project-conflict message owns a shrinkable anywhere-wrapping flex item', async () => {
  const [app, css] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/assets/shell.css', import.meta.url), 'utf8'),
  ])
  const rule = /\.error-line \.error-line__message\s*\{(?<body>[^}]*)\}/u.exec(css)

  assert.match(app, /className="error-line__message"/u)
  assert.notEqual(rule, null)
  assert.match(rule.groups.body, /min-width:\s*0/u)
  assert.match(rule.groups.body, /overflow-wrap:\s*anywhere/u)
})

/** F028, ADR-010/023, and B.6 r12 require the owner keyboard SOP to commit the
 * edited project path directly, without relying on browser-specific implicit submit.
 */
test('Project input Enter and form submit share one project-open path', async () => {
  const source = await readFile(new URL('../src/ProjectSelector.tsx', import.meta.url), 'utf8')

  assert.match(source, /function openProject\(\)/u)
  assert.match(source, /function submitProject\([^)]*\)[^{]*\{\s*event\.preventDefault\(\)\s*openProject\(\)/u)
  assert.match(source, /function handleProjectKeyDown\([^)]*\)[^{]*\{[\s\S]*?event\.preventDefault\(\)\s*openProject\(\)/u)
  assert.match(source, /onKeyDown=\{handleProjectKeyDown\}/u)
})
