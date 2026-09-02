/** PLAN v2.107: walk the first-prompt feature in the real packaged owner app. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const evidenceDir = resolve(argument('--evidence-dir'))
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

try {
  await mkdir(evidenceDir, { recursive: true })
  const response = await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  if (response === null || !response.ok()) {
    throw new Error(`real packaged app did not load: ${response?.status() ?? 'no response'}`)
  }
  if (await page.getByText('NOT THE OWNER APP', { exact: false }).count() > 0) {
    throw new Error('real walk refuses fixture-curtain evidence')
  }

  await frame('header').getByText('Palace ready', { exact: false }).waitFor({
    state: 'visible',
    timeout: 60_000,
  })
  const threads = frame('threads')
  const selected = threads.locator('.thread-item--selected')
  await selected.waitFor({ state: 'visible' })
  const selectedThread = await selected.innerText()
  if (!selectedThread.toLowerCase().includes('empty')) {
    throw new Error(`real walk requires a fresh empty startup thread: ${selectedThread}`)
  }
  const composer = frame('conversation').getByTestId('composer')
  await composer.waitFor({ state: 'visible' })
  await waitUntil(async () => composer.isEnabled())
  await composer.fill('Open the first-turn memory review for the M3FP front-door verification.')
  await composer.press('Enter')

  const gate = frame('gate').getByTestId('memory-gate')
  await gate.waitFor({ state: 'visible', timeout: 60_000 })
  const heading = await gate.getByText('Review what Harness remembers', { exact: false }).innerText()
  await page.screenshot({
    path: resolve(evidenceDir, '05-real-packaged-front-door.png'),
    fullPage: false,
  })
  const result = {
    packet: 'M3FP',
    fixture: false,
    packaged_owner_app: true,
    palace_ready: true,
    fresh_thread: true,
    selected_thread: selectedThread,
    first_prompt_gate_visible: true,
    heading,
  }
  await writeFile(
    resolve(evidenceDir, 'real-walk.json'),
    `${JSON.stringify(result, null, 2)}\n`,
    'utf8',
  )
  console.log(`M3FP real packaged walk PASS: ${JSON.stringify(result)}`)
} finally {
  await context.close()
  await browser.close()
}

function frame(moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

async function waitUntil(predicate, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await predicate()) return
    await new Promise((resolveWait) => setTimeout(resolveWait, 100))
  }
  throw new Error('real packaged app did not settle')
}

function argument(name) {
  const index = args.indexOf(name)
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${name} is required`)
  }
  return value
}
