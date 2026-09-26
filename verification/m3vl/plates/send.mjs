/** M3VL send-back 2: send one prompt to one thread through the real app, confirm it left over the
 * socket, pass the memory gate, and optionally wait for the run to finish (journal run.done).
 *   node send.mjs --base-url <url> --home <NOCTURNE_HOME> --thread <id> --prompt <text> [--wait] */
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const value = (name) => args[args.indexOf(name) + 1]
const [baseUrl, home, threadId, prompt] = ['--base-url', '--home', '--thread', '--prompt'].map(value)
const journal = resolve(home, 'transcripts', `${createHash('sha256').update(threadId).digest('hex')}.jsonl`)
const runsDone = async () => (await readFile(journal, 'utf8').catch(() => '')).split('\n').filter((line) => line.includes('"type":"run.done"')).length
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
let left = false
page.on('websocket', (ws) => ws.on('framesent', (frame) => {
  const text = String(frame.payload)
  if (text.includes('"prompt.submit"') && text.includes(prompt.slice(0, 40))) left = true
}))
const frame = (id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
try {
  const before = await runsDone()
  await page.goto(baseUrl)
  await frame('threads').getByTestId('new-thread').waitFor()
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await frame('threads').locator(`[data-thread-id="${threadId}"] button`).first().click()
  await page.waitForTimeout(2500)
  const composer = frame('conversation').getByTestId('composer')
  await composer.fill('')
  await composer.fill(prompt)
  await composer.press('Enter')
  for (let i = 0; i < 20 && !left; i++) await page.waitForTimeout(250)
  if (!left) {
    await page.screenshot({ path: '/tmp/m3vl-send-failed.png' })
    throw new Error('the prompt did not leave the app')
  }
  try {
    await frame('gate').getByTestId('memory-gate').waitFor({ state: 'visible', timeout: 30_000 })
    await frame('gate').getByTestId('memory-gate-continue').click()
  } catch { /* Later turns open no memory check. */ }
  console.log(`sent to ${threadId.slice(0, 8)} at ${new Date().toISOString()}`)
  if (args.includes('--wait')) {
    const deadline = Date.now() + 1_200_000
    while (await runsDone() <= before) { if (Date.now() > deadline) throw new Error('run did not finish'); await new Promise((r) => setTimeout(r, 2000)) }
    console.log(`run finished at ${new Date().toISOString()}`)
  }
} finally { await browser.close() }
