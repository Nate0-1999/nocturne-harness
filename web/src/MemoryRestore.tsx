import { useRef, useState } from 'react'

type MemoryChange = { memory_id: string; label: string; current_revision: number; candidate_revision: number | null }
type RestorePreview = {
  backup_id: string
  manifest: {
    memories_lost: MemoryChange[]
    edits_reverted: MemoryChange[]
    pins_undone: MemoryChange[]
    event_counts: { table: string; current: number; candidate: number }[]
  }
}

/** D.2 092: preview the real restore manifest before the existing stopped-app ritual. */
export function MemoryRestore() {
  const dialog = useRef<HTMLDialogElement>(null)
  const [backup, setBackup] = useState('')
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
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
    <div className="app-settings-actions"><button type="button" onClick={() => dialog.current?.showModal()}>Restore memories</button></div>
    <dialog ref={dialog} className="memory-restore-dialog" aria-labelledby="memory-restore-title">
      <h2 id="memory-restore-title">Roll back these memories?</h2>
      <p>Preview a local Palace backup before restoring. Your current Palace remains active.</p>
      <label>Backup ID <input value={backup} disabled={busy} onChange={(event) => {
        setBackup(event.target.value); setPreview(null)
      }} /></label>
      <button type="button" disabled={busy || !backup.trim()} onClick={() => void inspect()}>{busy ? 'Inspecting…' : 'Preview memories'}</button>
      {error && <p role="alert">{error}</p>}
      {preview && <>
        {([
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
      <button type="button" onClick={() => dialog.current?.close()}>Close preview</button>
    </dialog>
  </section>
}
