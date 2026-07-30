import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react'

import { AssistantMarkdown } from './AssistantMarkdown'
import { harnessClient } from './socket'
import { useHarnessStore, type MemoryPanelState } from './store'
import { MemoryGate } from './MemoryGate'
import { MemoryPanel } from './MemoryPanel'
import type {
  AssistantTranscriptMessage,
  ChatMessage,
  UserMessageState,
} from './protocol'

const EMPTY_MESSAGES: ChatMessage[] = []
const EMPTY_MEMORY_PANEL: MemoryPanelState = {
  items: [],
  total: 0,
  status: 'idle',
  pending: null,
  lastResponse: null,
  completedEditRequestId: null,
}

function shortId(value: string): string {
  return value.slice(0, 8).toUpperCase()
}

function connectionCopy(connection: string): string {
  switch (connection) {
    case 'connected':
      return 'Link live'
    case 'connecting':
      return 'Connecting'
    case 'reconnecting':
      return 'Resyncing'
    default:
      return 'Offline'
  }
}

function terminalCopy(reason: UserMessageState): string | null {
  switch (reason) {
    case 'cancelled':
      return 'Stopped · partial kept'
    case 'budget_exceeded':
      return 'Budget limit reached · partial kept'
    case 'error':
      return 'Run error · partial kept'
    default:
      return null
  }
}

function messageStatus(
  message: AssistantTranscriptMessage,
  state: UserMessageState | undefined,
  activeRunId: string | undefined,
  activeState: string | undefined,
): string | null {
  if (activeRunId === message.run_id) {
    if (activeState === 'cancelling') {
      return 'Stopping'
    }
    return activeState === 'waiting_gate' ? 'Waiting for memory review' : 'Streaming'
  }
  return state === undefined ? (message.partial ? 'Partial' : null) : terminalCopy(state)
}

