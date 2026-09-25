/** M3VL send-back 1 captures from the real app (headless): each 3D module beside its reference plate,
 * and a ten-second recording of a module on live data.
 *   node capture.mjs --base-url <url> --evidence-dir <dir> --shots [--tier efficient]
 *   node capture.mjs --base-url <url> --evidence-dir <dir> --record roots|palace|farm */

import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const evidenceDir = resolve(argument('--evidence-dir'))
const record = args.includes('--record') ? argument('--record') : null
const tier = args.includes('--tier') ? argument('--tier') : 'full'
const MODULES = { roots: ['Roots', 'roots', '.work-viz__viewport', 'FL-129', 'roots.png'],
  palace: ['Palace', 'palace_nebula', '.palace-nebula__viewport', 'FL-133', 'palace.png'],
  farm: ['Farm', 'farm', '.work-viz__viewport', 'FL-126', 'farm.png'] }
const viewport = { width: 1600, height: 1000 }
// The scene region of each viewport, as fractions [x, y, width, height]: the plate is framed on its subject,
// so the capture is too. Palace: the centred square; Roots: the band above the readout; Farm: the scene centre.
const CROPS = { palace: 'square', roots: [0, 0.02, 1, 0.74], farm: [0.03, 0.05, 0.94, 0.62] }

const videoDir = resolve(evidenceDir, 'receipts', 'video-raw')
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--enable-unsafe-webgpu', '--ignore-gpu-blocklist', '--force-device-scale-factor=2'] })
// Retina density, as on the owner's display (forced at the browser so it reaches the module frames);
// the three modules on a layer of their own.
const context = await browser.newContext({ viewport, deviceScaleFactor: 2, ...(record ? { recordVideo: { dir: videoDir, size: { width: viewport.width * 2, height: viewport.height * 2 } } } : {}) })
const opened = Date.now()
const page = await context.newPage()
const log = { base_url: baseUrl, tier, captures: [] }

try {
  await mkdir(resolve(evidenceDir, 'receipts'), { recursive: true })
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await frame('threads').getByTestId('new-thread').waitFor({ state: 'visible' })
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await page.getByTestId('stage-layer-create').click()
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  for (const [name] of Object.values(MODULES)) {
    const add = page.locator('li').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Add', exact: true })
    if (await add.count()) await add.click()
  }
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  for (const [key, [, moduleId, selector, row, plate]] of Object.entries(MODULES)) {
    if (record && record !== key) continue
    const host = page.locator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
    await host.scrollIntoViewIfNeeded()
    const view = frame(moduleId).locator(selector)
    await view.locator('canvas').waitFor({ timeout: 60_000 })
    if (key === 'farm') await frame(moduleId).getByRole('button', { name: 'Farm', exact: true }).click()
    if (tier === 'efficient') await frame(moduleId).locator(key === 'palace' ? 'select[aria-label="Nebula hardware tier"]' : 'select[aria-label="Visualization detail"]').selectOption('efficient')
    await page.waitForTimeout(6000)
    const box = await boundingBox(host, view)
    if (record) {
      // Live data drives the scene; a slow drag orbits the camera so depth reads (camera motion only).
      const start = (Date.now() - opened) / 1000
      const [x, y] = [box.x + box.width * 0.5, box.y + box.height * 0.5]
      await page.mouse.move(x - 12, y)
      await page.mouse.down()
      for (let step = 1; step <= 100; step++) { await page.mouse.move(x - 12 + step * 0.25, y - Math.sin(step / 100 * Math.PI) * 3); await page.waitForTimeout(100) }
      await page.mouse.up()
      await page.waitForTimeout(500)
      log.captures.push({ module: key, record_start_s: start, crop: box, camera: 'slow orbit by mouse drag, 25 px (about 30 degrees) over 10 s' })
      continue
    }
    const name = `${key}-${tier}${key === 'roots' ? '-sheet' : ''}.png`
    await page.screenshot({ path: resolve(evidenceDir, name) })
    await view.screenshot({ path: resolve(evidenceDir, 'receipts', `${key}-${tier}-viewport.png`) })
    const telemetry = await frame(moduleId).locator('.palace-nebula__telemetry, .work-viz__primitives, .work-viz__readout').allInnerTexts()
    log.captures.push({ module: key, row, full: name, crop: box, telemetry, at: new Date().toISOString() })
    if (tier === 'full') await sideBySide(key, row, resolve(evidenceDir, 'receipts', `${key}-${tier}-viewport.png`), plate)
  }
} finally {
  await context.close()
  await browser.close()
}
if (record) {
  const [video] = (await readdir(videoDir)).filter((file) => file.endsWith('.webm'))
  const { record_start_s: start, crop } = log.captures[0]
  const even = (value) => Math.max(2, Math.round(value / 2) * 2)
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', String(start), '-t', '10', '-i', resolve(videoDir, video),
    '-vf', `crop=${even(crop.width * 2)}:${even(crop.height * 2)}:${Math.round(crop.x * 2)}:${Math.round(crop.y * 2)},fps=30`,
    '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '32', resolve(evidenceDir, `${record}-live.webm`)])
  await rm(videoDir, { recursive: true })
}
await writeFile(resolve(evidenceDir, 'receipts', `capture-${record ?? tier}.json`), `${JSON.stringify(log, null, 2)}\n`)
console.log(JSON.stringify(log.captures.map(({ module, telemetry }) => ({ module, telemetry }))))

async function boundingBox(host, view) {
  const outer = await host.boundingBox()
  const inner = await view.evaluate((element) => { const rect = element.getBoundingClientRect(); return { x: rect.x, y: rect.y, width: rect.width, height: rect.height } })
  return { x: outer.x + inner.x, y: outer.y + inner.y, width: inner.width, height: inner.height }
}

async function sideBySide(key, row, captured, plate) {
  const image = async (path) => `data:image/png;base64,${(await readFile(path)).toString('base64')}`
  const ground = key === 'roots' ? '#f5f5f2' : '#030509'
  const compose = await context.browser().newPage({ viewport: { width: 1440, height: 790 } })
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
