import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'

import type { MemoryPanelState } from './store'
import type { MemoryPanelConflictPayload, MemoryUnit, Ulid } from './protocol'

interface MemoryPanelProps {
  panel: MemoryPanelState
  connected: boolean
  removeEnabled: boolean
  mobileOpen: boolean
  inert: boolean
  onClose: () => void
  onRefresh: () => Promise<Ulid>
  onRemove: (memoryId: string) => Promise<Ulid>
  onEdit: (memoryId: string, expectedRevision: number, body: string) => Promise<Ulid>
  onPin: (memoryId: string, expectedRevision: number, pin: boolean) => Promise<Ulid>
}

interface EditorState {
  memoryId: string
  label: string
  body: string
  expectedRevision: number
  requestId: Ulid | null
}

const FOCUSABLE =
  'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'

function operationCopy(operation: string): string {
  switch (operation) {
    case 'refresh':
      return 'Refreshing'
    case 'remove':
      return 'Removing'
    case 'edit':
      return 'Saving'
    case 'pin':
      return 'Updating pin'
    default:
      return 'Working'
  }
}

function resultCopy(result: string): string {
  switch (result) {
    case 'removed':
      return 'Removed from this thread’s next model context.'
    case 'edited':
      return 'Memory body saved for future injections. This thread keeps its committed copy.'
    case 'pin_changed':
      return 'Pin state updated for future injections.'
    default:
      return ''
  }
}

function memoryTitle(memory: MemoryUnit): string {
  return memory.label.trim() || 'Untitled memory'
}

