/** PLAN M3GT: give the real app real data before the theme captures — a fresh thread in the
 * harness repository, one prompt through the real gate and model, and one remembered fact.
 * usage: node verification/m3gt/seed.mjs --base-url <url> --folder <project> --out <dir> */

import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const argument = (name) => args[args.indexOf(name) + 1]
const baseUrl = argument('--base-url')
const folder = argument('--folder')
const out = resolve(argument('--out'))

await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal'] })
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage()
const frame = (id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`).first()
await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
await page.evaluate(() => localStorage.setItem('nocturne.stage.sheet-mode.v1', 'true'))
await page.reload({ waitUntil: 'domcontentloaded' })

const threads = frame('threads')
const path = threads.getByPlaceholder(/folder path/i)
for (let tries = 0; tries < 5 && !(await path.isVisible().catch(() => false)); tries += 1) {
  await threads.getByTestId('new-thread').click()
  await page.waitForTimeout(800)
}
await path.fill(folder)
await threads.getByRole('button', { name: /create/i }).click()
const conversation = frame('conversation')
await conversation.locator('.thread-empty').waitFor({ state: 'visible' })
await page.waitForTimeout(2500) // the new thread takes the composer; typing earlier is cleared

async function turn(prompt, expected) {
  const before = await conversation.locator('.transcript article').count()
  await conversation.getByTestId('composer').fill(prompt)
  await conversation.getByTestId('composer').press('Enter')
  for (let waited = 0; waited < 900; waited += 1) {
    for (const candidate of page.frames()) {
      const gate = candidate.getByTestId('memory-gate-continue')
      if (await gate.count() > 0 && await gate.first().isVisible().catch(() => false)) await gate.first().click()
    }
    const now = await conversation.locator('.transcript article').count()
    const text = await conversation.locator('.transcript').innerText()
    const busy = /working…|streaming|sending|run error/i.test(text)
    if (now >= before + 2 && !busy && await conversation.getByTestId('composer').isEnabled()
      && expected.test(await conversation.locator('.transcript article').last().innerText())) return
    await page.waitForTimeout(1000)
  }
  await page.screenshot({ path: `${out}/seed-timeout.png` })
  throw new Error(`no settled answer for: ${prompt}`)
}

await turn('/remember Nate prefers chamfered corners on every control, never rounded ones.', /chamfer|corner|remember|known/i)
await turn('In two sentences: what does web/src/themes.ts in this repository define?', /theme/i)
await page.screenshot({ path: `${out}/seeded.png` })
await browser.close()
console.log('seeded')
