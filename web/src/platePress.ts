/** Deterministic, data-only theme derivation for PLAN M2UX5 / SPEC D.2 107-114. */

export const COLORWAY_STORAGE_KEY = 'nocturne.colorways.v1'
export const COLORWAY_SCHEMA_VERSION = 1
const K = 12
const SEED = 40
const MAX_IMAGE_BYTES = 12 * 1024 * 1024
const MAX_SAMPLE_EDGE = 512

type Rgb = readonly [number, number, number]
type Lab = readonly [number, number, number]

export interface PlateCluster {
  area_share_percent: number
  hex: string
  oklch: { l: number; c: number; h: number }
}

export interface PressedColorway {
  schema_version: 1
  id: `pressed-${string}`
  label: string
  sha256: string
  image: { width: number; height: number }
  kmeans: { color_space: 'OKLab'; k: number; seed: number }
  clusters: PlateCluster[]
  accent_passes: {
    earned: { hex: string; area_share_percent: number; h: number }
    specular: { base: string; peak: string; area_share_percent: number }
  }
  chrome_percentile_ramp: Array<{ percentile: number; l: number; hex: string }>
  roles: Record<string, string>
  contrast_repairs: Array<{ pair: string; raw: string; worn: string }>
  validation: { checks: Record<string, boolean>; passed: boolean }
  tokens: Record<string, string>
}

export interface PlatePressFailure {
  ok: false
  message: string
}

export interface PlatePressSuccess {
  ok: true
  colorway: PressedColorway
}

export type PlatePressResult = PlatePressFailure | PlatePressSuccess

export interface SeamColorEntry {
  variable: string
  neo_noir: string
  seraph_dressed: string
  gold_lines: string
}

function linear(channel: number): number {
  const value = channel / 255
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
}

function gamma(value: number): number {
  const clipped = Math.min(1, Math.max(0, value))
  const srgb = clipped <= 0.0031308
    ? 12.92 * clipped
    : 1.055 * clipped ** (1 / 2.4) - 0.055
  return Math.round(srgb * 255)
}

export function rgbToOklab(rgb: Rgb): Lab {
  const [red, green, blue] = rgb.map(linear)
  const l = 0.4122214708 * red! + 0.5363325363 * green! + 0.0514459929 * blue!
  const m = 0.2119034982 * red! + 0.6806995453 * green! + 0.1073969566 * blue!
  const s = 0.0883024619 * red! + 0.2817188376 * green! + 0.6299787005 * blue!
  const lr = Math.cbrt(l)
  const mr = Math.cbrt(m)
  const sr = Math.cbrt(s)
  return [
    0.2104542553 * lr + 0.793617785 * mr - 0.0040720468 * sr,
    1.9779984951 * lr - 2.428592205 * mr + 0.4505937099 * sr,
    0.0259040371 * lr + 0.782771766 * mr - 0.808675766 * sr,
  ]
}

