/** M3VL captures from the real app (headless): each 3D module beside its reference plate, and a
 * recording of one module while a trigger changes its real data on camera.
 *   node capture.mjs --base-url <url> --evidence-dir <dir> --shots [--tier efficient]
 *   node capture.mjs --base-url <url> --evidence-dir <dir> --record roots|palace|farm */

import { createRequire } from 'node:module'
import { execFileSync, spawn } from 'node:child_process'
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const evidenceDir = resolve(argument('--evidence-dir'))
const record = args.includes('--record') ? argument('--record') : null
const only = record ?? (args.includes('--only') ? argument('--only') : null)
const tier = args.includes('--tier') ? argument('--tier') : 'full'
const seconds = args.includes('--seconds') ? Number(argument('--seconds')) : 10
// The data change is started on camera: the trigger runs when recording begins, after an optional lead.
const trigger = args.includes('--trigger') ? argument('--trigger') : null
const lead = args.includes('--lead') ? Number(argument('--lead')) : 0
const MODULES = { roots: ['Roots', 'roots', '.work-viz__viewport', 'FL-129', 'roots.png'],
  palace: ['Palace', 'palace_nebula', '.palace-nebula__viewport', 'FL-133', 'palace.png'],
  farm: ['Farm', 'farm', '.work-viz__viewport', 'FL-126', 'farm.png'] }
// Farm and Palace fill a module resized to the whole Stage (black ground); Roots uses the Sheet, the plate's
// white ground, with its agents table folded so the scene has the height.
const VIEWS = { farm: 'stage', palace: 'stage', roots: args.includes('--roots-stage') ? 'stage' : 'sheet' }
// The scene region of each viewport, as fractions [x, y, width, height]: the plate is framed on its subject,
// so the capture is too. Palace: the centred square; Roots: the band above the readout; Farm: the scene centre.
const CROPS = { palace: 'square', roots: [0.21, 0.03, 0.54, 0.76], farm: [0.1, 0, 0.8, 1] }
const videoDir = resolve(evidenceDir, 'receipts', 'video-raw')
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--enable-unsafe-webgpu', '--ignore-gpu-blocklist', '--force-device-scale-factor=2'] })
const log = { base_url: baseUrl, tier, captures: [] }
let context, page, opened

