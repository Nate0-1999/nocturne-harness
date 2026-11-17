import { useState } from 'react'
import { useRackPlugin } from './rack'
import { ConfirmButton, Select } from './kit'
import { failureMessage } from './requestFailure'
import { rewindNotice, type RewindScope } from './runEventDisplay'

export function RewindControl({ threadId, promptId, prompt, disabled, onRewound }: {
  threadId: string; promptId: string; prompt: string; disabled: boolean
  onRewound: (notice: string, returnedPrompt: string | null) => void
}) {
  const { events } = useRackPlugin()
  const [scope, setScope] = useState<RewindScope>('both')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  async function rewind() {
    setBusy(true)
    try {
      const result = await events.dispatch({ type: 'thread.rewind', thread_id: threadId, prompt_id: promptId, scope }) as { commits_kept?: unknown } | null
      const kept = Array.isArray(result?.commits_kept) ? result.commits_kept.filter((line): line is string => typeof line === 'string') : []
      setStatus('')
      onRewound(rewindNotice(scope, prompt, kept), scope === 'files' ? null : prompt)
    } catch (error) { setStatus(failureMessage(error, 'The thread was not rewound. Reload it and try again.')) }
    finally { setBusy(false) }
  }
  return <span className="rewind-control">
    <Select aria-label="Rewind scope" data-tooltip-detail="What a rewind restores: the chat, the files, or both." value={scope} disabled={busy || disabled}
      onChange={(event) => setScope(event.target.value as typeof scope)}>
      <option value="both">Chat + files</option><option value="conversation">Chat</option><option value="files">Files</option>
    </Select>
    {/* M3W5B-35: a rewind drops later turns and their file edits, so it asks first (ui-taste 4).
        M3W6B-21: the question opens under the controls, so the button just clicked stays put. */}
    <ConfirmButton action="restore" iconOnly type="button" disabled={busy || disabled}
      data-tooltip="Rewind to here"
      data-tooltip-detail="Return to before this turn. Asks first. Ignored files and real Git history stay unchanged."
      question="Rewind to before this turn?"
      lost={scope === 'files' ? 'File edits made after it are undone.' : scope === 'conversation' ? 'Later turns are set aside.' : 'Later turns are set aside and their file edits undone.'}
      onConfirm={() => void rewind()}>Rewind</ConfirmButton>
    {status && <small role="status">{status}</small>}
  </span>
}