function oklabToRgb(lab: Lab): Rgb {
  const [lightness, a, b] = lab
  const lr = lightness + 0.3963377774 * a + 0.2158037573 * b
  const mr = lightness - 0.1055613458 * a - 0.0638541728 * b
  const sr = lightness - 0.0894841775 * a - 1.291485548 * b
  const l = lr ** 3
  const m = mr ** 3
  const s = sr ** 3
  return [
    gamma(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    gamma(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    gamma(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ]
}

function hex(rgb: Rgb): string {
  return `#${rgb.map((value) => value.toString(16).padStart(2, '0')).join('')}`
}

function parseHex(value: string): Rgb | null {
  const match = /^#([0-9a-f]{6})$/i.exec(value.trim())
  if (match === null) return null
  const bytes = match[1]!
  return [
    Number.parseInt(bytes.slice(0, 2), 16),
    Number.parseInt(bytes.slice(2, 4), 16),
    Number.parseInt(bytes.slice(4, 6), 16),
  ]
}

function distance(left: Lab, right: Lab): number {
  return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2 + (left[2] - right[2]) ** 2
}

function chroma(lab: Lab): number {
  return Math.hypot(lab[1], lab[2])
}

function hue(lab: Lab): number {
  return (Math.atan2(lab[2], lab[1]) * 180 / Math.PI + 360) % 360
}

function hueDistance(left: number, right: number): number {
  const delta = Math.abs(left - right) % 360
  return Math.min(delta, 360 - delta)
}

/** CPython's integer-seeded MT19937, keeping M2UX4's pinned seed meaningful in-product. */
class PythonRandom {
  private readonly state = new Uint32Array(624)
  private index = 624

  constructor(seed: number) {
    this.init(19650218)
    this.initByArray([seed >>> 0])
  }

  private init(seed: number): void {
    this.state[0] = seed >>> 0
    for (let index = 1; index < 624; index += 1) {
      const previous = this.state[index - 1]!
      this.state[index] = (Math.imul(previous ^ (previous >>> 30), 1812433253) + index) >>> 0
    }
  }

  private initByArray(key: readonly number[]): void {
    let stateIndex = 1
    let keyIndex = 0
    for (let remaining = Math.max(624, key.length); remaining > 0; remaining -= 1) {
      const previous = this.state[stateIndex - 1]!
      this.state[stateIndex] = (
        (this.state[stateIndex]! ^ Math.imul(previous ^ (previous >>> 30), 1664525)) +
        key[keyIndex]! + keyIndex
      ) >>> 0
      stateIndex += 1
      keyIndex += 1
      if (stateIndex >= 624) {
        this.state[0] = this.state[623]!
        stateIndex = 1
      }
      if (keyIndex >= key.length) keyIndex = 0
    }
    for (let remaining = 623; remaining > 0; remaining -= 1) {
      const previous = this.state[stateIndex - 1]!
      this.state[stateIndex] = (
        (this.state[stateIndex]! ^ Math.imul(previous ^ (previous >>> 30), 1566083941)) - stateIndex
      ) >>> 0
      stateIndex += 1
      if (stateIndex >= 624) {
        this.state[0] = this.state[623]!
        stateIndex = 1
      }
    }
    this.state[0] = 0x80000000
  }

  private int32(): number {
    if (this.index >= 624) {
      for (let index = 0; index < 624; index += 1) {
        const value = (this.state[index]! & 0x80000000) |
          (this.state[(index + 1) % 624]! & 0x7fffffff)
        let next = this.state[(index + 397) % 624]! ^ (value >>> 1)
        if ((value & 1) !== 0) next ^= 0x9908b0df
        this.state[index] = next >>> 0
      }
      this.index = 0
    }
    let value = this.state[this.index++]!
    value ^= value >>> 11
    value ^= (value << 7) & 0x9d2c5680
    value ^= (value << 15) & 0xefc60000
    value ^= value >>> 18
    return value >>> 0
  }

  random(): number {
    const high = this.int32() >>> 5
    const low = this.int32() >>> 6
    return (high * 67108864 + low) / 9007199254740992
  }
}

function weightedPick(weights: readonly number[], random: PythonRandom): number {
  const needle = random.random() * weights.reduce((total, value) => total + value, 0)
  let running = 0
  for (let index = 0; index < weights.length; index += 1) {
    running += weights[index]!
    if (running >= needle) return index
  }
  return weights.length - 1
}

export function extractPlateClusters(pixels: Uint8ClampedArray): PlateCluster[] {
  const histogram = new Map<number, number>()
  for (let index = 0; index < pixels.length; index += 4) {
    if (pixels[index + 3] === 0) continue
    const key = (pixels[index]! << 16) | (pixels[index + 1]! << 8) | pixels[index + 2]!
    histogram.set(key, (histogram.get(key) ?? 0) + 1)
  }
  const colors = [...histogram.keys()].sort((left, right) => left - right)
  if (colors.length < K) return []
  const rgbs: Rgb[] = colors.map((value) => [value >>> 16, (value >>> 8) & 255, value & 255])
  const labs = rgbs.map(rgbToOklab)
  const counts = colors.map((value) => histogram.get(value)!)
  const random = new PythonRandom(SEED)
  let centers: Lab[] = [labs[weightedPick(counts, random)]!]
  while (centers.length < K) {
    const weights = labs.map((lab, index) => counts[index]! * Math.min(
      ...centers.map((center) => distance(lab, center)),
    ))
    centers.push(labs[weightedPick(weights, random)]!)
  }
  let assignments = Array.from({ length: colors.length }, () => -1)
  for (let iteration = 0; iteration < 40; iteration += 1) {
    const next = labs.map((lab) => {
      let winner = 0
      let best = distance(lab, centers[0]!)
      for (let center = 1; center < K; center += 1) {
        const candidate = distance(lab, centers[center]!)
        if (candidate < best) {
          winner = center
          best = candidate
        }
      }
      return winner
    })
    if (next.every((value, index) => value === assignments[index])) break
    assignments = next
    const totals = Array.from({ length: K }, () => [0, 0, 0, 0])
    labs.forEach((lab, index) => {
      const target = totals[assignments[index]!]!
      const count = counts[index]!
      target[0]! += lab[0] * count
      target[1]! += lab[1] * count
      target[2]! += lab[2] * count
      target[3]! += count
    })
    centers = totals.map((total, index) => total[3] === 0
      ? centers[index]!
      : [total[0]! / total[3]!, total[1]! / total[3]!, total[2]! / total[3]!] as Lab)
  }
  const clusterCounts = Array.from({ length: K }, () => 0)
  assignments.forEach((assignment, index) => {
    clusterCounts[assignment]! += counts[index]!
  })
  const total = clusterCounts.reduce((sum, value) => sum + value, 0)
  return centers.map((center, index) => ({
    area_share_percent: Number((clusterCounts[index]! * 100 / total).toFixed(6)),
    hex: hex(oklabToRgb(center)),
    oklch: {
      l: Number(center[0].toFixed(6)),
      c: Number(chroma(center).toFixed(6)),
      h: Number(hue(center).toFixed(3)),
    },
  })).sort((left, right) => (
    right.area_share_percent - left.area_share_percent || left.hex.localeCompare(right.hex)
  ))
}

function luminance(value: string): number {
  const parsed = parseHex(value)
  if (parsed === null) return 0
  const [red, green, blue] = parsed.map((channel) => linear(channel) as number)
  return 0.2126 * red! + 0.7152 * green! + 0.0722 * blue!
}

function contrast(left: string, right: string): number {
  const values = [luminance(left), luminance(right)].sort((a, b) => b - a)
  return (values[0]! + 0.05) / (values[1]! + 0.05)
}

function repairContrast(raw: string, ground: string, floor: number): string {
  if (contrast(raw, ground) >= floor) return raw
  const parsed = parseHex(raw)
  if (parsed === null) return raw
  const source = rgbToOklab(parsed)
  const toward = luminance(ground) < 0.5 ? 1 : 0
  let low = Math.min(source[0], toward)
  let high = Math.max(source[0], toward)
  let best = raw
  for (let iteration = 0; iteration < 28; iteration += 1) {
    const lightness = (low + high) / 2
    const candidate = hex(oklabToRgb([lightness, source[1], source[2]]))
    if (contrast(candidate, ground) >= floor) {
      best = candidate
      if (toward === 1) high = lightness
      else low = lightness
    } else if (toward === 1) low = lightness
    else high = lightness
  }
  return best
}

function percentile(sorted: readonly number[], value: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * value))]!
}

