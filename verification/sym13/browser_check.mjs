/** SYM13/P2.3: the rendered recipe grid makes live completion legible without new authority. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const evidenceDir = args.includes('--evidence-dir')
  ? resolve(args[args.indexOf('--evidence-dir') + 1])
  : dirname(fileURLToPath(import.meta.url))
const baseUrl = args.includes('--base-url')
  ? args[args.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8873'
const fixture = args.includes('--fixture')
  ? args[args.indexOf('--fixture') + 1]
  : 'SYM13 REGRESSION'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const failedResponses = []

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('response', (response) => {
  if (response.status() >= 400) {
    failedResponses.push({ status: response.status(), url: response.url() })
  }
})

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(`${baseUrl}/?fixture=${encodeURIComponent(fixture)}`, {
    waitUntil: 'domcontentloaded',
  })
  await page.getByTestId('stage-viewport').waitFor()
  await page.getByRole('tab', { name: 'Graph' }).click()
  await page.getByTestId('stage-library-toggle').click()
  const recipeRow = page.getByTestId('stage-library').getByRole('listitem').filter({ hasText: 'Recipe' })
  await recipeRow.getByRole('button', { name: 'Add' }).click()
  await page.getByRole('button', { name: 'Close stage library' }).click()

  const frame = page.frameLocator('iframe[data-testid="rack-plugin-frame-recipe"]')
  await frame.getByRole('heading', { name: 'Recipe' }).waitFor()
  const headings = await frame.locator('.recipe-grid__heading').allTextContents()
  assertJsonEqual(headings, [
    'Packet / input', 'Own prep',
    ...Array.from({ length: 11 }, (_, index) => `Stage ${index + 1}`),
    'Milestone',
  ])
  if (await frame.locator('.recipe-grid__ingredient').count() !== 13) {
    throw new Error('the Symphony recipe does not expose all 13 packet/input rows')
  }

  const state = await frame.locator('.recipe-grid').evaluate((grid) => {
    const done = [...grid.querySelectorAll('[data-progress="done"]')]
    const current = [...grid.querySelectorAll('[data-progress="current"]')]
    const milestone = grid.querySelector('.recipe-grid__milestone')
    return {
      doneOpacity: [...new Set(done.map((cell) => getComputedStyle(cell).opacity))],
      doneFilters: [...new Set(done.map((cell) => getComputedStyle(cell).filter))],
      currentText: current.map((cell) => cell.textContent?.replace(/\s+/gu, ' ').trim()),
      currentShadows: [...new Set(current.map((cell) => getComputedStyle(cell).boxShadow))],
      milestoneHeight: milestone?.getBoundingClientRect().height ?? 0,
      gridHeight: grid.getBoundingClientRect().height,
    }
  })
  assertJsonEqual(state.doneOpacity, ['0.52'])
  if (state.doneFilters.some((value) => !value.includes('saturate'))) {
    throw new Error(`completed cells did not desaturate: ${JSON.stringify(state.doneFilters)}`)
  }
  const currentFrontier = state.currentText.join(' ')
  if (
    state.currentText.length !== 4
    || !currentFrontier.includes('SYM13')
    || !currentFrontier.includes('Serve the recipe grid')
    || !currentFrontier.includes('SYMPHONY')
  ) {
    throw new Error(`the one live frontier was not carried across the grid: ${JSON.stringify(state.currentText)}`)
  }
  if (state.currentShadows.some((value) => value === 'none')) {
    throw new Error('the current frontier did not carry the one lit accent')
  }
  if (state.milestoneHeight < state.gridHeight * 0.9) {
    throw new Error('the served milestone is not one full-height cell')
  }

  const currentStage = frame.locator('.recipe-grid__stage[data-progress="current"] > button')
  await currentStage.waitFor({ state: 'visible' })
  await currentStage.evaluate((button) => button.click())
  await frame.locator('.recipe-inspector h2').waitFor()
  const inspector = await frame.locator('.recipe-inspector').innerText()
  if (!inspector.includes('RUNNING') || !inspector.includes('SYM13') || !inspector.includes('Make completion legible from left to right.')) {
    throw new Error(`the selected current cell lost its why or identity: ${inspector}`)
  }

  assertDiagnostics({ consoleProblems, pageErrors, failedResponses })
  await page.screenshot({ path: join(evidenceDir, 'recipe-grid.png') })
  await writeFile(join(evidenceDir, 'recipe-grid.json'), `${JSON.stringify({
    fixture,
    headings,
    state,
    inspector,
    console_problems: consoleProblems,
    page_errors: pageErrors,
    failed_responses: failedResponses,
  }, null, 2)}\n`, 'utf8')
  console.log('SYM13 recipe canon PASS: packet rows, joins, dimming, frontier, served milestone')
} finally {
  await context.close()
  await browser.close()
}

function assertJsonEqual(actual, expected) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`)
  }
}

function assertDiagnostics({ consoleProblems, pageErrors, failedResponses }) {
  const expectedFixtureGap = ({ status, url }) => {
    const parsed = new URL(url)
    if (status === 503 && parsed.pathname === '/v1/rack/query') {
      return ['scorer_console', 'context_window'].includes(parsed.searchParams.get('resource'))
    }
    return status === 404 && ['/v1/approval-queue', '/v1/seeds/jump-start'].includes(parsed.pathname)
  }
  const unexpectedResponses = failedResponses.filter((response) => !expectedFixtureGap(response))
  const unexpectedConsoleProblems = consoleProblems.filter(
    (message) => !message.startsWith('Failed to load resource:'),
  )
  if (
    unexpectedResponses.length !== 0
    || unexpectedConsoleProblems.length !== 0
    || pageErrors.length !== 0
  ) {
    throw new Error(JSON.stringify({
      consoleProblems,
      pageErrors,
      failedResponses,
      unexpectedResponses,
    }))
  }
}
