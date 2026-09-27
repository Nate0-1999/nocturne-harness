import { buildChambers, parentPath, type Chamber, type DirectoryEntry, type WorkProject } from './visualization.ts'

export interface FarmChamber extends Chamber { hiddenFiles: number; hiddenFolders: number }
export interface FarmLayout {
  chambers: FarmChamber[]; focus: string; depth: number; files: number; folders: number
}

// Geometry budgets for the efficient tier; depth folding preserves every entry in the counts.
export const FARM_CHAMBERS = 64, FARM_CELLS = 512

export function layoutFarm(project: WorkProject, focus = '.'): FarmLayout {
  const steps = farmLayoutSteps(project, focus)
  let step = steps.next()
  while (!step.done) step = steps.next()
  return step.value
}

/** Yield between bounded batches; only the bounded geometry reaches the synchronous layout. */
export function* farmLayoutSteps(project: WorkProject, focus = '.'): Generator<void, FarmLayout> {
  const prefix = focus === '.' ? '' : `${focus}/`
  const depthOf = (path: string) => path === '.' ? 0 : path.split('/').length
  const nodes: DirectoryEntry[] = [], directoriesAt: number[] = [], filesAt: number[] = []
  const totals = new Map<string, { files: number; folders: number }>()
  let files = 0, folders = 0, batch = 0
  for (const source of project.nodes) {
    if (++batch % 128 === 0) yield
    if (source.path !== focus && !source.path.startsWith(prefix)) continue
    const node = { ...source, path: source.path === focus ? '.' : source.path.slice(prefix.length) }
    nodes.push(node)
    const directory = node.kind === 'directory', level = depthOf(node.path)
    if (directory) { folders++; directoriesAt[level] = (directoriesAt[level] ?? 0) + 1 }
    else { files++; filesAt[level - 1] = (filesAt[level - 1] ?? 0) + 1 }
    if (node.path === '.') continue
    for (let parent = parentPath(node.path);; parent = parentPath(parent)) {
      const total = totals.get(parent) ?? { files: 0, folders: 0 }
      if (directory) total.folders++
      else total.files++
      totals.set(parent, total)
      if (parent === '.') break
    }
  }
  const maxDepth = directoriesAt.length
  let depth = 0
  let visibleFolders = directoriesAt[0] ?? 0, visibleFiles = 0
  for (let next = 1; next <= maxDepth; next++) {
    visibleFolders += directoriesAt[next] ?? 0
    visibleFiles += filesAt[next - 1] ?? 0
    if (visibleFolders > FARM_CHAMBERS || visibleFiles > FARM_CELLS) break
    depth = next
  }
  const visible: DirectoryEntry[] = []
  for (const node of nodes) {
    if (++batch % 128 === 0) yield
    if (node.path.startsWith('.git/') || node.path.includes('/.git/')) continue
    if (node.kind === 'directory' ? depthOf(node.path) <= depth : depthOf(parentPath(node.path)) < depth) visible.push(node)
  }
  yield
  // Keep the established .git chamber, now counted and expandable like any depth frontier.
  const chambers = buildChambers({ ...project, nodes: visible }).map((chamber): FarmChamber => {
    const collapsed = depthOf(chamber.path) === depth || chamber.path === '.git' || chamber.path.endsWith('/.git')
    const total = totals.get(chamber.path) ?? { files: 0, folders: 0 }
    const allFiles = total.files
    return { ...chamber, beneath: allFiles,
      radius: collapsed ? 1.05 + Math.min(0.65, Math.sqrt(allFiles) * 0.16) : chamber.radius,
      hiddenFiles: collapsed ? allFiles : 0,
      hiddenFolders: collapsed ? total.folders : 0 }
  })
  return { chambers, focus, depth, files, folders }
}
