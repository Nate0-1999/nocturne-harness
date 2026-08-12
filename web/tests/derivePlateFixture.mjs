/** Test adapter for PLAN M2UX5: exercise the browser derivation core on decoded RGBA bytes. */

import { readFile } from 'node:fs/promises'

import { deriveColorway } from '../src/platePress.ts'

const [rgbaPath, widthText, heightText, sha256, seamPath] = process.argv.slice(2)
if ([rgbaPath, widthText, heightText, sha256, seamPath].some((value) => value === undefined)) {
  throw new Error('usage: derivePlateFixture.mjs RGBA WIDTH HEIGHT SHA256 SEAM_JSON')
}

const raw = await readFile(rgbaPath)
const seamDocument = JSON.parse(await readFile(seamPath, 'utf8'))
const result = deriveColorway(
  new Uint8ClampedArray(raw.buffer, raw.byteOffset, raw.byteLength),
  Number(widthText),
  Number(heightText),
  sha256,
  seamDocument.colors,
)
process.stdout.write(`${JSON.stringify(result)}\n`)
