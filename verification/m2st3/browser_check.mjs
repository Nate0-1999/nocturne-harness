/** PLAN M2ST3/M2ST4 and SPEC B.6 r12: human numbers, compact absence, and label declutter. */

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
  : 'http://127.0.0.1:8807'
const fixture = args.includes('--fixture')
  ? args[args.indexOf('--fixture') + 1]
  : 'M2ST3 REGRESSION'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent(fixture)}`
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const consoleProblems = []
const pageErrors = []
const observations = {}
const outageResponses = []
let palaceOutageExpected = false
let expectedOutageConsoleErrors = 0

page.on('console', (message) => {
  if (message.type() !== 'error') return
  if (
    palaceOutageExpected &&
    message.text() === 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'
  ) {
    expectedOutageConsoleErrors += 1
    return
  }
  consoleProblems.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('response', (response) => {
  if (palaceOutageExpected && response.status() >= 400) {
    outageResponses.push({ status: response.status(), url: response.url() })
  }
})

try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(fixtureUrl, { waitUntil: 'domcontentloaded' })
  await frame(page, 'header').getByTestId('connection').getByText('Palace ready').waitFor()
  await page.getByTestId('stage-viewport').waitFor()

  const vitals = frame(page, 'vitals')
  await vitals.getByText('Ledger drift · -$0.08').waitFor()
  const vitalsText = await vitals.locator('body').innerText()
  for (const forbidden of ['0.084555772000', '11.1111111111111111%', 'Not recorded yet']) {
    if (vitalsText.includes(forbidden)) throw new Error(`raw Vitals copy leaked: ${forbidden}`)
  }
  for (const expected of ['-$0.08', '$0.08', '11.1%', '—']) {
    if (!vitalsText.includes(expected)) throw new Error(`human Vitals copy missing: ${expected}`)
  }
  const laneCollisions = await vitals.locator('.vitals-lane').evaluateAll((lanes) => lanes.flatMap((lane, index) => {
    const identity = lane.querySelector('.vitals-lane__identity')?.getBoundingClientRect()
    const readout = lane.querySelector('.vitals-lane__readout')?.getBoundingClientRect()
    if (identity === undefined || readout === undefined) return [`lane-${index}:missing`]
    const overlaps = Math.min(identity.right, readout.right) > Math.max(identity.left, readout.left) &&
      Math.min(identity.bottom, readout.bottom) > Math.max(identity.top, readout.top)
    return overlaps ? [`lane-${index}:identity-readout`] : []
  }))
  if (laneCollisions.length !== 0) throw new Error(`spend lane collision: ${laneCollisions.join(', ')}`)
  const gaugeWidths = await vitals.locator('.vitals-gauge').evaluateAll((gauges) => ({
    absent: gauges.filter((gauge) => gauge.matches('.vitals-gauge--not_recorded,.vitals-gauge--placeholder')).map((gauge) => gauge.getBoundingClientRect().width),
    measured: gauges.filter((gauge) => gauge.matches('.vitals-gauge--measured')).map((gauge) => gauge.getBoundingClientRect().width),
  }))
  if (gaugeWidths.absent.length === 0 || gaugeWidths.measured.length === 0) {
    throw new Error(`missing gauge comparison: ${JSON.stringify(gaugeWidths)}`)
  }
  if (Math.max(...gaugeWidths.absent) >= Math.min(...gaugeWidths.measured)) {
    throw new Error(`absent gauges still burn a measured column: ${JSON.stringify(gaugeWidths)}`)
  }
  observations.vitals = { lane_collisions: laneCollisions, gauge_widths: gaugeWidths }
  observations.human_number_scan = await assertNoPrecisionLeaks(page, 'work')
  for (let step = 0; step < 6; step += 1) {
    await page.getByRole('button', { name: 'Zoom in' }).click()
  }
  await page.getByTestId('stage-viewport').dispatchEvent('wheel', { deltaX: -450, deltaY: 680 })
  await page.waitForTimeout(160)
  await page.evaluate(() => globalThis.scrollTo(0, 0))
  await page.screenshot({ path: join(evidenceDir, '01-spend-human-numbers-1280x900.png') })

  let consoleFrame = frame(page, 'injection_console')
  if (await page.locator('iframe[data-testid="rack-plugin-frame-injection_console"]').count() === 0) {
    await page.getByRole('tab', { name: 'Injection' }).click()
    consoleFrame = frame(page, 'injection_console')
  }
  await consoleFrame.locator('.contribution-row output').first().waitFor()
  const contributionCopy = await consoleFrame.locator('.contribution-row output').allTextContents()
  if (!contributionCopy.includes('0.099') || !contributionCopy.includes('-2.86e-9')) {
    throw new Error(`ordinary contribution cards did not use human numbers: ${JSON.stringify(contributionCopy)}`)
  }
  observations.card_contributions = contributionCopy
  observations.card_human_number_scan = await assertNoPrecisionLeaks(page, 'ordinary-memory-cards')

  let graph = frame(page, 'memory_graph')
  if (await page.locator('iframe[data-testid="rack-plugin-frame-memory_graph"]').count() === 0) {
    await page.getByRole('tab', { name: 'Graph' }).click()
    graph = frame(page, 'memory_graph')
  }
  await graph.locator('.graph-stage').waitFor()
  const graphAudit = await graph.locator('svg').evaluate((svg) => {
    const nodes = [...svg.querySelectorAll('.graph-node')]
    const labels = [...svg.querySelectorAll('.graph-node-label')].filter(
      (label) => getComputedStyle(label).visibility !== 'hidden' && label.textContent?.trim(),
    )
    const collisions = []
    for (let index = 0; index < labels.length; index += 1) {
      for (let other = index + 1; other < labels.length; other += 1) {
        const left = labels[index].getBoundingClientRect()
        const right = labels[other].getBoundingClientRect()
        const overlaps = Math.min(left.right, right.right) > Math.max(left.left, right.left) &&
          Math.min(left.bottom, right.bottom) > Math.max(left.top, right.top)
        if (overlaps) {
          collisions.push([labels[index].textContent, labels[other].textContent])
        }
      }
    }
    return {
      node_count: nodes.length,
      visible_label_count: labels.length,
      visible_labels: labels.map((label) => label.textContent),
      priorities: labels.map((label) => Number(label.getAttribute('data-priority'))),
      collisions,
    }
  })
  if (graphAudit.node_count !== 10 || graphAudit.visible_label_count >= graphAudit.node_count) {
    throw new Error(`graph labels were not priority-decluttered: ${JSON.stringify(graphAudit)}`)
  }
  if (graphAudit.collisions.length !== 0) {
    throw new Error(`graph label collision: ${JSON.stringify(graphAudit.collisions)}`)
  }
  observations.graph = graphAudit
  observations.graph_human_number_scan = await assertNoPrecisionLeaks(page, 'graph')
  await page.screenshot({ path: join(evidenceDir, '02-graph-decluttered-1280x900.png') })

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  palaceOutageExpected = true
  await page.request.post(`${baseUrl}/__scenario__/palace/unavailable`)
  await page.reload({ waitUntil: 'domcontentloaded' })
  const degradedStatus = frame(page, 'header').getByTestId('connection')
  await degradedStatus.getByText('Palace unavailable').waitFor()
  if ((await degradedStatus.innerText()).includes('Palace ready')) {
    throw new Error('the header claimed Palace health while its live query returned 503')
  }
  const unexpectedOutageResponses = outageResponses.filter(({ status, url }) => (
    status !== 503 || !url.startsWith(`${baseUrl}/v1/rack/query?`)
  ))
  if (
    expectedOutageConsoleErrors === 0 ||
    !outageResponses.some(({ url }) => url.includes('resource=vitals')) ||
    unexpectedOutageResponses.length !== 0
  ) {
    throw new Error(JSON.stringify({
      expectedOutageConsoleErrors,
      outageResponses,
      unexpectedOutageResponses,
    }))
  }
  observations.degraded_palace = {
    header: (await degradedStatus.innerText()).trim(),
    expected_console_503s: expectedOutageConsoleErrors,
    failed_queries: outageResponses,
  }

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  await writeFile(join(evidenceDir, 'honest-display.json'), `${JSON.stringify({
    fixture,
    observations,
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }, null, 2)}\n`, 'utf8')
  console.log('M2ST3 honest display PASS: human numbers, honest Palace status, compact absence, and graph declutter')
} finally {
  await context.close()
  await browser.close()
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}

async function assertNoPrecisionLeaks(targetPage, state) {
  const leaks = []
  const checkedScopes = []
  for (const candidateFrame of targetPage.frames()) {
    const scope = candidateFrame === targetPage.mainFrame()
      ? 'shell'
      : new URL(candidateFrame.url()).searchParams.get('rack_module') ?? 'unknown-module'
    checkedScopes.push(scope)
    const frameLeaks = await candidateFrame.locator('body').evaluate((body) => {
      const visible = (element) => {
        const style = getComputedStyle(element)
        const rect = element.getBoundingClientRect()
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) !== 0 && rect.width > 0 && rect.height > 0 &&
          element.closest('[aria-hidden="true"], [inert]') === null
      }
      const precisionPattern = /(?:^|[^\w.])[-+$]?\d+\.\d{4,}(?![\w.])/gu
      return [...body.querySelectorAll('*')].flatMap((element) => {
        if (
          !visible(element) ||
          element.closest('[data-raw-precision], .receipt, [data-testid*="receipt"], .instrument-inspector') !== null
        ) return []
        const directText = [...element.childNodes]
          .filter((node) => node.nodeType === Node.TEXT_NODE)
          .map((node) => node.textContent ?? '')
          .join(' ')
        return [...directText.matchAll(precisionPattern)].map((match) => ({
          text: match[0].trim(),
          element: element.tagName.toLowerCase(),
        }))
      })
    })
    leaks.push(...frameLeaks.map((leak) => ({ scope, ...leak })))
  }
  if (leaks.length !== 0) {
    throw new Error(`human-number precision leaks in ${state}: ${JSON.stringify(leaks)}`)
  }
  return { state, checked_scopes: [...new Set(checkedScopes)].sort(), leaks }
}