function chromeRamp(pixels: Uint8ClampedArray): Array<{ percentile: number; l: number; hex: string }> {
  const lowChroma: Array<{ l: number; rgb: Rgb }> = []
  for (let index = 0; index < pixels.length; index += 4) {
    if (pixels[index + 3] === 0) continue
    const rgb: Rgb = [pixels[index]!, pixels[index + 1]!, pixels[index + 2]!]
    const lab = rgbToOklab(rgb)
    if (chroma(lab) < 0.045) lowChroma.push({ l: lab[0], rgb })
  }
  lowChroma.sort((left, right) => left.l - right.l)
  if (lowChroma.length < 64) return []
  return [2, 50, 70, 85, 93, 97, 99, 99.8].map((point) => {
    const l = percentile(lowChroma.map((entry) => entry.l), point / 100)
    const nearest = lowChroma.reduce((winner, entry) => (
      Math.abs(entry.l - l) < Math.abs(winner.l - l) ? entry : winner
    ))
    return { percentile: point, l: Number(l.toFixed(6)), hex: hex(nearest.rgb) }
  })
}

function rgbDistance(left: string, right: string): number {
  const a = parseHex(left)!
  const b = parseHex(right)!
  return Math.sqrt(a.reduce((sum, value, index) => sum + ((value - b[index]!) / 255) ** 2, 0))
}

