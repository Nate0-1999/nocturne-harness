import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'

import type { MemoryPanelState } from './store'
import type { MemoryPanelConflictPayload, MemoryUnit, Ulid } from './protocol'
import { ContributionBars, useContributionMap, useScorerAuditionMap } from './ContributionBars'
import { formatHumanScore } from './humanNumbers.ts'
import { useRackPlugin, useRackSelection, useRackSnapshot } from './rack'
import { ContextBars } from './ContextBars'

interface MemoryPanelProps {
  panel: MemoryPanelState
  connected: boolean
  removeEnabled: boolean
  mobileOpen: boolean
  inert: boolean
  onClose: () => void
  onRefresh: () => Promise<Ulid>
  onAdd: (memoryId: string) => Promise<Ulid>
  onRemove: (memoryId: string) => Promise<Ulid>
  onEdit: (memoryId: string, expectedRevision: number, body: string) => Promise<Ulid>
  onPin: (memoryId: string, expectedRevision: number, pin: boolean) => Promise<Ulid>
  onDelete: (memoryId: string, expectedRevision: number) => Promise<Ulid>
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
    case 'add':
      return 'Adding'
    case 'edit':
      return 'Saving'
    case 'pin':
      return 'Updating pin'
    case 'delete':
      return 'Deleting'
    default:
      return 'Working'
  }
}

