import { useState } from 'react'
import { useRackPlugin } from './rack'
import { Button, Select } from './kit'

export function RewindControl({ threadId, promptId, disabled }: {
  threadId: string; promptId: string; disabled: boolean
}) {
  const { events } = useRackPlugin()
  const [scope, setScope] = useState<'conversation' | 'files' | 'both'>('both')
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [status, setStatus] = useState('')
  async function rewind() {
    setConfirming(false)
    setBusy(true)
    try {
      await events.dispatch({ type: 'thread.rewind', thread_id: threadId, prompt_id: promptId, scope })
      setStatus('Restored. The abandoned continuation is retained.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Rewind failed') }
    finally { setBusy(false) }
  }
  return <span className="rewind-control">
    <Select aria-label="Rewind scope" data-tooltip-detail="What a rewind restores: the chat, the files, or both." value={scope} disabled={busy || disabled}
      onChange={(event) => setScope(event.target.value as typeof scope)}>
      <option value="both">Chat + files</option><option value="conversation">Chat</option><option value="files">Files</option>
    </Select>
    <Button action="restore" iconOnly type="button" disabled={busy || disabled} onClick={() => setConfirming(true)}
      data-tooltip="Rewind to here" aria-haspopup="dialog" aria-expanded={confirming}
      data-tooltip-detail="Return to before this turn. Asks first. Ignored files and real Git history stay unchanged.">Rewind</Button>
    {/* M3W5B-35: a rewind drops later turns and their file edits, so it asks first (ui-taste 4). */}
    {confirming && <span className="rewind-control__confirm" role="dialog" aria-label="Rewind to before this turn?">
      <span>Rewind here?</span>
      <Button action="confirm" variant="danger" type="button" autoFocus disabled={busy || disabled}
        data-tooltip-detail="Yes: later turns are set aside and their edits undone." onClick={() => void rewind()}>Yes</Button>
      <Button action="close" type="button" data-tooltip-detail="Keep the conversation as it is." onClick={() => setConfirming(false)}>No</Button>
    </span>}
    {status && <small role="status">{status}</small>}
  </span>
}