export function MemoryPanel({
  panel,
  connected,
  removeEnabled,
  mobileOpen,
  inert,
  onClose,
  onRefresh,
  onRemove,
  onEdit,
  onPin,
}: MemoryPanelProps) {
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [clientError, setClientError] = useState<string | null>(null)
  const panelRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const busy = panel.pending !== null
  const response = panel.lastResponse
  const editorResponse =
    editor?.requestId !== null &&
    editor?.requestId !== undefined &&
    response?.request_id === editor.requestId
      ? response
      : null
  const editConflict =
    editorResponse?.action === 'conflict' && editorResponse.operation === 'edit'
      ? editorResponse
      : null
  const editError =
    editorResponse?.action === 'error' && editorResponse.operation === 'edit'
      ? editorResponse
      : null
  const editSaved =
    editor?.requestId !== null &&
    editor?.requestId !== undefined &&
    panel.completedEditRequestId === editor.requestId
  const pinConflict =
    response?.action === 'conflict' && response.operation === 'pin'
      ? response
      : null
  const panelError = response?.action === 'error' ? response : null
  const panelNotice =
    response?.action === 'state' ? resultCopy(response.result) : ''

  useEffect(() => {
    if (!mobileOpen) {
      return
    }
    const panelElement = panelRef.current
    globalThis.requestAnimationFrame(() => closeRef.current?.focus())

    const containFocus = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || panelElement === null) {
        return
      }
      const focusable = Array.from(
        panelElement.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((element) => element.offsetParent !== null)
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    globalThis.addEventListener('keydown', containFocus)
    return () => globalThis.removeEventListener('keydown', containFocus)
  }, [mobileOpen, onClose])

  function reportClientError(error: unknown, fallback: string) {
    setClientError(error instanceof Error ? error.message : fallback)
  }

  async function refresh() {
    try {
      setClientError(null)
      await onRefresh()
    } catch (error) {
      reportClientError(error, 'Memories could not be refreshed')
    }
  }

  async function remove(memoryId: string) {
    try {
      setClientError(null)
      await onRemove(memoryId)
    } catch (error) {
      reportClientError(error, 'Memory could not be removed from context')
    }
  }

  async function togglePin(memory: MemoryUnit) {
    if (memory.status !== 'active') {
      setClientError('This memory is unavailable. Refresh before taking another action.')
      return
    }
    try {
      setClientError(null)
      await onPin(memory.memory_id, memory.revision, !memory.pin)
    } catch (error) {
      reportClientError(error, 'Pin state could not be updated')
    }
  }

  function beginEdit(memory: MemoryUnit) {
    if (memory.status !== 'active') {
      setClientError('This memory is unavailable. Refresh before taking another action.')
      return
    }
    setClientError(null)
    setEditor({
      memoryId: memory.memory_id,
      label: memoryTitle(memory),
      body: memory.body,
      expectedRevision: memory.revision,
      requestId: null,
    })
  }

  async function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (editor === null || !editor.body.trim() || editSaved) {
      return
    }
    const currentMemory = editConflict?.memory
    if (currentMemory !== undefined && currentMemory.status !== 'active') {
      return
    }
    const expectedRevision =
      currentMemory?.revision ?? editor.expectedRevision
    try {
      setClientError(null)
      const requestId = await onEdit(
        editor.memoryId,
        expectedRevision,
        editor.body,
      )
      setEditor({
        ...editor,
        expectedRevision,
        requestId,
      })
    } catch (error) {
      reportClientError(error, 'Memory body could not be saved')
    }
  }

  function onEditorKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      setEditor(null)
    }
  }

  return (
    <aside
      ref={panelRef}
      className={`memory-panel${mobileOpen ? ' memory-panel--open' : ''}`}
      aria-labelledby="memory-panel-title"
      aria-modal={mobileOpen || undefined}
      role={mobileOpen ? 'dialog' : undefined}
      inert={inert || undefined}
      data-testid="memory-panel"
    >
      <header className="memory-panel__header">
        <div>
          <p className="eyebrow">Current principal</p>
          <h2 id="memory-panel-title">Memory</h2>
        </div>
        <button
          ref={closeRef}
          className="memory-panel__close"
          type="button"
          aria-label="Close memory drawer"
          onClick={onClose}
        >
          Back
        </button>
      </header>

      <div className="memory-panel__toolbar">
        <p>
          <strong>{panel.total}</strong>
          <span>{panel.total === 1 ? ' active unit' : ' active units'}</span>
        </p>
        <button
          type="button"
          data-testid="memory-refresh"
          disabled={!connected || busy}
          onClick={refresh}
        >
          {panel.pending?.operation === 'refresh' ? 'Refreshing' : 'Refresh'}
        </button>
      </div>

      <div className="memory-panel__feedback" aria-live="polite">
        {panel.pending !== null && (
          <p className="memory-panel__pending">
            {operationCopy(panel.pending.operation)}…
          </p>
        )}
        {clientError !== null && (
          <p className="memory-panel__alert" role="alert">
            {clientError}
          </p>
        )}
        {panelError !== null && (
          <p className="memory-panel__alert" role="alert">
            {panelError.message}
          </p>
        )}
        {pinConflict !== null && (
          <PinConflictNotice conflict={pinConflict} />
        )}
        {panelNotice && panel.pending === null && (
          <p className="memory-panel__notice">{panelNotice}</p>
        )}
        {!removeEnabled &&
          panel.items.some((item) => item.in_context) &&
          panel.pending === null && (
            <p className="memory-panel__notice">
              Finish or stop the active response before removing context.
            </p>
          )}
      </div>

      <div
        className="memory-panel__content"
        aria-busy={panel.status === 'loading' || busy}
      >
        {(panel.status === 'idle' || panel.status === 'loading') &&
        panel.items.length === 0 ? (
          <div className="memory-panel__empty" data-testid="memory-loading">
            <p className="eyebrow">Authoritative state</p>
            <h3>Loading memories</h3>
            <p>Waiting for the daemon’s current-principal view.</p>
          </div>
        ) : panel.items.length === 0 ? (
          <div className="memory-panel__empty" data-testid="memory-empty">
            <p className="eyebrow">Nothing stored</p>
            <h3>No active memories</h3>
            <p>Memories saved in conversation will appear here.</p>
          </div>
        ) : (
          <div className="memory-panel__list" data-testid="memory-list">
            {panel.items.map(({ memory, in_context: inContext }) => {
              const editing =
                editor?.memoryId === memory.memory_id && !editSaved
              const unavailable = memory.status !== 'active'
              return (
                <article
                  key={memory.memory_id}
                  className={`principal-memory${
                    inContext ? ' principal-memory--context' : ''
                  }${
                    unavailable ? ' principal-memory--unavailable' : ''
                  }`}
                >
                  <header className="principal-memory__header">
                    <h3>{memoryTitle(memory)}</h3>
                    <div
                      className="principal-memory__badges"
                      aria-label="Memory state"
                    >
                      {inContext && (
                        <span className="memory-badge memory-badge--context">
                          In context
                        </span>
                      )}
                      {!inContext && !unavailable && (
                        <span className="memory-badge">Stored</span>
                      )}
                      {unavailable && (
                        <span
                          className="memory-badge memory-badge--unavailable"
                          data-testid="memory-unavailable"
                        >
                          Unavailable · {memory.status}
                        </span>
                      )}
                      {memory.pin && (
                        <span className="memory-badge memory-badge--pinned">
                          Pinned
                        </span>
                      )}
                      <span className="memory-badge">{memory.kind}</span>
                      <span className="memory-badge">r{memory.revision}</span>
                    </div>
                  </header>

                  {editing && editor !== null ? (
                    <form
                      className="principal-memory__editor"
                      onSubmit={submitEdit}
                    >
                      <label htmlFor={`memory-body-${memory.memory_id}`}>
                        Memory body
                      </label>
                      <textarea
                        id={`memory-body-${memory.memory_id}`}
                        value={editor.body}
                        aria-invalid={!editor.body.trim() || undefined}
                        autoFocus
                        disabled={busy || editSaved}
                        onChange={(event) =>
                          setEditor({ ...editor, body: event.target.value })
                        }
                        onKeyDown={onEditorKeyDown}
                      />
                      {editConflict !== null && (
                        <div
                          className="memory-edit-conflict"
                          role="alert"
                          data-testid="memory-edit-conflict"
                        >
                          <strong>Revision conflict</strong>
                          <p>{editConflict.message}</p>
                          <p>
                            The current stored body is revision{' '}
                            {editConflict.memory.revision}:
                          </p>
                          <blockquote>{editConflict.memory.body}</blockquote>
                          {editConflict.memory.status === 'active' ? (
                            <p>
                              Your draft is preserved. Review both versions,
                              then retry explicitly.
                            </p>
                          ) : (
                            <p>
                              Your draft is preserved here, but this memory is
                              now {editConflict.memory.status} and cannot be
                              edited. Refresh to clear this transient row.
                            </p>
                          )}
                        </div>
                      )}
                      {editError !== null && (
                        <p className="memory-panel__alert" role="alert">
                          {editError.message}
                        </p>
                      )}
                      {editSaved && (
                        <p className="memory-panel__notice" role="status">
                          Saved for future injections. This thread keeps its
                          committed copy.
                        </p>
                      )}
                      <div className="principal-memory__editor-actions">
                        <button
                          type="button"
                          onClick={() => setEditor(null)}
                        >
                          {editSaved ? 'Done' : 'Cancel'}
                        </button>
                        {!editSaved && (
                          <button
                            className="principal-memory__primary"
                            type="submit"
                            disabled={
                              !connected ||
                              busy ||
                              !editor.body.trim() ||
                              (editConflict !== null &&
                                editConflict.memory.status !== 'active')
                            }
                          >
                            {editConflict !== null || editError !== null
                              ? 'Retry save'
                              : 'Save body'}
                          </button>
                        )}
                      </div>
                    </form>
                  ) : (
                    <>
                      <p className="principal-memory__body">{memory.body}</p>
                      <div className="principal-memory__actions">
                        <button
                          type="button"
                          disabled={!connected || busy || unavailable}
                          onClick={() => beginEdit(memory)}
                        >
                          Edit body
                        </button>
                        <button
                          type="button"
                          aria-pressed={memory.pin}
                          disabled={!connected || busy || unavailable}
                          onClick={() => togglePin(memory)}
                        >
                          {memory.pin ? 'Unpin' : 'Pin'}
                        </button>
                        {inContext && (
                          <button
                            className="principal-memory__remove"
                            type="button"
                            disabled={!connected || !removeEnabled || busy}
                            onClick={() => remove(memory.memory_id)}
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </div>
    </aside>
  )
}

function PinConflictNotice({
  conflict,
}: {
  conflict: MemoryPanelConflictPayload
}) {
  return (
    <div
      className="memory-panel__alert memory-panel__alert--block"
      role="alert"
      data-testid="memory-pin-conflict"
    >
      <strong>Pin conflict</strong>
      <p>{conflict.message}</p>
      {conflict.memory.status === 'active' ? (
        <p>
          Current state: {conflict.memory.pin ? 'pinned' : 'not pinned'},
          revision {conflict.memory.revision}. Choose the action again to retry.
        </p>
      ) : (
        <p>
          This memory is now {conflict.memory.status} and unavailable. Refresh
          before taking another action.
        </p>
      )}
    </div>
  )
}
