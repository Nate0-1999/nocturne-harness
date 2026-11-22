import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { ActionIcon, Button } from './kit'
import { agentColor, parentPath, type DirectoryEntry, type WorkAgent, type WorkProject } from './visualization'
import './assets/farm-explorer.css'

type Row = { id: string; node: DirectoryEntry; level: number; parent: string | null; root: string }

/** SD-102: the Farm's recorded tree and presence, with the same path selection as a cell. */
export function FarmExplorer({ projects, agents, selectedPath, pickPath }: {
  projects: WorkProject[]; agents: WorkAgent[]; selectedPath: string | null; pickPath: (path: string) => void
}) {
  const [opened, setOpened] = useState<Record<string, boolean>>({})
  const [focused, setFocused] = useState<string | null>(null)
  const tree = useRef<HTMLDivElement>(null)
  const isOpen = (row: Row) => opened[row.id] ?? row.node.path === '.'
  const rows = useMemo(() => {
    const result: Row[] = []
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
        const row = { id, node, level, parent, root: project.root }
        result.push(row)
        if (node.kind === 'directory' && (opened[id] ?? node.path === '.')) {
          for (const child of children.get(node.path) ?? []) visit(child, level + 1, id)
        }
      }
      const root = project.nodes.find((node) => node.path === '.')
      if (root) visit(root, 1, null)
    }
    return result
  }, [projects, opened])
  const badges = useMemo(() => {
    const paths = new Map<string, { agent: WorkAgent; touched: boolean }[]>()
    const add = (path: string, agent: WorkAgent, touched: boolean) => {
      if (!paths.has(path)) paths.set(path, [])
      paths.get(path)!.push({ agent, touched })
    }
    for (const agent of agents) {
      add(agent.location, agent, false)
      for (const touch of agent.touched_files ?? []) if (touch.path !== agent.location) add(touch.path, agent, true)
    }
    return paths
  }, [agents])
  const tabStop = rows.some((row) => row.id === focused) ? focused : rows[0]?.id
  const toggle = (row: Row) => setOpened((current) => ({ ...current, [row.id]: !isOpen(row) }))
  const move = (id: string | undefined) => {
    if (id === undefined) return
    const element = Array.from(tree.current!.querySelectorAll<HTMLElement>('[role=treeitem]')).find((item) => item.dataset.path === id)
    element?.focus()
  }
  const keyDown = (event: KeyboardEvent<HTMLDivElement>, row: Row, index: number) => {
    if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End', 'Enter', ' '].includes(event.key)) return
    event.preventDefault()
    switch (event.key) {
      case 'ArrowDown': move(rows[index + 1]?.id); break
      case 'ArrowUp': move(rows[index - 1]?.id); break
      case 'Home': move(rows[0]?.id); break
      case 'End': move(rows.at(-1)?.id); break
      case 'ArrowRight':
        if (row.node.kind === 'directory') { if (!isOpen(row)) toggle(row); else move(rows[index + 1]?.parent === row.id ? rows[index + 1].id : undefined) }
        break
      case 'ArrowLeft':
        if (row.node.kind === 'directory' && isOpen(row)) toggle(row)
        else move(row.parent ?? undefined)
        break
      default: pickPath(row.id)
    }
  }
  return <div className="farm-explorer" role="tree" aria-label="Project folders and files" ref={tree}>
    {rows.map((row, index) => <div key={row.id} role="treeitem" aria-level={row.level}
      aria-expanded={row.node.kind === 'directory' ? isOpen(row) : undefined} aria-selected={row.id === selectedPath}
      tabIndex={row.id === tabStop ? 0 : -1} data-path={row.id}
      className="farm-explorer__row" style={{ paddingInlineStart: `${(row.level - 1) * 20 + 8}px` }}
      onFocus={() => setFocused(row.id)} onKeyDown={(event) => keyDown(event, row, index)}
      onClick={() => pickPath(row.id)} title={row.id}>
      {row.node.kind === 'directory' ? <Button action={isOpen(row) ? 'collapse' : 'expand'} iconOnly
        className="farm-explorer__fold" tabIndex={-1} title={`${isOpen(row) ? 'Collapse' : 'Expand'} ${row.node.path === '.' ? row.root : row.node.path}`}
        aria-label={`${isOpen(row) ? 'Collapse' : 'Expand'} ${row.node.path === '.' ? row.root : row.node.path}`}
        onClick={(event) => { event.stopPropagation(); toggle(row) }} /> : <span className="farm-explorer__fold" />}
      <ActionIcon action="open" />
      <span className="farm-explorer__name">{row.node.path === '.' ? row.root : row.node.path.split('/').at(-1)}</span>
      <span className="farm-explorer__kind">{row.node.kind === 'directory' ? '' : row.node.kind === 'link' ? 'Link' : `${row.node.bytes.toLocaleString()} B`}</span>
      <span className="farm-explorer__agents">{(badges.get(row.id) ?? []).map(({ agent, touched }) =>
        <span key={agent.id} style={{ color: agentColor(agent.id) }} title={`${agent.label} · ${touched ? 'touched this file' : agent.state}`}>
          {agent.label}{touched ? ' · touched' : ''}
        </span>)}</span>
    </div>)}
  </div>
}
