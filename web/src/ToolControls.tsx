import { useEffect, useState } from 'react'
import { useRackPlugin } from './rack'

interface InventoryEntry {
  name: string
  kind: 'tool' | 'skill'
  source: string
  version: string
  description: string
  enabled: boolean
}

export function ToolInventory({ threadId }: { threadId: string | null }) {
  const { query } = useRackPlugin()
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<InventoryEntry[]>([])
  const [status, setStatus] = useState('')
  async function toggle() {
    setOpen(!open)
    if (open || threadId === null) return
    setStatus('Reading installed tools…')
    try {
      const result = await query.query({ resource: 'tools', thread_id: threadId })
      const value = result.data as unknown as { entries: InventoryEntry[] }
      setEntries(value.entries)
      setStatus('Installed sources · disabled entries are unavailable to the model')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Tools unavailable')
    }
  }
  return <div className="tool-inventory">
    <button type="button" disabled={threadId === null} aria-expanded={open} onClick={() => void toggle()}>Tools & skills</button>
    {open && <section aria-label="Tools and skills" className="tool-inventory__panel">
      <p role="status">{status}</p>
      <ul>{entries.map((entry) => <li key={`${entry.kind}:${entry.name}`}>
        <strong>{entry.name}</strong> · {entry.kind} · {entry.enabled ? 'Enabled' : 'Off'}
        <p>{entry.description}</p>
        <small>{entry.source.startsWith('https://')
          ? <a href={entry.source} target="_blank" rel="noreferrer">{entry.source}</a>
          : entry.source}<br />{entry.version}</small>
      </li>)}</ul>
    </section>}
  </div>
}

export function ToolsetSettings() {
  const [selection, setSelection] = useState('pydantic')
  const [loaded, setLoaded] = useState(false)
  const [status, setStatus] = useState('Reading toolset…')
  useEffect(() => {
    fetch('/v1/toolset').then(async (response) => {
      if (!response.ok) throw new Error('Toolset unavailable')
      setSelection((await response.json()).toolset)
      setLoaded(true)
      setStatus('Applies at the next turn. Memory tools stay available.')
    }).catch((error: Error) => setStatus(error.message))
  }, [])
  async function change(toolset: string) {
    try {
      const response = await fetch('/v1/toolset', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolset }),
      })
      if (!response.ok) throw new Error('Toolset change failed')
      setSelection((await response.json()).toolset)
      setStatus('Saved · applies at the next turn. Memory tools stay available.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Toolset unavailable') }
  }
  return <section>
    <h2>Workspace tools</h2>
    <label>Toolset<select aria-label="Workspace toolset" disabled={!loaded} value={selection} onChange={(event) => void change(event.target.value)}>
      <option value="pydantic">Pydantic · files, shell, browser, skills and delegation</option>
      <option value="none">Off</option>
    </select></label>
    <p role="status">{status}</p>
  </section>
}
