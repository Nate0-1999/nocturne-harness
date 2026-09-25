/** M3VL row walk on the real app: shared selection (FL-130), time order (FL-132), history (FL-134),
 * Stage and Sheet (FL-142), and one context capture for rows this rendering walk does not exercise. */
import { createRequire } from 'node:module'
import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [baseUrl, evidenceDir] = [process.argv[2], resolve(process.argv[3])]
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--enable-unsafe-webgpu', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
const frame = (id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
const shot = (name) => page.screenshot({ path: resolve(evidenceDir, name) })
const log = {}
try {
  await page.goto(baseUrl)
  await frame('threads').getByTestId('new-thread').waitFor()
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await page.waitForTimeout(3000)
  await shot('context.png')
  await page.getByTestId('stage-layer-create').click()
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  for (const name of ['Palace', 'Farm', 'Roots']) {
    const add = page.locator('li').filter({ has: page.getByText(name, { exact: true }) }).getByRole('button', { name: 'Add', exact: true })
    if (await add.count()) await add.click()
  }
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  const [roots, farm, palace] = [frame('roots'), frame('farm'), frame('palace_nebula')]
  await roots.locator('canvas').waitFor({ timeout: 60_000 })
  await palace.locator('canvas').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(5000)
  // FL-142: Sheet carries the legends and the white Roots ground; Stage renders the same modules.
  log.sheet = { roots_legend: await roots.locator('.work-viz__foot').innerText(), palace_legend: (await palace.locator('.palace-nebula__legend').innerText()).slice(0, 200) }
  await shot('FL-142.png')
  await page.getByRole('button', { name: 'Stage', exact: true }).click()
  await page.waitForTimeout(4000)
  log.stage = { canvases: await page.locator('[data-testid^="rack-plugin-frame-"]').evaluateAll((frames) => frames.length) }
  await shot('FL-142-stage.png')
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await page.waitForTimeout(3000)
  // FL-130: picking a root in the Roots module selects that agent in the Farm too.
  const agent = roots.locator('.work-viz__data tbody tr button').filter({ hasText: 'root.1' }).first()
  await agent.click()
  await page.waitForTimeout(3000)
  log.selection = {
    picked: await agent.innerText(),
    roots_selected_row: await roots.locator('.work-viz__data tbody tr[data-selected] button').innerText(),
    farm_selected_row: await farm.locator('.work-viz__data tbody tr[data-selected] button').innerText().catch(() => 'none'),
    farm_readout: await farm.locator('.work-viz__readout').innerText(),
  }
  await page.locator('[data-testid="rack-plugin-frame-farm"]').scrollIntoViewIfNeeded()
  await shot('FL-130.png')
  // FL-132: Time order selects the longest-waiting agent in both modules.
  await roots.getByRole('button', { name: 'Time order' }).click()
  await page.waitForTimeout(4000)
  log.time_order = {
    roots_pressed: await roots.getByRole('button', { name: 'Time order' }).getAttribute('aria-pressed'),
    farm_pressed: await farm.getByRole('button', { name: 'Time order' }).getAttribute('aria-pressed'),
    roots_selected_row: await roots.locator('.work-viz__data tbody tr[data-selected] button').innerText().catch(() => 'none'),
  }
  await page.locator('[data-testid="rack-plugin-frame-roots"]').scrollIntoViewIfNeeded()
  await shot('FL-132.png')
  await roots.getByRole('button', { name: 'Time order' }).click()
  // FL-134: scrub to the first recorded state, then back to Live.
  await page.locator('[data-testid="rack-plugin-frame-roots"]').scrollIntoViewIfNeeded()
  const history = roots.getByLabel('Visualization history')
  // The first state holds only the daemon's launch folder (a 31,878-entry repository) on which the
  // unchanged Farm freezes the page (flagged); scrub to the first state with a thread's work instead.
  await history.fill(process.argv[4] ?? '0')
  await page.waitForTimeout(5000)
  log.history = {
    early_state_roots: await roots.locator('.work-viz__readout strong').innerText(),
    early_state_palace: await palace.locator('.palace-nebula__readouts article').first().innerText(),
  }
  await shot('FL-134.png')
  await page.locator('[data-testid="rack-plugin-frame-roots"]').scrollIntoViewIfNeeded()
  await roots.getByRole('button', { name: 'Live', exact: true }).click()
  const settled = Date.now()
  await roots.locator('.work-viz__readout strong').filter({ hasNotText: /^0 roots$/ }).waitFor({ timeout: 30_000 }).catch(() => {})
  log.history.live_settled_ms = Date.now() - settled
  log.history.live_roots = await roots.locator('.work-viz__readout strong').innerText()
  log.history.live_palace = await palace.locator('.palace-nebula__readouts article').first().innerText()
} finally {
  await writeFile(resolve(evidenceDir, 'receipts', 'rows-walk.json'), `${JSON.stringify(log, null, 2)}\n`)
  console.log(JSON.stringify(log, null, 1))
  await browser.close()
}
