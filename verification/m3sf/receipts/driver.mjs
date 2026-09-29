// M3SF interactive driver (from M3EX's): holds one browser page; POST /run evaluates an async body
// with (page, frame, shot, clip, sleep) in scope. No walk logic lives here.
import { createRequire } from 'node:module'
import http from 'node:http'
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
const require = createRequire('/private/tmp/m3sf-work/harness/web/package.json')
const { chromium } = require('playwright-core')
const ROOT = '/private/tmp/m3sf-verification'
const CAP = `${ROOT}/captures`, CLIPS = `${ROOT}/clips`
const context = await chromium.launchPersistentContext(`${ROOT}/driver/profile`, { channel: 'chrome', headless: true, args: ['--use-angle=metal', '--enable-gpu'], viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] })
let page = context.pages()[0] ?? await context.newPage()
page.setDefaultTimeout(10_000)
const hook = p => {
  p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') appendFileSync(`${ROOT}/logs/console.log`, `${new Date().toISOString()} ${m.type()} ${m.text()}\n`) })
  p.on('pageerror', e => appendFileSync(`${ROOT}/logs/console.log`, `${new Date().toISOString()} pageerror ${e.message}\n`))
}
hook(page)
context.on('page', p => hook(p))
const frame = id => page.frameLocator(`[data-testid="rack-plugin-frame-${id}"]`)
const sleep = ms => new Promise(r => setTimeout(r, ms))
async function shot(name, note = '', opts = {}) {
  let file = `${CAP}/${name}.png`, i = 2
  while (existsSync(file)) file = `${CAP}/${name}-${i++}.png`
  await page.screenshot({ path: file, ...opts })
  appendFileSync(`${ROOT}/captures.jsonl`, JSON.stringify({ t: new Date().toISOString(), file: file.split('/').pop(), note }) + '\n')
  return file
}
let rec = null
const clip = {
  async start(name) {
    const cdp = await context.newCDPSession(page)
    const dir = `${CLIPS}/${name}-frames`; mkdirSync(dir, { recursive: true })
    rec = { name, cdp, dir, frames: [] }
    cdp.on('Page.screencastFrame', async f => {
      const n = rec.frames.length
      writeFileSync(`${dir}/${String(n).padStart(5, '0')}.jpg`, Buffer.from(f.data, 'base64'))
      rec.frames.push(f.metadata.timestamp)
      try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }) } catch {}
    })
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 70, maxWidth: 1440, maxHeight: 900, everyNthFrame: 1 })
    return dir
  },
  async stop() {
    if (!rec) return null
    await rec.cdp.send('Page.stopScreencast'); await sleep(300)
    const { name, dir, frames } = rec; rec = null
    if (!frames.length) return 'no frames'
    const lines = frames.map((t, i) => `file '${dir}/${String(i).padStart(5, '0')}.jpg'\nduration ${Math.max(0.04, ((frames[i + 1] ?? t + 0.5) - t)).toFixed(3)}`)
    lines.push(`file '${dir}/${String(frames.length - 1).padStart(5, '0')}.jpg'`)
    writeFileSync(`${dir}/list.txt`, lines.join('\n'))
    const out = `${CLIPS}/${name}.mp4`
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', `${dir}/list.txt`, '-vf', 'scale=1280:-2,format=yuv420p', '-r', '15', '-t', '15', out])
    return { out, frames: frames.length, seconds: (frames.at(-1) - frames[0]).toFixed(1) }
  },
}
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
http.createServer(async (req, res) => {
  let body = ''; for await (const c of req) body += c
  let out
  try {
    const fn = new AsyncFunction('page', 'context', 'frame', 'shot', 'clip', 'sleep', 'setPage', body)
    const r = await fn(page, context, frame, shot, clip, sleep, p => { page = p })
    out = { ok: true, result: r }
  } catch (e) { out = { ok: false, error: String(e?.message ?? e).slice(0, 3000) } }
  res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(out, null, 1))
}).listen(9556, '127.0.0.1', () => console.log('driver on 9556'))
