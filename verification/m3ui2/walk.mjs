/** PLAN M3UI2: one fresh run of the charged rows (FL-201, FL-113, FL-199) on the real app, every theme.
 * usage: node verification/m3ui2/walk.mjs --base-url <url> --out <run-dir>
 * A fresh browser per run; a fresh thread through the real gate and model first, so the modules hold real data. */

import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const argument = (name) => args[args.indexOf(name) + 1]
const baseUrl = argument('--base-url')
const out = resolve(argument('--out'))
const THEMES = ['neo-noir', 'seraph-dressed', 'gold-lines', 'wizard-mode', 'technomancer']
const SCALE = [8.96, 10.24, 11.52, 13.12, 16.8] // --text-xs..--text-lg at a 16px root; --text-xl is the clamp above them
const FAMILIES = ['Inter', 'JetBrains Mono', 'Arial Narrow']
const verdicts = { 'FL-201': [], 'FL-113': [], 'FL-199': [] }
const fail = (row, message) => verdicts[row].push(message)

await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal'] })
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage()
const frame = (id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`).first()
await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })

// The heartbeat on the real Palace and model: fresh thread, first prompt, gate, answer.
const threads = frame('threads')
await threads.getByTestId('new-thread').click()
await threads.getByRole('button', { name: /create/i }).click()
const conversation = frame('conversation')
await conversation.locator('.thread-empty').waitFor({ state: 'visible' })
await page.waitForTimeout(2500) // the new thread takes the composer; typing earlier is cleared
await conversation.getByTestId('composer').fill('In one sentence: which corner style does Nate prefer on controls?')
await conversation.getByTestId('composer').press('Enter')
let gate = null
for (let waited = 0; gate === null && waited < 120; waited += 1) {
  for (const candidate of page.frames()) {
    if (await candidate.getByTestId('memory-gate-continue').count() > 0) gate = candidate
  }
  if (gate === null) await page.waitForTimeout(1000)
}
if (gate === null) {
  await page.screenshot({ path: `${out}/no-gate.png` })
  throw new Error('the memory gate never opened')
}
await page.screenshot({ path: `${out}/gate.png` })
await gate.getByTestId('memory-gate-continue').click()
await conversation.locator('.transcript').getByText(/chamfer/i).first().waitFor({ state: 'visible', timeout: 15 * 60 * 1000 })
for (let waited = 0; waited < 900 && !(await conversation.getByTestId('composer').isEnabled()); waited += 1) await page.waitForTimeout(1000)

// FL-113: a descriptive tip, the fine grid, an easy tab, a small archive button, a clickable model device.
await page.getByTestId('stage-fit').hover()
const tip = page.locator('.control-tooltip').first()
await tip.waitFor({ state: 'visible' })
const tipText = (await tip.innerText()).trim()
await page.screenshot({ path: `${out}/FL-113-tip.png` })
if (!/\n/.test(tipText) || tipText.length < 25) fail('FL-113', `the tip is not a title plus a description: ${JSON.stringify(tipText)}`)
const grid = await page.locator('.stage-canvas').evaluate((element) => {
  const style = getComputedStyle(element)
  return { image: style.backgroundImage.slice(0, 60), size: style.backgroundSize }
})
if (grid.image === 'none' || !(parseFloat(grid.size) <= 16)) fail('FL-113', `the stage grid is missing or coarse: ${JSON.stringify(grid)}`)
const tabsBefore = await page.getByRole('tab').count()
await page.getByTestId('stage-layer-create').click()
if (await page.getByRole('tab').count() !== tabsBefore + 1) fail('FL-113', 'one click did not create a layer tab')
await page.screenshot({ path: `${out}/FL-113-tab.png` })
await page.getByRole('tab').nth(tabsBefore).locator('xpath=following-sibling::button').click()
await page.getByRole('tab').first().click()
const archive = await threads.locator('.thread-item__archive').first().boundingBox()
if (archive === null || archive.width > 32 || archive.height > 32) fail('FL-113', `the archive button is not small: ${JSON.stringify(archive)}`)
const model = conversation.locator('.chat-header__model')
if (await model.evaluate((element) => getComputedStyle(element).cursor) !== 'pointer' || await model.locator('svg').count() === 0
  || !/open/i.test(await model.innerText())) fail('FL-113', 'the model device does not read as clickable')
await page.screenshot({ path: `${out}/FL-113.png` })

// FL-199: common actions carry the one set's icon; primary buttons pair it with a word; row actions are icon-only with a tip.
const memory = frame('memory')
const expected = [
  [conversation.locator('.send-button'), 'lucide-send', true], [threads.getByTestId('new-thread'), 'lucide-plus', true],
  [threads.locator('.thread-item__archive').first(), 'lucide-archive', false], [memory.getByRole('button', { name: /refresh/i }), 'lucide-rotate-ccw', true],
  [page.getByTestId('rack-settings-memory'), 'lucide-settings', false], [page.getByTestId('stage-layer-create'), 'lucide-plus', false],
  [memory.locator('.kit-button--danger').first(), 'lucide-trash-2', false],
]
for (const [button, icon, worded] of expected) {
  const found = await button.evaluate((element) => ({
    icons: [...element.querySelectorAll('svg')].map((svg) => svg.getAttribute('class')),
    words: [...element.childNodes].filter((node) => node.nodeType === 3 || !node.matches?.('svg, .visually-hidden')).map((node) => node.textContent.trim()).join(''),
    tip: element.getAttribute('data-tooltip') ?? element.getAttribute('aria-label') ?? element.getAttribute('title'),
  })).catch((error) => ({ icons: [], words: '', tip: null, error: String(error).slice(0, 80) }))
  if (!found.icons.some((name) => name.includes(icon.replace(/-2$/, '')))) fail('FL-199', `${icon} missing: ${JSON.stringify(found)}`)
  if (worded && found.words === '') fail('FL-199', `${icon}: a primary action shows no word`)
  if (!worded && (found.words !== '' || !found.tip)) fail('FL-199', `${icon}: a row action needs the icon alone and a tip: ${JSON.stringify(found)}`)
}
const unusual = conversation.getByRole('button', { name: /tools & skills/i })
if (await unusual.locator('svg').count() !== 0) fail('FL-199', 'an unusual action wears an invented icon')
const foreign = await page.evaluate(() => [...document.querySelectorAll('button svg')].filter((svg) => !svg.classList.contains('lucide')).length)
if (foreign !== 0) fail('FL-199', `${foreign} button icons are not from the one set`)
await page.screenshot({ path: `${out}/FL-199.png` })
await browser.close()

// FL-201: the measurement, every theme. One icon size; every text run on the scale and the three families; no boxed marker.
const measure = fileURLToPath(new URL('./measure.mjs', import.meta.url))
for (const theme of THEMES) {
  await mkdir(`${out}/${theme}`, { recursive: true })
  execFileSync('node', [measure, '--base-url', baseUrl, '--theme', theme, '--out', `${out}/${theme}/measure.json`,
    '--table', `${out}/${theme}/scale.md`, '--shots', `${out}/${theme}`], { stdio: 'inherit' })
  const measured = JSON.parse(await readFile(`${out}/${theme}/measure.json`, 'utf8'))
  const sizes = new Set()
  for (const documents of Object.values(measured.layers)) {
    for (const [moduleId, found] of Object.entries(documents)) {
      for (const icon of found.icons.filter((candidate) => candidate.icon.startsWith('lucide-'))) sizes.add(`${icon.width}x${icon.height}`)
      for (const text of found.texts) {
        if (text.role === 'hidden') continue
        const hero = text.size > 16.8 && text.size <= 33.6
        if (!FAMILIES.includes(text.family) || !(SCALE.includes(text.size) || hero)) fail('FL-201', `${theme} ${moduleId}: ${text.family} ${text.size}px at ${text.where}`)
      }
      for (const tell of found.tells.filter((candidate) => candidate.kind === 'boxed-marker')) fail('FL-201', `${theme} ${moduleId}: boxed marker ${tell.where}`)
    }
  }
  if (sizes.size !== 1) fail('FL-201', `${theme}: icon sizes ${[...sizes].join(', ')}`)
}

const result = Object.fromEntries(Object.entries(verdicts).map(([row, problems]) => [row, problems.length === 0 ? 'PASS' : problems]))
await writeFile(`${out}/verdicts.json`, `${JSON.stringify(result, null, 1)}\n`, 'utf8')
console.log(JSON.stringify(result, null, 1))
if (Object.values(result).some((verdict) => verdict !== 'PASS')) process.exit(1)
