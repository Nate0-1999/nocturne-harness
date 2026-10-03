/** M3MD single-key: M3G's OFF mode (one OpenAI-compatible endpoint, one key, no OpenRouter key).
 * FL-202 there: the browser lists the source's own models, no scores, no policies, no thinking
 * level. FL-158: /model mid-thread, and the next reply's spend row names the new model.
 * Its helpers are copied from walk.mjs. */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const baseUrl = argument('--base-url')
const run = argument('--run')
const project = argument('--project')
const evidenceDir = resolve(argument('--evidence-dir'), `single-key-${run}`)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await context.newPage()
const receipt = { run, base_url: baseUrl, steps: [] }
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
  await send('Name one planet in one word.')
  await settled()
  const first = (await parameters()).resolved_model
  expect(first === 'openai:openai/gpt-4.1-mini', `single key started on ${first}`)

  await conversation.getByTestId('active-model').click()
  const device = frame('model_device')
  await waitUntil(async () => (await device.locator('[data-testid="model-browser-list"] li').count()) > 50)
  const listed = await fetchJson(`${baseUrl}/v1/models?thread_id=${threadId}`)
  expect(listed.configurations.length === 0, 'single-key mode offered token-cost policies')
  expect(listed.models.every((item) => item.model.startsWith('openai:') && item.score === null && !item.reasoning),
    'single-key list is not the source\'s own')
  expect(await device.locator('#model-device-effort').count() === 0, 'a thinking level was offered')
  await capture('FL-202-single-key.png')
  step('the source\'s own list', { models: listed.models.length, chat_policy: listed.chat_policy })

  await page.getByTestId('back-to-stage').click()
  await send('/model openai:openai/gpt-4.1')
  await settled()
  await conversation.getByText('Model changed from openai:openai/gpt-4.1-mini to openai:openai/gpt-4.1', { exact: false }).first().waitFor()
  await send('Name one ocean in one word.')
  await settled()
  const spend = await fetchJson(`${baseUrl}/v1/rack/query?resource=spend_table&as_of=now&thread_ids=${threadId}`)
  const models = spend.data.threads.flatMap((thread) => thread.models.map((item) => item.model))
  expect(models.some((model) => String(model).includes('gpt-4.1') && !String(model).includes('mini')),
    `no spend row names gpt-4.1: ${JSON.stringify(models)}`)
  await shot('conversation', 'FL-158.png')
  step('/model on the single key', { spend_models: models })
  console.log(`M3MD single-key walk run ${run} PASS`)
} catch (error) {
  receipt.error = String(error?.stack ?? error)
  await page.screenshot({ path: resolve(evidenceDir, 'failure.png') }).catch(() => {})
  console.error(`M3MD single-key walk run ${run} FAIL: ${String(error?.message ?? error).slice(0, 400)}`)
  process.exitCode = 1
} finally {
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
