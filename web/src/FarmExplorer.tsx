import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { CircleUserRound } from 'lucide-react'
import { ActionIcon, Button } from './kit'
import { agentColor, type WorkAgent, type WorkProject } from './visualization'
import { explorerPresence, explorerRows, type ExplorerRow as Row } from './explorerTree'
import './assets/farm-explorer.css'

function showNames(group: HTMLSpanElement) {
  const tip = group.querySelector<HTMLElement>('[popover]')!
  const rect = group.getBoundingClientRect()
  tip.style.left = `${Math.max(12, rect.right - Math.min(280, window.innerWidth - 24))}px`
  const above = window.innerHeight - rect.bottom < 200 && rect.top > window.innerHeight - rect.bottom
  tip.style.top = above ? 'auto' : `${rect.bottom + 8}px`
  tip.style.bottom = above ? `${window.innerHeight - rect.top + 8}px` : 'auto'
  tip.showPopover()
}

function hideNames(group: HTMLSpanElement) {
  group.querySelector<HTMLElement>('[popover]')!.hidePopover()
}

/** SD-102: the Farm's recorded tree and presence, with the same path selection as a cell. */
export function FarmExplorer({ projects, agents, selectedPath, pickPath }: {
  projects: WorkProject[]; agents: WorkAgent[]; selectedPath: string | null; pickPath: (path: string) => void
}) {
  const [opened, setOpened] = useState<Record<string, boolean>>({})
  const [focused, setFocused] = useState<string | null>(null)
  const tree = useRef<HTMLDivElement>(null)
  const isOpen = (row: Row) => opened[row.id] ?? row.node.path === '.'
  const rows = useMemo(() => explorerRows(projects, opened), [projects, opened])
  const badges = useMemo(() => explorerPresence(agents), [agents])
  const tabStop = rows.some((row) => row.id === focused) ? focused : rows[0]?.id
  const toggle = (row: Row) => setOpened((current) => ({ ...current, [row.id]: !isOpen(row) }))
  const move = (id: string | undefined) => {
    if (id === undefined) return
    const element = Array.from(tree.current!.querySelectorAll<HTMLElement>('[role=treeitem]')).find((item) => item.dataset.path === id)
    element?.focus()
  }
  const keyDown = (event: KeyboardEvent<HTMLDivElement>, row: Row, index: number) => {
    if (event.target !== event.currentTarget) return
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
      {badges.has(row.id) && <span className="farm-explorer__agents" tabIndex={0} aria-label={badges.get(row.id)!.names}
        onMouseEnter={(event) => showNames(event.currentTarget)}
        onMouseLeave={(event) => { if (!event.currentTarget.contains(document.activeElement)) hideNames(event.currentTarget) }}
        onFocus={(event) => showNames(event.currentTarget)}
        onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) hideNames(event.currentTarget) }}>
        {badges.get(row.id)!.visible.map(({ agent, touched }) =>
        <span key={agent.id} style={{ color: agentColor(agent.id) }} title={`${agent.label} · ${touched ? 'touched this file' : agent.state}`}>
          <CircleUserRound className="kit-icon" aria-hidden="true" />
          <span className="visually-hidden">{agent.label}{touched ? ' · touched' : ''}</span>
        </span>)}
        {badges.get(row.id)!.remaining > 0 && <span>+{badges.get(row.id)!.remaining}</span>}
        <span className="farm-explorer__names" popover="manual" role="tooltip" tabIndex={0}>{badges.get(row.id)!.names}</span>
      </span>}
    </div>)}
  </div>
}