function deuteranopia(value: string): readonly number[] {
  const [red, green, blue] = parseHex(value)!.map((channel) => channel / 255)
  return [0.625 * red! + 0.375 * green!, 0.7 * red! + 0.3 * green!, blue!]
}

function tupleDistance(left: readonly number[], right: readonly number[]): number {
  return Math.sqrt(left.reduce((sum, value, index) => sum + (value - right[index]!) ** 2, 0))
}

function parseCssColor(value: string): { rgb: Rgb; alpha: number } | null {
  const direct = parseHex(value)
  if (direct !== null) return { rgb: direct, alpha: 1 }
  const numbers = value.match(/[\d.]+/g)?.map(Number)
  if (numbers === undefined || numbers.length < 3) return null
  let alpha = numbers[3] ?? 1
  if (value.includes('%') && numbers.length >= 4) alpha /= 100
  return { rgb: [numbers[0]!, numbers[1]!, numbers[2]!], alpha }
}

function cssColor(rgb: Rgb, alpha: number): string {
  return alpha >= 0.999
    ? hex(rgb)
    : `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${Number(alpha.toFixed(4))})`
}

function buildTokens(roles: Record<string, string>, ramp: PressedColorway['chrome_percentile_ramp'], seam: readonly SeamColorEntry[]): Record<string, string> {
  const anchorNames = [
    'ground', 'surface_deep', 'surface', 'surface_raised', 'ink', 'muted', 'dim',
    'accent', 'accent_strong', 'earned', 'danger',
  ]
  const seraphAnchors: Record<string, string> = {
    ground: '#05060f', surface_deep: '#0a0d1a', surface: '#0d1226',
    surface_raised: '#141d3a', ink: '#eef4fb', muted: '#9fb0c9', dim: '#6b7a99',
    accent: '#5d8cf2', accent_strong: '#a5c4ff', earned: '#db9969', danger: '#d94048',
  }
  const tokens: Record<string, string> = {}
  for (const entry of seam) {
    if (entry.neo_noir === entry.seraph_dressed && entry.neo_noir === entry.gold_lines) {
      tokens[entry.variable] = entry.seraph_dressed
      continue
    }
    const parsed = parseCssColor(entry.seraph_dressed)
    if (parsed === null) continue
    const source = rgbToOklab(parsed.rgb)
    const role = anchorNames.reduce((winner, name) => {
      const winnerLab = rgbToOklab(parseHex(seraphAnchors[winner]!)!)
      const candidateLab = rgbToOklab(parseHex(seraphAnchors[name]!)!)
      return distance(source, candidateLab) < distance(source, winnerLab) ? name : winner
    })
    tokens[entry.variable] = cssColor(parseHex(roles[role]!)!, parsed.alpha)
  }
  const stops = ramp.map((entry) => entry.hex)
  Object.assign(tokens, {
    '--plate-night': roles.ground,
    '--plate-night-deep': roles.surface_deep,
    '--plate-cobalt': roles.surface,
    '--plate-cobalt-day': roles.surface_raised,
    '--plate-horizon': roles.earned,
    '--plate-horizon-deep': roles.surface_deep,
    '--plate-chrome-seam': stops[0],
    '--plate-chrome-dark': stops[1],
    '--plate-chrome-transition': stops[2],
    '--plate-chrome-mid': stops[3],
    '--plate-chrome-bright': stops[5],
    '--plate-chrome-blaze': stops[6],
    '--plate-chrome-peak': stops[7],
    '--plate-gold-base': roles.earned,
    '--plate-gold-peak': roles.earned,
    '--plate-iris': roles.accent,
    '--plate-coral': roles.danger,
    '--plate-coral-peak': roles.danger,
    '--theme-sky-wash': `linear-gradient(to bottom, ${roles.ground}, ${roles.surface_deep} 34%, ${roles.surface} 72%, ${roles.surface_raised} 90%, ${roles.earned} 100%)`,
    '--theme-rim': `linear-gradient(135deg, ${stops[7]} 0 7%, ${stops[1]} 7% 43%, ${stops[6]} 43% 49%, ${stops[0]} 49% 78%, ${stops[7]} 78% 83%, ${stops[1]} 83% 100%)`,
    '--theme-rim-hover': `linear-gradient(135deg, ${stops[7]} 0 12%, ${stops[0]} 12% 38%, ${stops[6]} 38% 52%, ${stops[1]} 52% 72%, ${stops[7]} 72% 88%, ${stops[0]} 88% 100%)`,
    '--theme-horizon': roles.earned,
  })
  return tokens
}

