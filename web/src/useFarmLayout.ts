import { useEffect, useRef, useState } from 'react'
import { farmLayoutSteps, type FarmLayout } from './farmLayout'
import type { WorkProject } from './visualization'

export function useFarmLayout(project: WorkProject | undefined, focus: string) {
  const cache = useRef(new Map<string, { revision: string; layouts: Map<string, FarmLayout> }>())
  const [result, setResult] = useState<{ root: string; layout: FarmLayout } | null>(null)
  useEffect(() => {
    if (!project) return
    let active = true
    const update = async () => {
      // Hash bounded chunks so serializing a large poll cannot monopolize a frame.
      const encoder = new TextEncoder(), hashes = [project.root]
      for (let start = 0; start < project.nodes.length; start += 128) {
        const bytes = encoder.encode(JSON.stringify(project.nodes.slice(start, start + 128)))
        hashes.push(Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (n) => n.toString(16).padStart(2, '0')).join(''))
        if (!active) return
      }
      const hash = hashes.join(':')
      if (!active) return
      let saved = cache.current.get(project.root)
      if (hash !== saved?.revision) {
        saved = { revision: hash, layouts: new Map() }
        cache.current.set(project.root, saved)
      }
      let layout = saved!.layouts.get(focus)
      if (!layout) {
        const started = performance.now()
        const steps = farmLayoutSteps(project, focus)
        let step = steps.next()
        while (!step.done) {
          await new Promise((resolve) => setTimeout(resolve, 0))
          if (!active) return
          const deadline = performance.now() + 2
          do { step = steps.next() } while (!step.done && performance.now() < deadline)
        }
        layout = step.value
        saved!.layouts.set(focus, layout)
        performance.clearMeasures('farm-layout')
        performance.measure('farm-layout', { start: started, detail: { entries: project.nodes.length, focus } })
      }
      setResult((current) => current?.layout === layout ? current : { root: project.root, layout })
    }
    void update()
    return () => { active = false }
  }, [project, focus])
  return result?.root === project?.root && result?.layout.focus === focus ? result.layout : null
}
