/** M3HW PROOF: four hours on the harness repository with the app open — daemon CPU and memory,
 * the store, the worktrees, and every 3D module's fps recorded every ten minutes, while the app
 * is used like an owner uses it (long reads, remembered facts, an oversized query, a Symphony).
 * usage: node soak.mjs <app-url> <out-dir> [minutes=240] [--idle] */
import { execSync } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const [base, out, minutesArg] = process.argv.slice(2)
const MINUTES = Number(minutesArg ?? 240)
const PORT = new URL(base).port
const PALACE_HOME = process.env.SOAK_PALACE_HOME ?? '/private/tmp/m3hw-verification/home/palaces/test-m3hw'
const PROJECT = process.env.SOAK_PROJECT ?? '/private/tmp/m3hw-verification/project/harness'
const PROFILE = process.env.SOAK_PROFILE ?? '/private/tmp/m3hw-work/soak-profile'
mkdirSync(out, { recursive: true })
const log = (row) => appendFileSync(`${out}/soak.jsonl`, `${JSON.stringify({ at: new Date().toISOString(), ...row })}\n`)
const sh = (command) => execSync(command, { encoding: 'utf8' }).trim()
const seconds = (time) => time.split(':').reduce((total, part) => total * 60 + Number(part), 0)

const context = await chromium.launchPersistentContext(PROFILE, {
  channel: 'chrome', headless: true, viewport: { width: 1600, height: 1000 },
  args: ['--use-angle=metal', '--enable-unsafe-webgpu'],
})
const page = context.pages()[0] ?? await context.newPage()
const frame = async (id) => (await page.locator(`[data-testid="rack-plugin-frame-${id}"]`).elementHandle()).contentFrame()

await page.goto(base, { waitUntil: 'domcontentloaded' })
await page.getByRole('button', { name: 'Library', exact: true }).click()
for (const name of ['Farm', 'Roots', 'Palace']) {
  const add = page.getByRole('button', { name: `Add ${name}`, exact: true })
  if (await add.count() && await add.isEnabled()) await add.click()  // a kept profile has them
}
await page.getByRole('button', { name: 'Library', exact: true }).click()
await page.getByRole('button', { name: 'Sheet', exact: true }).click()
await page.waitForTimeout(8000)

async function send(prompt, { fresh }) {
  if (fresh) {
    const threads = await frame('threads')
    await threads.getByTestId('new-thread').click({ force: true, timeout: 15000 })
    await threads.getByRole('button', { name: /^create$/i }).click({ force: true, timeout: 15000 })
    await page.waitForTimeout(3000)
  }
  const composer = (await frame('conversation')).getByTestId('composer')
  await composer.fill(prompt, { force: true, timeout: 15000 })
  await composer.press('Enter', { timeout: 15000 })
  // A first turn with memories opens the memory check; the owner reads it and continues.
  await page.frameLocator('[data-testid="rack-plugin-frame-gate"]').getByTestId('memory-gate-continue')
    .click({ force: true, timeout: 25000 }).catch(() => {})
}

async function symphony() {
  await send('take this to a symphony', { fresh: true })
  const card = (await frame('conversation')).getByTestId('symphony-deliberation').last()
  await card.waitFor({ state: 'visible', timeout: 180000 })
  const field = (name) => card.getByLabel(name, { exact: true }).first()
  await field('Desired outcome').fill('README.md gains one line under its first heading: "Soak note: measured by M3HW."')
  await field('Why this deserves a Symphony').fill('Two attempts and three judges prove a small edit lands and its worktrees are removed after.')
  await field('Step 1').fill('Add the line "Soak note: measured by M3HW." right after the first heading of README.md')
  await field('Done when').fill('README.md contains that exact line after its first heading and no other file changed')
  const stratagems = card.getByLabel(/Stratagems/)
  if (await stratagems.count()) await stratagems.fill('Direct: edit README.md\nCheck first: read README.md, then edit')
  const judges = card.locator('.symphony-judge')
  for (const [index, seat] of ['motivation', 'implementation', 'performance'].entries()) {
    const judge = judges.nth(index)
    await judge.getByLabel('Rubric', { exact: true }).fill('The README has exactly the requested line after its first heading')
    await judge.getByLabel('Required evidence', { exact: true }).fill('git diff of README.md')
    if (seat === 'performance') await judge.getByLabel('Precalculated metric', { exact: true }).fill('one line added, zero lines removed')
  }
  for (const [label, value] of Object.entries({ Attempts: 2, 'Spend USD': 1.0, Rounds: 2, Depth: 0, 'Children / attempt': 0, Minutes: 45 })) {
    await field(label).fill(String(value))
  }
  await card.locator('.symphony-sign input').check({ force: true })
  await card.getByRole('button', { name: /Sign & run/ }).click({ force: true })
}

