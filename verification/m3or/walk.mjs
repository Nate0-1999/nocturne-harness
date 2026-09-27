/** Owner-authorized Playwright replay of M3OR's real-app launch and result walk.
 * Start the disposable verification app separately; never pass credentials here.
 * The recovery watcher terminates only its identified step-2 completion process.
 */
import { createRequire } from 'node:module'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const require = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const [baseUrl, project, launchFile, evidenceDir] = process.argv.slice(2)
if (!evidenceDir) throw new Error('Usage: node walk.mjs URL SCRATCH_PROJECT LAUNCH_JSON EVIDENCE_DIR')
const launch = JSON.parse(await readFile(launchFile, 'utf8')).launch
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } })
page.setDefaultTimeout(15_000)
const frame = id => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
const chat = frame('conversation')
const capture = name => page.screenshot({ path: resolve(evidenceDir, `${name}.png`) })
try {
  await mkdir(evidenceDir, { recursive: true })
  await page.goto(baseUrl)
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await frame('threads').getByTestId('new-thread').press('Enter')
  await frame('threads').getByTestId('thread-workspace-root').fill(project)
  await frame('threads').getByRole('button', { name: 'Create', exact: true }).press('Enter')
  await chat.getByText('New thread', { exact: true }).first().waitFor()
  const modes = await chat.getByLabel('Orchestration mode').locator('option').allTextContents()
  if (modes.join(',') !== 'Duet,Symphony') throw new Error('Mode selector differs')
  await chat.locator('summary').filter({ hasText: 'Duet configuration' }).click()
  await chat.getByLabel('Agent policy value').waitFor()
  await capture('FL-089-duet')
  await chat.getByLabel('Orchestration mode').selectOption('Symphony')
  await chat.getByLabel('Judge policy value').waitFor()
  await capture('FL-089-symphony')
  await chat.locator('summary').filter({ hasText: 'Symphony configuration' }).click()
  await chat.getByLabel('Desired outcome').fill(launch.objective)
  await chat.getByLabel('Why this deserves a Symphony').fill(launch.motivation)
  for (let i = 0; i < launch.recipe.length; i++) {
    if (i) await chat.getByRole('button', { name: 'Add recipe step', exact: true }).press('Enter')
    const step = launch.recipe[i]
    await chat.getByLabel(`Step ${i + 1}`, { exact: true }).fill(step.title)
    await chat.getByLabel('Done when', { exact: true }).nth(i).fill(step.done_when)
    await chat.getByLabel('Search node — spend may occur here', { exact: true }).nth(i).setChecked(step.search)
  }
  const searches = launch.recipe.filter(step => step.search)
  for (let i = 0; i < searches.length; i++) {
    await chat.getByLabel('Stratagems · one named approach per line').nth(i).fill(searches[i].stratagems.join('\n'))
  }
  for (let i = 0; i < launch.judge_charters.length; i++) {
    const charter = launch.judge_charters[i]
    await chat.getByLabel('Rubric', { exact: true }).nth(i).fill(charter.rubric[0])
    await chat.getByLabel('Required evidence', { exact: true }).nth(i).fill(charter.evidence_requirements[0])
    if (charter.seat === 'performance') await chat.getByLabel('Precalculated metric').fill(charter.metrics[0])
  }
  for (const [label, key] of Object.entries({ Attempts: 'attempts', 'Spend USD': 'spend_wall_usd', Rounds: 'max_rounds', Depth: 'depth_cap', 'Children / attempt': 'children_per_attempt', Minutes: 'duration_minutes' })) {
    await chat.getByLabel(label, { exact: true }).fill(String(launch.authority[key]))
  }
  await chat.getByRole('checkbox', { name: /I authorize/ }).check()
  await capture('FL-094')
  await chat.getByRole('button', { name: 'Sign & run Symphony', exact: true }).press('Enter')
  await chat.getByTestId('symphony-result').waitFor({ timeout: 900_000 })
  await chat.getByTestId('symphony-result').screenshot({ path: resolve(evidenceDir, 'FL-085.png') })
  await writeFile(resolve(evidenceDir, 'result.txt'), await chat.getByTestId('symphony-result').innerText())
  await page.getByRole('button', { name: 'Stack', exact: true }).press('Enter')
  for (const detail of await chat.locator('.deck-stack details').all()) await detail.locator('summary').press('Enter')
  await chat.locator('.deck-stack').screenshot({ path: resolve(evidenceDir, 'judging.png') })
  await page.getByRole('button', { name: 'Focused', exact: true }).press('Enter')
  await chat.getByTestId('archive-thread').press('Enter')
  await page.getByTestId('back-to-stage').waitFor({ timeout: 180_000 })
  await page.getByTestId('back-to-stage').click()
  await page.getByRole('tab', { name: 'Graph', exact: true }).click()
  await frame('memory_graph').getByRole('heading', { name: 'Memory Graph', exact: true }).waitFor()
  await capture('FL-124-graph')
  await page.getByRole('tab', { name: 'Work', exact: true }).click()
  await capture('FL-124')
} finally {
  await browser.close()
}
