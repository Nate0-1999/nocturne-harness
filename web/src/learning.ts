import { formatHumanPercent, formatHumanQuantity } from './humanNumbers.ts'

export type LearningMeasurementStatus = 'measured' | 'not_recorded'

export const FORCE_RETRAIN_LABEL = 'FORCE RETRAIN'
export const FORCE_VALUES_LABEL = 'Force values'
export const AUDITION_LABEL = 'Audition'
export const ACTIVATE_LABEL = 'Activate'

export interface ScorerAccuracyPoint {
  version: string
  created_at: string
  status: LearningMeasurementStatus
  accuracy_percent: string | null
  holdout_dispositions: number | null
  disagreements: number | null
  weighted_dispositions: string | null
  weighted_wrong: string | null
}

export interface LiveAgreementPoint {
  event_uid: string
  ts: string
  scorer_version: string
  right: number
  wrong: number
  weighted_right: string
  weighted_wrong: string
  weighted_agreement_percent: string
}

export interface ReplayScoreView {
  disagreements: number
  weighted_disagreements: string
  injected_tokens: number
}

export interface LearnerRunView {
  run_uid: string
  trigger: 'manual' | 'background'
  result: 'insufficient_data' | 'not_better' | 'proposed'
  incumbent_version: string
  proposal_version: string | null
  eligible_dispositions: number
  training_dispositions: number
  holdout_dispositions: number
  training_pairs: number
  source_boundary: string | null
  incumbent: ReplayScoreView | null
  challenger: ReplayScoreView | null
  reason: string
  ts: string
}

export interface LearningAnnotation {
  kind: 'activation' | 'force_values' | 'retrain'
  event_uid: string
  ts: string
  version: string
  result: 'insufficient_data' | 'not_better' | 'proposed' | null
}

export interface ScorerConsoleLearning {
  eligible_dispositions: number
  hygiene_excluded_dispositions: number
  minimum_dispositions: number
  remaining_to_floor: number
  floor_met: boolean
  retrain_signal_stride: number
  evaluated_through: number | null
  signals_since_last_run: number
  signals_until_next_run: number
  active_scorer_version: string
  right: number
  wrong: number
  weighted_right: string
  weighted_wrong: string
  weighted_agreement_percent: string | null
  live_agreement: LiveAgreementPoint[]
  retrain_runs: LearnerRunView[]
  annotations: LearningAnnotation[]
}

export interface ScorerConsoleTelemetry {
  learning: ScorerConsoleLearning
  accuracy: ScorerAccuracyPoint[]
}

export interface LearningChartPoint {
  id: string
  timestamp: string
  version: string
  percent: string
  x: number
  y: number
}

export interface LearningChartAnnotation extends LearningAnnotation {
  x: number
  label: string
}

export interface LearningTimelineModel {
  live: LearningChartPoint[]
  generations: LearningChartPoint[]
  annotations: LearningChartAnnotation[]
  unmeasuredGenerations: number
}

export function scorerConsoleTelemetry(value: unknown): ScorerConsoleTelemetry | null {
  if (!isRecord(value) || !isRecord(value.learning) || !Array.isArray(value.accuracy)) {
    return null
  }
  return {
    learning: value.learning as unknown as ScorerConsoleLearning,
    accuracy: value.accuracy as unknown as ScorerAccuracyPoint[],
  }
}

export function learningFloorCopy(learning: ScorerConsoleLearning): string {
  return learning.floor_met
    ? `${learning.eligible_dispositions} authentic signals · floor met`
    : `${learning.eligible_dispositions} / ${learning.minimum_dispositions} authentic signals · ${learning.remaining_to_floor} to floor`
}

export function learningCadenceCopy(learning: ScorerConsoleLearning): string {
  if (!learning.floor_met) {
    return `${learning.signals_until_next_run} authentic signals until the first background retrain`
  }
  if (learning.evaluated_through === null) {
    return `Floor met · waiting for the first background retrain`
  }
  return `${learning.signals_since_last_run} / ${learning.retrain_signal_stride} since the last retrain · ${learning.signals_until_next_run} to next`
}

export function learningHygieneCopy(learning: ScorerConsoleLearning): string {
  const count = learning.hygiene_excluded_dispositions
  return `${count} otherwise-gradable verification, test, or fixture ${count === 1 ? 'signal' : 'signals'} excluded`
}

export function learningAgreementCopy(learning: ScorerConsoleLearning): string {
  const score = learning.weighted_agreement_percent === null
    ? 'weighted agreement not recorded'
    : `${formatHumanPercent(learning.weighted_agreement_percent)} weighted agreement`
  return `${learning.right} right · ${learning.wrong} wrong · ${score}`
}

