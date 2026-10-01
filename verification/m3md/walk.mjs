/** M3MD: the model browser on the real app — FL-202 (chip, ranked list, pins, one-click switch,
 * thinking level, the four policies), FL-106 (/model mid-thread, a table renders), FL-107
 * (temperature journaled for the next turn) and FL-154 (the role policies). One fresh thread per
 * run; it switches to the strong model the `max` policy picks mid-thread. After m3co/walk.mjs. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const run = argument('--run')
const project = argument('--project')
const evidenceDir = resolve(argument('--evidence-dir'), `run-${run}`)
const pinTarget = 'openrouter:openai/gpt-4.1-mini'
const commandTarget = 'openrouter:openai/gpt-4.1-mini'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await context.newPage()
const receipt = { run, base_url: baseUrl, steps: [] }
const startPolicies = await fetchJson(`${baseUrl}/v1/model-policies`)
let threadId = null
let answersBefore = 0

try {
  await mkdir(evidenceDir, { recursive: true })
  const response = await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
  if (response === null || !response.ok()) throw new Error(`app did not load: ${response?.status()}`)
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  const threads = frame('threads')
  const conversation = frame('conversation')
  const before = new Set((await fetchJson(`${baseUrl}/v1/transcripts/catalog`)).threads.map((thread) => thread.thread_id))
  // New thread toggles the folder form, which an empty home already shows.
  const folder = threads.getByPlaceholder('Choose or type a folder path')
  await threads.getByTestId('new-thread').waitFor()
  for (let attempt = 0; attempt < 6 && !(await folder.isVisible()); attempt += 1) {
    await threads.getByTestId('new-thread').click()
    await new Promise((resolveWait) => setTimeout(resolveWait, 1_500))
  }
  await folder.fill(project)
  await threads.getByRole('button', { name: 'Create', exact: true }).click()
  await waitUntil(async () => (await fetchJson(`${baseUrl}/v1/transcripts/catalog`)).threads
    .some((thread) => !before.has(thread.thread_id)))
  threadId = (await fetchJson(`${baseUrl}/v1/transcripts/catalog`)).threads
    .find((thread) => !before.has(thread.thread_id)).thread_id
  await conversation.getByTestId('composer').waitFor({ state: 'visible' })
  await waitUntil(async () => conversation.getByTestId('composer').isEnabled())

  // 1. A first turn on the configured model; the chip reads model · thinking · context · price.
  await send('Name one planet in one word.')
  await settled()
  const configured = (await parameters()).resolved_model
  expect(configured === startPolicies.policies.chat.replace('pinned:', ''), `fresh thread is on ${configured}`)
  const firstChip = await chipText()
  expect(/ · .*context · /.test(firstChip), `chip lacks context and price: ${firstChip}`)
  await shot('conversation', 'FL-202-chip.png')
  step('chip after the first turn', { chip: firstChip })

  // 2. The chip opens the browser: the source's models ranked by score, with price and context.
  await conversation.getByTestId('active-model').click()
  const device = frame('model_device')
  await waitUntil(async () => (await device.locator('[data-testid="model-browser-list"] li').count()) > 50)
  const scores = await device.locator('[data-testid="model-browser-list"] li .model-row__pick > span:nth-child(2)').allTextContents()
  const ranked = scores.filter((value) => value !== '—').map(Number)
  expect(ranked.slice(0, 20).every((value, index, all) => index === 0 || all[index - 1] >= value), `rank order broken: ${scores.slice(0, 20)}`)
  await capture('FL-202.png')
  step('browser opened from the chip', { listed: scores.length, top_scores: scores.slice(0, 5) })

  // 3. Pin one: it sits on top and stays there after the search is cleared and the list reloads.
  await device.getByRole('searchbox', { name: 'Search models' }).fill('gpt-4.1-mini')
  await row(device, pinTarget).getByRole('button', { name: 'Pin to top' }).click()
  await device.getByRole('searchbox', { name: 'Search models' }).fill('')
  await waitUntil(async () => (await firstRowModel(device)) === pinTarget)
  const pins = (await fetchJson(`${baseUrl}/v1/models`)).pins
  expect(pins.includes(pinTarget), `pin not saved: ${pins}`)
  await capture('FL-202-pin.png')
  step('pinned to the top', { first_row: await firstRowModel(device), pins })

  // 4. Max, one click: this thread switches to the strong model mid-thread and new threads start there.
  const browserBefore = await fetchJson(`${baseUrl}/v1/models?thread_id=${threadId}`)
  const max = browserBefore.configurations.find((item) => item.policy === 'max')
  // Until run.done (receipts included) the switch is refused by design (ADR-023); retry like a person.
  await retryUntil(() => device.getByTestId('model-config-max').click(),
    async () => (await parameters()).resolved_model === max.model)
  await device.getByTestId('model-device-resolved').getByText(max.model, { exact: true }).waitFor()
  const policies = await fetchJson(`${baseUrl}/v1/model-policies`)
  expect(policies.policies.chat === 'max', `chat policy is ${policies.policies.chat}`)
  // 5. The thinking level sits beside the model for a model that takes one.
  await retryUntil(() => device.locator('#model-device-effort').selectOption('low'),
    async () => (await parameters()).values['model.effort'] === 'low')
  await waitUntil(async () => (await device.locator('#model-device-effort').inputValue()) === 'low')
  await capture('FL-202-max.png')
  step('Max selected', { configurations: browserBefore.configurations, chat_policy: policies.policies.chat })

  await page.getByTestId('back-to-stage').click()
  await send('In one sentence, what is a memory palace?')
  await settled(600_000)
  const strongChip = await chipText()
  expect(strongChip.includes('low thinking'), `chip lacks the thinking level: ${strongChip}`)
  const spend = await fetchJson(`${baseUrl}/v1/rack/query?resource=spend_table&as_of=now&thread_ids=${threadId}`)
  expect(JSON.stringify(spend).includes(max.model.replace('openrouter:', '')), 'no spend row names the strong model')
  await shot('conversation', 'FL-202-strong.png')
  step('answered on the strong model', { chip: strongChip, model: max.model })

  // 6. FL-106: /model mid-thread, then a table renders from the new model.
  await send(`/model ${commandTarget}`)
  await settled()
  await conversation.getByText(`Model changed from ${max.model} to ${commandTarget}`, { exact: false }).first().waitFor()
  await send('Reply with only a markdown table (not inside a code block) with columns Planet and Order for Mercury and Venus.')
  await settled(600_000)
  await conversation.locator('table').last().waitFor()
  await shot('conversation', 'FL-106.png')
  step('/model then a table', { chip: await chipText() })

  // 7. FL-107: temperature in the device is journaled and the next turn runs with it.
  await conversation.getByTestId('active-model').click()
  await retryUntil(() => device.locator('[id="control-model.temperature"]').fill('0.3'),
    async () => (await parameters()).values['model.temperature'] === 0.3)
  await waitUntil(async () => (await device.locator('[data-parameter-id="model.temperature"] output').textContent()) === '0.3')
  await capture('FL-107.png')
  await page.getByTestId('back-to-stage').click()
  await send('Say TEMP-CHECK and one word.')
  await settled()
  const journaled = (await parameters()).changes.filter((change) => change.parameter_id === 'model.temperature')
  expect(journaled.length > 0, 'temperature change was not journaled')
  step('temperature journaled', { last: journaled.at(-1) })

  // 8. FL-154: the role policies in App settings.
  await page.getByRole('button', { name: /settings/i }).first().click()
  await page.getByText('Agent model policies').first().scrollIntoViewIfNeeded()
  await capture('FL-154.png')
  step('role policies', await fetchJson(`${baseUrl}/v1/model-policies`))
  console.log(`M3MD walk run ${run} PASS`)
} catch (error) {
  receipt.error = String(error?.stack ?? error)
  await page.screenshot({ path: resolve(evidenceDir, 'failure.png') }).catch(() => {})
  console.error(`M3MD walk run ${run} FAIL: ${String(error?.message ?? error).slice(0, 400)}`)
  process.exitCode = 1
} finally {
  // Leave the next run fresh: the starting chat policy, no pin, the thread archived.
  await putJson(`${baseUrl}/v1/model-policies/chat`, { policy: startPolicies.policies.chat }).catch(() => {})
  await putJson(`${baseUrl}/v1/model-pins`, { model: pinTarget, pinned: false }).catch(() => {})
  if (threadId !== null) await fetch(`${baseUrl}/v1/threads/${threadId}/archive`, { method: 'POST' }).catch(() => {})
  receipt.thread_id = threadId
  await writeFile(resolve(evidenceDir, 'walk.json'), `${JSON.stringify(receipt, null, 2)}\n`)
  await context.close()
  await browser.close()
}

function step(name, detail) {
  receipt.steps.push({ at: new Date().toISOString(), name, ...detail })
  console.log(`${name}: ${JSON.stringify(detail).slice(0, 300)}`)
}

function expect(condition, message) {
  if (!condition) throw new Error(message)
}

function row(device, model) {
  return device.locator('li', { has: device.locator(`[data-model="${model}"]`) })
}

async function firstRowModel(device) {
  return device.locator('[data-testid="model-browser-list"] li .model-row__pick').first().getAttribute('data-model')
}

async function chipText() {
  return (await frame('conversation').getByTestId('active-model-detail').textContent()) ?? ''
}

async function parameters() {
  return (await fetchJson(`${baseUrl}/v1/rack/query?resource=parameters&as_of=now&thread_id=${threadId}`)).data
}

async function capture(name) {
  // Hover tips would cover the values being proven; the pointer rests on empty margin.
  await page.mouse.move(4, 600)
  await new Promise((resolveWait) => setTimeout(resolveWait, 400))
  await page.screenshot({ path: resolve(evidenceDir, name) })
}

async function shot(moduleId, name) {
  const element = page.locator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
  await element.scrollIntoViewIfNeeded()
  await page.mouse.move(4, 600)
  await new Promise((resolveWait) => setTimeout(resolveWait, 400))
  await element.screenshot({ path: resolve(evidenceDir, name) })
}

async function send(prompt) {
  const conversation = frame('conversation')
  await waitUntil(async () =>
    await conversation.getByTestId('composer').isEnabled() &&
    await conversation.getByTestId('composer').inputValue() === '')
  answersBefore = await conversation.locator('article[data-role="assistant"]').count()
  await conversation.getByTestId('composer').fill(prompt)
  await conversation.getByTestId('composer').press('Enter')
  try {
    await frame('gate').getByTestId('memory-gate').waitFor({ state: 'visible', timeout: 20_000 })
    await frame('gate').getByTestId('memory-gate-continue').click()
  } catch {
    // Later turns open no first-turn memory check.
  }
}

async function settled(timeoutMs = 300_000) {
  const conversation = frame('conversation')
  // Settled means a new answer exists and nothing is still sending, working or streaming.
  const answers = conversation.locator('article[data-role="assistant"]')
  await waitUntil(async () =>
    await answers.count() > answersBefore &&
    !/Working…|Streaming|Sending/i.test(await conversation.locator('.transcript').innerText()) &&
    await conversation.getByTestId('composer').isEnabled() &&
    await conversation.getByTestId('composer').inputValue() === '' &&
    !(await conversation.getByText('Working…').first().isVisible().catch(() => false)), timeoutMs)
}

function frame(moduleId) {
  return page.frameLocator(`[data-testid="rack-plugin-frame-${moduleId}"]`)
}

async function retryUntil(action, predicate, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    await action()
    try {
      await waitUntil(predicate, 8_000)
      return
    } catch {
      receipt.retries = (receipt.retries ?? 0) + 1
    }
  }
  throw new Error('a control write was still refused after three minutes')
}

async function waitUntil(predicate, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      if (await predicate()) return
    } catch (error) {
      lastError = error
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 250))
  }
  throw lastError ?? new Error('walk condition did not settle')
}

async function fetchJson(url) {
  const response = await fetch(url)
  const payload = await response.json()
  if (!response.ok) throw new Error(`${response.status} from ${url}: ${JSON.stringify(payload)}`)
  return payload
}

async function putJson(url, body) {
  const response = await fetch(url, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(`${response.status} from ${url}`)
  return response.json()
}

function argument(name) {
  const index = args.indexOf(name)
  const value = index < 0 ? undefined : args[index + 1]
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${name} is required`)
  return value
}
