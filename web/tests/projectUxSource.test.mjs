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

/** F035, ADR-023 clause 5, and B.6 r12 require the Project control itself to render
 * the reconciled daemon value instead of relying on an App remount timing side effect.
 */
test('Project control derives its visible draft from snapshot reconciliation', async () => {
  const [selector, app] = await Promise.all([
    readFile(new URL('../src/ProjectSelector.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(selector, /reconcileProjectControlState\([\s\S]*?awaitingSnapshot/u)
  assert.match(selector, /control !== storedControl[\s\S]*?setStoredControl\(control\)/u)
  assert.match(selector, /const projectDraft = control\.edit \?\? projectPathEditValue\(currentProjectKey\)/u)
  assert.doesNotMatch(app, /key=\{projectSelectorContextKey/u)
})

/** F041, ADR-005, and B.6 r12 require both Rack projections to withhold a
 * catalog-requested project while the daemon snapshot is still pending.
 */
test('Rack exposes only snapshot-acknowledged project bindings', async () => {
  const rack = await readFile(new URL('../src/rack.tsx', import.meta.url), 'utf8')
  const selector = await readFile(new URL('../src/ProjectSelector.tsx', import.meta.url), 'utf8')

  assert.equal((rack.match(/authoritativeProjectPath\(/gu) ?? []).length, 2)
  assert.match(rack, /awaitingSnapshot \?\? true/u)
  assert.match(selector, /const scopeLabel = awaitingSnapshot \? null : projectScopeLabel/u)
  assert.match(selector, /Confirming project/u)
})
