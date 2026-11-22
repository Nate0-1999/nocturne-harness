import { parentPath, type DirectoryEntry, type WorkAgent, type WorkProject } from './visualization.ts'

export type ExplorerRow = { id: string; node: DirectoryEntry; level: number; parent: string | null; root: string }

export function explorerRows(projects: WorkProject[], opened: Record<string, boolean>): ExplorerRow[] {
  const result: ExplorerRow[] = []
  for (const project of projects) {
    const children = new Map<string, DirectoryEntry[]>()
    for (const node of project.nodes) {
      if (node.path === '.') continue
      const parent = parentPath(node.path)
      if (!children.has(parent)) children.set(parent, [])
      children.get(parent)!.push(node)
    }
    for (const siblings of children.values()) siblings.sort((a, b) =>
      Number(b.kind === 'directory') - Number(a.kind === 'directory') || a.path.localeCompare(b.path))
    const visit = (node: DirectoryEntry, level: number, parent: string | null) => {
      const id = `${project.root}${node.path === '.' ? '' : `/${node.path}`}`
      result.push({ id, node, level, parent, root: project.root })
      if (node.kind === 'directory' && (opened[id] ?? node.path === '.')) {
        for (const child of children.get(node.path) ?? []) visit(child, level + 1, id)
      }
    }
    const root = project.nodes.find((node) => node.path === '.')
    if (root) visit(root, 1, null)
  }
  return result
}

export function explorerPresence(agents: WorkAgent[]) {
  const paths = new Map<string, { agent: WorkAgent; touched: boolean }[]>()
  const add = (path: string, agent: WorkAgent, touched: boolean) => {
    if (!paths.has(path)) paths.set(path, [])
    paths.get(path)!.push({ agent, touched })
  }
  for (const agent of agents) {
    add(agent.location, agent, false)
    for (const touch of agent.touched_files ?? []) if (touch.path !== agent.location) add(touch.path, agent, true)
  }
  return new Map(Array.from(paths, ([path, badges]) => [path, {
    visible: badges.slice(0, 3), remaining: Math.max(0, badges.length - 3),
    names: badges.map(({ agent, touched }) => `${agent.label} · ${touched ? 'touched this file' : agent.state}`).join('; '),
  }]))
}