const activities = process.argv.includes('--idle') ? [] : [  // --idle: the app open, untouched
  [2, 'long read', () => send('Using the read tool, read each of these files one at a time: src/harness/deploy.py, src/harness/run_loop.py, src/harness/daemon.py, src/harness/conductor.py, src/harness/onboarding.py, web/src/App.tsx. After reading all six, write a 600-word summary of how they fit together.', { fresh: true })],
  [20, 'remember', () => send('/remember The M3HW soak measures Nocturne on the harness repository for four hours with the app open.', { fresh: true })],
  [40, 'oversized query', () => send('Using only the bash tool, run exactly this command: cat uv.lock uv.lock — then tell me in one sentence what the tool returned to you.', { fresh: true })],
  [60, 'symphony', symphony],
  [100, 'long read', () => send('Read src/harness/visualization.py and web/src/WorkVisualization.tsx with the read tool, then explain in 400 words how the Farm gets its tree.', { fresh: true })],
  [120, 'remember', () => send('/remember The visualization store keeps 24 hours of history; trees are stored once and then as changes.', { fresh: true })],
  [150, 'long read', () => send('Using the read tool, read src/harness/symphony_runtime.py and src/harness/supervisor.py, then list every place a worker process is started or stopped.', { fresh: true })],
  [180, 'remember', () => send('/remember Finished Symphony worktrees are removed once their result is kept; SYMPHONY_WORKTREES_KEPT keeps more.', { fresh: true })],
  [210, 'oversized query', () => send('Using only the bash tool, run exactly this command: cat web/package-lock.json web/package-lock.json — then say in one sentence what came back.', { fresh: true })],
]

let previous = null
async function sample(minute, capture) {
  const pid = sh(`lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t`)
  const [time, rss] = sh(`ps -o time=,rss= -p ${pid}`).split(/\s+/)
  const now = Date.now()
  const cpu = previous === null ? null : Math.round(1000 * (seconds(time) - previous.cpu) / ((now - previous.now) / 1000)) / 10
  previous = { cpu: seconds(time), now }
  const main = sh(`pgrep -f -- "--user-data-dir=${PROFILE}" | head -1`)
  const tree = sh('ps -axo pid=,ppid=,rss=').split('\n').map((line) => line.trim().split(/\s+/).map(Number))
  const chrome = tree.filter(([p, parent]) => p === Number(main) || parent === Number(main))
  const store = ['', '-wal'].reduce((n, suffix) => n + (existsSync(`${PALACE_HOME}/visualization.sqlite3${suffix}`) ? statSync(`${PALACE_HOME}/visualization.sqlite3${suffix}`).size : 0), 0)
  const worktrees = existsSync(`${PROJECT}/.nocturne-worktrees`) ? Number(sh(`du -sk ${PROJECT}/.nocturne-worktrees`).split(/\s+/)[0]) * 1024 : 0
  const modules = {}
  for (const id of ['farm', 'roots', 'palace_nebula', 'conversation']) {
    const handle = page.locator(`[data-testid="rack-plugin-frame-${id}"]`)
    await handle.scrollIntoViewIfNeeded({ timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(500)
    modules[id] = await (await frame(id)).evaluate(() => new Promise((resolve) => {
      let n = 0, worst = 0, last = performance.now(); const t0 = last
      const tick = (at) => { n++; worst = Math.max(worst, at - last); last = at
        if (at - t0 < 3000) requestAnimationFrame(tick)
        else resolve({ fps: Math.round(n / ((at - t0) / 1000)), worst_ms: Math.round(worst),
          own_fps: document.body.innerText.match(/(\d+|—) fps/)?.[1] ?? null,
          heap_mb: Math.round((performance.memory?.usedJSHeapSize ?? 0) / 1e6), elements: document.getElementsByTagName('*').length }) }
      requestAnimationFrame(tick)
    })).catch((error) => ({ error: String(error).slice(0, 120) }))
    if (capture && id === 'palace_nebula') await handle.screenshot({ path: `${out}/palace-${String(minute).padStart(3, '0')}.png` }).catch(() => {})
  }
  if (capture) await page.screenshot({ path: `${out}/sheet-${String(minute).padStart(3, '0')}.png` }).catch(() => {})
  // macOS ps counts freed-but-reusable pages as resident; the physical footprint is the memory
  // Activity Monitor reports, so both are recorded.
  const footprint = sh(`vmmap --summary ${pid} | awk '/^Physical footprint:/{print $3}'`)
  const row = { kind: 'sample', minute, daemon_pid: Number(pid), daemon_cpu_percent: cpu, daemon_rss_mb: Math.round(Number(rss) / 1024), daemon_footprint: footprint,
    chrome_rss_mb: Math.round(chrome.reduce((n, row) => n + row[2], 0) / 1024), chrome_processes: chrome.length,
    store_mb: Math.round(store / 1e5) / 10, worktrees_mb: Math.round(worktrees / 1e6), modules }
  log(row)
  return row
}

const started = Date.now()
const done = new Set()
let nextSample = 0
while (true) {
  const minute = (Date.now() - started) / 60000
  for (const [at, label, run] of activities) {
    if (minute >= at && !done.has(at)) {
      done.add(at)
      try { await run(); log({ kind: 'activity', minute: at, label, sent: true }) }
      catch (error) { log({ kind: 'activity', minute: at, label, sent: false, error: String(error).slice(0, 300) }) }
    }
  }
  if (minute >= nextSample) {
    await sample(nextSample, nextSample % 30 === 0).catch((error) => log({ kind: 'sample', minute: nextSample, error: String(error).slice(0, 300) }))
    nextSample += 10
    if (nextSample > MINUTES) break
  }
  await page.waitForTimeout(30000)
}
log({ kind: 'end', minutes: MINUTES })
await context.close()
