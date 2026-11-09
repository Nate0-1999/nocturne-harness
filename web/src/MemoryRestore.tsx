import { useRef, useState } from 'react'
import { Button, Select } from './kit'

type MemoryChange = { memory_id: string; label: string; current_revision: number; candidate_revision: number | null }
type Backup = { backup_id: string; created_at: string; reason: 'manual' | 'pre_migration' }
type RestorePreview = {
  backup_id: string
  manifest: {
    memories_returned: MemoryChange[]
    memories_lost: MemoryChange[]
    edits_reverted: MemoryChange[]
    pins_undone: MemoryChange[]
    event_counts: { table: string; current: number; candidate: number }[]
  }
}

/** D.2 092: preview the real restore manifest before the existing stopped-app ritual. */
export function MemoryRestore() {
  const dialog = useRef<HTMLDialogElement>(null)
  const [backups, setBackups] = useState<Backup[] | null>(null)
  const [backup, setBackup] = useState('')
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // FL-168: the pop-up lists this home's backups, newest first; nobody types an ID.
  async function open() {
    dialog.current?.showModal()
    setBackups(null)
    setPreview(null)
    setError('')
    try {
      const response = await fetch('/v1/restore/backups')
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail ?? 'Backups unavailable')
      setBackups(body.backups)
      setBackup(body.backups[0]?.backup_id ?? '')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Backups unavailable')
    }
  }
  async function inspect() {
    setBusy(true)
    setPreview(null)
    setError('')
    try {
      const response = await fetch(`/v1/restore/${encodeURIComponent(backup.trim())}/preview`, { method: 'POST' })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail ?? 'Restore preview unavailable')
      setPreview(body)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Restore preview unavailable')
    } finally {
      setBusy(false)
    }
  }
  return <section>
    <h2>Memory restore</h2>
    <div className="app-settings-actions"><Button action="restore" type="button" data-tooltip-detail="Preview a local Palace backup before restoring anything." onClick={() => void open()}>Restore memories</Button></div>
    <dialog ref={dialog} className="memory-restore-dialog" aria-labelledby="memory-restore-title">
      <h2 id="memory-restore-title">Roll back these memories?</h2>
      {backups?.length === 0 && <p>No backups yet. Run <code>nocturne backup</code> to make one.</p>}
      {backups !== null && backups.length > 0 && <label>Backup <Select data-tooltip-detail="The backup to roll back to, newest first." value={backup} disabled={busy} onChange={(event) => {
        setBackup(event.target.value); setPreview(null)
      }}>{backups.map((item) => <option key={item.backup_id} value={item.backup_id}>
        {new Date(item.created_at).toLocaleString()} · {item.reason === 'manual' ? 'manual' : 'before an update'}
      </option>)}</Select></label>}
      {backups !== null && backups.length > 0 && <Button action="preview" type="button" data-tooltip-detail="Show what this backup would change. Nothing is restored yet." disabled={busy || !backup.trim()} onClick={() => void inspect()}>{busy ? 'Inspecting…' : 'Preview memories'}</Button>}
      {error && <p role="alert">{error}</p>}
      {preview && <>
        {([
          ['Memories that come back', preview.manifest.memories_returned],
          ['Memories lost', preview.manifest.memories_lost],
          ['Edits reverted', preview.manifest.edits_reverted],
          ['Pins undone', preview.manifest.pins_undone],
        ] as const).map(([heading, memories]) => <section key={heading}>
          <h3>{heading} · {memories.length}</h3>
          {memories.length === 0 ? <p>None</p> : <ul>{memories.map((memory) => <li key={memory.memory_id}>
            <strong>{memory.label}</strong> · {memory.memory_id}
            {memory.candidate_revision !== null && ` · r${memory.current_revision} → r${memory.candidate_revision}`}
          </li>)}</ul>}
        </section>)}
        <h3>Event counts · current → restored</h3>
        <ul>{preview.manifest.event_counts.map((count) => <li key={count.table}>{count.table}: {count.current} → {count.candidate}</li>)}</ul>
        <p>To restore, stop Nocturne and run <code>nocturne restore {preview.backup_id}</code>. The command rechecks this list and asks for confirmation before switching.</p>
      </>}
      <Button action="close" type="button" data-tooltip-detail="Close without restoring anything." onClick={() => dialog.current?.close()}>Close preview</Button>
    </dialog>
  </section>
}