try {
  await mkdir(resolve(evidenceDir, 'receipts'), { recursive: true })
  for (const [key, [name, moduleId, selector, row, plate]] of Object.entries(MODULES)) {
    if (only && only !== key) continue
    // Retina density, as on the owner's display (forced at the browser so it reaches the module frames).
    const viewport = VIEWS[key] === 'sheet' ? { width: 1000, height: 1000 } : { width: 1600, height: 1000 }
    context = await browser.newContext({ viewport, deviceScaleFactor: 2,
      ...(record ? { recordVideo: { dir: videoDir, size: { width: viewport.width * 2, height: viewport.height * 2 } } } : {}) })
    opened = Date.now()
    page = await context.newPage()
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await frame('threads').getByTestId('new-thread').waitFor({ state: 'visible' })
    if (VIEWS[key] === 'sheet') await page.getByRole('button', { name: 'Sheet', exact: true }).click()
    await page.getByTestId('stage-layer-create').click()
    await page.getByRole('button', { name: 'Library', exact: true }).click()
    await page.locator('li').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Add', exact: true }).click()
    await page.getByRole('button', { name: 'Library', exact: true }).click()
    if (VIEWS[key] === 'stage') {
      const handle = page.getByTestId(`rack-resize-${moduleId}-se`)
      await handle.focus()
      for (let i = 0; i < 12; i++) { await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowDown') }
      await page.evaluate(() => (document.activeElement instanceof HTMLElement) && document.activeElement.blur())
      await page.mouse.move(2, 2)
    }
    const host = page.locator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
    await host.scrollIntoViewIfNeeded()
    const view = frame(moduleId).locator(selector)
    await view.locator('canvas').waitFor({ timeout: 60_000 })
    if (key === 'farm') await frame(moduleId).getByRole('button', { name: 'Farm', exact: true }).click()
    // The Farm shows one project at a time; pick it with the module's own Project control.
    if (key === 'farm' && args.includes('--farm-project')) await frame(moduleId).getByLabel('Visualized project').selectOption(argument('--farm-project'))
    if (key === 'roots') await frame(moduleId).locator('details.work-viz__data[open] > summary').first().click()
    if (tier === 'efficient') await frame(moduleId).locator(key === 'palace' ? 'select[aria-label="Nebula hardware tier"]' : 'select[aria-label="Visualization detail"]').selectOption('efficient')
    await page.waitForTimeout(6000)
    await host.scrollIntoViewIfNeeded()
    const box = await boundingBox(host, view)
    if (record) {
      // Live data drives the scene; a slow drag orbits the camera so depth reads (camera motion only).
      const triggered = trigger ? spawn('/bin/zsh', ['-c', trigger], { stdio: 'inherit' }) : null
      if (lead) await page.waitForTimeout(lead * 1000)
      const start = (Date.now() - opened) / 1000, steps = seconds * 10
      const [x, y] = [box.x + box.width * 0.5, box.y + box.height * 0.5]
      await page.mouse.move(x - 12, y)
      await page.mouse.down()
      for (let step = 1; step <= steps; step++) { await page.mouse.move(x - 12 + step * 25 / steps, y - Math.sin(step / steps * Math.PI) * 3); await page.waitForTimeout(100) }
      await page.mouse.up()
      await page.waitForTimeout(500)
      log.captures.push({ module: key, view: VIEWS[key], record_start_s: start, seconds, trigger, lead, crop: box,
        camera: `slow orbit by mouse drag, 25 px over ${seconds} s` })
      if (triggered && triggered.exitCode === null) log.captures.at(-1).trigger_still_running = true
      await context.close()
      continue
    }
    const file = `${key}-${tier}${VIEWS[key] === 'sheet' ? '-sheet' : ''}.png`
    await page.screenshot({ path: resolve(evidenceDir, file) })
    await page.screenshot({ path: resolve(evidenceDir, 'receipts', `${key}-${tier}-viewport.png`), clip: box })
    const telemetry = await frame(moduleId).locator('.palace-nebula__telemetry, .work-viz__primitives, .work-viz__readout').allInnerTexts()
    log.captures.push({ module: key, view: VIEWS[key], row, full: file, crop: box, telemetry, at: new Date().toISOString() })
    if (tier === 'full') await sideBySide(key, row, resolve(evidenceDir, 'receipts', `${key}-${tier}-viewport.png`), plate)
    await context.close()
  }
} finally {
  await browser.close()
}
if (record) {
  const [video] = (await readdir(videoDir)).filter((file) => file.endsWith('.webm'))
  const { record_start_s: start, crop } = log.captures[0]
  const even = (value) => Math.max(2, Math.round(value / 2) * 2)
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', String(start), '-t', String(seconds), '-i', resolve(videoDir, video),
    '-vf', `crop=${even(crop.width * 2)}:${even(crop.height * 2)}:${Math.round(crop.x * 2)}:${Math.round(crop.y * 2)},fps=30`,
    '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '30', resolve(evidenceDir, `${record}${VIEWS[record] === 'stage' && record === 'roots' ? '-stage' : ''}-live.webm`)])
  await rm(videoDir, { recursive: true })
}
await writeFile(resolve(evidenceDir, 'receipts', `capture-${record ?? tier}.json`), `${JSON.stringify(log, null, 2)}\n`)
console.log(JSON.stringify(log.captures.map(({ module, telemetry, crop }) => ({ module, telemetry, crop }))))

async function boundingBox(host, view) {
  // The Stage scales its modules: map the iframe's own coordinates through that scale to the page.
  const outer = await host.boundingBox()
  const inner = await view.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, frame: window.innerWidth }
  })
  const scale = outer.width / inner.frame
  return { x: outer.x + inner.x * scale, y: outer.y + inner.y * scale, width: inner.width * scale, height: inner.height * scale }
}

async function sideBySide(key, row, captured, plate) {
  const image = async (path) => `data:image/png;base64,${(await readFile(path)).toString('base64')}`
  const ground = key === 'roots' ? '#f5f5f2' : '#030509'
  const compose = await browser.newPage({ viewport: { width: 1440, height: 790 } })
  await compose.setContent(`<body style="margin:0;background:#11151c;font:20px system-ui;color:#eef">
    <div style="display:grid;grid-template-columns:1fr 1fr;height:46px;align-items:center;padding:0 16px"><span>${MODULES[key][0]} · live application</span><span>Reference plate</span></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;height:720px">
      <div style="background:${ground};display:grid;place-items:center;overflow:hidden"><canvas id="crop" style="max-width:100%;max-height:720px"></canvas></div>
      <div style="background:${ground};display:grid;place-items:center;overflow:hidden"><img src="${await image(new URL(`../../m3vz/plates/${plate}`, import.meta.url).pathname)}" style="max-width:100%;max-height:720px"></div>
    </div><div style="font-size:14px;color:#aab;padding:2px 16px">Native capture cropped to the scene region; aspect preserved. The full capture is beside this file.</div></body>`)
  const crop = await compose.evaluate(async ([source, region]) => {
    const img = new Image(); img.src = source; await img.decode()
    const [x, y, w, h] = region === 'square'
      ? [(img.width - img.height) / 2 / img.width, 0, img.height / img.width, 1] : region
    const canvas = document.getElementById('crop')
    canvas.width = Math.round(w * img.width); canvas.height = Math.round(h * img.height)
    canvas.getContext('2d').drawImage(img, x * img.width, y * img.height, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height)
    return { x: Math.round(x * img.width), y: Math.round(y * img.height), width: canvas.width, height: canvas.height }
  }, [await image(captured), CROPS[key]])
  log.captures.at(-1).side_by_side = { file: `${row}-plate.png`, crop_px: crop }
  await compose.waitForTimeout(300)
  await compose.screenshot({ path: resolve(evidenceDir, `${row}-plate.png`) })
  await compose.close()
}

function frame(moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function argument(name) {
  const index = args.indexOf(name)
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${name} is required`)
  return value
}
