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
import { useRackPlugin, useRackSnapshot } from './rack'

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
  // A-077 (F175): ×! answered Yes; Continue runs the memory panel's delete for each.
  const [deleted, setDeleted] = useState<string[]>([])
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
    setDeleted((current) => current.filter((candidate) => candidate !== memoryId))
    setAddedBack((current) => current.filter((candidate) => candidate !== memoryId))
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
    setDeleted((current) => current.filter((candidate) => candidate !== memoryId))
    setAddedBack((current) => current.filter((candidate) => candidate !== memoryId))
    setRemoved((current) => ({ ...current, [memoryId]: reason }))
    setModifierFor(null)
    setConfirmDeleteFor(null)
  }

  function confirmDelete(memoryId: string): void {
    chooseRemoval(memoryId, 'never')
    setDeleted((current) => [...current, memoryId])
  }

  function withdrawDelete(memoryId: string): void {
    setDeleted((current) => current.filter((candidate) => candidate !== memoryId))
    setRemoved((current) => {
      const next = { ...current }
      delete next[memoryId]
      return next
    })
  }

  function toggleAddBack(memoryId: string): void {
    setDeleted((current) => current.filter((candidate) => candidate !== memoryId))
    setRemoved((current) => {
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
        ...(deleted.length > 0 ? { deleted } : {}),
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

  function gateCard(card: ScoredMemoryCard, nearMiss = false): ReactNode {
    return (
      <GateCard
        key={card.memory_id}
        card={card}
        reason={removed[card.memory_id]}
        deleted={deleted.includes(card.memory_id)}
        added={nearMiss ? addedBack.includes(card.memory_id) : undefined}
        onAdd={nearMiss ? toggleAddBack : undefined}
        modifierOpen={modifierFor === card.memory_id}
        confirmOpen={confirmDeleteFor === card.memory_id}
        onConfirmDelete={(memoryId) => { setModifierFor(null); setConfirmDeleteFor(memoryId) }}
        onDelete={confirmDelete}
        onWithdrawDelete={withdrawDelete}
        onCloseConfirm={() => setConfirmDeleteFor(null)}
        disabled={controlsDisabled}
        onRemove={toggleDefaultRemoval}
        onLongPressStart={beginLongPress}
        onLongPressMove={moveLongPress}
        onLongPressEnd={clearLongPress}
        onChooseReason={chooseRemoval}
        onCloseModifier={() => setModifierFor(null)}
      />
    )
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
            {gate.stage === 'review' && <GateAudition injectionId={gate.injection_id} />}
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
                  <p>{gate.injected.length - injectedRemovedCount} selected</p>
                </div>
                {gate.injected.length === 0 ? (
                  <p className="memory-gate__empty">
                    No memories met the injection threshold.
                  </p>
                ) : (
                  <div className="memory-grid">
                    {gate.injected.map((card) => gateCard(card))}
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
                    {gate.near_misses.map((card) => gateCard(card, true))}
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
                <span>{removedCount} removed{deleted.length > 0 ? ` · ${deleted.length} deleted` : ''} · {addedBack.length} added</span>
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
            <Button action="stop" variant="bare"
              className="memory-gate__stop"
              type="button"
              data-testid="memory-gate-stop"
              disabled={cancelling || !connected}
              onClick={stopRun}
            >
              {cancelling ? 'Stopping…' : 'Stop run'}
            </Button>
            <Button action={gate.stage === "review" ? "next" : resolutionAction === "edit" ? "save" : "remove"} variant="bare"
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
          <Button action="edit"
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

interface GateCardProps {
  card: ScoredMemoryCard
  reason: RemovalReason | undefined
  deleted: boolean
  /** Near misses only: whether the card is added back, and the + toggle. */
  added?: boolean
  onAdd?: (memoryId: string) => void
  modifierOpen: boolean
  confirmOpen: boolean
  disabled: boolean
  onConfirmDelete: (memoryId: string) => void
  onDelete: (memoryId: string) => void
  onWithdrawDelete: (memoryId: string) => void
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

/** One card for injected memories and near misses: ×, ×! and, on a near miss, + (M4GA). */
function GateCard({
  card,
  reason,
  deleted,
  added,
  onAdd,
  modifierOpen,
  confirmOpen,
  disabled,
  onConfirmDelete,
  onDelete,
  onWithdrawDelete,
  onCloseConfirm,
  onRemove,
  onLongPressStart,
  onLongPressMove,
  onLongPressEnd,
  onChooseReason,
  onCloseModifier,
}: GateCardProps) {
  const removed = reason !== undefined
  const nearMiss = onAdd !== undefined
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
      tone={added ? 'added' : removed ? 'removed' : nearMiss ? 'near-miss' : 'injected'}
      status={deleted ? 'Will be deleted' : removed ? `Removed · ${reason.replace('_', ' ')}` : undefined}
      action={
        <>
          {onAdd !== undefined && (
            <Button action={added ? 'confirm' : 'add'} iconOnly variant="primary"
              className="memory-card__add"
              type="button"
              data-testid="near-miss-toggle"
              data-memory-id={card.memory_id}
              data-tooltip={added ? `Added ${card.label}` : `Add ${card.label}`}
              data-tooltip-detail="Add this memory to the thread; a strong signal it was relevant."
              aria-pressed={added}
              aria-label={added ? `Added ${card.label}` : `Add ${card.label}`}
              disabled={disabled}
              onClick={() => onAdd(card.memory_id)}
            >
              <span aria-hidden="true">{added ? '✓' : '+'}</span>
            </Button>
          )}
          <Button action="remove" iconOnly
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
            data-tooltip-detail={nearMiss
              ? 'Leave this memory out as not relevant. Alt or press and hold: never show it.'
              : 'Leave this memory out of this turn as not relevant. Alt or press and hold: mark it wrong.'}
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
          <Button action="delete" iconOnly variant="danger"
            className="memory-card__delete"
            type="button"
            data-testid="memory-delete"
            data-memory-id={card.memory_id}
            data-tooltip="Delete permanently"
            data-tooltip-detail="Delete this memory from the Palace when you continue, as the Memory panel does. Asks first."
            aria-haspopup="dialog"
            aria-expanded={confirmOpen}
            aria-pressed={deleted}
            aria-label={deleted ? `Keep ${card.label}` : `Permanently delete ${card.label}`}
            disabled={disabled}
            onClick={() => deleted ? onWithdrawDelete(card.memory_id) : onConfirmDelete(card.memory_id)}
          >
            <span aria-hidden="true">×!</span>
          </Button>
        </>
      }
      prompt={
        <>
          {confirmOpen && (
            <div
              className="memory-card__modifier"
              role="dialog"
              aria-label={`Permanently delete ${card.label}?`}
              data-testid="memory-delete-confirm"
            >
              <span>Permanently delete?</span>
              <Button action="confirm" variant="danger" type="button" autoFocus disabled={disabled}
                data-tooltip-detail="Yes: delete it from the Palace when you continue."
                onClick={() => onDelete(card.memory_id)}>
                Yes
              </Button>
              <Button action="close" type="button" disabled={disabled} data-tooltip-detail="Keep the memory as it is." onClick={onCloseConfirm}>
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
              {!nearMiss && (
                <Button
                  ref={firstReasonRef}
                  type="button"
                  disabled={disabled}
                  onClick={() => onChooseReason(card.memory_id, 'wrong')}
                >
                  Wrong
                </Button>
              )}
              <Button variant="danger"
                ref={nearMiss ? firstReasonRef : undefined}
                type="button"
                disabled={disabled}
                onClick={() => onChooseReason(card.memory_id, 'never')}
              >
                Never
              </Button>
              <Button action="close" type="button" disabled={disabled} onClick={onCloseModifier}>
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
  prompt?: ReactNode
}

function MemoryCardFrame({ card, tone, status, action, prompt }: MemoryCardFrameProps) {
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
      prompt={prompt}
      tone={tone}
    >
      {audition !== undefined && <p className="scorer-preview-mark">Current {formatHumanScore(audition.incumbent_score)} · Proposed {formatHumanScore(audition.preview_score)} · #{audition.preview_rank} {audition.disposition.replaceAll('_', ' ')}</p>}
    </MemoryCard>
  )
}

function GateAudition({ injectionId }: { injectionId: string }) {
  const { query, events } = useRackPlugin()
  const rack = useRackSnapshot()
  const [proposals, setProposals] = useState<{ version: string }[]>([])
  const [status, setStatus] = useState('')
  useEffect(() => {
    globalThis.dispatchEvent(new CustomEvent('nocturne:scorer-audition', { detail: {} }))
    void query.query({ resource: 'scorer_console', as_of: 'now', thread_id: rack.selectedThreadId ?? undefined })
      .then((result) => setProposals((result.data as unknown as { proposed_versions: { version: string }[] }).proposed_versions))
      .catch(() => setStatus('Proposals are temporarily unavailable.'))
  }, [query, injectionId, rack.selectedThreadId])
  async function audition(version: string) {
    try {
      const result = await events.dispatch({ type: 'scorer.audition', injection_id: injectionId, proposal_version: version })
      globalThis.dispatchEvent(new CustomEvent('nocturne:scorer-audition', { detail: result }))
      setStatus(`Auditioning ${version}. Current scores still govern.`)
    } catch { setStatus('This proposal could not be auditioned.') }
  }
  return <section aria-label="Scorer audition">
    {proposals.map((proposal) => <Button key={proposal.version} data-tooltip-detail="Compare proposed and current scores without changing this gate." onClick={() => void audition(proposal.version)}>Audition {proposal.version}</Button>)}
    {status && <p role="status">{status}</p>}
  </section>
}