function resultCopy(result: string): string {
  switch (result) {
    case 'removed':
      return 'Removed from this thread’s next model context.'
    case 'added':
      return 'Added and locked into this thread’s next model context.'
    case 'edited':
      return 'Memory body saved. This thread refreshes it before the next response.'
    case 'pin_changed':
      return 'Pin state updated for future injections.'
    case 'deleted':
      return 'Deleted from the Palace. Its revision history is preserved.'
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
  onAdd,
  onRemove,
  onEdit,
  onPin,
  onDelete,
}: MemoryPanelProps) {
  const contributions = useContributionMap()
  const auditions = useScorerAuditionMap()
  const rackSelection = useRackSelection()
  const { events } = useRackPlugin()
  const rack = useRackSnapshot()
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [deleting, setDeleting] = useState<MemoryUnit | null>(null)
  const deleteDialog = useRef<HTMLDialogElement>(null)
  const [clientError, setClientError] = useState<string | null>(null)
  const panelRef = useRef<HTMLElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const openedSelection = useRef<string | null>(null)
  const busy = panel.pending !== null
  const activeCount = panel.items.filter((item) => item.memory.status === 'active').length
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

  async function add(memoryId: string) {
    try {
      setClientError(null)
      await onAdd(memoryId)
    } catch (error) {
      reportClientError(error, 'Memory could not be re-added to context')
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

  async function deleteMemory() {
    if (deleting === null) return
    try {
      setClientError(null)
      await onDelete(deleting.memory_id, deleting.revision)
      deleteDialog.current?.close()
      setDeleting(null)
    } catch (error) {
      reportClientError(error, 'Memory could not be deleted')
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

  useEffect(() => {
    if (rackSelection?.kind !== 'memory') { openedSelection.current = null; return }
    if (openedSelection.current === rackSelection.id) return
    const selected = panel.items.find((item) => item.memory.memory_id === rackSelection.id)?.memory
    if (selected !== undefined && selected.status === 'active') {
      openedSelection.current = selected.memory_id
      queueMicrotask(() => {
        setClientError(null)
        setEditor({
          memoryId: selected.memory_id, label: memoryTitle(selected), body: selected.body,
          expectedRevision: selected.revision, requestId: null,
        })
      })
    }
  }, [panel.items, rackSelection])

  async function saveEdit() {
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

  function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void saveEdit()
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
        <h2 id="memory-panel-title">Memory</h2>
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
          <strong>{activeCount}</strong>
          <span>{activeCount === 1 ? ' active unit' : ' active units'}</span>
          {panel.items.length > activeCount && <span> · {panel.items.length - activeCount} retained in context</span>}
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
        {response?.action === 'conflict' && response.operation === 'delete' && (
          <p role="alert">This memory changed before deletion. Refresh, review its latest version, and delete again.</p>
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
            <h3>Loading memories</h3>
            <p>Loading memories from your Palace.</p>
          </div>
        ) : panel.items.length === 0 ? (
          <div className="memory-panel__empty" data-testid="memory-empty">
            <p className="eyebrow">Nothing stored</p>
            <h3>No active memories</h3>
            <p>Memories saved in conversation will appear here.</p>
          </div>
        ) : (
          <div className="memory-panel__list" data-testid="memory-list">
            {panel.items.map(({ memory, score, revisions, near_miss: nearMiss, in_context: inContext, thread_excluded: threadExcluded }) => {
              const origin = memory.origin_thread_id ?? memory.thread_origin
              const originThread = rack.catalog.find((thread) => thread.thread_id === origin)
              const editing =
                editor?.memoryId === memory.memory_id
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
                        <span className="memory-badge">{nearMiss ? 'Near miss · suggestion' : 'Stored'}</span>
                      )}
                      {unavailable && (
                        <span
                          className="memory-badge memory-badge--unavailable"
                          data-testid="memory-unavailable"
                        >
                          {inContext && revisions?.some((revision) => String(revision.reason).includes('supersede'))
                            ? 'Superseded after injection · retained in this conversation'
                            : `Unavailable · ${memory.status}`}
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

                  <p className="principal-memory__where" data-testid="memory-origin-location">
                    WHERE · {memory.origin_location ?? 'Older memory · location unavailable'}
                  </p>
                  <p>Project · {memory.project_key ?? 'No project'}</p>
                  <p>Thread · {originThread?.title ?? origin ?? 'No origin thread'}</p>
                  <p>Keywords · {memory.keywords.join(', ') || 'None recorded'}</p>
                  {originThread !== undefined && <div className="principal-memory__actions"><button type="button" onClick={() => {
                    void events.dispatch({ type: 'thread.select', thread_id: originThread.thread_id })
                      .catch((error: unknown) => reportClientError(error, 'Origin conversation could not be opened'))
                  }}>Open the conversation</button></div>}
                  <details><summary>Revision history · r{memory.revision}</summary>
                    {(revisions?.length ?? 0) === 0 ? <p>History unavailable.</p> : <ol>
                      {revisions?.map((revision) => <li key={String(revision.rev_uid)}>
                        r{String(revision.revision ?? '—')} · {String(revision.reason)} · {String(revision.ts)}
                        {typeof revision.body === 'string' && <blockquote>{revision.body}</blockquote>}
                      </li>)}
                    </ol>}
                  </details>
                  <p aria-label="Current context score">Score · {score == null ? 'Unavailable' : formatHumanScore(score)}</p>

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
                          Saved. Per-message scoring refreshes this thread
                          before the next response.
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
                            type="button"
                            disabled={
                              !connected ||
                              busy ||
                              !editor.body.trim() ||
                              (editConflict !== null &&
                                editConflict.memory.status !== 'active')
                            }
                            onClick={() => { void saveEdit() }}
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
                      {auditions[memory.memory_id] !== undefined && <p className="scorer-preview-mark">Audition: {formatHumanScore(auditions[memory.memory_id].preview_score)} · #{auditions[memory.memory_id].preview_rank} {auditions[memory.memory_id].disposition.replace('_', ' ')}</p>}
                      {contributions[memory.memory_id] !== undefined && <ContributionBars values={contributions[memory.memory_id]} />}
                      <div className="principal-memory__actions">
                        <button
                          type="button"
                          disabled={!connected || busy || unavailable}
                          onClick={() => beginEdit(memory)}
                          aria-label="Edit body"
                          title="Edit body"
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          aria-pressed={memory.pin}
                          aria-label={memory.pin ? 'Unpin' : 'Pin'}
                          title={memory.pin ? 'Unpin' : 'Pin'}
                          disabled={!connected || busy || unavailable}
                          onClick={() => togglePin(memory)}
                        >
                          <span aria-hidden="true">⚑</span>
                        </button>
                        <button type="button" aria-label="Delete memory" title="Delete memory"
                          disabled={!connected || busy || unavailable}
                          onClick={() => { setDeleting(memory); deleteDialog.current?.showModal() }}>
                          <span aria-hidden="true">⌫</span>
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
                        {(threadExcluded || nearMiss) && (
                          <button
                            className="principal-memory__primary"
                            type="button"
                            disabled={!connected || !removeEnabled || busy || unavailable}
                            onClick={() => add(memory.memory_id)}
                          >
                            {nearMiss ? 'Add to context' : 'Re-add'}
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
      <dialog ref={deleteDialog} aria-labelledby="delete-memory-title" className="memory-restore-dialog"
        onClose={() => setDeleting(null)}>
        <h2 id="delete-memory-title">Delete this memory from the Palace?</h2>
        <p><strong>{deleting?.label}</strong></p>
        <p>{deleting?.body}</p>
        <p>It will no longer be offered to conversations. Its history is preserved and can be restored; this does not erase past conversations.</p>
        <button type="button" onClick={() => deleteDialog.current?.close()}>Cancel</button>
        <button type="button" disabled={!connected || busy || deleting === null} onClick={() => void deleteMemory()}>Delete from Palace</button>
      </dialog>
    </aside>
  )
}

export function MemoryTrace() {
  const rack = useRackSnapshot()
  const { events } = useRackPlugin()
  const [error, setError] = useState<string | null>(null)
  const thread = rack.selectedThreadId === null ? null : rack.threads[rack.selectedThreadId]
  if (thread === null || thread === undefined) return <p>Select a conversation to inspect its memory trace.</p>
  const panel = thread.memoryPanel
  const items = panel.items.filter((item) => item.in_context || item.near_miss || item.thread_excluded)
  const disabled = rack.connection !== 'connected' || thread.awaitingSnapshot || thread.activeRun !== null || panel.pending !== null
  function change(type: 'memory.add' | 'memory.remove', memoryId: string) {
    setError(null)
    void events.dispatch({ type, memory_id: memoryId }).catch(() => setError('The memory change could not be sent. Try again.'))
  }
  return <section aria-label="Selected conversation memory trace">
    <h2>Memory trace</h2>
    <ContextBars />
    {error && <p role="alert">{error}</p>}
    {panel.lastResponse?.action === 'error' && <p role="alert">{panel.lastResponse.message}</p>}
    {items.length === 0 && <p>This conversation has no injected memories or near-miss suggestions.</p>}
    {items.map((item) => <article key={item.memory.memory_id}>
      <h3>{item.memory.label} · {item.in_context ? 'In context' : item.near_miss ? 'Near miss' : 'Removed'}</h3>
      <p>{item.memory.body}</p>
      <button type="button" disabled={disabled || (!item.in_context && item.memory.status !== 'active')}
        onClick={() => change(item.in_context ? 'memory.remove' : 'memory.add', item.memory.memory_id)}>
        {item.in_context ? 'Pop off' : item.near_miss ? 'Add to context' : 'Re-add'}
      </button>
    </article>)}
  </section>
}

export function SelectedMemoryPanel({ memoryId }: { memoryId: string }) {
  const rack = useRackSnapshot()
  const { events } = useRackPlugin()
  const thread = rack.selectedThreadId === null ? null : rack.threads[rack.selectedThreadId]
  if (thread === null || thread === undefined) return <p>Select a conversation to inspect its memories.</p>
  const items = thread.memoryPanel.items.filter((item) => item.memory.memory_id === memoryId)
  if (items.length === 0) return <p>This memory is not active in the Palace.</p>
  return <MemoryPanel panel={{ ...thread.memoryPanel, items, total: items.length }}
    connected={rack.connection === 'connected' && !thread.awaitingSnapshot}
    removeEnabled={thread.activeRun === null} mobileOpen={false} inert={false} onClose={() => {}}
    onRefresh={() => events.dispatch({ type: 'memory.refresh' })}
    onAdd={(id) => events.dispatch({ type: 'memory.add', memory_id: id })}
    onRemove={(id) => events.dispatch({ type: 'memory.remove', memory_id: id })}
    onEdit={(id, revision, body) => events.dispatch({ type: 'memory.edit', memory_id: id, expected_revision: revision, body })}
    onPin={(id, revision, pin) => events.dispatch({ type: 'memory.pin', memory_id: id, expected_revision: revision, pin })}
    onDelete={(id, revision) => events.dispatch({ type: 'memory.delete', memory_id: id, expected_revision: revision })}
  />
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
