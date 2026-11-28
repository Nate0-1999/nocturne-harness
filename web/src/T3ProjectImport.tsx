import { useState } from 'react'
import { Button, Select } from './kit'

type Project = { folder: string, tools: string[], count: number }

async function requestProjects(body: Record<string, string>) {
  const response = await fetch('/v1/t3/projects', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), cache: 'no-store',
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail ?? 'Refresh the project list and try again.')
  return data
}

export function T3ProjectImport({ onOpen }: { onOpen: (id: string) => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [folder, setFolder] = useState('')
  const [busy, setBusy] = useState(false)
  const [line, setLine] = useState('')

  async function load() {
    setBusy(true)
    setLine('')
    try {
      const data = await requestProjects({})
      setProjects(data.projects)
      setFolder('')
      if (!data.projects.length) setLine('No recent Codex or Claude Code projects.')
    } catch (error) {
      setLine(error instanceof Error ? error.message : 'The project list could not be loaded.')
    } finally { setBusy(false) }
  }

  async function bringIn() {
    setBusy(true)
    try {
      const data = await requestProjects({ folder })
      setProjects(null)
      const count = data.threads.length
      if (count === 1) onOpen(data.threads[0])
      setLine(`${count} ${count === 1 ? 'conversation' : 'conversations'} in Threads.` +
        (data.skipped ? ` ${data.skipped} skipped by T3.` : ''))
    } catch (error) {
      setLine(error instanceof Error ? error.message : 'The project could not be imported.')
    } finally { setBusy(false) }
  }

  return <section className="t3-project-import" aria-label="Import project">
    {projects === null
      ? <Button action="import" disabled={busy} onClick={() => void load()}
          title="Choose a local tool project">Import project</Button>
      : <>
        <label>Project <Select aria-label="Project to import" value={folder} disabled={busy}
          onChange={event => setFolder(event.target.value)}>
          <option value="">Choose a project</option>
          {projects.map(p => <option key={p.folder} value={p.folder}>
            {p.tools.join(' + ')} · {p.folder} · {p.count}
          </option>)}
        </Select></label>
        <small>Last 30 days · up to 100 conversations per import · 200 messages each</small>
        <div><Button action="import" disabled={busy || !folder} onClick={() => void bringIn()}
          title="Bring this project into Threads">Import project</Button>
        <Button disabled={busy} onClick={() => { setProjects(null); setLine('') }} title="Close project list">Cancel</Button></div>
      </>}
    {line && <span role="status">{line}</span>}
  </section>
}
