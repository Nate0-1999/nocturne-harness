import { useState } from 'react'
import { useRackPlugin } from './rack'

export function RewindControl({ threadId, promptId, disabled }: {
  threadId: string; promptId: string; disabled: boolean
}) {
  const { events } = useRackPlugin()
  const [scope, setScope] = useState<'conversation' | 'files' | 'both'>('both')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  async function rewind() {
    setBusy(true)
    try {
      await events.dispatch({ type: 'thread.rewind', thread_id: threadId, prompt_id: promptId, scope })
      setStatus('Restored. The abandoned continuation is retained.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Rewind failed') }
    finally { setBusy(false) }
  }
  return <span className="rewind-control">
    <select aria-label="Rewind scope" value={scope} disabled={busy || disabled}
      onChange={(event) => setScope(event.target.value as typeof scope)}>
      <option value="both">Chat + files</option><option value="conversation">Chat</option><option value="files">Files</option>
    </select>
    <button type="button" disabled={busy || disabled} onClick={() => void rewind()}
      title="Return to before this turn. Ignored files and real Git history stay unchanged.">Rewind</button>
    {status && <small role="status">{status}</small>}
  </span>
}