function App() {
  const catalog = useHarnessStore((state) => state.catalog)
  const selectedThreadId = useHarnessStore((state) => state.selectedThreadId)
  const threads = useHarnessStore((state) => state.threads)
  const connection = useHarnessStore((state) => state.connection)
  const globalError = useHarnessStore((state) => state.globalError)
  const selectedThread = selectedThreadId === null ? null : threads[selectedThreadId]
  const selectedMeta = catalog.find((entry) => entry.thread_id === selectedThreadId)
  const [draft, setDraft] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [memoryDrawerOpen, setMemoryDrawerOpen] = useState(false)
  const [hasUnread, setHasUnread] = useState(false)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const mobileThreadsRef = useRef<HTMLButtonElement>(null)
  const mobileMemoriesRef = useRef<HTMLButtonElement>(null)
  const railCloseRef = useRef<HTMLButtonElement>(null)
  const followOutputRef = useRef(true)
  const drawerWasOpenRef = useRef(false)
  const memoryDrawerWasOpenRef = useRef(false)

  const sortedCatalog = useMemo(
    () => [...catalog].sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
    [catalog],
  )
  const messages = useMemo(() => {
    if (selectedThread === null) {
      return EMPTY_MESSAGES
    }
    const represented = new Set(
      selectedThread.messages.map((message) => message.message_id),
    )
    const optimistic: ChatMessage[] = selectedThread.outboundPrompts
      .filter((outbound) => !represented.has(outbound.prompt_id))
      .map((outbound) => ({
        message_id: outbound.prompt_id,
        run_id: null,
        role: 'user',
        content: outbound.prompt,
        state: 'submitting',
      }))
    return optimistic.length === 0
      ? selectedThread.messages
      : [...selectedThread.messages, ...optimistic]
  }, [selectedThread])
  const activeRun = selectedThread?.activeRun ?? null
  const openGate = selectedThread?.openGate ?? null
  const memoryPanel = selectedThread?.memoryPanel ?? EMPTY_MEMORY_PANEL
  const queuedPrompts = selectedThread?.queuedPrompts ?? []
  const awaitingSnapshot = selectedThread?.awaitingSnapshot ?? true
  const canSend =
    connection === 'connected' &&
    !awaitingSnapshot &&
    openGate === null &&
    draft.trim().length > 0
  const closeMemoryDrawer = useCallback(() => setMemoryDrawerOpen(false), [])

  const runStates = useMemo(() => {
    const states = new Map<string, UserMessageState>()
    for (const message of messages) {
      if (message.role === 'user' && message.run_id !== null) {
        states.set(message.run_id, message.state)
      }
    }
    return states
  }, [messages])

  useEffect(() => {
    harnessClient.connect()
    const state = useHarnessStore.getState()
    if (state.catalog.length === 0) {
      harnessClient.createThread()
    } else if (state.selectedThreadId === null) {
      harnessClient.selectThread(state.catalog[0].thread_id)
    } else {
      harnessClient.requestSnapshot(state.selectedThreadId)
    }
    return () => harnessClient.disconnect()
  }, [])

  useEffect(() => {
    followOutputRef.current = true
    globalThis.requestAnimationFrame(() => {
      const transcript = transcriptRef.current
      if (transcript !== null) {
        transcript.scrollTop = transcript.scrollHeight
      }
    })
  }, [selectedThreadId])

  useEffect(() => {
    const transcript = transcriptRef.current
    if (transcript === null || messages.length === 0) {
      return
    }
    if (followOutputRef.current) {
      globalThis.requestAnimationFrame(() => {
        transcript.scrollTop = transcript.scrollHeight
      })
    } else {
      setHasUnread(true)
    }
  }, [messages])

  useEffect(() => {
    const composer = composerRef.current
    if (composer === null) {
      return
    }
    composer.style.height = 'auto'
    composer.style.height = `${Math.min(composer.scrollHeight, 144)}px`
  }, [draft])

  useEffect(() => {
    if (drawerOpen) {
      drawerWasOpenRef.current = true
      globalThis.requestAnimationFrame(() => railCloseRef.current?.focus())
      const closeOnEscape = (event: globalThis.KeyboardEvent) => {
        if (event.key === 'Escape') {
          setDrawerOpen(false)
        }
      }
      globalThis.addEventListener('keydown', closeOnEscape)
      return () => globalThis.removeEventListener('keydown', closeOnEscape)
    }

    if (drawerWasOpenRef.current) {
      drawerWasOpenRef.current = false
      globalThis.requestAnimationFrame(() => mobileThreadsRef.current?.focus())
    }
  }, [drawerOpen])

  useEffect(() => {
    if (memoryDrawerOpen) {
      memoryDrawerWasOpenRef.current = true
      return
    }
    if (memoryDrawerWasOpenRef.current) {
      memoryDrawerWasOpenRef.current = false
      globalThis.requestAnimationFrame(() => mobileMemoriesRef.current?.focus())
    }
  }, [memoryDrawerOpen])

  function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSend) {
      return
    }
    const prompt = draft.trim()
    try {
      harnessClient.submitPrompt(prompt)
      setDraft('')
      followOutputRef.current = true
      setHasUnread(false)
    } catch (error) {
      useHarnessStore
        .getState()
        .setTransportError(error instanceof Error ? error.message : 'Prompt could not be sent')
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      formRef.current?.requestSubmit()
    }
  }

  function createThread() {
    harnessClient.createThread()
    setDrawerOpen(false)
    setMemoryDrawerOpen(false)
    setDraft('')
    setHasUnread(false)
  }

  function selectThread(threadId: string) {
    harnessClient.selectThread(threadId)
    setDrawerOpen(false)
    setMemoryDrawerOpen(false)
    setDraft('')
    setHasUnread(false)
  }

  function cancelRun() {
    if (activeRun === null || activeRun.state === 'cancelling') {
      return
    }
    try {
      harnessClient.cancelRun(activeRun.run_id)
    } catch (error) {
      useHarnessStore
        .getState()
        .setTransportError(error instanceof Error ? error.message : 'Run could not be stopped')
    }
  }

  function onTranscriptScroll() {
    const transcript = transcriptRef.current
    if (transcript === null) {
      return
    }
    const nearBottom =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 96
    followOutputRef.current = nearBottom
    if (nearBottom) {
      setHasUnread(false)
    }
  }

  function scrollToLatest() {
    const transcript = transcriptRef.current
    if (transcript === null) {
      return
    }
    followOutputRef.current = true
    setHasUnread(false)
    transcript.scrollTo({ top: transcript.scrollHeight })
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label="Harness">
          <span className="brand__mark" aria-hidden="true">H</span>
          <span className="brand__word">Harness</span>
          <span className="brand__mode">M1 direct</span>
        </div>

        <div className="mobile-navigation">
          <button
            ref={mobileThreadsRef}
            className="mobile-threads"
            type="button"
            data-testid="mobile-threads"
            aria-expanded={drawerOpen}
            onClick={() => {
              setMemoryDrawerOpen(false)
              setDrawerOpen(true)
            }}
          >
            Threads
            <span>{catalog.length.toString().padStart(2, '0')}</span>
          </button>
          <button
            ref={mobileMemoriesRef}
            className="mobile-memories"
            type="button"
            data-testid="mobile-memories"
            aria-expanded={memoryDrawerOpen}
            onClick={() => {
              setDrawerOpen(false)
              setMemoryDrawerOpen(true)
            }}
          >
            Memory
            <span>{memoryPanel.total}</span>
          </button>
        </div>

        <p className={`connection connection--${connection}`} data-testid="connection" aria-live="polite">
          <span className="connection__signal" aria-hidden="true" />
          {connectionCopy(connection)}
        </p>
      </header>

      <div className="workspace">
        {(drawerOpen || memoryDrawerOpen) && (
          <button
            className="drawer-scrim"
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            onClick={() => {
              setDrawerOpen(false)
              setMemoryDrawerOpen(false)
            }}
          />
        )}

        <aside
          className={`thread-rail${drawerOpen ? ' thread-rail--open' : ''}`}
          aria-labelledby="thread-rail-title"
          inert={memoryDrawerOpen || openGate !== null || undefined}
        >
          <div className="thread-rail__header">
            <div>
              <p className="eyebrow">Local navigation</p>
              <h2 id="thread-rail-title">Threads</h2>
            </div>
            <button
              ref={railCloseRef}
              className="rail-close"
              type="button"
              data-testid="mobile-close-threads"
              aria-label="Close threads"
              onClick={() => setDrawerOpen(false)}
            >
              Back
            </button>
          </div>

          <button className="new-thread" type="button" data-testid="new-thread" onClick={createThread}>
            <span aria-hidden="true">＋</span>
            New thread
          </button>

          <nav className="thread-list" data-testid="thread-list" aria-label="Known threads">
            {sortedCatalog.map((entry) => {
              const runtime = threads[entry.thread_id]
              const isSelected = entry.thread_id === selectedThreadId
              const liveState = runtime?.activeRun?.state
              const queueCount = runtime?.queuedPrompts.length ?? 0
              const outboundCount = runtime?.outboundPrompts.length ?? 0
              const detail =
                runtime?.awaitingSnapshot
                  ? 'Not loaded'
                  : liveState === 'cancelling'
                  ? 'Stopping'
                  : liveState === 'waiting_gate'
                    ? 'Review memory'
                  : liveState !== undefined
                    ? 'Live'
                    : outboundCount > 0
                      ? 'Sending'
                    : queueCount > 0
                      ? `${queueCount} queued`
                      : runtime?.messages.length
                        ? `${runtime.messages.length} messages`
                        : 'Empty'
              return (
                <button
                  key={entry.thread_id}
                  className={`thread-item${isSelected ? ' thread-item--selected' : ''}`}
                  type="button"
                  data-thread-id={entry.thread_id}
                  aria-current={isSelected ? 'page' : undefined}
                  onClick={() => selectThread(entry.thread_id)}
                >
                  <span className="thread-item__title">{entry.title}</span>
                  <span className="thread-item__meta">
                    <span>{detail}</span>
                    <span>{shortId(entry.thread_id)}</span>
                  </span>
                </button>
              )
            })}
          </nav>

          <p className="catalog-note">
            This list is browser-local. The daemon snapshot remains authoritative.
          </p>
        </aside>

        <main
          className="chat-panel"
          aria-labelledby="thread-title"
          inert={
            drawerOpen || memoryDrawerOpen || openGate !== null || undefined
          }
        >
          <header className="chat-header">
            <div className="chat-header__identity">
              <p className="eyebrow">Current thread</p>
              <h1 id="thread-title">{selectedMeta?.title ?? 'Opening thread'}</h1>
            </div>
            <div className="run-metrics" aria-label="Run status">
              {activeRun !== null && (
                <span className={`run-state run-state--${activeRun.state}`}>
                  {activeRun.state === 'cancelling'
                    ? 'Stopping'
                    : activeRun.state === 'waiting_gate'
                      ? 'Memory review'
                      : 'Run active'}
                </span>
              )}
              {queuedPrompts.length > 0 && <span>{queuedPrompts.length} queued</span>}
              {selectedThread?.usage !== null && selectedThread?.usage !== undefined && (
                <span data-testid="usage">
                  {selectedThread.usage.requests} req · {selectedThread.usage.input_tokens} in ·{' '}
                  {selectedThread.usage.output_tokens} out
                </span>
              )}
              {selectedThreadId !== null && <span>{shortId(selectedThreadId)}</span>}
            </div>
            <p
              className="chat-header__model"
              data-testid="active-model"
              aria-label={`Active model: ${selectedThread?.resolvedModel ?? 'awaiting daemon'}`}
            >
              <span aria-hidden="true">Model</span>
              <span className="chat-header__model-value">
                {selectedThread?.resolvedModel ?? 'Awaiting daemon'}
              </span>
            </p>
          </header>

          {(globalError !== null || selectedThread?.lastError !== null) && (
            <div className="error-line" role="status" data-testid="error-line">
              <span aria-hidden="true">!</span>
              {selectedThread?.lastError?.message ?? globalError?.message}
            </div>
          )}

          <div
            className="transcript"
            ref={transcriptRef}
            data-testid="transcript"
            onScroll={onTranscriptScroll}
          >
            <div className="transcript__inner">
              {awaitingSnapshot ? (
                <div className="thread-empty thread-empty--loading" data-testid="thread-loading">
                  <p className="eyebrow">Authoritative state</p>
                  <h2>Hydrating thread</h2>
                  <p>Waiting for the daemon snapshot before accepting input.</p>
                </div>
              ) : messages.length === 0 ? (
                <div className="thread-empty" data-testid="thread-empty">
                  <p className="eyebrow">Channel open</p>
                  <h2>New thread</h2>
                  <p>Send a prompt when you’re ready. Nothing here demands a response.</p>
                </div>
              ) : (
                messages.map((message) => (
                  <MessageRow
                    key={message.message_id}
                    message={message}
                    queuePosition={
                      message.role === 'user'
                        ? queuedPrompts.findIndex(
                            (queued) => queued.prompt_id === message.message_id,
                          ) + 1
                        : 0
                    }
                    runState={
                      message.run_id === null ? undefined : runStates.get(message.run_id)
                    }
                    activeRunId={activeRun?.run_id}
                    activeState={activeRun?.state}
                  />
                ))
              )}
            </div>
          </div>

          {hasUnread && (
            <button className="new-response" type="button" data-testid="new-response" onClick={scrollToLatest}>
              New response ↓
            </button>
          )}

          <form className="composer" ref={formRef} onSubmit={submitPrompt} aria-label="Prompt composer">
            <div className="composer__body">
              <label className="visually-hidden" htmlFor="prompt-input">
                Message Harness
              </label>
              <textarea
                id="prompt-input"
                ref={composerRef}
                data-testid="composer"
                value={draft}
                rows={1}
                placeholder={connection === 'connected' ? 'Message Harness' : 'Waiting for connection'}
                disabled={
                  connection !== 'connected' || awaitingSnapshot || openGate !== null
                }
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onComposerKeyDown}
              />
              <p className="composer__hint">
                {openGate !== null
                  ? 'Review memory before the model starts'
                  : activeRun === null
                    ? 'Enter to send'
                    : 'New prompts queue at the turn boundary'}
                <span>Shift+Enter for newline</span>
              </p>
            </div>
            <div className="composer__actions">
              {activeRun !== null && (
                <button
                  className="stop-button"
                  type="button"
                  data-testid="stop"
                  disabled={activeRun.state === 'cancelling'}
                  onClick={cancelRun}
                >
                  {activeRun.state === 'cancelling' ? 'Stopping' : 'Stop'}
                </button>
              )}
              <button className="send-button" type="submit" data-testid="send" disabled={!canSend}>
                {activeRun === null ? 'Send' : 'Queue'}
                <span aria-hidden="true">↗</span>
              </button>
            </div>
          </form>
        </main>

        <MemoryPanel
          panel={memoryPanel}
          connected={connection === 'connected' && !awaitingSnapshot}
          removeEnabled={activeRun === null}
          mobileOpen={memoryDrawerOpen}
          inert={drawerOpen || openGate !== null}
          onClose={closeMemoryDrawer}
          onRefresh={() => harnessClient.refreshMemoryPanel()}
          onRemove={(memoryId) =>
            harnessClient.removeMemoryFromContext(memoryId)
          }
          onEdit={(memoryId, expectedRevision, body) =>
            harnessClient.editMemoryBody(memoryId, expectedRevision, body)
          }
          onPin={(memoryId, expectedRevision, pin) =>
            harnessClient.setMemoryPin(memoryId, expectedRevision, pin)
          }
        />
      </div>
      {openGate !== null && (
        <MemoryGate
          key={`${openGate.run_id}:${openGate.injection_id}:${openGate.stage}:${
            openGate.wrong_removed[0]?.memory_id ?? 'review'
          }:${openGate.wrong_removed[0]?.revision ?? 0}`}
          gate={openGate}
          connected={connection === 'connected'}
          cancelling={activeRun?.state === 'cancelling'}
          serverError={selectedThread?.lastError?.detail ?? null}
          onCommit={(decision) => harnessClient.commitGate(decision)}
          onStop={cancelRun}
        />
      )}
    </div>
  )
}

