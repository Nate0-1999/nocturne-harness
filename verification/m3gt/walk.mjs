/** PLAN M3GT: one fresh run of the charged rows on the real app — FL-147 (Wizard Mode and
 * Technomancer: names whole, the scripts conjure in the heads and rain down the Stage, reading
 * surfaces still) and FL-203 (Art Deco and Bellagio Lobby Ceiling picked in Settings, both
 * faces: every module wears the theme, the frames, grid, Stage and head strips carry its
 * ornaments, names whole, one scale) — after a heartbeat through the real gate and model.
 * usage: node verification/m3gt/walk.mjs --base-url <url> --folder <project> --out <run-dir> --run <n> */

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
const folder = argument('--folder')
const out = resolve(argument('--out'))
const run = argument('--run')
const GROUNDS = { 'art-deco': { dark: '#0a0907', light: '#efe7d3' }, bellagio: { dark: '#0a0806', light: '#e8d9bb' } }
const SCALE = [8.96, 10.24, 11.52, 13.12, 16.8]
const FAMILIES = ['Inter', 'JetBrains Mono', 'Arial Narrow']
const verdicts = { heartbeat: [], 'FL-147': [], 'FL-203': [], 'FL-201': [] }
const fail = (row, message) => verdicts[row].push(message)
const checked = {}
const rgb = (hex) => `rgb(${[1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16)).join(', ')})`