export function learningWeightedTotalsCopy(learning: ScorerConsoleLearning): string {
  return `${formatHumanQuantity(learning.weighted_right)} weighted right · ${formatHumanQuantity(learning.weighted_wrong)} weighted wrong`
}

export function generationAccuracyCopy(point: ScorerAccuracyPoint | undefined): string {
  if (point === undefined || point.status === 'not_recorded' || point.accuracy_percent === null) {
    return 'Held-out agreement not recorded'
  }
  return `${formatHumanPercent(point.accuracy_percent)} held-out agreement`
}

export interface ConsoleRefreshResetPolicy {
  draft: boolean
  preview: boolean
  receipt: boolean
  audition: boolean
}

export interface LearningNotice {
  copy: string
  eligibleDispositions: number | null
}

export function consoleRefreshResetPolicy(
  previousActiveVersion: string | null,
  nextActiveVersion: string,
  explicitReset: boolean,
): ConsoleRefreshResetPolicy {
  const reset = explicitReset || (
    previousActiveVersion !== null && previousActiveVersion !== nextActiveVersion
  )
  return { draft: reset, preview: reset, receipt: reset, audition: reset }
}

export function learningNoticeAfterSnapshot(
  notice: LearningNotice | null,
  eligibleDispositions: number,
): LearningNotice | null {
  return notice !== null &&
    notice.eligibleDispositions !== null &&
    notice.eligibleDispositions !== eligibleDispositions
    ? null
    : notice
}

export function learningTimelineModel(
  learning: ScorerConsoleLearning,
  accuracy: readonly ScorerAccuracyPoint[],
): LearningTimelineModel {
  const measuredGenerations = accuracy.filter(
    (point): point is ScorerAccuracyPoint & { accuracy_percent: string } =>
      point.status === 'measured' && point.accuracy_percent !== null,
  )
  const timestamps = [
    ...learning.live_agreement.map((point) => timestamp(point.ts)),
    ...measuredGenerations.map((point) => timestamp(point.created_at)),
    ...learning.annotations.map((annotation) => timestamp(annotation.ts)),
  ]
  const first = timestamps.length === 0 ? 0 : Math.min(...timestamps)
  const last = timestamps.length === 0 ? 0 : Math.max(...timestamps)
  const x = (value: string) => last === first
    ? 50
    : 8 + ((timestamp(value) - first) / (last - first)) * 84
  const y = (value: string) => 88 - percent(value) * 0.76
  const live = learning.live_agreement
    .map((point) => ({
      id: point.event_uid,
      timestamp: point.ts,
      version: point.scorer_version,
      percent: point.weighted_agreement_percent,
      x: x(point.ts),
      y: y(point.weighted_agreement_percent),
    }))
    .sort(compareChartPoints)
  const generations = measuredGenerations
    .map((point) => ({
      id: point.version,
      timestamp: point.created_at,
      version: point.version,
      percent: point.accuracy_percent,
      x: x(point.created_at),
      y: y(point.accuracy_percent),
    }))
    .sort(compareChartPoints)
  const annotations = learning.annotations
    .map((annotation) => ({
      ...annotation,
      x: x(annotation.ts),
      label: annotationCopy(annotation),
    }))
    .sort((left, right) => timestamp(left.ts) - timestamp(right.ts))
  return {
    live,
    generations,
    annotations,
    unmeasuredGenerations: accuracy.length - measuredGenerations.length,
  }
}

export function chartPolyline(points: readonly LearningChartPoint[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(' ')
}

function annotationCopy(annotation: LearningAnnotation): string {
  switch (annotation.kind) {
    case 'activation':
      return `Activated ${annotation.version}`
    case 'force_values':
      return `Forced values into ${annotation.version}`
    case 'retrain':
      return annotation.result === null
        ? `Retrained ${annotation.version}`
        : `Retrain ${annotation.result.replaceAll('_', ' ')} · ${annotation.version}`
  }
}

function compareChartPoints(left: LearningChartPoint, right: LearningChartPoint): number {
  return timestamp(left.timestamp) - timestamp(right.timestamp) || left.id.localeCompare(right.id)
}

function timestamp(value: string): number {
  const parsed = Date.parse(value)
  if (!Number.isFinite(parsed)) {
    throw new TypeError('Learning telemetry timestamp must be an offset timestamp')
  }
  return parsed
}

function percent(value: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) {
    throw new TypeError('Learning telemetry percentage must be between 0 and 100')
  }
  return parsed
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
