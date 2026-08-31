/** M3CU: activity belongs in Palace State; surgery belongs in the existing consent queue. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = args.includes('--base-url')
  ? args[args.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8807'
const fixture = args.includes('--fixture')
  ? args[args.indexOf('--fixture') + 1]
  : 'M2ST3 REGRESSION'
const evidenceDir = args.includes('--evidence-dir')
  ? resolve(args[args.indexOf('--evidence-dir') + 1])
  : dirname(fileURLToPath(import.meta.url))
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1920, height: 1000 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const decisions = []

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('response', (response) => {
  if (response.url().includes('/v1/approval-queue/') && response.url().endsWith('/decisions')) {
    decisions.push({ url: response.url(), status: response.status() })
  }
})

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(`${baseUrl}/?fixture=${encodeURIComponent(fixture)}`, { waitUntil: 'domcontentloaded' })
  await frame('header').getByTestId('connection').getByText('Palace ready').waitFor()

  const state = frame('palace_state')
  await state.locator('[aria-label="Curator activity"]').waitFor()
  for (const expected of [
    'Curators',
    '1 proposals waiting',
    'Latest completed · next pass in 9 writes or 2 removals',
  ]) {
    await state.getByText(expected, { exact: true }).waitFor()
  }

  const queue = frame('palace_queue')
  await queue.getByRole('heading', { name: 'Corpus repairs need your consent' }).waitFor()
  await queue.getByText('Owner architecture', { exact: true }).waitFor()
  await queue.getByText(
    'Two stable terms make this memory findable without changing its claim.',
    { exact: true },
  ).waitFor()
  await queue.getByRole('button', { name: 'Approve repair' }).waitFor()
  await page.screenshot({ path: join(evidenceDir, 'curator-state-and-consent.png'), fullPage: true })
  const keepButton = queue.getByRole('button', { name: 'Keep as is' })
  await keepButton.focus()
  await keepButton.press('Enter')
  await queue.locator('.seed-status').waitFor()
  await page.waitForTimeout(1_000)
  const decisionStatus = await queue.locator('.seed-status').innerText()
  if (decisionStatus !== 'Proposal rejected. The Palace was not changed.') {
    throw new Error(JSON.stringify({ decisionStatus, decisions, consoleProblems, pageErrors }))
  }

  if (decisions.length !== 1 || decisions[0]?.status !== 200) {
    throw new Error(JSON.stringify({ decisions }))
  }

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  await page.screenshot({ path: join(evidenceDir, 'curator-denial.png'), fullPage: true })
  await writeFile(join(evidenceDir, 'curator-proof.json'), `${JSON.stringify({
    fixture,
    palace_state: 'latest completed; 9 writes or 2 removals; 1 proposal waiting',
    proposal: 'keyword_repair with visible rationale',
    decision: 'explicit human denial; Palace unchanged',
    decision_transport: decisions[0],
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }, null, 2)}\n`, 'utf8')
  console.log('M3CU browser PASS: curator activity, rationale, and explicit consent')
} finally {
  await context.close()
  await browser.close()
}

function frame(moduleId) {
  return page.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}
