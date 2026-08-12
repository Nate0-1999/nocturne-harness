/** PLAN M2ST2/M2ST4 and SPEC B.6 r12: live controls, fixed-scope honesty, and label diet. */

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
  : 'http://127.0.0.1:8777'
const fixture = args.includes('--fixture')
  ? args[args.indexOf('--fixture') + 1]
  : 'M2ST2 REGRESSION'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent(fixture)}`
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
  await mkdir(evidenceDir, { recursive: true })
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
  observations.control_conformance = await auditRenderedControls(page)

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
    fixture,
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

async function auditRenderedControls(targetPage) {
  const controls = []
  for (const candidateFrame of targetPage.frames()) {
    const scope = candidateFrame === targetPage.mainFrame()
      ? 'shell'
      : new URL(candidateFrame.url()).searchParams.get('rack_module') ?? 'unknown-module'
    controls.push(...await candidateFrame.locator('button, select, input, textarea, a[href]').evaluateAll(
      (elements, frameScope) => elements.flatMap((element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          Number(style.opacity) === 0 ||
          rect.width <= 0 ||
          rect.height <= 0 ||
          element.closest('[aria-hidden="true"], [inert]') !== null
        ) return []
        const labels = 'labels' in element && element.labels !== null
          ? [...element.labels].map((label) => label.textContent ?? '').join(' ')
          : ''
        const name = (
          element.getAttribute('aria-label') ||
          labels ||
          element.textContent ||
          element.getAttribute('title') ||
          element.getAttribute('value') ||
          ''
        ).trim().replace(/\s+/gu, ' ')
        return [{
          scope: frameScope,
          tag: element.tagName.toLowerCase(),
          name,
          disabled: 'disabled' in element && element.disabled,
        }]
      }),
      scope,
    ))
  }
  const unnamed = controls.filter((control) => control.name === '')
  if (unnamed.length !== 0) {
    throw new Error(`rendered controls without an accessible function name: ${JSON.stringify(unnamed)}`)
  }
  return {
    rendered: controls.length,
    enabled: controls.filter((control) => !control.disabled).length,
    disabled_contextually: controls.filter((control) => control.disabled).length,
    scopes: [...new Set(controls.map((control) => control.scope))].sort(),
  }
}
