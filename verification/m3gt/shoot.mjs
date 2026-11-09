/** PLAN M3GT: one capture of the real app per theme and face, same framing every time.
 * usage: node verification/m3gt/shoot.mjs --base-url <url> --out <dir> --themes a,b,c
 *        [--faces dark,light] [--view stage|sheet] [--layer <tab name>] [--wait <ms>] [--reduced] */

import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback)
const baseUrl = option('--base-url')
const out = resolve(option('--out'))
const themes = option('--themes').split(',')
const faces = option('--faces', 'dark').split(',')
const view = option('--view', 'stage')
const layer = option('--layer', null)
const wait = Number(option('--wait', '2500'))

await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal', '--enable-unsafe-webgpu'] })
for (const face of faces) {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    colorScheme: face,
    reducedMotion: args.includes('--reduced') ? 'reduce' : 'no-preference',
  })
  const page = await context.newPage()
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  for (const theme of themes) {
    await page.evaluate(([chosen, sheet]) => {
      localStorage.setItem('nocturne.theme.v1', chosen)
      localStorage.setItem('nocturne.stage.sheet-mode.v1', sheet ? 'true' : 'false')
    }, [theme, view === 'sheet'])
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.getByRole('tab').first().waitFor({ state: 'visible' })
    if (layer !== null) await page.getByRole('tab', { name: new RegExp(layer, 'i') }).first().click()
    if (view === 'stage') await page.getByTestId('stage-fit').click().catch(() => {})
    await page.waitForTimeout(wait)
    await page.screenshot({ path: `${out}/${theme}-${face}${layer === null ? '' : `-${layer.toLowerCase()}`}.png` })
  }
  await context.close()
}
await browser.close()
console.log('shot', themes.length * faces.length)
