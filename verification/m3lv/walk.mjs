/** M3LV: one fresh run of the charged rows on the real app (FL-126 129 130 132 133 134; F155).
 *   NOCTURNE_HOME=<scratch home> node walk.mjs --base-url <url> --out <run dir> --run <n> --python <venv python> --scripts <dir>
 * A fresh browser and fresh threads each run. The Sheet shows Palace, Farm, Roots and Conversation; the page is recorded
 * with a wall clock (milliseconds) burned in at its bottom-right, outside every module. Every feed change and the moment
 * each module showed it are logged with wall times in run.json, so "within one poll" is measured, not eyeballed. */

import { createRequire } from 'node:module'
import { execFileSync, spawn } from 'node:child_process'
import { mkdir, readdir, rename, rm, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const arg = (name) => { const value = args[args.indexOf(name) + 1]; if (!args.includes(name) || !value) throw new Error(`${name} is required`); return value }
const base = arg('--base-url').replace(/\/$/, ''), out = resolve(arg('--out')), run = arg('--run')
const python = arg('--python'), scripts = resolve(arg('--scripts')), local = args.includes('--local')
const log = { run, base, started: new Date().toISOString(), events: [], checks: {} }
// Every prompt and fact carries this attempt's stamp: a repeated fact is reinforced, not added, and a repeated title is ambiguous.
const stamp = `${run}.${Date.now().toString(36).slice(-5)}`
const now = () => new Date().toISOString()
const note = (source, value) => { log.events.push({ t: now(), source, value }); console.log(now().slice(11, 23), source, JSON.stringify(value).slice(0, 160)) }
const sleep = (ms) => new Promise((done) => setTimeout(done, ms))
await mkdir(resolve(out, 'video-raw'), { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true,
  args: ['--enable-unsafe-webgpu', '--ignore-gpu-blocklist', '--use-angle=metal'] })
const viewport = { width: 1600, height: 1250 }
const main = await browser.newContext({ viewport, recordVideo: { dir: resolve(out, 'video-raw'), size: viewport } })
await main.addInitScript(() => {
  if (window.top !== window) return
  const draw = () => {
    let clock = document.getElementById('m3lv-clock')
    if (!clock && document.body) {
      clock = document.createElement('div'); clock.id = 'm3lv-clock'
      clock.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:2147483647;font:600 20px ui-monospace,monospace;color:#fff;background:#c0106a;padding:3px 8px;pointer-events:none'
      document.body.appendChild(clock)
    }
    if (clock) { const t = new Date(); clock.textContent = `${t.toLocaleTimeString('en-US', { hour12: false })}.${String(t.getMilliseconds()).padStart(3, '0')}` }
    requestAnimationFrame(draw)
  }
  requestAnimationFrame(draw)
})
const videoStart = Date.now()
const page = await main.newPage()
// A debugging build prints M3LVDEBUG traces of every thread and selection change; a release build prints none.
page.on('console', (message) => { if (message.text().includes('M3LVDEBUG')) log.events.push({ t: now(), source: 'trace', value: message.text().slice(10, 260) }) })
const chatContext = await browser.newContext({ viewport: { width: 1400, height: 1000 } })
const chat = await chatContext.newPage()
const frame = (p, id) => p.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
const shot = (name) => page.screenshot({ path: resolve(out, name) })
const text = async (locator) => (await locator.innerText().catch(() => '')).replace(/\s+/g, ' ').trim()

// The feed as the modules see it, read cheaply: trees already held are named by digest (M3HW's known=).
let digests = []
// The walk's own reads retry a dropped connection (ECONNRESET once in a run); the modules' reads are untouched.
async function getJson(url) {
  for (let attempt = 1; ; attempt++) {
    try { return await (await page.request.get(url)).json() } catch (error) { if (attempt === 3) throw error; note('retry', String(error).slice(0, 80)); await sleep(500) }
  }
}
async function feed() {
  const url = `${base}/v1/visualization${digests.length ? `?known=${digests.join(',')}` : ''}`
  const data = await getJson(url)
  digests = data.projects.flatMap((project) => project.digest ? [project.digest] : [])
  return data
}
async function graphNodes() {
  const data = await getJson(`${base}/v1/rack/query?resource=memory_graph&as_of=now`)
  return (data.data?.nodes ?? []).length
}

// A thread left with its gate open covers the stage with the gate; continue it before touching the stage.
async function clearGate(p) {
  for (let i = 0; i < 6; i++) {
    const gate = frame(p, 'gate').getByTestId('memory-gate-continue')
    if (!(await gate.count().catch(() => 0))) return
    await gate.first().click().catch(() => {}); note('gate', 'continued'); await sleep(1500)
  }
}
async function openStage() {
  await page.goto(base, { waitUntil: 'domcontentloaded' })
  await sleep(4000); await clearGate(page)
  await page.getByRole('button', { name: 'Sheet', exact: true }).click()
  await page.getByTestId('stage-layer-create').click()
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  for (const name of ['Palace', 'Farm', 'Roots', 'Conversation']) await page.getByRole('button', { name: `Add ${name}`, exact: true }).click()
  await page.getByRole('button', { name: 'Library', exact: true }).click()
  await frame(page, 'farm').locator('.work-viz__viewport canvas').waitFor({ timeout: 60_000 })
  if (process.env.M3LV_PROJECT) await frame(page, 'farm').getByLabel('Visualized project').selectOption(process.env.M3LV_PROJECT)
  await chat.goto(base, { waitUntil: 'domcontentloaded' })
  await sleep(4000); await clearGate(chat)
  await chat.getByRole('button', { name: 'Sheet', exact: true }).click()
  await frame(chat, 'conversation').locator('#prompt-input').waitFor({ timeout: 60_000 })
  await page.bringToFront()
  await sleep(8000)
}
async function newThread() {
  await continueGate(); await sleep(500)
  const threads = frame(chat, 'threads')
  await threads.getByRole('button', { name: 'New thread' }).first().click(); await sleep(1500)
  const create = threads.getByRole('button', { name: 'Create', exact: true })
  if (await create.count()) await create.first().click()
  await sleep(3000)
}
async function send(prompt) {
  const input = frame(chat, 'conversation').locator('#prompt-input')
  await input.fill(prompt); await input.press('Enter')
}
async function continueGate() {
  const gate = frame(chat, 'gate').getByTestId('memory-gate-continue')
  if (await gate.count().catch(() => 0)) { await gate.first().click().catch(() => {}); note('gate', 'continued') }
  await clearGate(page)
}
// Thread titles are the first prompt cut at 80 characters.
const agentOf = (data, prompt) => data.agents.find((agent) => agent.label.slice(0, 60) === prompt.slice(0, 60))

try {
  await openStage()
  note('stage', 'Palace, Farm, Roots and Conversation on a new Sheet layer')

  const seen = {}
  const watch = async (name, read) => {
    let value; try { value = typeof read === 'function' ? await read() : read } catch (error) { value = `unreadable: ${String(error).slice(0, 60)}` }
    if (JSON.stringify(value) !== JSON.stringify(seen[name])) { seen[name] = value; note(name, value) }
  }
  // --local walks only what needs no Palace (FL-130, FL-132, FL-134): the selection, time order and history scrub
  // read the local recorder; the live segment (a model turn, a /remember, a curator pass) needs the real Palace.
  let second
  if (local) {
    const waiting = (await feed()).agents.filter((agent) => agent.waiting_since !== null).sort((a, b) => Date.parse(b.waiting_since) - Date.parse(a.waiting_since))
    second = waiting.find((agent) => agent.label.startsWith('M3LV run'))?.label ?? waiting[0].label
    note('local', { newestWaiting: second.slice(0, 60) })
    log.checks.live_seconds = [(Date.now() - videoStart) / 1000]
  } else {
    // T1: a thread whose reply waits, so time order has a longest wait of this run to find.
    const first = `M3LV run ${stamp}: reply with exactly: first reply of run ${run}.`
    await newThread(); await send(first)
    // 'waiting' also means an open gate, so the reply waits only once the thread has run after its gate.
    for (let i = 0, ran = false; i < 160; i++) {
      await continueGate(); const state = agentOf(await feed(), first)?.state
      if (state === 'running') ran = true
      if (ran && state === 'waiting') break
      await sleep(1000)
    }
    note('T1', agentOf(await feed(), first) ?? 'missing')

    // LIVE 1 — roots grow and the ant moves: a fresh thread moves to web/src and reads two files.
    const liveStart = Date.now()
    // A new thread starts where the last one stood (T1 shows where): T2 visits docs, reading there so the stop is sampled,
    // then ends in a folder other than its start, so its ant has to walk.
    const start = agentOf(await feed(), first)?.location ?? ''
    const [destination, file] = start.endsWith('web/src') ? ['src/harness', 'visualization.py'] : ['web/src', 'visualization.ts']
    note('T2.plan', { start: start.split('/').slice(-2).join('/'), destination })
    second = `M3LV run ${stamp}: use the move tool to go to the docs folder and list the files there, then use the move tool again to go to the ${destination} folder, read ${file} there with your file tools, then answer in one sentence.`
    await newThread(); await send(second)
    const rowOf = async (label) => text(frame(page, 'farm').locator('details.work-viz__data table tbody tr').filter({ hasText: label.slice(0, 40) }).first())
    for (let i = 0; i < 480; i++) {
      await continueGate()
      const data = await feed(), agent = agentOf(data, second)
      await watch('feed.T2', agent && { state: agent.state, where: agent.location.split('/').slice(-2).join('/'), turns: agent.turns?.length, calls: agent.tool_calls?.length, files: agent.touched_files?.length })
      await watch('roots.readout', await text(frame(page, 'roots').locator('.work-viz__readout strong')) + ' | ' + (await text(frame(page, 'roots').locator('.work-viz__readout span').first())))
      await watch('farm.T2row', agent ? await rowOf(second) : null)
      if (agent?.state === 'waiting' && seen.settled === undefined) seen.settled = Date.now()
      if (seen.settled && Date.now() - seen.settled > 6000) break
      await sleep(250)
    }
    await shot(`FL-126-run${run}.png`); await shot(`FL-129-run${run}.png`)

    // LIVE 2 — memories arrive: a /remember on its own fresh thread.
    const before = await graphNodes()
    note('palace.api', `${before} nodes`)
    // Distinct subjects: the save door refuses a fact too similar to one already held (so a rerun takes the next).
    const facts = ['the violin maker tunes every string with a brass fork', 'the glacier camp keeps its maps in a tin box',
      'the rooftop garden rain barrel is painted teal', 'the night baker proofs rye dough in the cellar',
      'the observatory dome turns on six iron wheels', 'the ferry captain logs the wind at noon',
      'the bell foundry casts its bells in late autumn', 'the archive stores wax cylinders in cedar drawers',
      'the beekeeper marks each queen with a white dot', 'the canal lock opens with a bronze crank']
    await newThread()
    // The watch runs while the save is in flight, so the moment the Palace has the memory is caught.
    let saved = false
    const palaceWatch = (async () => {
      for (let i = 0, settledAt = 0; i < 400; i++) {
        // The Palace is read once a second: the walk must not add load on a shared database instance (F159).
        if (i % 4 === 0) await watch('palace.api', async () => `${await graphNodes()} nodes`)
        await watch('palace.readout', await text(frame(page, 'palace_nebula').locator('.palace-nebula__readouts article').first()))
        if (!settledAt && seen['palace.readout']?.includes(`${before + 1} bodies`)) settledAt = Date.now()
        if ((settledAt && Date.now() - settledAt > 3000) || saved === null) break
        await sleep(250)
      }
    })()
    const reply = async () => (await text(frame(chat, 'conversation').locator('body'))).split('NOCTURNE').at(-1).slice(0, 120)
    for (const fact of facts.slice((Number(run) - 1) * 3)) {
      await send(`/remember In the M3LV walk, ${fact}.`)
      let answer = ''
      for (let i = 0; i < 40 && !/Remembered|Not saved|Already known/.test(answer); i++) { await sleep(500); answer = await reply() }
      note('remember', answer)
      if (answer.includes('Remembered')) { saved = true; break }
    }
    if (!saved) saved = null
    await palaceWatch

    // LIVE 3 — ghosts: memories filed under a single keyword and a fact filed twice give a real curator pass findings.
    const env = { ...process.env }
    execFileSync(python, [resolve(scripts, 'seed_curator.py'), `walk ${stamp}`], { env, stdio: 'inherit' })
    const pass = spawn(python, [resolve(scripts, 'curate.py')], { env, stdio: ['ignore', 'pipe', 'inherit'] })
    let receipt = ''; pass.stdout.on('data', (chunk) => { receipt += chunk })
    let ghosted = false
    for (let i = 0, doneAt = 0; i < 400; i++) {
      const events = (await feed()).progress?.events ?? []
      const last = events.at(-1)
      await watch('feed.progress', last && { phase: last.phase, targets: last.memory_ids.length, ts: last.ts.slice(11, 19) })
      await watch('palace.curator', await text(frame(page, 'palace_nebula').locator('[aria-label="Curator progress"]')))
      if (!ghosted && /\b[1-9]\d* targets/.test(seen['palace.curator'] ?? '')) { ghosted = true; await shot(`FL-133-run${run}.png`) }
      if (pass.exitCode !== null && !doneAt) doneAt = Date.now()
      if (doneAt && Date.now() - doneAt > 4000) break
      await sleep(250)
    }
    note('curator.receipt', receipt.trim())
    if (!ghosted) await shot(`FL-133-run${run}.png`)
    log.checks.live_seconds = [(liveStart - videoStart) / 1000, (Date.now() - videoStart) / 1000]

  }
  // FL-134 — the history scrub: every recorded state renders; a slow read keeps the drawn scene.
  const farm = frame(page, 'farm'), slider = farm.getByLabel('Visualization history')
  const scene = async () => ({ notice: await farm.locator('.work-viz__notice').allInnerTexts(), farmCanvas: await farm.locator('.work-viz__viewport canvas').count(),
    clock: await text(farm.locator('.work-viz__toolbar time').first()), status: await farm.locator('.work-viz__toolbar [role=status]').allInnerTexts(),
    chambers: await text(farm.locator('.work-viz__readout strong')), roots: await text(frame(page, 'roots').locator('.work-viz__readout strong')),
    palace: await text(frame(page, 'palace_nebula').locator('.palace-nebula__readouts article').first()),
    palaceNotice: await frame(page, 'palace_nebula').locator('.palace-nebula__notice').allInnerTexts() })
  const max = Number(await slider.getAttribute('max'))
  log.checks.scrub = []
  for (const [k, index] of [0, Math.floor(max / 2), Math.max(0, max - 3)].entries()) {
    await slider.fill(String(index))
    await sleep(200); const early = await scene()
    await sleep(3000); const settled = await scene()
    await shot(`FL-134-run${run}-${k + 1}.png`)
    log.checks.scrub.push({ index, of: max, early, settled })
    note('scrub', { index, early: early.notice.concat(early.palaceNotice), settled: settled.clock })
  }
  await main.route(/\/v1\/visualization\?as_of=(?!now)/, async (route) => { await sleep(4000); await route.continue() })
  await slider.fill(String(Math.floor(max / 3)))
  await sleep(700); log.checks.slow_read = await scene(); await shot(`FL-134-run${run}-slow.png`)
  await sleep(5000); log.checks.slow_read_after = await scene()
  await main.unroute(/\/v1\/visualization\?as_of=(?!now)/)
  note('scrub.slow', log.checks.slow_read)
  await farm.getByRole('button', { name: 'Live', exact: true }).click(); await sleep(3000)

  // FL-130 — pick an ant in the Farm (a file selected first, so only an ant click selects an agent), switch to Roots.
  const selected = async () => (await farm.locator('tr[data-selected]').allInnerTexts()).map((row) => row.split('\t')[0])
  // Pick an agent from the Farm's table; a click that changed nothing is logged with what lay under the pointer and retried.
  const pickRow = async (prompt) => {
    const button = farm.locator('details.work-viz__data table tbody tr').filter({ hasText: prompt.slice(0, 40) }).getByRole('button').first()
    for (let attempt = 1; attempt <= 3; attempt++) {
      await button.scrollIntoViewIfNeeded()
      const hit = await button.evaluate((element) => { const box = element.getBoundingClientRect(), top = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
        return { onButton: element.contains(top), top: `${top?.tagName}.${top?.className}`.slice(0, 60), y: Math.round(box.y), viewport: innerHeight } })
      await button.click(); await sleep(1500)
      const now = (await selected())[0] ?? null
      note('pick', { prompt: prompt.slice(0, 40), attempt, hit, selected: now?.slice(0, 40) })
      if (now?.startsWith(prompt.slice(0, 40))) return attempt
    }
    return 0
  }
  await farm.getByRole('button', { name: 'Browse folder' }).click()
  await farm.locator('.work-viz__data ul li').filter({ hasText: 'README.md' }).getByRole('button').first().click(); await sleep(1200)
  await farm.getByRole('button', { name: 'Browse folder' }).click(); await sleep(1200)
  const canvas = await farm.locator('.work-viz__viewport canvas').boundingBox()
  // Where each resting ant stands, from the module's own layout and camera (antpos.mjs); click around that point.
  const full = await (await page.request.get(`${base}/v1/visualization`)).text()
  await writeFile(resolve(out, 'feed.tmp.json'), full)
  const ants = JSON.parse(execFileSync('node', ['--experimental-strip-types', resolve(scripts, 'antpos.mjs'), resolve(out, 'feed.tmp.json'),
    String(canvas.width), String(canvas.height), process.env.M3LV_PROJECT ?? ''].filter(Boolean), { encoding: 'utf8' }))
  await rm(resolve(out, 'feed.tmp.json'))
  let picked = null, clicks = 0, target = null
  for (const ant of ants.filter((item) => item.chamber === '.')) {
    for (let dy = -6; dy <= 6 && !picked; dy += 3) for (let dx = -6; dx <= 6 && !picked; dx += 3) {
      await page.mouse.click(canvas.x + ant.x + dx, canvas.y + ant.y + dy); clicks++; await sleep(200)
      // A click that opened a folder is undone, so every click lands on the same layout.
      if (!(await text(farm.locator('.work-viz__toolbar span').filter({ hasText: 'showing' }))).startsWith('. ')) {
        await farm.getByRole('button', { name: 'Up one folder' }).click(); await sleep(1500) }
      const rows = await selected(); if (rows.length) { picked = rows[0]; target = ant }
    }
    if (picked) break
  }
  log.checks.ant = { predicted: ants, target, clicks }
  note('farm.antPick', { picked, clicks })
  if (!picked) { await pickRow(second); picked = (await selected())[0]; note('farm.tablePick', picked ?? 'none') }
  const farmReadout = await text(farm.locator('.work-viz__readout'))
  await farm.getByRole('button', { name: 'Roots', exact: true }).click(); await sleep(3000)
  log.checks.selection = { picked, byAnt: target !== null, antLabel: target?.label ?? null, farmReadout,
    afterSwitch: { rows: await selected(), readout: await text(farm.locator('.work-viz__readout')), rootsModule: await text(frame(page, 'roots').locator('.work-viz__readout')) } }
  await shot(`FL-130-run${run}.png`)
  note('selection', log.checks.selection.afterSwitch.rows)

  // FL-132 — time order: from another thread, the panels move to the longest-waiting reply. A reply stops waiting once
  // its thread is viewed, so the start is any other thread of this walk (the newest waiting one when several wait).
  const agentsNow = (await feed()).agents
  const waiting = agentsNow.filter((agent) => agent.waiting_since !== null)
    .sort((a, b) => Date.parse(a.waiting_since) - Date.parse(b.waiting_since))
  const expected = waiting[0]
  const start = expected?.label.startsWith(second.slice(0, 40)) ? agentsNow.find((agent) => agent.id !== expected.id && agent.label.startsWith('M3LV run'))?.label ?? second : second
  note('time_order.start', { start: start.slice(0, 50), expected: expected?.label.slice(0, 50) })
  log.checks.t2_pick_attempts = await pickRow(start)
  const beforeOrder = { rows: await selected(), conversation: (await text(frame(page, 'conversation').locator('body'))).slice(0, 400) }
  await farm.getByRole('button', { name: 'Time order' }).click()
  const trace = []
  for (let i = 0; i < 16; i++) { await sleep(250); trace.push({ t: now(), rows: await selected() }) }
  const conversation = await text(frame(page, 'conversation').locator('body'))
  log.checks.time_order = { expected: expected && { label: expected.label, waiting_since: expected.waiting_since }, waiting: waiting.map((agent) => [agent.label.slice(0, 50), agent.waiting_since]),
    before: beforeOrder, trace: trace.filter((item, index) => index === 0 || JSON.stringify(item.rows) !== JSON.stringify(trace[index - 1].rows)),
    conversationShowsExpected: expected ? conversation.includes(expected.label.slice(0, 40)) : false }
  await shot(`FL-132-run${run}.png`)
  await farm.getByRole('button', { name: 'Time order' }).click(); await sleep(1000)
  note('time_order', { expected: expected?.label.slice(0, 50), after: trace.at(-1).rows, conversation: log.checks.time_order.conversationShowsExpected })
} finally {
  log.finished = now()
  await chatContext.close()
  await main.close()
  await browser.close()
  const [raw] = (await readdir(resolve(out, 'video-raw'))).filter((file) => file.endsWith('.webm'))
  if (raw && log.checks.live_seconds) {
    const [from, to = (Date.parse(log.finished) - videoStart) / 1000] = log.checks.live_seconds
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', String(Math.max(0, from - 2)), '-t', String(to - from + 4), '-i', resolve(out, 'video-raw', raw),
      '-vf', 'scale=1200:-2,fps=15', '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '40', resolve(out, `live-run${run}.webm`)])
    await rm(resolve(out, 'video-raw'), { recursive: true })
  } else if (raw) await rename(resolve(out, 'video-raw', raw), resolve(out, `raw-run${run}.webm`))
  await writeFile(resolve(out, `run${run}.json`), `${JSON.stringify(log, null, 2)}\n`)
}
