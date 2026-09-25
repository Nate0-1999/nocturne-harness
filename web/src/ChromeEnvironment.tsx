import { useEffect, useMemo } from 'react'
import { DataTexture, DataUtils, EquirectangularReflectionMapping, HalfFloatType, LinearFilter, LinearSRGBColorSpace, RGBAFormat } from 'three'

type Light = { at: [number, number, number]; size: number; color: [number, number, number] }

// A dark studio: cool-white softboxes, cobalt fill and a few sharp glints, in HDR so chrome and glass
// catch real, bright reflections. Lighting only; nothing here encodes or fabricates data.
const LIGHTS: Light[] = [
  { at: [-0.45, 0.55, 0.7], size: 0.3, color: [5.2, 5.6, 6.2] },
  { at: [0.5, 0.75, 0.45], size: 0.16, color: [7, 7.4, 8] },
  { at: [0.65, -0.15, 0.65], size: 0.5, color: [0.25, 0.55, 2.6] },
  { at: [-0.8, -0.35, 0.2], size: 0.35, color: [0.12, 0.3, 1.6] },
  ...Array.from({ length: 12 }, (_, index): Light => {
    const azimuth = index * 2.399963 + 0.4, elevation = Math.sin(index * 1.7) * 0.9
    return { at: [Math.cos(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.abs(Math.sin(azimuth)) * Math.cos(elevation)],
      size: 0.035 + (index % 3) * 0.012, color: [26, 27, 30] }
  }),
]

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
      const strip = Math.max(0, 1 - Math.abs(Math.abs(direction[0]) - 0.97) / 0.02) * (Math.abs(elevation) < 1 ? 1 : 0)
      for (let channel = 0; channel < 3; channel++) color[channel] += strip * [3.6, 3.9, 4.4][channel]
      if (elevation > 1.2) for (let channel = 0; channel < 3; channel++) color[channel] += [2.4, 2.6, 3][channel]
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