interface ChromaOutlier {
  hex: string
  area_share_percent: number
  h: number
}

function rareHighChroma(
  pixels: Uint8ClampedArray,
  excluded: readonly string[],
): ChromaOutlier[] {
  const bins = new Map<number, { count: number; red: number; green: number; blue: number }>()
  let opaque = 0
  for (let index = 0; index < pixels.length; index += 4) {
    if (pixels[index + 3] === 0) continue
    opaque += 1
    const rgb: Rgb = [pixels[index]!, pixels[index + 1]!, pixels[index + 2]!]
    const lab = rgbToOklab(rgb)
    if (chroma(lab) < 0.07 || lab[0] < 0.35) continue
    const bin = Math.floor(hue(lab) / 15)
    const current = bins.get(bin) ?? { count: 0, red: 0, green: 0, blue: 0 }
    current.count += 1
    current.red += rgb[0]
    current.green += rgb[1]
    current.blue += rgb[2]
    bins.set(bin, current)
  }
  const minimum = Math.max(4, Math.floor(opaque * 0.0002))
  return [...bins.entries()].filter(([, value]) => value.count >= minimum)
    .map(([bin, value]) => ({
      ...value,
      h: bin * 15 + 7.5,
      hex: hex([
        Math.round(value.red / value.count),
        Math.round(value.green / value.count),
        Math.round(value.blue / value.count),
      ]),
    }))
    // An earned outlier must be a third identity, not sparse noise from accent or danger.
    .filter((candidate) => excluded.every((color) => {
      const candidateHue = candidate.h
      const excludedHue = hue(rgbToOklab(parseHex(color)!))
      return hueDistance(candidateHue, excludedHue) >= 35 && rgbDistance(candidate.hex, color) >= 0.2
    }))
    .sort((left, right) => left.count - right.count || left.h - right.h)
    .map((candidate) => ({
      hex: candidate.hex,
      area_share_percent: Number((candidate.count * 100 / opaque).toFixed(6)),
      h: Number(candidate.h.toFixed(3)),
    }))
}

function roleAssignment(pixels: Uint8ClampedArray, clusters: readonly PlateCluster[]): {
  roles: Record<string, string>
  repairs: PressedColorway['contrast_repairs']
  earned: ChromaOutlier
} | null {
  const viable = clusters.filter((cluster) => cluster.area_share_percent >= 0.25)
  if (viable.length < 6 || Math.max(...viable.map((cluster) => cluster.oklch.c)) < 0.045) return null
  const byLight = [...viable].sort((left, right) => left.oklch.l - right.oklch.l)
  const ground = byLight[0]!.hex
  const rawInk = byLight.at(-1)!.hex
  const rawMuted = byLight[Math.max(1, Math.floor(byLight.length * 0.72))]!.hex
  const danger = [...viable].filter((cluster) => cluster.oklch.c >= 0.04)
    .sort((left, right) => hueDistance(left.oklch.h, 25) - hueDistance(right.oklch.h, 25))[0]!
  const accent = [...viable].filter((cluster) => (
    cluster.hex !== danger.hex && rgbDistance(cluster.hex, danger.hex) >= 0.2 &&
    tupleDistance(deuteranopia(cluster.hex), deuteranopia(danger.hex)) >= 0.1
  )).sort((left, right) => right.oklch.c - left.oklch.c)[0]
  if (accent === undefined) return null
  const rareAccents = rareHighChroma(pixels, [accent.hex, danger.hex])
  const earnedPool = [...viable].filter((cluster) => (
    cluster.hex !== accent.hex && cluster.hex !== danger.hex && cluster.oklch.c >= 0.04 &&
    rgbDistance(cluster.hex, accent.hex) >= 0.2 && rgbDistance(cluster.hex, danger.hex) >= 0.2
  )).sort((left, right) => left.area_share_percent - right.area_share_percent)
  const earnedCandidates = [
    ...rareAccents,
    ...earnedPool.map((cluster) => ({
      hex: cluster.hex,
      area_share_percent: cluster.area_share_percent,
      h: cluster.oklch.h,
    })),
  ]
  const earned = earnedCandidates.find((candidate) => {
    const worn = repairContrast(candidate.hex, ground, 3)
    return [accent.hex, danger.hex, rawInk].every((color) => (
      rgbDistance(worn, color) >= 0.2 &&
      tupleDistance(deuteranopia(worn), deuteranopia(color)) >= 0.1
    ))
  }) ?? null
  if (earned === null) return null
  const earnedRaw = earned.hex
  const ink = repairContrast(rawInk, ground, 7)
  const muted = repairContrast(rawMuted, ground, 4.5)
  const accentWorn = repairContrast(accent.hex, ground, 3)
  const dangerWorn = repairContrast(danger.hex, ground, 3)
  const earnedWorn = repairContrast(earnedRaw, ground, 3)
  const roles = {
    ground,
    surface_deep: byLight[1]!.hex,
    surface: byLight[2]!.hex,
    surface_raised: byLight[3]!.hex,
    ink,
    muted,
    dim: byLight[Math.max(1, Math.floor(byLight.length * 0.55))]!.hex,
    accent: accentWorn,
    accent_strong: repairContrast(accent.hex, ground, 4.5),
    earned: earnedWorn,
    danger: dangerWorn,
  }
  const repairs = [
    { pair: 'ink_on_ground', raw: rawInk, worn: ink },
    { pair: 'muted_on_ground', raw: rawMuted, worn: muted },
    { pair: 'accent_on_ground', raw: accent.hex, worn: accentWorn },
    { pair: 'danger_on_ground', raw: danger.hex, worn: dangerWorn },
    { pair: 'earned_on_ground', raw: earnedRaw, worn: earnedWorn },
  ].filter((repair) => repair.raw !== repair.worn)
  return { roles, repairs, earned }
}

