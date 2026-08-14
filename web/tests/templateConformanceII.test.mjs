import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const webRoot = new URL('../', import.meta.url)

/** PLAN M2TC / P2 requires one settings dialog and one formatted tip system across every control surface. */
test('shared settings and descriptive hover tips have no strip-specific chrome escape', async () => {
  const [app, tooltip, css] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/ControlTooltip.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
  ])

  assert.match(app, /<dialog open className="rack-module__settings-dialog"/u)
  assert.match(app, /manifest=\{RACK_MANIFESTS\.gate\}/u)
  assert.match(app, /data-tooltip=\{`Resize \$\{manifest\.name\}/u)
  assert.doesNotMatch(app, /rack-module__chrome--strip/u)
  assert.doesNotMatch(css, /rack-module__chrome--strip/u)
  for (const selector of [
    "'button'",
    "'input:not([type=\"hidden\"])'",
    "'select'",
    "'textarea'",
    "'[role=\"button\"]'",
  ]) assert.equal(tooltip.includes(selector), true)
  assert.match(tooltip, /<strong>\{tooltip\.title\}<\/strong>/u)
  assert.match(tooltip, /<span>\{tooltip\.detail\}<\/span>/u)
  assert.match(css, /\.control-tooltip\s*\{/u)
  assert.match(css, /\.rack-module__settings-toggle\s*\{[^}]*border-radius:\s*50%/su)
})

/** PLAN M2TC findings 22-23 / P2 make archive quiet and Model Device visibly actionable. */
test('archive is icon-compact while Model Device advertises its click action', async () => {
  const [app, shellCss, rackCss] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/shell.css', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
  ])

  assert.match(app, /data-tooltip="Archive this thread"/u)
  assert.match(app, /className="chat-header__model-action"/u)
  assert.match(app, /data-tooltip="Open Model Device"/u)
  assert.match(shellCss, /\.thread-item__archive\s*\{[^}]*width:\s*1\.65rem/su)
  assert.match(shellCss, /\.chat-header__model\s*\{[^}]*cursor:\s*pointer/su)
  assert.match(rackCss, /\.archive-button\s*\{[^}]*width:\s*1\.75rem/su)
})