interface MessageRowProps {
  message: ChatMessage
  queuePosition: number
  runState: UserMessageState | undefined
  activeRunId: string | undefined
  activeState: string | undefined
}

function MessageRow({
  message,
  queuePosition,
  runState,
  activeRunId,
  activeState,
}: MessageRowProps) {
  if (message.role === 'user') {
    const status =
      message.state === 'submitting'
        ? 'Sending'
        : message.state === 'queued'
          ? `Queued ${Math.max(queuePosition, 1)}`
          : null
    return (
      <article className={`message message--user message--${message.state}`} data-role="user">
        <header className="message__label">
          <span>You</span>
          {status !== null && <span>{status}</span>}
        </header>
        <p className="message__content">{message.content}</p>
      </article>
    )
  }

  const status = messageStatus(message, runState, activeRunId, activeState)
  const tone = runState === 'error' ? 'danger' : runState === 'budget_exceeded' ? 'budget' : 'normal'
  return (
    <article className={`message message--assistant message--${tone}`} data-role="assistant">
      <header className="message__label">
        <span>Harness</span>
        {status !== null && <span className="message__status">{status}</span>}
      </header>
      {message.content ? (
        <AssistantMarkdown content={message.content} />
      ) : (
        <p className="message__content message__content--quiet">Working…</p>
      )}
      {message.thinking && (
        <details className="run-detail">
          <summary>Process signal</summary>
          <p>{message.thinking}</p>
        </details>
      )}
      {message.events.length > 0 && (
        <details className="run-detail">
          <summary>{message.events.length} run event{message.events.length === 1 ? '' : 's'}</summary>
          <pre>{JSON.stringify(message.events, null, 2)}</pre>
        </details>
      )}
    </article>
  )
}

export default App
