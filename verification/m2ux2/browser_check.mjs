/** PLAN M2UX2 rendered crawl: every reachable dismissible view returns home in one click. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.argv.includes('--base-url')
  ? process.argv[process.argv.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8802'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent('M2UX2 REGRESSION')}`
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const crawl = []

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
  await waitForRack(page)
  await seedArchiveableThread(page)

  for (const view of [
    ['palace_queue', () => header(page).getByRole('button', { name: 'Palace queue' }).click()],
    ['memory_graph', () => header(page).getByRole('button', { name: 'Graph' }).click()],
    ['injection_console', () => header(page).getByRole('button', { name: 'Injection' }).click()],
    ['model_device', () => chat(page).locator('button[aria-label^="Active model:"]').click()],
  ]) {
    await view[1]()
    await returnToStage(page, view[0])
    crawl.push({ view: view[0], return: 'one-click' })
  }

  await header(page).getByRole('button', { name: 'Graph' }).click()
  await page.locator('[data-rack-module="memory_graph"]').waitFor()
  await page.screenshot({ path: join(evidenceDir, '01-graph-back-to-stage-1280x900.png') })
  await page.getByTestId('back-to-stage').click()

  await page.setViewportSize({ width: 390, height: 844 })
  await header(page).getByRole('button', { name: 'Threads' }).click()
  await threads(page).getByRole('button', { name: 'Close threads' }).click()
  await expectDrawerClosed(threads(page))
  crawl.push({ view: 'threads', return: 'one-click' })

  await header(page).getByRole('button', { name: 'Memory' }).click()
  await memory(page).getByRole('button', { name: 'Close memory drawer' }).click()
  await expectDrawerClosed(memory(page))
  crawl.push({ view: 'memory', return: 'one-click' })

  await header(page).getByRole('button', { name: 'Threads' }).click()
  const archive = threads(page).getByRole('button', { name: /^Archive /u }).first()
  await archive.click()
  await page.locator('[data-rack-module="thread_end"]').waitFor()
  await threadEnd(page).getByText('What should survive?').waitFor()
  await page.screenshot({ path: join(evidenceDir, '02-thread-list-archive-review-390x844.png') })
  const trace = await page.evaluate(async (url) => {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`trace failed: ${response.status}`)
    return response.json()
  }, `${baseUrl}/__scenario__/trace?fixture=${encodeURIComponent('M2UX2 REGRESSION')}`)
  if (trace.pending_thread_candidates !== 5) {
    throw new Error(`archive did not land in ordinary extraction: ${JSON.stringify(trace)}`)
  }
  await page.getByTestId('back-to-stage').click()
  await page.locator('[data-rack-module="thread_end"]').waitFor({ state: 'detached' })
  crawl.push({ view: 'thread_end', return: 'one-click', extraction_candidates: 5 })

  await page.screenshot({ path: join(evidenceDir, '03-stage-restored-390x844.png') })
  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  const evidence = {
    fixture: 'M2UX2 REGRESSION',
    crawl,
    trace,
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }
  await writeFile(join(evidenceDir, 'crawl.json'), `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
  console.log(`M2UX2 crawl PASS: ${crawl.length} reachable views, archive extraction traced`)
} finally {
  await context.close()
  await browser.close()
}

async function waitForRack(targetPage) {
  await header(targetPage).getByTestId('connection').getByText('Palace ready').waitFor()
  await targetPage.getByTestId('rack-grid').waitFor()
}

async function seedArchiveableThread(targetPage) {
  await chat(targetPage).getByTestId('composer').fill(
    'Keep the stage reachable and route thread archive through ordinary extraction.',
  )
  await chat(targetPage).getByTestId('send').click()
  await targetPage.getByTestId('rack-plugin-frame-gate').waitFor()
  await frame(targetPage, 'gate').getByTestId('memory-gate-continue').click()
  await targetPage.getByTestId('rack-plugin-frame-gate').waitFor({ state: 'detached' })
  await chat(targetPage).getByTestId('assistant-markdown').getByText(/M2H final post/u).waitFor()
}

async function returnToStage(targetPage, moduleId) {
  const overlay = targetPage.locator(`[data-rack-module="${moduleId}"]`)
  await overlay.waitFor()
  const back = targetPage.getByTestId('back-to-stage')
  await back.getByText('Back to stage').waitFor()
  await back.click()
  await overlay.waitFor({ state: 'detached' })
  await targetPage.getByTestId('rack-grid').waitFor()
}

async function expectDrawerClosed(targetFrame) {
  await targetFrame.locator('[data-drawer-open]').waitFor({ state: 'detached' })
}

function header(targetPage) { return frame(targetPage, 'header') }
function threads(targetPage) { return frame(targetPage, 'threads') }
function memory(targetPage) { return frame(targetPage, 'memory') }
function chat(targetPage) { return frame(targetPage, 'chat') }
function threadEnd(targetPage) { return frame(targetPage, 'thread_end') }
function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}
