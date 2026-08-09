export type SnapshotBarrierDisposition =
  | 'outside'
  | 'drop'
  | 'error'
  | 'snapshot'

export interface SnapshotBarrierRoute {
  disposition: SnapshotBarrierDisposition
  publish: boolean
}

export function snapshotBarrierRoute(
  barrierThreadId: string | null,
  envelopeThreadId: string | undefined,
  eventType: string | null,
): SnapshotBarrierRoute {
  let disposition: SnapshotBarrierDisposition
  if (barrierThreadId === null || envelopeThreadId !== barrierThreadId) {
    disposition = 'outside'
  } else if (eventType === 'error') {
    disposition = 'error'
  } else if (eventType === 'thread.snapshot') {
    disposition = 'snapshot'
  } else {
    disposition = 'drop'
  }
  return { disposition, publish: disposition !== 'drop' }
}

export function isProjectContextConflict<
  ErrorType extends { detail: unknown },
>(error: ErrorType | null): boolean {
  const detail = error?.detail
  return (
    typeof detail === 'object' &&
    detail !== null &&
    !Array.isArray(detail) &&
    'code' in detail &&
    detail.code === 'project_context_conflict'
  )
}

export function snapshotErrorAfterReconciliation<
  ErrorType extends { detail: unknown },
>(
  previous: ErrorType | null,
  projectConflictAwaitingSnapshot: boolean,
): ErrorType | null {
  return projectConflictAwaitingSnapshot && isProjectContextConflict(previous)
    ? previous
    : null
}

export function snapshotRequestError<ErrorType extends { detail: unknown }>(
  previous: ErrorType | null,
  projectConflictAwaitingSnapshot: boolean,
): ErrorType | null {
  return !projectConflictAwaitingSnapshot && isProjectContextConflict(previous)
    ? null
    : previous
}
