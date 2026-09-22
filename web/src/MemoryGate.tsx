import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
  type SyntheticEvent,
} from 'react'

import type {
  GateCommitPayload,
  GateOpenPayload,
  JsonValue,
  MemoryUnit,
  RemovalReason,
  ScoredMemoryCard,
} from './protocol'
import { useContributionMap, useScorerAuditionMap } from './ContributionBars'
import { MemoryCard, Provenance } from './MemoryCard'
import { formatHumanScore } from './humanNumbers.ts'
import { Button, TextArea } from './kit'

const LONG_PRESS_MS = 550
const LONG_PRESS_MOVE_TOLERANCE_PX = 10

type WrongResolutionAction = 'edit' | 'expire'

interface MemoryGateProps {
  gate: GateOpenPayload
  connected: boolean
  cancelling: boolean
  serverError: JsonValue | null
  onCommit: (decision: GateCommitPayload) => void
  onStop: () => void
}

function gateRejectionMessage(detail: JsonValue | null): string | null {
  if (
    typeof detail !== 'object' ||
    detail === null ||
    Array.isArray(detail) ||
    detail.code !== 'gate_not_committable'
  ) {
    return null
  }
  return typeof detail.message === 'string' && detail.message.trim()
    ? detail.message
    : 'That decision no longer matches the open gate. Review it and try again.'
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function MemoryGate({
  gate,
  connected,
  cancelling,
  serverError,
  onCommit,
  onStop,
}: MemoryGateProps) {
  const wrongUnit =
    gate.stage === 'wrong_resolution' ? (gate.wrong_removed[0] ?? null) : null
  const dialogRef = useRef<HTMLDialogElement>(null)
  const longPressTimerRef = useRef<number | null>(null)
  const longPressStartRef = useRef<{
    pointerId: number
    memoryId: string
    x: number
    y: number
  } | null>(null)
  const suppressClickRef = useRef<string | null>(null)
  const [removed, setRemoved] = useState<Partial<Record<string, RemovalReason>>>({})
  const [addedBack, setAddedBack] = useState<string[]>([])
  const [modifierFor, setModifierFor] = useState<string | null>(null)
  const [confirmDeleteFor, setConfirmDeleteFor] = useState<string | null>(null)
  const [pendingCommit, setPendingCommit] = useState<{
    errorAtSubmit: JsonValue | null
    gateAtSubmit: GateOpenPayload
  } | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [resolutionAction, setResolutionAction] =
    useState<WrongResolutionAction>('edit')
  const [resolutionBody, setResolutionBody] = useState(wrongUnit?.body ?? '')

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog === null) {
      return
    }
    if (!dialog.open) {
      dialog.showModal()
    }
    dialog.focus({ preventScroll: true })
    return () => {
      if (dialog.open) {
        dialog.close()
      }
    }
  }, [])

  useEffect(() => {
    return () => {
      if (longPressTimerRef.current !== null) {
        globalThis.clearTimeout(longPressTimerRef.current)
      }
    }
  }, [])

  const rejection = gateRejectionMessage(serverError)
  const commitRejected =
    pendingCommit !== null &&
    serverError !== pendingCommit.errorAtSubmit &&
    rejection !== null
  const resolutionAttemptFailed =
    pendingCommit !== null &&
    gate.stage === 'wrong_resolution' &&
    gate !== pendingCommit.gateAtSubmit &&
    gate.resolution_error !== undefined &&
    gate.resolution_error !== null
  const submitting =
    pendingCommit !== null && !commitRejected && !resolutionAttemptFailed
  const removedCount = Object.keys(removed).length
  const injectedRemovedCount = gate.injected.filter(
    (card) => removed[card.memory_id] !== undefined,
  ).length
  const finalMemoryCount =
    gate.injected.length - injectedRemovedCount + addedBack.length
  const controlsDisabled = submitting || cancelling || !connected
  const resolutionInvalid =
    gate.stage === 'wrong_resolution' &&
    (wrongUnit === null ||
      (resolutionAction === 'edit' && !resolutionBody.trim()))
  const submitBlocked = controlsDisabled || resolutionInvalid
  const displayedError =
    localError ??
    (commitRejected ? rejection : null) ??
    (gate.resolution_error?.trim() ? gate.resolution_error : null) ??
    (!connected
      ? 'Connection lost. Your choices remain; reconnect before continuing.'
      : null)

  function clearLongPress(): void {
    if (longPressTimerRef.current !== null) {
      globalThis.clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
    longPressStartRef.current = null
  }

  function beginLongPress(
    event: PointerEvent<HTMLButtonElement>,
    memoryId: string,
  ): void {
    if (event.button !== 0 || controlsDisabled) {
      return
    }
    clearLongPress()
    longPressStartRef.current = {
      pointerId: event.pointerId,
      memoryId,
      x: event.clientX,
      y: event.clientY,
    }
    longPressTimerRef.current = globalThis.setTimeout(() => {
      suppressClickRef.current = memoryId
      setModifierFor(memoryId)
      longPressTimerRef.current = null
      longPressStartRef.current = null
    }, LONG_PRESS_MS)
  }

  function moveLongPress(event: PointerEvent<HTMLButtonElement>): void {
    const start = longPressStartRef.current
    if (start === null || start.pointerId !== event.pointerId) {
      return
    }
    if (
      Math.hypot(event.clientX - start.x, event.clientY - start.y) >
      LONG_PRESS_MOVE_TOLERANCE_PX
    ) {
      clearLongPress()
    }
  }

  function toggleDefaultRemoval(
    event: MouseEvent<HTMLButtonElement>,
    memoryId: string,
  ): void {
    if (suppressClickRef.current === memoryId) {
      suppressClickRef.current = null
      event.preventDefault()
      return
    }
    if (event.altKey) {
      setModifierFor(memoryId)
      return
    }
    setModifierFor(null)
    setRemoved((current) => {
      const next = { ...current }
      if (next[memoryId] === undefined) {
        next[memoryId] = 'not_relevant'
      } else {
        delete next[memoryId]
      }
      return next
    })
  }

  function chooseRemoval(memoryId: string, reason: RemovalReason): void {
    setRemoved((current) => ({ ...current, [memoryId]: reason }))
    setModifierFor(null)
    setConfirmDeleteFor(null)
  }

  function toggleAddBack(memoryId: string): void {
    setRemoved((current) => {
      if (current[memoryId] !== 'never') {
        return current
      }
      const next = { ...current }
      delete next[memoryId]
      return next
    })
    setAddedBack((current) =>
      current.includes(memoryId)
        ? current.filter((candidate) => candidate !== memoryId)
        : [...current, memoryId],
    )
  }

  function toggleNearMissNever(memoryId: string): void {
    setAddedBack((current) =>
      current.filter((candidate) => candidate !== memoryId),
    )
    setRemoved((current) => {
      const next = { ...current }
      if (next[memoryId] === 'never') {
        delete next[memoryId]
      } else {
        next[memoryId] = 'never'
      }
      return next
    })
  }

  function submitDecision(): void {
    if (submitBlocked) {
      return
    }
    let decision: GateCommitPayload
    if (gate.stage === 'wrong_resolution' && wrongUnit !== null) {
      decision = {
        run_id: gate.run_id,
        injection_id: gate.injection_id,
        removed: [],
        added_back: [],
        wrong_resolution:
          resolutionAction === 'edit'
            ? {
                memory_id: wrongUnit.memory_id,
                expected_revision: wrongUnit.revision,
                action: 'edit',
                body: resolutionBody,
              }
            : {
                memory_id: wrongUnit.memory_id,
                expected_revision: wrongUnit.revision,
                action: 'expire',
              },
      }
    } else {
      decision = {
        run_id: gate.run_id,
        injection_id: gate.injection_id,
        removed: [
          ...gate.injected.flatMap((card) => {
            const reason = removed[card.memory_id]
            return reason === undefined
              ? []
              : [{ memory_id: card.memory_id, reason }]
          }),
          ...gate.near_misses.flatMap((card) =>
            removed[card.memory_id] === 'never'
              ? [{ memory_id: card.memory_id, reason: 'never' as const }]
              : [],
          ),
        ],
        added_back: gate.near_misses
          .filter((card) => addedBack.includes(card.memory_id))
          .map((card) => card.memory_id),
      }
    }
    setPendingCommit({ errorAtSubmit: serverError, gateAtSubmit: gate })
    setLocalError(null)
    try {
      onCommit(decision)
    } catch (error) {
      setPendingCommit(null)
      setLocalError(errorMessage(error, 'The memory decision could not be sent.'))
    }
  }

  function stopRun(): void {
    if (cancelling || !connected) {
      return
    }
    setLocalError(null)
    try {
      onStop()
    } catch (error) {
      setLocalError(errorMessage(error, 'The run could not be stopped.'))
    }
  }

  function keepDialogOpen(event: SyntheticEvent<HTMLDialogElement>): void {
    event.preventDefault()
    if (modifierFor !== null) {
      setModifierFor(null)
    }
  }

  function onDialogKeyDown(event: KeyboardEvent<HTMLDialogElement>): void {
    if (event.key === 'Escape' && modifierFor !== null) {
      event.preventDefault()
      event.stopPropagation()
      setModifierFor(null)
      return
    }
    const target = event.target
    const isContinue =
      target instanceof HTMLElement && target.dataset.testid === 'memory-gate-continue'
    if (event.key === 'Enter' && (target === event.currentTarget || isContinue)) {
      event.preventDefault()
      submitDecision()
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="memory-gate"
      data-testid="memory-gate"
      aria-labelledby="memory-gate-title"
      aria-describedby="memory-gate-description"
      aria-busy={submitting}
      tabIndex={-1}
      onCancel={keepDialogOpen}
      onKeyDown={onDialogKeyDown}
    >
      <div className="memory-gate__surface">
        <header className="memory-gate__header">
          <div>
            <p className="eyebrow">
              {gate.stage === 'review'
                ? 'First-turn memory check'
                : 'Wrong memory resolution'}
            </p>
            <h2 id="memory-gate-title">
              {gate.stage === 'review'
                ? 'Review what Harness remembers'
                : 'Correct or expire this memory'}
            </h2>
            <p id="memory-gate-description">
              {gate.stage === 'review'
                ? 'The model has not started. Keep, remove, or add memories, then continue.'
                : 'The model is still stopped. Edit the current body or expire the memory before continuing.'}
            </p>
          </div>
          <div className="memory-gate__identity" aria-label="Injection details">
            <span>
              Stage <code>{gate.stage.replace('_', ' ')}</code>
            </span>
            <span>
              Injection <code>{gate.injection_id}</code>
            </span>
            <span>
              Retrieval recipe <code>{gate.scorer_version}</code>
            </span>
            <span>
              Snapshot <time dateTime={gate.snapshot_ts}>{gate.snapshot_ts}</time>
            </span>
          </div>
        </header>

        <div className="memory-gate__content">
          {gate.stage === 'review' ? (
            <>
              <section
                className="memory-gate__section"
                aria-labelledby="injected-memories-title"
              >
                <div className="memory-gate__section-heading">
                  <h3 id="injected-memories-title">Injected memories</h3>
                  <p>{gate.injected.length} selected</p>
                </div>
                {gate.injected.length === 0 ? (
                  <p className="memory-gate__empty">
                    No memories met the injection threshold.
                  </p>
                ) : (
                  <div className="memory-grid">
                    {gate.injected.map((card) => (
                      <InjectedCard
                        key={card.memory_id}
                        card={card}
                        reason={removed[card.memory_id]}
                        modifierOpen={modifierFor === card.memory_id}
                        confirmOpen={confirmDeleteFor === card.memory_id}
                        onConfirmDelete={(memoryId) => { setModifierFor(null); setConfirmDeleteFor(memoryId) }}
                        onCloseConfirm={() => setConfirmDeleteFor(null)}
                        disabled={controlsDisabled}
                        onRemove={toggleDefaultRemoval}
                        onLongPressStart={beginLongPress}
                        onLongPressMove={moveLongPress}
                        onLongPressEnd={clearLongPress}
                        onChooseReason={chooseRemoval}
                        onCloseModifier={() => setModifierFor(null)}
                      />
                    ))}
                  </div>
                )}
              </section>

              <section
                className="memory-gate__section"
                aria-labelledby="near-misses-title"
              >
                <div className="memory-gate__section-heading">
                  <h3 id="near-misses-title">Near misses</h3>
                  <p>{addedBack.length} added</p>
                </div>
                {gate.near_misses.length === 0 ? (
                  <p className="memory-gate__empty">
                    No near-miss memories were returned.
                  </p>
                ) : (
                  <div className="memory-grid">
                    {gate.near_misses.map((card) => {
                      const added = addedBack.includes(card.memory_id)
                      const never = removed[card.memory_id] === 'never'
                      return (
                        <MemoryCardFrame
                          key={card.memory_id}
                          card={card}
                          tone={added ? 'added' : never ? 'removed' : 'near-miss'}
                          status={never ? 'Removed · never' : undefined}
                          action={
                            <>
                              <Button variant="primary"
                                className="memory-card__add"
                                type="button"
                                data-testid="near-miss-toggle"
                                data-memory-id={card.memory_id}
                                data-tooltip={added ? `Added ${card.label}` : `Add ${card.label}`}
                                data-tooltip-detail="Add this memory to the thread; a strong signal it was relevant."
                                aria-pressed={added}
                                aria-label={added ? `Added ${card.label}` : `Add ${card.label}`}
                                disabled={controlsDisabled}
                                onClick={() => toggleAddBack(card.memory_id)}
                              >
                                <span aria-hidden="true">{added ? '✓' : '+'}</span>
                              </Button>
                              <Button variant="danger"
                                className="memory-card__delete"
                                type="button"
                                data-testid="near-miss-never"
                                data-memory-id={card.memory_id}
                                data-tooltip="Delete permanently"
                                data-tooltip-detail="Never show this memory again, in any conversation. Asks first."
                                aria-pressed={never}
                                aria-haspopup="dialog"
                                aria-expanded={confirmDeleteFor === card.memory_id}
                                aria-label={`Permanently delete ${card.label}`}
                                disabled={controlsDisabled}
                                onClick={() => never ? toggleNearMissNever(card.memory_id) : setConfirmDeleteFor(card.memory_id)}
                              >
                                <span aria-hidden="true">×!</span>
                              </Button>
                              {confirmDeleteFor === card.memory_id && (
                                <div className="memory-card__modifier" role="dialog" aria-label={`Permanently delete ${card.label}?`} data-testid="memory-delete-confirm">
                                  <span>Permanently delete?</span>
                                  <Button variant="danger" type="button" autoFocus disabled={controlsDisabled}
                                    data-tooltip-detail="Yes: this memory is never shown again."
                                    onClick={() => { toggleNearMissNever(card.memory_id); setConfirmDeleteFor(null) }}>
                                    Yes
                                  </Button>
                                  <Button type="button" data-tooltip-detail="Keep the memory as it is." onClick={() => setConfirmDeleteFor(null)}>No</Button>
                                </div>
                              )}
                            </>
                          }
                        />
                      )
                    })}
                  </div>
                )}
              </section>
            </>
          ) : wrongUnit === null ? (
            <p className="memory-gate__empty" role="alert">
              The correction stage did not include a current memory unit.
            </p>
          ) : (
            <WrongResolutionEditor
              unit={wrongUnit}
              action={resolutionAction}
              body={resolutionBody}
              disabled={controlsDisabled}
              onActionChange={setResolutionAction}
              onBodyChange={setResolutionBody}
            />
          )}
        </div>

        <footer className="memory-gate__footer">
          <div className="memory-gate__summary" aria-live="polite">
            {gate.stage === 'review' ? (
              <>
                <strong>
                  {finalMemoryCount}{' '}
                  {finalMemoryCount === 1 ? 'memory' : 'memories'} will be used
                </strong>
                <span>{removedCount} removed · {addedBack.length} added</span>
              </>
            ) : (
              <>
                <strong>Resolve the wrong memory to continue</strong>
                <span>Current revision {wrongUnit?.revision ?? 'unavailable'}</span>
              </>
            )}
          </div>
          {displayedError !== null && (
            <p className="memory-gate__error" role="alert">
              {displayedError}
            </p>
          )}
          <div className="memory-gate__actions">
            <Button variant="bare"
              className="memory-gate__stop"
              type="button"
              data-testid="memory-gate-stop"
              disabled={cancelling || !connected}
              onClick={stopRun}
            >
              {cancelling ? 'Stopping…' : 'Stop run'}
            </Button>
            <Button variant="bare"
              className="memory-gate__continue"
              type="button"
              data-testid="memory-gate-continue"
              disabled={submitBlocked}
              onClick={submitDecision}
            >
              {submitting
                ? gate.stage === 'review'
                  ? 'Applying memory…'
                  : 'Applying resolution…'
                : gate.stage === 'review'
                  ? 'Continue'
                  : resolutionAction === 'edit'
                    ? 'Save correction'
                    : 'Expire memory'}
              {!submitting && <span aria-hidden="true">↗</span>}
            </Button>
          </div>
        </footer>
      </div>
    </dialog>
  )
}

interface WrongResolutionEditorProps {
  unit: MemoryUnit
  action: WrongResolutionAction
  body: string
  disabled: boolean
  onActionChange: (action: WrongResolutionAction) => void
  onBodyChange: (body: string) => void
}

function WrongResolutionEditor({
  unit,
  action,
  body,
  disabled,
  onActionChange,
  onBodyChange,
}: WrongResolutionEditorProps) {
  const bodyInvalid = action === 'edit' && !body.trim()

  return (
    <section
      className="memory-gate__section wrong-resolution"
      aria-labelledby="wrong-resolution-title"
    >
      <div className="memory-gate__section-heading">
        <div>
          <p className="eyebrow">Marked wrong</p>
          <h3 id="wrong-resolution-title">{unit.label}</h3>
        </div>
        <p>Revision {unit.revision}</p>
      </div>

      <div className="wrong-resolution__unit">
        <div className="wrong-resolution__metadata">
          <span>{unit.kind.replace('_', ' ')}</span>
          <span>{unit.status}</span>
          <code>{unit.memory_id}</code>
        </div>

        <div
          className="wrong-resolution__choices"
          role="group"
          aria-label="Choose how to resolve this wrong memory"
        >
          <Button
            type="button"
            data-testid="wrong-resolution-edit"
            aria-pressed={action === 'edit'}
            disabled={disabled}
            onClick={() => onActionChange('edit')}
          >
            Edit body
          </Button>
          <Button variant="danger"
            type="button"
            data-testid="wrong-resolution-expire"
            aria-pressed={action === 'expire'}
            disabled={disabled}
            onClick={() => onActionChange('expire')}
          >
            Expire memory
          </Button>
        </div>

        {action === 'edit' ? (
          <label className="wrong-resolution__editor">
            Corrected body
            <TextArea
              data-testid="wrong-resolution-body"
              value={body}
              rows={8}
              required
              aria-invalid={bodyInvalid}
              disabled={disabled}
              onChange={(event) => onBodyChange(event.target.value)}
            />
            <span>
              Replace the body with the durable fact Harness should remember.
            </span>
            {bodyInvalid && <strong>Body cannot be blank.</strong>}
          </label>
        ) : (
          <div className="wrong-resolution__expire">
            <strong>Expire this memory</strong>
            <p>
              This tombstones the current unit so it will no longer be selected or
              searched.
            </p>
            <blockquote>{unit.body}</blockquote>
          </div>
        )}
      </div>
    </section>
  )
}

interface InjectedCardProps {
  card: ScoredMemoryCard
  reason: RemovalReason | undefined
  modifierOpen: boolean
  confirmOpen: boolean
  disabled: boolean
  onConfirmDelete: (memoryId: string) => void
  onCloseConfirm: () => void
  onRemove: (event: MouseEvent<HTMLButtonElement>, memoryId: string) => void
  onLongPressStart: (
    event: PointerEvent<HTMLButtonElement>,
    memoryId: string,
  ) => void
  onLongPressMove: (event: PointerEvent<HTMLButtonElement>) => void
  onLongPressEnd: () => void
  onChooseReason: (memoryId: string, reason: RemovalReason) => void
  onCloseModifier: () => void
}

function InjectedCard({
  card,
  reason,
  modifierOpen,
  confirmOpen,
  disabled,
  onConfirmDelete,
  onCloseConfirm,
  onRemove,
  onLongPressStart,
  onLongPressMove,
  onLongPressEnd,
  onChooseReason,
  onCloseModifier,
}: InjectedCardProps) {
  const removed = reason !== undefined
  const removeButtonRef = useRef<HTMLButtonElement>(null)
  const firstReasonRef = useRef<HTMLButtonElement>(null)
  const modifierWasOpenRef = useRef(false)
  const modifierId = `memory-reason-${card.memory_id}`

  useEffect(() => {
    if (modifierOpen && !modifierWasOpenRef.current) {
      firstReasonRef.current?.focus({ preventScroll: true })
    } else if (!modifierOpen && modifierWasOpenRef.current) {
      removeButtonRef.current?.focus({ preventScroll: true })
    }
    modifierWasOpenRef.current = modifierOpen
  }, [modifierOpen])

  return (
    <MemoryCardFrame
      card={card}
      tone={removed ? 'removed' : 'injected'}
      status={removed ? `Removed · ${reason.replace('_', ' ')}` : undefined}
      action={
        <>
          <Button
            ref={removeButtonRef}
            className="memory-card__remove"
            type="button"
            data-testid="memory-remove"
            data-memory-id={card.memory_id}
            aria-pressed={removed}
            aria-haspopup="dialog"
            aria-expanded={modifierOpen}
            aria-controls={modifierOpen ? modifierId : undefined}
            aria-label={
              removed
                ? `Restore ${card.label}`
                : `Remove ${card.label} as not relevant`
            }
            data-tooltip={removed ? `Restore ${card.label}` : 'Remove'}
            data-tooltip-detail="Leave this memory out of this turn as not relevant. Alt or press and hold: mark it wrong."
            disabled={disabled}
            onPointerDown={(event) => onLongPressStart(event, card.memory_id)}
            onPointerMove={onLongPressMove}
            onPointerUp={onLongPressEnd}
            onPointerCancel={onLongPressEnd}
            onPointerLeave={onLongPressEnd}
            onContextMenu={(event) => event.preventDefault()}
            onClick={(event) => onRemove(event, card.memory_id)}
          >
            <span aria-hidden="true">×</span>
          </Button>
          <Button variant="danger"
            className="memory-card__delete"
            type="button"
            data-testid="memory-delete"
            data-memory-id={card.memory_id}
            data-tooltip="Delete permanently"
            data-tooltip-detail="Never show this memory again, in any conversation. Asks first."
            aria-haspopup="dialog"
            aria-expanded={confirmOpen}
            aria-label={`Permanently delete ${card.label}`}
            disabled={disabled || reason === 'never'}
            onClick={() => onConfirmDelete(card.memory_id)}
          >
            <span aria-hidden="true">×!</span>
          </Button>
          {confirmOpen && (
            <div
              className="memory-card__modifier"
              role="dialog"
              aria-label={`Permanently delete ${card.label}?`}
              data-testid="memory-delete-confirm"
            >
              <span>Permanently delete?</span>
              <Button variant="danger" type="button" autoFocus disabled={disabled}
                data-tooltip-detail="Yes: this memory is never shown again."
                onClick={() => onChooseReason(card.memory_id, 'never')}>
                Yes
              </Button>
              <Button type="button" disabled={disabled} data-tooltip-detail="Keep the memory as it is." onClick={onCloseConfirm}>
                No
              </Button>
            </div>
          )}
          {modifierOpen && (
            <div
              id={modifierId}
              className="memory-card__modifier"
              role="dialog"
              aria-label={`Why remove ${card.label}?`}
              data-testid="memory-modifier"
            >
              <span>Remove as</span>
              <Button
                ref={firstReasonRef}
                type="button"
                disabled={disabled}
                onClick={() => onChooseReason(card.memory_id, 'wrong')}
              >
                Wrong
              </Button>
              <Button variant="danger"
                type="button"
                disabled={disabled}
                onClick={() => onChooseReason(card.memory_id, 'never')}
              >
                Never
              </Button>
              <Button type="button" disabled={disabled} onClick={onCloseModifier}>
                Cancel
              </Button>
            </div>
          )}
        </>
      }
    />
  )
}

interface MemoryCardFrameProps {
  card: ScoredMemoryCard
  tone: 'injected' | 'removed' | 'near-miss' | 'added'
  status?: string
  action: ReactNode
}

function MemoryCardFrame({ card, tone, status, action }: MemoryCardFrameProps) {
  const contributions = useContributionMap()
  const audition = useScorerAuditionMap()[card.memory_id]
  return (
    <MemoryCard
      memoryId={card.memory_id}
      label={card.label}
      body={card.body}
      score={card.score}
      pin={card.pin}
      features={card.features}
      contributions={contributions[card.memory_id]}
      provenance={<>
        <Provenance term="Rank">#{card.rank}</Provenance>
        <Provenance term="Kind">{card.kind.replace('_', ' ')}</Provenance>
        <Provenance term="Id"><code>{card.memory_id}</code></Provenance>
      </>}
      status={status}
      actions={action}
      tone={tone}
    >
      {audition !== undefined && <p className="scorer-preview-mark">Audition: {formatHumanScore(audition.preview_score)} · #{audition.preview_rank} {audition.disposition.replace('_', ' ')}</p>}
    </MemoryCard>
  )
}

