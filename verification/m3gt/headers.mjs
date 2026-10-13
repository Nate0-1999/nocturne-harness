/** PLAN M3GT / FL-147 / TASTE-09: every module name reads whole in its header — measured per
 * module (the name's text never overflows its box) on the Stage at fit and in the Sheet, every
 * theme given, with a 2x crop of the top header row and of the Stage gaps where the rain falls.
 * usage: node verification/m3gt/headers.mjs --base-url <url> --out <dir> --themes a,b [--faces dark,light] */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback)
const baseUrl = option('--base-url')
const out = resolve(option('--out'))
const themes = option('--themes').split(',')
const faces = option('--faces', 'dark').split(',')

await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const result = {}
for (const face of faces) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2, colorScheme: face })
  const page = await context.newPage()
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  for (const theme of themes) {
    for (const view of ['stage', 'sheet']) {
      await page.evaluate(([chosen, sheet]) => {
        localStorage.setItem('nocturne.theme.v1', chosen)
        localStorage.setItem('nocturne.stage.sheet-mode.v1', sheet ? 'true' : 'false')
      }, [theme, view === 'sheet'])
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.getByRole('tab').first().waitFor({ state: 'visible' })
      if (view === 'stage') await page.getByTestId('stage-fit').click().catch(() => {})
      await page.waitForTimeout(3000)
      const names = await page.evaluate(() => [...document.querySelectorAll('.rack-module__drag strong')]
        .filter((name) => name.getClientRects().length > 0)
        .map((name) => ({ name: name.textContent, whole: name.scrollWidth <= name.clientWidth })))
      result[`${theme}/${face}/${view}`] = names
      if (view === 'stage') {
        const header = await page.locator('.rack-module__chrome').first().boundingBox()
        await page.screenshot({ path: `${out}/${theme}-${face}-headers.png`, clip: { x: 0, y: header.y, width: 1600, height: header.height + 2 } })
        await page.screenshot({ path: `${out}/${theme}-${face}-stage.png` })
      }
    }
  }
  await context.close()
}
await browser.close()
const cut = Object.entries(result).flatMap(([where, names]) => names.filter((name) => !name.whole).map((name) => `${where}: ${name.name}`))
await writeFile(`${out}/headers.json`, `${JSON.stringify({ cut, result }, null, 1)}\n`)
console.log(cut.length === 0 ? 'PASS: every name whole' : `FAIL: ${cut.join('; ')}`)
if (cut.length !== 0) process.exit(1)
