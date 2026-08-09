export type QueueDecision = 'approve' | 'deny'
export type QueueApprovalMode = 'explicit' | 'passive'
export type QueueActorClass = 'human' | 'passive'

export interface QueueDecisionIntent {
  decision: QueueDecision
  approval_mode: QueueApprovalMode
  actor_class: QueueActorClass
}

export function queueDecisionPayload(intent: QueueDecisionIntent): QueueDecisionIntent {
  return { ...intent }
}

export function seedBatchDecisionPayload(decision: QueueDecision): QueueDecisionIntent {
  return {
    decision,
    approval_mode: 'explicit',
    actor_class: 'human',
  }
}
