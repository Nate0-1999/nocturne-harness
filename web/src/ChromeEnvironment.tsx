import { useEffect, useMemo } from 'react'
import { CanvasTexture, EquirectangularReflectionMapping, SRGBColorSpace } from 'three'

/** M3VL plates: white strip reflections, black seams, a narrow cobalt horizon.
 * This is lighting, not scene population; no fabricated data marks or motion.
 */
export function ChromeEnvironment() {
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 1024
    canvas.height = 512
    const context = canvas.getContext('2d')!
    context.fillStyle = '#030509'
    context.fillRect(0, 0, 1024, 512)
    const sky = context.createLinearGradient(0, 0, 0, 512)
    // SPEC D.2 109's percentile rail: the missing middle makes a mirror.
    for (const [stop, color] of [[0, '#090807'], [.16, '#100f15'], [.2, '#eff8fa'],
      [.23, '#eff8fa'], [.245, '#090807'], [.48, '#030509'], [.5, '#436ac5'],
      [.52, '#090807'], [.7, '#100f15'], [.73, '#dbe5ee'], [.76, '#eff8fa'],
      [.78, '#090807'], [1, '#030509']] as const) sky.addColorStop(stop, color)
    context.fillStyle = sky
    context.fillRect(0, 0, 1024, 512)
    context.fillStyle = '#eff8fa'
    context.fillRect(100, 60, 38, 330)
    context.fillRect(640, 150, 110, 38)
    context.fillStyle = '#436ac5'
    context.fillRect(800, 250, 30, 150)
    // Uneven studio highlights break the long rings into the plate's liquid glints.
    for (let index = 0; index < 18; index++) {
      const x = (index * 173 + 67) % 1024, y = (index * 89 + 31) % 512
      const radius = 12 + index % 5 * 7
      const light = context.createRadialGradient(x, y, 0, x, y, radius)
      light.addColorStop(0, '#eff8fa')
      light.addColorStop(0.2, '#eff8fa')
      light.addColorStop(0.55, '#a1aebd')
      light.addColorStop(1, 'rgba(3,5,9,0)')
      context.fillStyle = light
      context.fillRect(x - radius, y - radius, radius * 2, radius * 2)
    }
    const texture = new CanvasTexture(canvas)
    texture.mapping = EquirectangularReflectionMapping
    texture.colorSpace = SRGBColorSpace
    return texture
  }, [])
  useEffect(() => () => texture.dispose(), [texture])
  return <primitive object={texture} attach="environment" />
}
