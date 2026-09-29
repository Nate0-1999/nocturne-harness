// M3EXF walk: the same scenes against the before app (0.1.40) and the after app, one fresh
// browser profile per scene. usage: node walk.mjs <base-url> <out-dir> [scene ...]
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
const require = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const [url, out, ...only] = process.argv.slice(2)
mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal', '--enable-gpu'] })
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const shot = (page, name, options = {}) => page.screenshot({ path: `${out}/${name}.png`, ...options })
const frame = (page, id) => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
async function open(viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ viewport })
  const page = await context.newPage()
  page.setDefaultTimeout(15_000)
  await page.goto(url)
  await sleep(5000)
  return { context, page }
}
const sheet = async (page) => { await page.getByRole('button', { name: 'Sheet', exact: true }).click(); await sleep(2500) }
const layer = async (page, name) => { await page.getByRole('tab', { name, exact: true }).click(); await sleep(2500) }
const library = async (page, add) => {
  await page.getByTestId('stage-library-toggle').click(); await sleep(800)
  if (add) { await page.getByRole('button', { name: `Add ${add}`, exact: true }).click(); await sleep(2500) }
}
const clip = async (page, id) => page.locator(`[data-testid="rack-plugin-frame-${id}"]`).boundingBox()

const scenes = {
  async 'm3ex-27-stage'() {
    const { context, page } = await open()
    await shot(page, 'm3ex-27-stage-first-look')
    await sheet(page); await page.reload(); await sleep(5000)
    await shot(page, 'm3ex-27-after-reload')
    await context.close()
  },
  async 'm3ex-28-stage'() {
    const { context, page } = await open()
    await page.getByTestId('stage-fit').click(); await sleep(1500)
    await shot(page, 'm3ex-28-whole-stage')
    await library(page, 'Jobs'); await page.keyboard.press('Escape'); await sleep(300)
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    await page.getByTestId('stage-fit').click(); await sleep(2000)
    await shot(page, 'm3ex-28-library-add')
    await context.close()
  },
  async 'm3ex-29-escape'() {
    const { context, page } = await open()
    await page.getByTestId('app-settings-toggle').click(); await sleep(600)
    await page.keyboard.press('Escape'); await sleep(600)
    await shot(page, 'm3ex-29-settings-after-escape')
    await library(page); await page.keyboard.press('Escape'); await sleep(600)
    await shot(page, 'm3ex-29-library-after-escape')
    await context.close()
  },
  async 'm3ex-26-tips'() {
    const { context, page } = await open()
    await sheet(page)
    await page.getByRole('button', { name: 'Stage', exact: true }).hover(); await sleep(400)
    await frame(page, 'threads').locator('[data-thread-id], .thread-row, li button').first().hover(); await sleep(400)
    await frame(page, 'conversation').getByRole('button', { name: /transmit/i }).hover(); await sleep(400)
    await page.mouse.move(720, 890); await sleep(800)
    await shot(page, 'm3ex-26-tips-after-leaving')
    await context.close()
  },
  async 'm3ex-30-slash'() {
    const { context, page } = await open()
    await sheet(page)
    await frame(page, 'conversation').locator('#prompt-input').click()
    await page.keyboard.type('/'); await sleep(600)
    await shot(page, 'm3ex-30-slash', { clip: await clip(page, 'conversation') })
    await page.keyboard.type('re'); await sleep(400)
    await shot(page, 'm3ex-30-slash-re', { clip: await clip(page, 'conversation') })
    await context.close()
  },
  async 'm3ex-32-second-conversation'() {
    const { context, page } = await open()
    await sheet(page); await library(page, 'Conversation')
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    const gears = page.getByTestId('rack-settings-conversation')
    await gears.last().scrollIntoViewIfNeeded(); await gears.last().click(); await sleep(800)
    await shot(page, 'm3ex-32-second-conversation-gear')
    await context.close()
  },
  async 'm3ex-32-follow'() {
    const { context, page } = await open()
    await sheet(page); await library(page, 'Conversation')
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    const gears = page.getByTestId('rack-settings-conversation')
    await gears.last().scrollIntoViewIfNeeded(); await gears.last().click(); await sleep(800)
    const picker = page.getByRole('combobox', { name: 'Conversation thread' }).last()
    const option = await picker.locator('option', { hasText: '/remember' }).first().getAttribute('value')
    await picker.selectOption(option); await sleep(5000)
    await page.keyboard.press('Escape'); await sleep(500)
    const frames = page.locator('[data-testid="rack-plugin-frame-conversation"]')
    await frames.last().scrollIntoViewIfNeeded(); await sleep(1500)
    await shot(page, 'm3ex-32-second-follows-another-thread', { clip: await frames.last().boundingBox() })
    for (const [name, index] of [['first', 0], ['second', 1]]) {
      const text = await frames.nth(index).contentFrame().locator('body').innerText()
      console.log(name, 'module shows:', text.split('\n').find((line) => /remember|List the files/.test(line)))
    }
    await context.close()
  },
  async 'm3ex-33-tips'() {
    const { context, page } = await open()
    await layer(page, 'Graph'); await library(page, 'Palace')
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    await page.locator('.rack-module__remove').last().hover(); await sleep(700)
    await shot(page, 'm3ex-33-module-remove-tip')
    await page.getByTestId('stage-layer-create').click(); await sleep(800)
    await page.locator('.stage-layers button[aria-label*="Layer 1"]').last().hover(); await sleep(700)
    await shot(page, 'm3ex-33-layer-remove-tip', { clip: { x: 0, y: 40, width: 900, height: 160 } })
    await context.close()
  },
  async 'm3ex-34-phone'() {
    const { context, page } = await open({ width: 390, height: 844 })
    await sheet(page)
    await shot(page, 'm3ex-34-phone')
    await context.close()
  },
  async 'm3ex-35-renders'() {
    const { context, page } = await open()
    await sheet(page)
    await frame(page, 'threads').getByRole('button', { name: /remember/i }).first().click().catch(() => {})
    await sleep(3000)
    await shot(page, 'm3ex-35-model-chip', { clip: await clip(page, 'conversation') })
    await page.getByTestId('stage-layer-create').click(); await sleep(800); await library(page)
    await shot(page, 'm3ex-35-library-label', { clip: { x: 960, y: 90, width: 480, height: 280 } })
    await page.keyboard.press('Escape'); await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    await layer(page, 'Graph'); await sleep(4000)
    await shot(page, 'm3ex-35-graph')
    const canvas = frame(page, 'memory_graph').locator('.graph-canvas')
    if (await canvas.count()) {
      const scroll = await canvas.evaluate((node) => { node.scrollTop = node.scrollHeight; return [node.scrollHeight, node.clientHeight] })
      console.log('graph canvas scroll/client height', scroll)
      await sleep(800)
      await shot(page, 'm3ex-35-graph-scrolled')
    }
    await context.close()
  },
  async 'm3ex-36-roots'() {
    const { context, page } = await open()
    await layer(page, 'Graph'); await library(page, 'Roots')
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    await page.getByTestId('stage-fit').click(); await sleep(10000)
    await shot(page, 'm3ex-36-roots-stage')
    await sheet(page); await sleep(8000)
    await shot(page, 'm3ex-36-roots-sheet')
    await context.close()
  },
  async 'm3ex-36-roots-switch'() {
    const { context, page } = await open()
    await layer(page, 'Graph'); await sheet(page); await library(page, 'Roots')
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    await sleep(6000)
    await page.getByRole('button', { name: 'Stage', exact: true }).click(); await sleep(1500)
    await sleep(8000)
    await shot(page, 'm3ex-36-roots-stage-after-sheet')
    await context.close()
  },
  async 'm3ex-16-remember'() {
    const { context, page } = await open()
    await sheet(page)
    await frame(page, 'threads').getByRole('button', { name: 'New thread' }).first().click(); await sleep(1500)
    const create = frame(page, 'threads').getByRole('button', { name: 'Create', exact: true })
    if (await create.count()) { await create.first().click() }
    await sleep(3000)
    const conversation = frame(page, 'conversation')
    await conversation.locator('#prompt-input').fill('/remember Web UI tests live in harness/web/tests and run with npm test; Python tests run with .venv/bin/python -m pytest -q.')
    await conversation.locator('#prompt-input').press('Enter')
    for (let i = 0; i < 90; i += 1) {
      await sleep(2000)
      const text = await conversation.locator('body').innerText()
      if (/Remembered|couldn't|saved nothing|Could not remember|Not saved/.test(text)) break
    }
    await sleep(1500)
    await shot(page, 'm3ex-16-remember-two-facts', { clip: await clip(page, 'conversation') })
    await context.close()
  },
  async 'm3ex-21-ingest'() {
    const { context, page } = await open()
    await sheet(page)
    const ingest = frame(page, 'palace_queue')
    await page.locator('[data-testid="rack-plugin-frame-palace_queue"]').scrollIntoViewIfNeeded()
    // FL-163's walk: a small fictional Markdown document through the drop/choose control.
    await ingest.locator('input[type="file"]').first().setInputFiles('/private/tmp/m3exf-work/walk-facts.md')
    for (let i = 0; i < 180; i += 1) {
      await sleep(5000)
      if (await ingest.locator('.seed-batch .seed-memory').count()) break
    }
    await sleep(2000)
    await ingest.locator('.seed-batch').first().scrollIntoViewIfNeeded().catch(() => {}); await sleep(800)
    await shot(page, 'm3ex-21-ingest-candidates', { clip: await clip(page, 'palace_queue') })
    const approve = ingest.getByTestId('seed-memory-approve')
    if (await approve.count()) {
      const before = await ingest.locator('.seed-batch .seed-memory').count()
      await approve.first().click(); await sleep(6000)
      await ingest.locator('.seed-batch').first().scrollIntoViewIfNeeded().catch(() => {}); await sleep(800)
      await shot(page, 'm3ex-21-ingest-one-approved', { clip: await clip(page, 'palace_queue') })
      console.log('candidates', before, '->', await ingest.locator('.seed-batch .seed-memory').count())
    }
    await ingest.getByRole('button', { name: /Reject batch/i }).first().click().catch(() => {}); await sleep(5000)
    await context.close()
  },
  async 'm3ex-23-job'() {
    const { context, page } = await open()
    await sheet(page); await library(page, 'Jobs')
    await page.getByRole('button', { name: 'Close stage library' }).click().catch(() => {})
    const jobs = frame(page, 'jobs')
    await page.locator('[data-testid="rack-plugin-frame-jobs"]').scrollIntoViewIfNeeded(); await sleep(3000)
    await jobs.getByRole('button', { name: /Run now/i }).first().click(); await sleep(12000)
    await jobs.getByRole('button', { name: /M3EXF walk job/ }).first().click().catch(() => {}); await sleep(1500)
    await shot(page, 'm3ex-23-job-verdict', { clip: await clip(page, 'jobs') })
    await context.close()
  },
  async 'heartbeat'() {
    const { context, page } = await open()
    await sheet(page)
    await frame(page, 'threads').getByRole('button', { name: 'New thread' }).first().click(); await sleep(1500)
    const create = frame(page, 'threads').getByRole('button', { name: 'Create', exact: true })
    if (await create.count()) { await create.first().click() }
    await sleep(3000)
    const conversation = frame(page, 'conversation')
    await conversation.locator('#prompt-input').fill('Reply with exactly: M3EXF heartbeat.')
    await conversation.locator('#prompt-input').press('Enter')
    let gated = false
    for (let i = 0; i < 120; i += 1) {
      await sleep(2000)
      const gate = frame(page, 'gate').getByTestId('memory-gate-continue')
      if (!gated && await gate.count()) { await shot(page, 'heartbeat-gate'); await gate.first().click(); gated = true }
      const text = await conversation.locator('body').innerText()
      if (/M3EXF heartbeat\.\s*$/m.test(text.split('Transmit to Nocturne')[0])) break
    }
    await sleep(1500)
    await shot(page, 'heartbeat-answer', { clip: await clip(page, 'conversation') })
    console.log('gate shown:', gated)
    await context.close()
  },
  async 'fl-081-gate-card'() {
    const { context, page } = await open()
    await sheet(page)
    await frame(page, 'threads').getByRole('button', { name: 'New thread' }).first().click(); await sleep(1500)
    const create = frame(page, 'threads').getByRole('button', { name: 'Create', exact: true })
    if (await create.count()) { await create.first().click() }
    await sleep(3000)
    const conversation = frame(page, 'conversation')
    await conversation.locator('#prompt-input').fill('Where are the fictional steel anchors kept?')
    await conversation.locator('#prompt-input').press('Enter')
    const gate = frame(page, 'gate')
    for (let i = 0; i < 60 && !(await gate.getByTestId('memory-gate-continue').count()); i += 1) await sleep(2000)
    await sleep(1500)
    await shot(page, 'fl-081-gate-cards')
    await gate.locator('.memory-card__title').first().hover(); await sleep(1200)
    await shot(page, 'fl-081-gate-card-hover')
    await gate.getByTestId('memory-gate-continue').first().click(); await sleep(60000)
    await shot(page, 'fl-081-gate-answer', { clip: await clip(page, 'conversation') })
    await context.close()
  },
  async 'taste-06-cards'() {
    const { context, page } = await open()
    await sheet(page)
    const memory = frame(page, 'memory')
    await memory.getByTestId('memory-refresh').click().catch(() => {}); await sleep(3000)
    await page.locator('[data-testid="rack-plugin-frame-memory"]').scrollIntoViewIfNeeded(); await sleep(500)
    await shot(page, 'taste-06-memory-cards', { clip: await clip(page, 'memory') })
    await memory.locator('.memory-card__title').first().hover(); await sleep(900)
    await shot(page, 'taste-06-memory-card-hover')
    await context.close()
  },
  async 'm3ex-18-delete'() {
    const { context, page } = await open()
    await sheet(page)
    const memory = frame(page, 'memory')
    await memory.getByTestId('memory-refresh').click().catch(() => {}); await sleep(3000)
    await page.locator('[data-testid="rack-plugin-frame-memory"]').scrollIntoViewIfNeeded()
    await memory.getByRole('button', { name: 'Permanently delete Commit style' }).click(); await sleep(700)
    await memory.locator('dialog select').selectOption('should_never_have_been_saved'); await sleep(300)
    await shot(page, 'm3ex-18-delete-dialog', { clip: await clip(page, 'memory') })
    await memory.getByRole('button', { name: 'Yes', exact: true }).click(); await sleep(3000)
    await layer(page, 'Graph'); await sleep(5000)
    const graph = frame(page, 'memory_graph')
    await graph.locator('g.graph-node:has(title:text-is("Commit style"))').click(); await sleep(1500)
    await shot(page, 'm3ex-18-graph-deleted-selected')
    const restore = graph.getByTestId('memory-restore')
    if (await restore.count()) {
      await restore.click(); await sleep(7000)
      await shot(page, 'm3ex-18-graph-after-restore')
    }
    await context.close()
  },
}
for (const [name, scene] of Object.entries(scenes)) {
  if (only.length && !only.includes(name)) continue
  try { await scene(); console.log('ok', name) } catch (error) { console.log('FAIL', name, String(error.message).split('\n')[0]) }
}
await browser.close()
