/** PLAN M2ST2 rendered proof: settings placement, live scope, fixed-scope honesty, and label diet. */

import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.argv.includes('--base-url')
  ? process.argv[process.argv.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8777'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent('M2ST2 REGRESSION')}`
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const observations = {}

page.on('console', (message) => {
  if (message.type() === 'error') consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))

try {
  await page.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
  await frame(page, 'header').getByTestId('connection').getByText('Link live').waitFor()

  const appGear = page.getByTestId('app-settings-toggle')
  await appGear.click()
  const appPanel = page.getByTestId('app-settings-panel')
  await appPanel.getByRole('heading', { name: 'Appearance' }).waitFor()
  if (await page.locator('.stage-toolbar [data-testid="theme-control"]').count() !== 0) {
    throw new Error('theme control still occupies the stage toolbar')
  }
  await appPanel.getByLabel('Theme').selectOption('seraph-dressed')
  if (await appPanel.getByLabel('Theme').inputValue() !== 'seraph-dressed') {
    throw new Error('app theme selector did not change')
  }
  const spendThemeRoot = frame(page, 'vitals').locator('html[data-theme="seraph-dressed"]')
  await spendThemeRoot.waitFor()
  if (await spendThemeRoot.getAttribute('data-theme') !== 'seraph-dressed') {
    throw new Error('selected theme did not reach the Spend frame')
  }
  observations.app_settings = {
    theme: 'seraph-dressed',
    layout_actions: await appPanel.locator('.app-settings-actions button').allTextContents(),
  }
  await page.screenshot({ path: join(evidenceDir, '01-app-settings-desktop.png') })
  await appPanel.getByRole('button', { name: 'Close app settings' }).click()

  const spendGear = page.getByTestId('rack-settings-vitals')
  await spendGear.press('Enter')
  const spendDialog = page.getByRole('dialog', { name: 'Spend settings' })
  const thisThread = spendDialog.getByRole('button', { name: 'This thread' })
  await thisThread.press('Enter')
  if (await thisThread.getAttribute('aria-pressed') !== 'true') {
    throw new Error('Spend scope control did not persist through the real Rack action')
  }
  await spendGear.press('Enter')

  const threadsGear = page.getByTestId('rack-settings-threads')
  await threadsGear.press('Enter')
  const threadsDialog = page.getByRole('dialog', { name: 'Channel Stack settings' })
  if ((await threadsDialog.innerText()).trim() !== 'This module follows the selected thread.') {
    throw new Error('fixed thread scope lacks its reason')
  }
  if (await threadsDialog.getByRole('button').count() !== 0) {
    throw new Error('fixed thread scope exposed a dead control')
  }
  observations.module_settings = {
    spend_scope: 'CURRENT',
    channel_stack_reason: (await threadsDialog.innerText()).trim(),
  }

  const visibleCopy = [await page.locator('body').innerText()]
  for (const moduleId of ['memory', 'vitals', 'context_bars', 'memory_graph', 'injection_console', 'model_device']) {
    if (await page.locator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`).count() !== 0) {
      visibleCopy.push(await frame(page, moduleId).locator('body').innerText())
    }
  }
  for (const forbidden of [
    'Current principal',
    'Authoritative state',
    'Active channel',
    'Local channels',
    'consent surface',
    'Corpus door',
    'MEMORY INSTRUMENT',
    'MEMORY TUNING',
  ]) {
    if (visibleCopy.some((copy) => copy.includes(forbidden))) {
      throw new Error(`internal label still visible: ${forbidden}`)
    }
  }

  await threadsGear.press('Enter')
  await page.setViewportSize({ width: 390, height: 844 })
  await appGear.click()
  const gearBox = await appGear.boundingBox()
  const threadButtonBox = await frame(page, 'header').getByTestId('mobile-threads').boundingBox()
  if (gearBox === null || threadButtonBox === null || rectanglesOverlap(gearBox, threadButtonBox)) {
    throw new Error(`phone header settings collision: ${JSON.stringify({ gearBox, threadButtonBox })}`)
  }
  observations.phone = { viewport: '390x844', gear_box: gearBox, thread_button_box: threadButtonBox }
  await page.screenshot({ path: join(evidenceDir, '02-app-settings-phone-390x844.png') })

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  await writeFile(join(evidenceDir, 'chrome-diet.json'), `${JSON.stringify({
    fixture: 'M2ST2 REGRESSION',
    observations,
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }, null, 2)}\n`, 'utf8')
  console.log('M2ST2 chrome diet PASS: rare settings contained, scope honest, labels useful')
} finally {
  await context.close()
  await browser.close()
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

function rectanglesOverlap(left, right) {
  return Math.min(left.x + left.width, right.x + right.width) > Math.max(left.x, right.x) &&
    Math.min(left.y + left.height, right.y + right.height) > Math.max(left.y, right.y)
}
