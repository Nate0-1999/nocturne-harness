/** PLAN M3GT / D.2 112: one contact sheet per theme — candidates across, both faces down,
 * each a real-app capture in the same framing, labelled with what it varies.
 * usage: node verification/m3gt/contact-sheet.mjs --captures <dir> --theme <id-prefix> --title <text>
 *        --labels "A: …|B: …|C: …|D: …" --out <file.png> [--faces dark,light] */

import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const requireFromWeb = createRequire(new URL('../../web/package.json', import.meta.url))
const { chromium } = requireFromWeb('playwright-core')
const args = process.argv.slice(2)
const argument = (name) => args[args.indexOf(name) + 1]
const captures = resolve(argument('--captures'))
const prefix = argument('--theme')
const labels = argument('--labels').split('|')
const out = resolve(argument('--out'))
const letters = labels.map((label) => label.split(':')[0].trim().toLowerCase())
const faces = (args.includes('--faces') ? argument('--faces') : 'dark,light').split(',')

const cell = (letter, face) => `<figure><img src="${pathToFileURL(`${captures}/${prefix}-${letter}-${face}.png`)}"><figcaption>${letter.toUpperCase()} · ${face}</figcaption></figure>`
const html = `<!doctype html><meta charset="utf-8"><style>
  body { margin: 0; padding: 28px; background: #1b1b1d; color: #eee; font: 15px Inter, sans-serif; }
  h1 { margin: 0 0 6px; font: 600 22px Inter, sans-serif; letter-spacing: 0.08em; }
  ol { display: grid; grid-template-columns: repeat(${labels.length}, 1fr); gap: 18px; margin: 0 0 14px; padding: 0; list-style: none; }
  li { color: #c9c9c9; }
  li b { color: #fff; }
  .grid { display: grid; grid-template-columns: repeat(${labels.length}, 760px); gap: 18px; }
  figure { margin: 0; }
  img { display: block; width: 760px; height: 475px; border: 1px solid #444; }
  figcaption { padding: 4px 0 0; color: #aaa; font: 13px "JetBrains Mono", monospace; text-transform: uppercase; }
</style><h1>${argument('--title')}</h1>
<ol>${labels.map((label) => `<li><b>${label.split(':')[0]}</b>${label.slice(label.indexOf(':'))}</li>`).join('')}</ol>
<div class="grid">${faces.map((face) => letters.map((letter) => cell(letter, face)).join('')).join('')}</div>`

await mkdir(dirname(out), { recursive: true })
const page = out.replace(/\.png$/, '.html')
await writeFile(page, html)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const tab = await browser.newPage({ viewport: { width: 56 + labels.length * 778, height: 400 } })
await tab.goto(pathToFileURL(page).href)
await tab.screenshot({ path: out, fullPage: true })
await browser.close()
console.log(out)
