import { useEffect, useMemo } from 'react'
import { DataTexture, DataUtils, EquirectangularReflectionMapping, HalfFloatType, LinearFilter, LinearSRGBColorSpace, RGBAFormat } from 'three'

type Light = { at: [number, number, number]; size: number; color: [number, number, number] }

// A dark studio: cool-white softboxes, cobalt fill and a few sharp glints, in HDR so chrome and glass
// catch real, bright reflections. Lighting only; nothing here encodes or fabricates data.
const LIGHTS: Light[] = [
  // A cluster of small cool-white softboxes: several crisp sparkles rather than one round highlight.
  ...[[-0.45, 0.55, 0.7], [-0.3, 0.62, 0.72], [-0.55, 0.42, 0.72], [0.5, 0.75, 0.45]].map((at, index): Light => ({
    at: at as [number, number, number], size: [0.09, 0.05, 0.06, 0.1][index], color: [11, 11.6, 12.8] })),
  { at: [0.65, -0.15, 0.65], size: 0.35, color: [0.12, 0.3, 1.5] },
  ...Array.from({ length: 16 }, (_, index): Light => {
    const azimuth = index * 2.399963 + 0.4, elevation = Math.sin(index * 1.7) * 0.9
    return { at: [Math.cos(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.abs(Math.sin(azimuth)) * Math.cos(elevation)],
      size: 0.025 + (index % 3) * 0.01, color: [30, 31, 34] }
  }),
]

// Thin tilted cobalt bands reflect as the plate's curved blue lines across glass and along chrome.
const BANDS = [[0.3, 0.9, 0.3], [-0.6, 0.5, 0.62], [0.8, 0.2, -0.55], [0.1, -0.7, 0.7]].map((normal) => {
  const length = Math.hypot(...normal)
  return normal.map((value) => value / length)
})

function studio(width: number, height: number): Uint16Array {
  const data = new Uint16Array(width * height * 4)
  const lights = LIGHTS.map(({ at, size, color }) => {
    const length = Math.hypot(...at)
    return { at: at.map((value) => value / length), cos: Math.cos(size), soft: Math.cos(size * 0.6), color }
  })
  for (let row = 0; row < height; row++) {
    const elevation = ((row + 0.5) / height - 0.5) * Math.PI
    for (let column = 0; column < width; column++) {
      const azimuth = ((column + 0.5) / width - 0.5) * Math.PI * 2
      const direction = [Math.cos(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.sin(azimuth) * Math.cos(elevation)]
      // Near-black room, a narrow cobalt horizon and two tall white strip lights at the sides.
      const horizon = Math.exp(-((elevation / 0.07) ** 2))
      const color = [0.004 + horizon * 0.05, 0.006 + horizon * 0.1, 0.014 + horizon * 0.45]
      const strip = 0.55 * Math.max(0, 1 - Math.abs(Math.abs(direction[0]) - 0.97) / 0.012) * (Math.abs(elevation) < 1 ? 1 : 0)
      for (let channel = 0; channel < 3; channel++) color[channel] += strip * [3.6, 3.9, 4.4][channel]
      if (elevation > 1.2) for (let channel = 0; channel < 3; channel++) color[channel] += [0.5, 0.55, 0.7][channel]
      for (const [index, normal] of BANDS.entries()) {
        const offset = Math.abs(direction[0] * normal[0] + direction[1] * normal[1] + direction[2] * normal[2])
        const band = Math.exp(-((offset / (0.012 + index * 0.004)) ** 2)) * (index % 2 ? 1.4 : 2.2)
        color[0] += band * 0.18; color[1] += band * 0.42; color[2] += band * 1.6
      }
      for (const light of lights) {
        const facing = direction[0] * light.at[0] + direction[1] * light.at[1] + direction[2] * light.at[2]
        if (facing <= light.cos) continue
        const weight = Math.min(1, (facing - light.cos) / Math.max(1e-6, light.soft - light.cos))
        for (let channel = 0; channel < 3; channel++) color[channel] += light.color[channel] * weight
      }
      const offset = (row * width + column) * 4
      for (let channel = 0; channel < 3; channel++) data[offset + channel] = DataUtils.toHalfFloat(color[channel])
      data[offset + 3] = DataUtils.toHalfFloat(1)
    }
  }
  return data
}

export function ChromeEnvironment() {
  const texture = useMemo(() => {
    const width = 512, height = 256
    const texture = new DataTexture(studio(width, height), width, height, RGBAFormat, HalfFloatType)
    texture.mapping = EquirectangularReflectionMapping
    texture.colorSpace = LinearSRGBColorSpace
    texture.magFilter = texture.minFilter = LinearFilter
    texture.needsUpdate = true
    return texture
  }, [])
  useEffect(() => () => texture.dispose(), [texture])
  return <primitive object={texture} attach="environment" />
}
