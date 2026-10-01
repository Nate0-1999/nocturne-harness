/** M3CL2 walk driver: one real-app page, driven by JS bodies POSTed to 127.0.0.1:8799/eval.
 * The pattern is M3EX's (a held page beats scripted walks); captures go to --evidence-dir. */
// Usage: node driver.mjs --base-url <app> --evidence-dir <dir> --project <folder> [--port 8799]

import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const evidenceDir = resolve(argument('--evidence-dir'))
const project = argument('--project')
const port = Number(args.includes('--port') ? argument('--port') : 8799)
await mkdir(evidenceDir, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await context.newPage()
const frame = (id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
const sleep = (ms) => new Promise((resolveSleep) => setTimeout(resolveSleep, ms))

async function waitUntil(predicate, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      if (await predicate()) return
    } catch (error) {
      lastError = error
    }
    await sleep(250)
  }
  throw lastError ?? new Error('walk condition did not settle')
}

async function api(path, init) {
  const response = await fetch(`${baseUrl}${path}`, init)
  const text = await response.text()
  try {
    return { status: response.status, body: JSON.parse(text) }
  } catch {
    return { status: response.status, body: text }
  }
}

const h = {
  sleep,
  waitUntil,
  api,
  async open() {
    await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
    await frame('conversation').getByTestId('composer').waitFor({ state: 'visible', timeout: 60_000 })
    const sheet = page.getByRole('button', { name: 'Sheet', exact: true })
    if ((await sheet.getAttribute('aria-pressed')) !== 'true') await sheet.click()
    return 'open'
  },
  async newThread() {
    const threads = frame('threads')
    await threads.getByTestId('new-thread').click()
    const folder = threads.getByTestId('thread-workspace-root')
    if (await folder.count()) await folder.fill(project)
    const create = threads.getByRole('button', { name: /^create$/i })
    if (await create.count()) await create.first().click()
    await waitUntil(async () => (await frame('conversation').getByTestId('composer').inputValue()) === '')
    await sleep(1000)
    return await threads.locator('.thread-item--selected').getAttribute('data-thread-id')
  },
  async send(prompt, { gate = 'continue' } = {}) {
    const composer = frame('conversation').getByTestId('composer')
    await waitUntil(async () => await composer.isEnabled(), 180_000)
    h.answers = await frame('conversation').locator('article[data-role="assistant"]').count()
    await composer.fill(prompt)
    await composer.press('Enter')
    // A new thread's composer can remount right after it opens and swallow the first Enter.
    for (let retry = 0; retry < 3 && (await composer.inputValue().catch(() => '')) === prompt; retry++) {
      await sleep(2000)
      if ((await composer.inputValue().catch(() => '')) === prompt) {
        await frame('conversation').getByTestId('send').click()
      }
    }
    if (gate === 'continue') {
      try {
        await frame('gate').getByTestId('memory-gate-continue').waitFor({ state: 'visible', timeout: 25_000 })
        await frame('gate').getByTestId('memory-gate-continue').click()
      } catch {
        // Only a thread's first prompt with something to review opens the gate.
      }
    }
    return 'sent'
  },
  async settled(timeoutMs = 600_000) {
    const composer = frame('conversation').getByTestId('composer')
    const answers = frame('conversation').locator('article[data-role="assistant"]')
    // A reply is read only after a new answer exists (the M3CL2 move re-walk read a stale one).
    await waitUntil(async () => (await answers.count()) > (h.answers ?? -1), timeoutMs)
    await sleep(1500)
    await waitUntil(async () => {
      const text = await frame('conversation').locator('body').innerText()
      return !/Streaming|Working…|Waiting for memory review|Stopping/u.test(text.slice(-4000)) &&
        await composer.isEnabled()
    }, timeoutMs)
    return 'settled'
  },
  async shot(name, moduleId = 'conversation') {
    await page.locator(`[data-testid="rack-plugin-frame-${moduleId}"]`).scrollIntoViewIfNeeded()
    const path = resolve(evidenceDir, name)
    await page.screenshot({ path })
    return path
  },
  async text(moduleId = 'conversation', tail = 3000) {
    const text = await frame(moduleId).locator('body').innerText()
    return text.slice(-tail)
  },
}

createServer(async (request, response) => {
  let body = ''
  for await (const chunk of request) body += chunk
  let payload
  try {
    const run = new (Object.getPrototypeOf(async function () {}).constructor)('page', 'frame', 'h', body)
    payload = { ok: true, result: await run(page, frame, h) }
  } catch (error) {
    payload = { ok: false, error: String(error?.stack ?? error).slice(0, 3000) }
  }
  response.writeHead(200, { 'content-type': 'application/json' })
  response.end(JSON.stringify(payload))
}).listen(port, '127.0.0.1', () => console.log(`M3CL2 driver ready on ${port}`))

function argument(name) {
  const index = args.indexOf(name)
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${name} is required`)
  return value
}
