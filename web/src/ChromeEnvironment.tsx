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
    // Bent light strips reflect as broken ribbons rather than latitude rings.
    for (let index = 0; index < 36; index++) {
      const x = (index * 173 + 29) % 1024, y = (index * 97 + 11) % 512
      const reach = 70 + index % 7 * 23, bend = index % 2 ? 90 : -90
      context.strokeStyle = index % 3 === 0 ? '#436ac5' : '#eff8fa'
      context.lineWidth = 2 + index % 4 * 2
      context.beginPath()
      context.moveTo(x, y)
      context.bezierCurveTo(x + reach * 0.3, y + bend, x + reach * 0.7, y - bend, x + reach, y + bend * 0.3)
      context.stroke()
    }
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
