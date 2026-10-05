import { useState } from 'react'
import { useRackPlugin } from './rack'
import { Button, Select } from './kit'
import { rewindNotice, type RewindScope } from './runEventDisplay'

export function RewindControl({ threadId, promptId, prompt, disabled, onRewound }: {
  threadId: string; promptId: string; prompt: string; disabled: boolean
  onRewound: (notice: string, returnedPrompt: string | null) => void
}) {
  const { events } = useRackPlugin()
  const [scope, setScope] = useState<RewindScope>('both')
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [status, setStatus] = useState('')
  async function rewind() {
    setConfirming(false)
    setBusy(true)
    try {
      const result = await events.dispatch({ type: 'thread.rewind', thread_id: threadId, prompt_id: promptId, scope }) as { commits_kept?: unknown } | null
      const kept = Array.isArray(result?.commits_kept) ? result.commits_kept.filter((line): line is string => typeof line === 'string') : []
      setStatus('')
      onRewound(rewindNotice(scope, prompt, kept), scope === 'files' ? null : prompt)
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Rewind failed') }
    finally { setBusy(false) }
  }
  return <span className="rewind-control">
    {/* M3W5B-35: a rewind drops later turns and their file edits, so it asks first (ui-taste 4).
        M3W6B-21: the question opens before the controls, so the button just clicked stays under
        the pointer instead of "No" sliding beneath it and its tip covering the prompt. */}
    {confirming && <span className="rewind-control__confirm" role="dialog" aria-label="Rewind to before this turn?">
      <span>Rewind here?</span>
      <Button action="confirm" variant="danger" type="button" autoFocus disabled={busy || disabled}
        data-tooltip-detail="Yes: later turns are set aside and their edits undone." onClick={() => void rewind()}>Yes</Button>
      <Button action="close" type="button" data-tooltip-detail="Keep the conversation as it is." onClick={() => setConfirming(false)}>No</Button>
    </span>}
    <Select aria-label="Rewind scope" data-tooltip-detail="What a rewind restores: the chat, the files, or both." value={scope} disabled={busy || disabled}
      onChange={(event) => setScope(event.target.value as typeof scope)}>
      <option value="both">Chat + files</option><option value="conversation">Chat</option><option value="files">Files</option>
    </Select>
    <Button action="restore" iconOnly type="button" disabled={busy || disabled} onClick={() => setConfirming(true)}
      data-tooltip="Rewind to here" aria-haspopup="dialog" aria-expanded={confirming}
      data-tooltip-detail="Return to before this turn. Asks first. Ignored files and real Git history stay unchanged.">Rewind</Button>
    {status && <small role="status">{status}</small>}
  </span>
}
