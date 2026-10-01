/** Where each ant rests on screen in the Farm at its default camera, computed with the module's own layout code
 * (farmLayout.ts, Farm.tsx's rest rule, VisualizationScene's camera), so a walk can click an ant in 3D.
 *   node --experimental-strip-types antpos.mjs <feed.json> <canvas-width> <canvas-height> [project-root] */
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { layoutFarm } from '../../web/src/farmLayout.ts'
import { identitySeed, parentPath } from '../../web/src/visualization.ts'

const require = createRequire(new URL('../../web/package.json', import.meta.url))
const { PerspectiveCamera, Vector3, Euler } = await import(require.resolve('three'))
const [file, w, h, rootArg] = process.argv.slice(2)
const feed = JSON.parse(readFileSync(file, 'utf8'))
const project = feed.projects.find((p) => p.root === (rootArg ?? feed.projects[0].root))
const layout = layoutFarm(project, '.')
const byPath = new Map(layout.chambers.map((c) => [c.path, c]))
const reach = Math.max(0, ...layout.chambers.map((c) => Math.hypot(c.position[0], c.position[1]) + c.radius))
const distance = Math.max(8, reach * 2.4 + 3.5), width = (reach + 1) * 2
const aspect = Number(w) / Number(h), fit = Math.max(distance, width * 1.5 / aspect)
const camera = new PerspectiveCamera(42, aspect, 0.1, Math.max(2000, distance * 4))
camera.position.set(0, fit * 0.12, fit); camera.lookAt(0, 0, 0); camera.updateMatrixWorld()
const inside = (a) => a.location === project.root || a.location.startsWith(`${project.root}/`)
const resident = feed.agents.filter(inside).sort((a, b) => a.id.localeCompare(b.id))
const out = resident.map((agent) => {
  let relative = agent.location === project.root ? '.' : agent.location.slice(project.root.length + 1)
  while (relative !== '.' && !byPath.has(relative)) relative = parentPath(relative)
  const home = byPath.get(relative), peers = resident.filter((p) => p.location === agent.location)
  const angle = identitySeed(agent.id) * Math.PI * 2 + peers.indexOf(agent) * 2.4
  const rest = new Vector3(home.position[0] + Math.cos(angle) * home.radius * 0.45, home.position[1] + Math.sin(angle) * home.radius * 0.45, home.position[2] + 0.2)
  rest.applyEuler(new Euler(-1.0, 0, 0)).project(camera)
  return { id: agent.id, label: agent.label, chamber: relative, x: (rest.x + 1) / 2 * Number(w), y: (1 - rest.y) / 2 * Number(h) }
})
console.log(JSON.stringify(out))