function specularPass(
  pixels: Uint8ClampedArray,
  ramp: PressedColorway['chrome_percentile_ramp'],
): PressedColorway['accent_passes']['specular'] {
  const peak = ramp.at(-1)!
  let opaque = 0
  let specular = 0
  for (let index = 0; index < pixels.length; index += 4) {
    if (pixels[index + 3] === 0) continue
    opaque += 1
    const lab = rgbToOklab([pixels[index]!, pixels[index + 1]!, pixels[index + 2]!])
    if (chroma(lab) < 0.045 && lab[0] >= peak.l) specular += 1
  }
  return {
    base: ramp[4]!.hex,
    peak: peak.hex,
    area_share_percent: Number((specular * 100 / opaque).toFixed(6)),
  }
}

function validateRoles(roles: Record<string, string>): PressedColorway['validation'] {
  const fleet = [roles.accent!, roles.earned!, roles.danger!, roles.ink!]
  const pairs = fleet.flatMap((left, index) => fleet.slice(index + 1).map((right) => [left, right] as const))
  const checks = {
    'ink / ground contrast': contrast(roles.ink!, roles.ground!) >= 7,
    'muted / ground contrast': contrast(roles.muted!, roles.ground!) >= 4.5,
    'fleet / ground contrast': fleet.every((color) => contrast(color, roles.ground!) >= 3),
    'fleet pair separation': pairs.every(([left, right]) => rgbDistance(left, right) >= 0.2),
    'deuteranopia separation': pairs.every(([left, right]) => (
      tupleDistance(deuteranopia(left), deuteranopia(right)) >= 0.1
    )),
    'one danger color': contrast(roles.danger!, roles.ground!) >= 3,
  }
  return { checks, passed: Object.values(checks).every(Boolean) }
}

function failingVisualPair(roles: Record<string, string>): string {
  const fleet = ['accent', 'earned', 'danger', 'ink'] as const
  for (let index = 0; index < fleet.length; index += 1) {
    for (const right of fleet.slice(index + 1)) {
      const left = fleet[index]!
      if (
        rgbDistance(roles[left]!, roles[right]!) < 0.2 ||
        tupleDistance(deuteranopia(roles[left]!), deuteranopia(roles[right]!)) < 0.1
      ) return `${left} / ${right}`
    }
  }
  if (contrast(roles.ink!, roles.ground!) < 7) return 'ink / ground'
  if (contrast(roles.muted!, roles.ground!) < 4.5) return 'muted / ground'
  return 'palette roles'
}

