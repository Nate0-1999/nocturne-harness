/** PLAN M3GT / SD-080: the Stage rain is idle-cheap and rests — main-thread time over a quiet
 * half minute per theme, the rain's play state once the page reports hidden, and under reduced motion.
 * usage: node verification/m3gt/rain-check.mjs --base-url <url> --out <file.json> [--no-rain: the same
 * themes with the rain removed, the baseline its cost is measured against] */

import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const argument = (name) => args[args.indexOf(name) + 1]
const baseUrl = argument('--base-url')
const SECONDS = 30
const rain = () => ['::before', '::after'].map((pseudo) => {
  const style = getComputedStyle(document.querySelector('.stage-viewport'), pseudo)
  return { pseudo, name: style.animationName, state: style.animationPlayState, images: style.backgroundImage.split('url(').length - 1 }
})

const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal'] })
const result = { seconds: SECONDS, themes: {} }
for (const theme of ['neo-noir', 'wizard-mode', 'technomancer']) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
  const page = await context.newPage()
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  await page.evaluate((chosen) => {
    localStorage.setItem('nocturne.theme.v1', chosen)
    localStorage.setItem('nocturne.stage.sheet-mode.v1', 'false')
  }, theme)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('tab').first().waitFor({ state: 'visible' })
  if (args.includes('--no-rain')) await page.addStyleTag({ content: '.stage-viewport::before, .stage-viewport::after { content: none !important }' })
  await page.waitForTimeout(5000)
  const cdp = await context.newCDPSession(page)
  await cdp.send('Performance.enable')
  const metric = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((m) => [m.name, m.value]))
  const before = await metric()
  const frames = await page.evaluate((seconds) => new Promise((done) => {
    let count = 0
    const tick = () => { count += 1; requestAnimationFrame(tick) }
    requestAnimationFrame(tick)
    setTimeout(() => done(count), seconds * 1000)
  }), SECONDS)
  const after = await metric()
  const visible = await page.evaluate(rain)
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  const hidden = await page.evaluate(rain)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const reduced = await page.evaluate(rain)
  result.themes[theme] = {
    main_thread_busy_percent: +(100 * (after.TaskDuration - before.TaskDuration) / SECONDS).toFixed(2),
    style_recalc_seconds: +(after.RecalcStyleDuration - before.RecalcStyleDuration).toFixed(3),
    layout_seconds: +(after.LayoutDuration - before.LayoutDuration).toFixed(3),
    js_heap_mb: +(after.JSHeapUsedSize / 1e6).toFixed(1),
    animation_frames: frames,
    rain_visible: visible,
    rain_hidden: hidden,
    rain_reduced_motion: reduced,
  }
  await context.close()
}
await browser.close()
await writeFile(argument('--out'), `${JSON.stringify(result, null, 1)}\n`)
console.log(JSON.stringify(result, null, 1))
