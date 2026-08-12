/** PLAN M2ST3 rendered proof: human numbers, compact absence, and decluttered labels. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const evidenceDir = dirname(fileURLToPath(import.meta.url))
const baseUrl = process.argv.includes('--base-url')
  ? process.argv[process.argv.indexOf('--base-url') + 1]
  : 'http://127.0.0.1:8807'
const fixtureUrl = `${baseUrl}/?fixture=${encodeURIComponent('M2ST3 REGRESSION')}`
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
  for (let step = 0; step < 6; step += 1) {
    await page.getByRole('button', { name: 'Zoom in' }).click()
  }
  await page.getByTestId('stage-viewport').dispatchEvent('wheel', { deltaX: -450, deltaY: 680 })
  await page.waitForTimeout(160)
  await page.evaluate(() => globalThis.scrollTo(0, 0))
  await page.screenshot({ path: join(evidenceDir, '01-spend-human-numbers-1280x900.png') })

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
  await page.screenshot({ path: join(evidenceDir, '02-graph-decluttered-1280x900.png') })

  if (consoleProblems.length !== 0 || pageErrors.length !== 0) {
    throw new Error(JSON.stringify({ consoleProblems, pageErrors }))
  }
  await writeFile(join(evidenceDir, 'honest-display.json'), `${JSON.stringify({
    fixture: 'M2ST3 REGRESSION',
    observations,
    console_problems: consoleProblems,
    page_errors: pageErrors,
  }, null, 2)}\n`, 'utf8')
  console.log('M2ST3 honest display PASS: human numbers, compact absence, and graph declutter')
} finally {
  await context.close()
  await browser.close()
}

function frame(targetPage, moduleId) {
  return targetPage.frameLocator(`iframe[data-testid="rack-plugin-frame-${moduleId}"]`)
}
