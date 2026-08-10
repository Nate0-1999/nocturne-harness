import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

/** SPEC B.6 and A-051 require both M2Z4 instruments to remain wheel/touch reachable. */
test('Graph and Injection remotes share a real viewport scroll container', async () => {
  const css = await readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8')
  const rule = /\.rack-remote--memory_graph\s*,\s*\.rack-remote--injection_console\s*\{(?<body>[^}]*)\}/u.exec(css)

  assert.notEqual(rule, null)
  assert.match(rule.groups.body, /overflow:\s*auto\s*;/u)
  assert.match(rule.groups.body, /overscroll-behavior:\s*contain\s*;/u)
})