export function deriveColorway(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  sha256: string,
  seam: readonly SeamColorEntry[],
): PlatePressResult {
  const clusters = extractPlateClusters(pixels)
  const assigned = roleAssignment(pixels, clusters)
  const ramp = chromeRamp(pixels)
  if (assigned === null) {
    return { ok: false, message: 'This plate has no distinct accent / ground pair. Try an image with a wider range of color.' }
  }
  if (ramp.length !== 8 || ramp[7]!.l < 0.9) {
    return { ok: false, message: 'This plate has no chrome dark / bright pair. Try an image with both deep shadow and a clear highlight.' }
  }
  const validation = validateRoles(assigned.roles)
  if (!validation.passed) {
    return { ok: false, message: `This plate cannot keep ${failingVisualPair(assigned.roles)} readable. Try an image with clearer color separation.` }
  }
  const id = `pressed-${sha256.slice(0, 16)}` as const
  return {
    ok: true,
    colorway: {
      schema_version: 1,
      id,
      label: `PLATE ${sha256.slice(0, 8).toUpperCase()}`,
      sha256,
      image: { width, height },
      kmeans: { color_space: 'OKLab', k: K, seed: SEED },
      clusters,
      accent_passes: {
        earned: assigned.earned,
        specular: specularPass(pixels, ramp),
      },
      chrome_percentile_ramp: ramp,
      roles: assigned.roles,
      contrast_repairs: assigned.repairs,
      validation,
      tokens: buildTokens(assigned.roles, ramp, seam),
    },
  }
}

export async function pressImage(file: File, seam: readonly SeamColorEntry[]): Promise<PlatePressResult> {
  if (file.size === 0 || file.size > MAX_IMAGE_BYTES || !['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    return { ok: false, message: 'Choose one PNG, JPEG, or WebP image smaller than 12 MB.' }
  }
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    return { ok: false, message: 'This image could not be read. Try a PNG, JPEG, or WebP file.' }
  }
  try {
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, MAX_SAMPLE_EDGE / Math.max(bitmap.width, bitmap.height))
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (context === null) return { ok: false, message: 'This browser could not inspect the plate.' }
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    const sha256 = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('')
    return deriveColorway(pixels, canvas.width, canvas.height, sha256, seam)
  } finally {
    bitmap.close()
  }
}

function isColorway(value: unknown): value is PressedColorway {
  if (typeof value !== 'object' || value === null) return false
  const item = value as Partial<PressedColorway>
  return item.schema_version === 1 && typeof item.id === 'string' && /^pressed-[0-9a-f]{16}$/.test(item.id) &&
    typeof item.sha256 === 'string' && /^[0-9a-f]{64}$/.test(item.sha256) &&
    typeof item.label === 'string' && typeof item.tokens === 'object' && item.tokens !== null &&
    Object.entries(item.tokens).every(([name, token]) => (
      /^--(?:seam|plate|theme)-[a-z0-9-]+$/.test(name) &&
      typeof token === 'string' && token.length <= 512 &&
      !/[;{}'"\\]|url\s*\(|var\s*\(/i.test(token) &&
      /^(?:#[0-9a-f]{6}|rgba?\([0-9., %]+\)|linear-gradient\((?:to bottom|135deg), [#0-9a-f (),.%]+\))$/i.test(token)
    ))
}

export function loadColorways(storage: Pick<Storage, 'getItem'>): PressedColorway[] {
  try {
    const raw = storage.getItem(COLORWAY_STORAGE_KEY)
    const parsed: unknown = raw === null ? [] : JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isColorway) : []
  } catch {
    return []
  }
}

export function saveColorways(storage: Pick<Storage, 'setItem'>, colorways: readonly PressedColorway[]): void {
  storage.setItem(COLORWAY_STORAGE_KEY, JSON.stringify([...colorways].sort((a, b) => a.id.localeCompare(b.id))))
}

let appliedTokens = new Set<string>()

export function applyColorwayTokens(root: HTMLElement, colorway: PressedColorway | null): void {
  for (const name of appliedTokens) root.style.removeProperty(name)
  appliedTokens = new Set()
  root.toggleAttribute('data-pressed-colorway', colorway !== null)
  if (colorway === null) return
  for (const [name, value] of Object.entries(colorway.tokens)) {
    root.style.setProperty(name, value)
    appliedTokens.add(name)
  }
}
