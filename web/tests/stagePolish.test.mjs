import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  STAGE_COLUMNS,
  STAGE_FINE_GRID_SIZE,
  STAGE_ROWS,
  STAGE_UNIT_HEIGHT,
  STAGE_UNIT_WIDTH,
} from '../src/stageLayout.ts'

const webRoot = new URL('../', import.meta.url)

/** PLAN M2SP / P2 makes the Stage feel continuous and puts its boundary beyond casual panning. */
test('the centered canvas is four times larger per axis and carries a subordinate fine grid', async () => {
  const [app, css] = await Promise.all([
    readFile(new URL('src/App.tsx', webRoot), 'utf8'),
    readFile(new URL('src/assets/rack.css', webRoot), 'utf8'),
  ])

  assert.equal(STAGE_COLUMNS * STAGE_UNIT_WIDTH, 4 * 32 * 96)
  assert.equal(STAGE_ROWS * STAGE_UNIT_HEIGHT, 4 * 22 * 72)
  assert.ok(STAGE_FINE_GRID_SIZE < STAGE_UNIT_HEIGHT)
  assert.match(app, /'--stage-fine-grid-size': `\$\{STAGE_FINE_GRID_SIZE\}px`/u)
  assert.match(css, /radial-gradient\(circle at 1px 1px,[^)]*var\(--line-strong\)/u)
  assert.match(css, /var\(--stage-fine-grid-size\) var\(--stage-fine-grid-size\)/u)
})

/** P2 and NATES_VISION section 18 restore crafted chamfers instead of box-on-box shells. */
test('every module and the stage-owned floating shells carry the shared chamfer language', async () => {
  const css = await readFile(new URL('src/assets/rack.css', webRoot), 'utf8')

  assert.match(css, /\.rack-module::before,\s*\.rack-module::after\s*\{/u)
  assert.match(css, /\.rack-module::before\s*\{[^}]*clip-path:\s*polygon\(0 0, 100% 0, 100% 100%\)/su)
  assert.match(css, /\.rack-module::after\s*\{[^}]*clip-path:\s*polygon\(0 0, 100% 100%, 0 100%\)/su)
  for (const selector of ['.rack-stage-header', '.app-settings-panel', '.stage-library', '.stage-recall']) {
    assert.match(css, new RegExp(`${selector.replace('.', '\\.') }\\s*\\{[^}]*clip-path:`, 'su'))
  }
  assert.match(css, /\.rack-module--law-bound \.rack-module__chrome::after/u)
})

/** PLAN M2SP / P2 requires layer creation to be visible on the Stage and complete in one action. */
test('the Stage exposes a labelled one-click layer creator beside its tabs', async () => {
  const app = await readFile(new URL('src/App.tsx', webRoot), 'utf8')

  assert.match(app, /data-testid="stage-layer-create"/u)
  assert.match(app, /data-tooltip="Create a layer"/u)
  assert.match(app, /onClick=\{\(\) => setLayout\(createStageLayer\)\}/u)
  assert.match(app, /<span aria-hidden="true">＋<\/span>\s*Layer/u)
})

/** M3EX-29: Escape closes the Settings panel and the Library, like the module gear dialog. */
test('escape closes settings and the library', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /if \(!appSettingsOpen && !libraryOpen\) return[\s\S]*?event\.key !== 'Escape'[\s\S]*?setAppSettingsOpen\(false\)\s*setLibraryOpen\(false\)/u)
})

/** M3EX-30: typing "/" lists the daemon's commands beside the composer, without
 * touching the composer function itself.
 */
test('slash commands are listed when the composer starts with a slash', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /<ChatModule key=\{snapshot\.selectedThreadId \?\? 'empty'\} \/>\s*<SlashCommandHint \/>/u)
  for (const command of ['/remember', '/compact', '/model', '/browser allow-web']) {
    assert.match(app, new RegExp(`\\['${command}', `, 'u'))
  }
  assert.match(app, /document\.getElementById\('prompt-input'\)[\s\S]*?\/\^\\\/\\S\*\$\/u\.test\(input\.value\)/u)
})

/** M3EX-34 / FL-101: at phone width the header keeps the Palace and its state and labels
 * its counts, the layer tabs get their own row, and module titles keep their room.
 */
test('phone width keeps the palace status, layer tabs and module titles readable', async () => {
  const css = await readFile(new URL('../src/assets/rack.css', import.meta.url), 'utf8')
  const phone = css.slice(css.indexOf('@media (max-width: 48.9rem) {'))
  assert.match(phone, /\.topbar \.connection \{\s*display: block;[\s\S]*?text-overflow: ellipsis;/u)
  assert.doesNotMatch(phone, /\.rack-remote--header \.mobile-navigation__label \{\s*display: none;/u)
  assert.match(phone, /\.stage-toolbar \{\s*flex-wrap: wrap;/u)
  assert.match(phone, /\.stage-toolbar \.stage-layers \{\s*flex: 1 1 100%;/u)
  assert.match(phone, /\.rack-module__drag > \.rack-module__attunement \{\s*display: none;/u)
})

/** M3EX-33: the layer × tip names the action once — "Remove layer", not "Remove Layer 1 layer";
 * the accessible name the canon uses is unchanged.
 */
test('the layer remove tip does not repeat the word layer', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /aria-label=\{`Remove \$\{candidate\.name\} layer`\}\s*data-tooltip="Remove layer"/u)
})

/** M3EX-33: the module × says it removes the module, not "Remove Palace" (which reads as
 * destroying the Palace).
 */
test('the module remove tip names the module, not its subject', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(app, /aria-label=\{`Remove \$\{manifest\.name\}`\}\s*data-tooltip="Remove module"/u)
})