await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal'] })
const frameOf = (page, id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`).first()

async function open(face, sheet) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: face })
  const page = await context.newPage()
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.evaluate((value) => localStorage.setItem('nocturne.stage.sheet-mode.v1', value), String(sheet))
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('tab').first().waitFor({ state: 'visible' })
  return { context, page }
}

// The heartbeat: a fresh thread, a remembered fact, a question, through the real gate and model.
{
  const { context, page } = await open('dark', true)
  const threads = frameOf(page, 'threads')
  const path = threads.getByPlaceholder(/folder path/i)
  for (let tries = 0; tries < 5 && !(await path.isVisible().catch(() => false)); tries += 1) {
    await threads.getByTestId('new-thread').click()
    await page.waitForTimeout(800)
  }
  await path.fill(folder)
  await threads.getByRole('button', { name: /create/i }).click()
  const conversation = frameOf(page, 'conversation')
  await conversation.locator('.thread-empty').waitFor({ state: 'visible' })
  await page.waitForTimeout(2500)
  const turn = async (prompt, expected) => {
    const before = await conversation.locator('.transcript article').count()
    await conversation.getByTestId('composer').fill(prompt)
    await conversation.getByTestId('composer').press('Enter')
    for (let waited = 0; waited < 600; waited += 1) {
      for (const candidate of page.frames()) {
        const gate = candidate.getByTestId('memory-gate-continue')
        if (await gate.count() > 0 && await gate.first().isVisible().catch(() => false)) await gate.first().click()
      }
      const now = await conversation.locator('.transcript article').count()
      const text = await conversation.locator('.transcript').innerText()
      if (now >= before + 2 && !/working…|streaming|sending|run error/i.test(text)
        && await conversation.getByTestId('composer').isEnabled()
        && expected.test(await conversation.locator('.transcript article').last().innerText())) return true
      await page.waitForTimeout(1000)
    }
    return false
  }
  if (!await turn(`/remember M3GT run ${run}: the Art Deco sun has an empty disc.`, /disc|sun|remember|known/i)) fail('heartbeat', 'the remember turn never settled')
  if (!await turn('In one sentence: what does web/scripts/build_ornament_motifs.py build?', /ornament|theme|svg|css/i)) fail('heartbeat', 'no answer settled')
  await page.screenshot({ path: `${out}/heartbeat.png` })
  await context.close()
}

/** In the page: names whole, the head strips, the Stage layers, frames and grid. */
const inspect = () => {
  const style = (element, pseudo) => getComputedStyle(element, pseudo)
  const viewport = document.querySelector('.stage-viewport')
  const drags = [...document.querySelectorAll('.rack-module__drag')].filter((drag) => drag.getClientRects().length > 0)
  return {
    theme: document.documentElement.dataset.theme,
    ground: style(document.documentElement).backgroundColor,
    accent: style(document.documentElement).getPropertyValue('--accent').trim(),
    names: drags.map((drag) => {
      const name = drag.querySelector('strong')
      return { name: name.textContent, whole: name.scrollWidth <= name.clientWidth }
    }),
    strips: drags.map((drag) => ({ image: style(drag, '::after').backgroundImage.slice(0, 26), animation: style(drag, '::after').animationName })),
    stage: ['::before', '::after'].map((pseudo) => ({
      image: style(viewport, pseudo).backgroundImage.slice(0, 26),
      zIndex: style(viewport, pseudo).zIndex,
      animation: style(viewport, pseudo).animationName,
      pointer: style(viewport, pseudo).pointerEvents,
    })),
    frames: [...document.querySelectorAll('.stage-canvas > .rack-module')].map((module) => style(module).borderTopColor),
    grid: style(document.querySelector('.stage-canvas')).backgroundImage.slice(0, 40),
  }
}

// FL-203: each new theme picked in Settings, in both faces.
for (const face of ['dark', 'light']) {
  const { context, page } = await open(face, false)
  for (const theme of ['art-deco', 'bellagio']) {
    await page.getByTestId('app-settings-toggle').click()
    await page.getByTestId('theme-control').selectOption(theme)
    await page.getByTestId('app-settings-panel').getByRole('button', { name: /close app settings/i }).click()
    await page.getByTestId('stage-fit').click().catch(() => {})
    await page.waitForTimeout(3500)
    const seen = await page.evaluate(inspect)
    const where = `${theme} ${face}`
    if (seen.theme !== theme) fail('FL-203', `${where}: the page wears ${seen.theme}`)
    if (seen.ground !== rgb(GROUNDS[theme][face])) fail('FL-203', `${where}: ground ${seen.ground}`)
    let modules = 0
    for (const frame of page.frames().filter((candidate) => candidate.url().includes('rack_module='))) {
      const module = await frame.evaluate(() => ({ theme: document.documentElement.dataset.theme, ground: getComputedStyle(document.documentElement).backgroundColor })).catch(() => null)
      if (module === null) continue
      modules += 1
      if (module.theme !== theme || module.ground !== rgb(GROUNDS[theme][face])) fail('FL-203', `${where}: a module wears ${JSON.stringify(module)}`)
    }
    if (modules < 8 || seen.names.length < 8 || seen.frames.length < 8) fail('FL-203', `${where}: too little seen (${modules} module documents, ${seen.names.length} names, ${seen.frames.length} frames)`)
    checked[where] = { modules, names: seen.names.length, frames: seen.frames.length, strips: seen.strips.length }
    if (!seen.stage[0].image.startsWith('url("data:image/svg') || seen.stage[0].zIndex !== '-1' || seen.stage[0].pointer !== 'none') fail('FL-203', `${where}: the Stage ornament ${JSON.stringify(seen.stage[0])}`)
    if (seen.strips.length === 0 || seen.strips.some((strip) => !strip.image.startsWith('url("data:image/svg'))) fail('FL-203', `${where}: head strips ${JSON.stringify(seen.strips)}`)
    if (seen.frames.some((color) => color !== rgb(seen.accent))) fail('FL-203', `${where}: frames ${[...new Set(seen.frames)]} against accent ${seen.accent}`)
    if (!seen.grid.startsWith(theme === 'art-deco' ? 'url("data:image/svg' : 'radial-gradient')) fail('FL-203', `${where}: grid ${seen.grid}`)
    for (const name of seen.names.filter((candidate) => !candidate.whole)) fail('FL-203', `${where}: ${name.name} is cut`)
    await page.screenshot({ path: `${out}/FL-203-${theme}-${face}.png` })
  }
  await context.close()
}

// FL-147: the grimoire themes — names whole, the scripts conjure in the heads and rain down the
// Stage under the modules, the reading surface still.
{
  const { context, page } = await open('dark', false)
  for (const theme of ['wizard-mode', 'technomancer']) {
    await page.getByTestId('app-settings-toggle').click()
    await page.getByTestId('theme-control').selectOption(theme)
    await page.getByTestId('app-settings-panel').getByRole('button', { name: /close app settings/i }).click()
    await page.getByTestId('stage-fit').click().catch(() => {})
    await page.waitForTimeout(3500)
    const seen = await page.evaluate(inspect)
    if (seen.names.length < 8) fail('FL-147', `${theme}: only ${seen.names.length} names seen`)
    checked[theme] = { names: seen.names.length, strips: seen.strips.length, stage: seen.stage.map((layer) => layer.animation) }
    for (const name of seen.names.filter((candidate) => !candidate.whole)) fail('FL-147', `${theme}: ${name.name} is cut`)
    if (seen.strips.some((strip) => !/^grimoire-(rune-inscribe|glitch-in)$/.test(strip.animation))) fail('FL-147', `${theme}: head strips ${JSON.stringify(seen.strips)}`)
    if (seen.stage.some((layer) => !layer.animation.startsWith('grimoire-stage-rain') || layer.zIndex !== '-1' || layer.pointer !== 'none')) fail('FL-147', `${theme}: the Stage rain ${JSON.stringify(seen.stage)}`)
    const still = await frameOf(page, 'conversation').locator('.message__content').first()
      .evaluate((element) => getComputedStyle(element).animationName).catch(() => 'none')
    if (still !== 'none') fail('FL-147', `${theme}: a reading surface animates (${still})`)
    await page.screenshot({ path: `${out}/FL-147-${theme}.png` })
    const header = await page.locator('.rack-module__chrome').first().boundingBox()
    await page.screenshot({ path: `${out}/FL-147-${theme}-headers.png`, clip: { x: 0, y: header.y, width: 1600, height: header.height + 2 } })
  }
  await context.close()
}
await browser.close()

// FL-201 in the new themes: M3UI2's measurement, unchanged — one icon size, every text run on
// the scale and the three families, no boxed marker.
const measure = fileURLToPath(new URL('../m3ui2/measure.mjs', import.meta.url))
for (const theme of ['art-deco', 'bellagio']) {
  await mkdir(`${out}/${theme}`, { recursive: true })
  execFileSync('node', [measure, '--base-url', baseUrl, '--theme', theme, '--out', `${out}/${theme}/measure.json`,
    '--table', `${out}/${theme}/scale.md`], { stdio: 'inherit' })
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
await writeFile(`${out}/verdicts.json`, `${JSON.stringify({ ...result, checked }, null, 1)}\n`, 'utf8')
console.log(JSON.stringify(result, null, 1))
if (Object.values(result).some((verdict) => verdict !== 'PASS')) process.exit(1)
