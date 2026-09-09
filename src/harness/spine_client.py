"""Typed asynchronous client for the enacted Spine HTTP API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Never
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictStr,
    TypeAdapter,
)

type JsonObject = dict[str, Any]

type ULID = StrictStr
type NonBlankString = StrictStr
type NonNegativeDecimalString = StrictStr
type SignedDecimalString = StrictStr


class ContractModel(BaseModel):
    """Closed JSON object for a body whose fields are fixed by Spine law."""

    model_config = ConfigDict(allow_inf_nan=False)


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROCEDURE = "procedure"
    PROJECT_NOTE = "project_note"
    PERSONA = "persona"
    PINNED = "pinned"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    CANDIDATE = "candidate"
    QUARANTINED = "quarantined"
    TOMBSTONED = "tombstoned"


class RemovalReason(StrEnum):
    NOT_RELEVANT = "not_relevant"
    WRONG = "wrong"
    NEVER = "never"


class FeedbackSignal(StrEnum):
    MID_THREAD_REMOVED = "mid_thread_removed"
    MID_THREAD_ADDED = "mid_thread_added"
    CITED = "cited"


type FiniteScore = Annotated[float, Field(strict=True)]
type RawFeatureScore = Annotated[float, Field(strict=True)]
type PositiveRank = Annotated[int, Field(strict=True)]


class MemoryFeatures(ContractModel):
    sem: RawFeatureScore
    kw: RawFeatureScore
    time: RawFeatureScore
    proj: RawFeatureScore
    freq: RawFeatureScore
    hist: RawFeatureScore
    loc: RawFeatureScore | None = None
    thread: RawFeatureScore | None = None
    where: RawFeatureScore | None = None


class MemoryCard(ContractModel):
    memory_id: UUID
    label: str
    body: str
    kind: MemoryKind
    pin: bool
    score: FiniteScore
    features: MemoryFeatures | None
    rank: int | None


class ScoredMemoryCard(MemoryCard):
    """Inject/prepare card, where C.4 requires scoring details."""

    features: MemoryFeatures
    rank: PositiveRank


class SimilarityMemoryCard(MemoryCard):
    """Dedup/search card, where C.4 requires scoring details to be null."""

    features: None
    rank: None


class MemoryUnit(ContractModel):
    """Shared C.4 projection of a C.2 memory_unit row, minus embedding."""

    memory_id: UUID
    principal_id: str
    label: str
    body: str
    kind: MemoryKind
    keywords: list[str]
    project_key: str | None
    thread_origin: str | None
    origin_thread_id: UUID | None
    origin_path: str | None
    origin_location: str | None = None
    pin: bool
    status: MemoryStatus
    revision: int
    stats: JsonObject
    bias: float
    embedding_model: str
    created_at: datetime
    updated_at: datetime


class InjectPrepareRequest(ContractModel):
    thread_id: UUID
    agent_id: str
    machine_id: str
    principal_id: str
    project_key: str | None = None
    location_path: str | None = None
    current_location: str | None = None
    agent_kind: str | None = None
    prompt: str
    model_context_tokens: int
    mode: Literal["gate", "autonomous"] = "gate"
    current_memory_ids: list[UUID] = Field(default_factory=list)
    confirmed_memory_ids: list[UUID] = Field(default_factory=list)
    excluded_memory_ids: list[UUID] = Field(default_factory=list)


class MemoryAllocation(ContractModel):
    memory_context_share: float = Field(strict=True)
    share_tokens: int = Field(strict=True)
    regular_tokens: int = Field(strict=True)
    pinned_tokens: int = Field(strict=True)
    total_tokens: int = Field(strict=True)
    pinned_overflow_tokens: int = Field(strict=True)


class InjectPrepareResponse(ContractModel):
    injection_id: UUID
    snapshot_ts: datetime
    scorer_version: str
    injected: list[ScoredMemoryCard]
    near_misses: list[ScoredMemoryCard]
    final_block: str | None
    memory_allocation: MemoryAllocation


class RemovedMemory(ContractModel):
    memory_id: UUID
    reason: RemovalReason


class InjectCommitRequest(ContractModel):
    injection_id: UUID
    removed: list[RemovedMemory]
    added_back: list[UUID]


class InjectCommitResponse(ContractModel):
    final_block: str
    wrong_removed: list[MemoryUnit]


class FeedbackRequest(ContractModel):
    injection_id: UUID
    memory_id: UUID
    signal: FeedbackSignal


class FeedbackResponse(ContractModel):
    ok: Literal[True]


class InjectionEventAnnotationInput(ContractModel):
    """One guarded A-053 verification-only classification request."""

    target_event_uid: ULID
    expected_principal_id: StrictStr
    expected_machine_id: StrictStr
    reason: NonBlankString
    annotator_principal_id: NonBlankString
    annotator_machine_id: NonBlankString
    annotator_origin_agent: NonBlankString


class TranscriptRecordInput(ContractModel):
    # WALL owner files / D.2 082: restoration requires ordered, digest-addressed journal rows.
    thread_id: UUID
    sequence: int = Field(strict=True, gt=0)
    journal_line: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AppendTranscriptsRequest(ContractModel):
    principal_id: NonBlankString
    records: list[TranscriptRecordInput]


class TranscriptRecordView(TranscriptRecordInput):
    received_at: datetime

class TranscriptStatus(ContractModel):
    principal_id: NonBlankString
    thread_count: int
    record_count: int
    latest_received_at: datetime | None

class TranscriptAppendResult(ContractModel):
    accepted: int
    replayed: int
    status: TranscriptStatus


class TranscriptList(ContractModel):
    principal_id: NonBlankString
    records: list[TranscriptRecordView]


class InjectionEventAnnotationsRequest(ContractModel):
    """One nonempty atomic batch with unique target event identities."""

    annotations: list[InjectionEventAnnotationInput]

class InjectionEventAnnotationsResponse(ContractModel):
    """Idempotent acceptance count, including identical replays."""

    accepted: int = Field(strict=True)


class CreateMemoryRequest(ContractModel):
    principal_id: str
    label: str
    body: str
    kind: MemoryKind
    keywords: list[str] | None = None
    project_key: str | None = None
    thread_origin: str | None = None
    origin_thread_id: UUID | None = None
    origin_path: str | None = None
    origin_location: str | None = None
    editor: str
    machine_id: str
    force: bool = False


class CreatedMemoryResponse(ContractModel):
    created: MemoryUnit


class SimilarMemoriesResponse(ContractModel):
    created: None
    similar: list[SimilarityMemoryCard]


type CreateMemoryResponse = CreatedMemoryResponse | SimilarMemoriesResponse


class MemorySplitChild(ContractModel):
    label: str
    body: str
    keywords: list[str]


class MemorySplitRequest(ContractModel):
    principal_id: str
    source_body: str
    children: list[MemorySplitChild]
    thread_origin: str | None = None
    origin_thread_id: UUID | None = None
    origin_path: str | None = None
    origin_location: str | None = None
    editor: str
    machine_id: str


class MemorySplitResponse(ContractModel):
    source: MemoryUnit
    created: list[MemoryUnit]


type CreateMemorySplitResponse = MemorySplitResponse | SimilarMemoriesResponse


class DuplicateMemoryConflict(ContractModel):
    duplicate_of: SimilarityMemoryCard


class LabelConflictTarget(ContractModel):
    memory_id: UUID
    label: str


class LabelConflict(ContractModel):
    label_conflict: LabelConflictTarget


type CreateMemoryConflict = DuplicateMemoryConflict | LabelConflict


class PatchMemoryRequest(ContractModel):
    expected_revision: int
    body: str | None = None
    label: str | None = None
    keywords: list[str] | None = None
    kind: MemoryKind | None = None
    origin_path: str | None = None
    pin: bool | None = None
    status: MemoryStatus | None = None
    editor: str
    reason: str
    machine_id: str


type PatchMemoryResponse = MemoryUnit


class RevisionConflict(ContractModel):
    conflict: MemoryUnit


type PatchMemoryConflict = RevisionConflict | LabelConflict


class ListMemoriesParams(ContractModel):
    project_key: str | None = None
    status: MemoryStatus | None = None
    q: str | None = None
    limit: int = Field(default=50)
    offset: int = Field(default=0)


class PagedMemoryListResponse(ContractModel):
    items: list[MemoryUnit]
    total: int
    limit: int
    offset: int


class SearchRequest(ContractModel):
    principal_id: str
    query: str
    k: int = Field(default=10, strict=True)
    project_key: str | None = None


class SearchResponse(ContractModel):
    results: list[SimilarityMemoryCard]


class ExtractionCandidate(ContractModel):
    label: str
    body: str
    kind: MemoryKind
    keywords: list[str]
    project_key: str | None = None
    verdict: Literal["new", "merge", "supersede", "contradict"]
    target_ids: list[UUID] = Field(default_factory=list)


class ExtractionRequest(ContractModel):
    principal_id: str
    thread_id: UUID
    machine_id: str
    editor: str
    origin_location: str | None = None
    candidates: list[ExtractionCandidate]


class SeedRequest(ContractModel):
    principal_id: str
    batch_uid: UUID
    source_name: str
    source_sha256: str
    markdown: str
    machine_id: str
    editor: str
    candidates: list[ExtractionCandidate]


class QueueCard(ContractModel):
    item_uid: ULID
    candidate: MemoryUnit
    birthplace: Literal["thread", "seed", "symphony", "curator"]
    birthplace_thread_id: UUID | None
    batch_uid: UUID | None
    source_name: str | None
    source_sha256: str | None
    birthplace_run_id: str | None = None
    birthplace_origin_agent: str | None = None
    judged_context: JsonObject | None = None
    candidate_revision: int | None = None
    curator_run_uid: str | None = None
    curator_finding_uid: str | None = None
    proposal_payload: JsonObject | None = None
    verdict: Literal[
        "new",
        "merge",
        "supersede",
        "contradict",
        "retire",
        "keyword_repair",
        "split",
    ]
    neighbors: list[SimilarityMemoryCard]
    target_ids: list[UUID]
    state: Literal["pending", "approved", "rejected"]
    created_at: datetime


class ExtractionResponse(ContractModel):
    cards: list[QueueCard]
    duplicate_count: int


class SeedResponse(ExtractionResponse):
    batch_uid: UUID


class QueueResponse(ContractModel):
    cards: list[QueueCard]


class CuratorActivity(ContractModel):
    principal_id: str
    admitted_writes: int
    last_run_writes: int
    pressure_events: int
    last_run_pressure: int
    trigger_every: int
    pressure_trigger_every: int
    writes_until_run: int
    pressure_until_run: int
    latest_run: JsonObject | None
    pending_cards: int


class SymphonyMemoryRecord(ContractModel):
    memory_id: UUID
    principal_id: str
    label: str
    body: str
    kind: MemoryKind
    keywords: list[str]
    project_key: str | None
    origin_thread_id: UUID | None
    origin_path: str | None
    origin_location: str | None
    pin: bool
    status: Literal["active", "candidate", "staged", "quarantined", "tombstoned"]
    revision: int
    run_id: str | None
    origin_agent: str | None
    staged: bool
    created_at: datetime
    updated_at: datetime


class StageSymphonyMemoryRequest(ContractModel):
    memory_id: UUID
    principal_id: NonBlankString
    label: NonBlankString
    body: NonBlankString
    kind: MemoryKind
    keywords: list[str] = Field(default_factory=list)
    project_key: str | None = None
    origin_thread_id: UUID
    origin_path: str | None = None
    origin_location: str | None = None
    run_id: ULID
    origin_agent: NonBlankString
    machine_id: NonBlankString

class StageSymphonyMemoryResponse(ContractModel):
    memory: SymphonyMemoryRecord


class SymphonyVisibilityRequest(ContractModel):
    principal_id: NonBlankString
    run_id: ULID
    origin_agent: NonBlankString

class SymphonyVisibilityResponse(ContractModel):
    memories: list[SymphonyMemoryRecord]


class JudgedContext(ContractModel):
    verdict: Literal["unanimous_pass"]
    summary: NonBlankString
    judge_ids: list[NonBlankString]
    evidence_refs: list[NonBlankString]

class ResolveSymphonyRunRequest(ContractModel):
    principal_id: NonBlankString
    batch_uid: UUID
    winner_origin_agent: NonBlankString
    machine_id: NonBlankString
    judged_context: JudgedContext


class ResolveSymphonyRunResponse(ContractModel):
    run_id: ULID
    batch_uid: UUID
    winner_origin_agent: str
    queue_cards: list[QueueCard]
    losers: list[SymphonyMemoryRecord]


class QueueDecisionIntent(ContractModel):
    """Human choice fields accepted at the owner API boundary."""

    # WALL Palace writes / F069: the browser cannot supply machine provenance.
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "deny"]
    approval_mode: Literal["explicit", "passive"]
    actor_class: Literal["human", "passive"]


class QueueDecisionRequest(QueueDecisionIntent):
    """Trusted Harness-to-Spine request with daemon-stamped provenance."""

    machine_id: str


class QueueDecisionResponse(ContractModel):
    card: QueueCard
    decision: Literal["approve", "deny"]
    approval_mode: Literal["explicit", "passive"]
    actor_class: Literal["human", "passive"]
    decision_uid: ULID


class BatchDecisionResponse(ContractModel):
    batch_uid: UUID
    decision: Literal["approve", "deny"]
    cards: list[QueueCard]


class SpendEvent(ContractModel):
    # WALL money / ADR024: persisted receipt quantities and dollars cannot exceed ledger precision.
    """One exact A-027 receipt line submitted to Spine."""

    event_uid: ULID
    ts: datetime
    product_type: Literal["llm.request", "llm.embedding"]
    quantity_type: NonBlankString
    unit_of_measure: NonBlankString
    quantity: Decimal = Field(gt=0, max_digits=30, decimal_places=9)
    cost_usd: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=12)
    basis: Literal["measured", "allocated", "estimated"]
    behavior: Literal["variable", "fixed", "step"]
    purpose: Literal[
        "building",
        "extraction",
        "curation",
        "judge",
        "remember",
        "embedding",
        "scout",
    ]
    principal_id: NonBlankString | None = None
    machine_id: NonBlankString | None = None
    origin_agent: NonBlankString | None = None
    thread_id: UUID | None = None
    run_id: ULID | None = None
    prompt_id: ULID | None = None
    memory_id: UUID | None = None
    model: NonBlankString | None = None
    provider: NonBlankString | None = None
    quantization: NonBlankString | None = None
    ref: NonBlankString
    meta: dict[str, JsonValue] = Field(default_factory=dict)

class SpendEventsRequest(ContractModel):
    # WALL money / ADR024: retain the Palace's atomic receipt batch boundary.
    events: list[SpendEvent] = Field(min_length=1, max_length=1000)

class SpendEventsResponse(ContractModel):
    accepted: int = Field(strict=True)


class SpendTableMetrics(ContractModel):
    """Exact quantities and honest known-cost state for one ledger grouping."""

    input_tokens: NonNegativeDecimalString
    kv_cache_tokens: NonNegativeDecimalString
    reasoning_tokens: NonNegativeDecimalString
    output_tokens: NonNegativeDecimalString
    total_usd: NonNegativeDecimalString | None
    total_receipt_lines: int = Field(strict=True)
    total_unpriced_lines: int = Field(strict=True)
    spend_per_hour_usd: NonNegativeDecimalString | None
    hourly_receipt_lines: int = Field(strict=True)
    hourly_unpriced_lines: int = Field(strict=True)

class ModelSpendRow(SpendTableMetrics):
    model: NonBlankString | None


class ThreadSpendRow(SpendTableMetrics):
    thread_id: UUID
    models: list[ModelSpendRow]

class PurposeSpendRow(SpendTableMetrics):
    purpose: Literal[
        "building",
        "extraction",
        "curation",
        "judge",
        "remember",
        "embedding",
        "scout",
    ]
    label: NonBlankString


class SpendTableSnapshot(ContractModel):
    as_of: datetime
    window_minutes: Literal[60]
    threads: list[ThreadSpendRow]
    purposes: list[PurposeSpendRow]

class VitalsSpendPoint(ContractModel):
    minute: datetime
    cost_usd: NonNegativeDecimalString | None
    receipt_lines: int = Field(strict=True)
    unpriced_lines: int = Field(strict=True)

class VitalsSpendLane(ContractModel):
    dimension: Literal["total", "purpose", "model"]
    key: NonBlankString | None
    label: NonBlankString
    points: list[VitalsSpendPoint]

class VitalsSpend(ContractModel):
    source_view: Literal["v_spend_rate", "spend_event"]
    latest_minute: datetime | None
    lanes: list[VitalsSpendLane]

type VitalsGaugeStatus = Literal["measured", "not_recorded", "placeholder"]
type VitalsLifecycleMetric = Literal[
    "created",
    "reinforced",
    "superseded",
    "merged",
    "quarantined",
    "tombstoned",
    "add_backs",
]
type VitalsPalaceMetric = Literal[
    "active_units",
    "pinned_units",
    "candidates_pending",
    "edges",
    "staged_units",
    "queue_depth",
]



class VitalsLifecycleRate(ContractModel):
    metric: VitalsLifecycleMetric
    status: VitalsGaugeStatus
    per_hour: int | None = Field(strict=True)
    source: NonBlankString | None

class VitalsPalaceCount(ContractModel):
    metric: VitalsPalaceMetric
    status: VitalsGaugeStatus
    count: int | None = Field(strict=True)
    source: NonBlankString | None

class VitalsReconciliation(ContractModel):
    status: Literal["not_recorded", "baseline", "balanced", "drift", "unavailable"]
    checked_at: datetime | None
    broker_usage_usd: NonNegativeDecimalString | None
    ledger_cost_usd: NonNegativeDecimalString | None
    broker_since_baseline_usd: NonNegativeDecimalString | None
    ledger_since_baseline_usd: NonNegativeDecimalString | None
    drift_usd: SignedDecimalString | None
    tolerance_usd: NonNegativeDecimalString | None
    unpriced_lines: int = Field(strict=True)
    source: Literal["openrouter:/api/v1/key"] | None
    error_code: Literal["broker_unavailable", "invalid_broker_response"] | None

class VitalsAccounting(ContractModel):
    """Harness-local receipt drift added at the public Rack boundary. [A-038]"""

    status: Literal["clear", "pending", "degraded"] = "clear"
    pending_lines: int = Field(default=0, strict=True)
    oldest_queued_at: datetime | None = None
    source: Literal["harness.receipt_queue"] = "harness.receipt_queue"

class VitalsResources(ContractModel):
    """Cross-process resource gauge enriched by Harness under A-044."""

    status: Literal["partial", "measured"]
    daemon_rss_bytes: int | None = Field(strict=True)
    daemon_uptime_seconds: int | None = Field(strict=True)
    disk_free_bytes: int | None = Field(strict=True)
    disk_total_bytes: int | None = Field(strict=True)
    database_bytes: int = Field(strict=True)
    journal_bytes: int | None = Field(strict=True)
    backup_bytes: int | None = Field(strict=True)
    warning: Literal["low_disk"] | None

class VitalsSnapshot(ContractModel):
    as_of: datetime
    window_minutes: Literal[60]
    spend: VitalsSpend
    reconciliation: VitalsReconciliation
    accounting: VitalsAccounting = Field(default_factory=VitalsAccounting)
    resources: VitalsResources
    lifecycle_rates: list[VitalsLifecycleRate]
    palace_counts: list[VitalsPalaceCount]

class MemoryGraphQuery(ContractModel):
    principal_id: NonBlankString
    memory_ids: list[UUID] | None


class MemoryGraphSnapshot(ContractModel):
    as_of: datetime
    graph_edge_sim: float
    nodes: list[JsonObject]
    edges: list[JsonObject]
    omitted_memory_ids: list[UUID]


class ScorerConsoleQuery(ContractModel):
    principal_id: NonBlankString
    thread_id: UUID | None
    as_of: Literal["now"] = "now"


class ScorerValues(ContractModel):
    # WALL Palace writes / A-034: browser controls bind only the declared parameter ranges.
    tau: float = Field(strict=True, ge=0, le=1)
    top_k: int = Field(strict=True, ge=1, le=8)
    memory_context_share: float = Field(strict=True, ge=0.01, le=0.50)
    half_life_time_days: float = Field(strict=True, gt=0)
    half_life_hist_days: float = Field(strict=True, gt=0)
    weights: dict[Literal["sem", "kw", "time", "proj", "freq", "hist"], float]


class ScorerConsoleSnapshot(ContractModel):
    as_of: datetime
    scope: Literal["GLOBAL", "CURRENT"]
    thread_id: UUID | None
    descriptors: list[JsonObject]
    active_version: NonBlankString
    configurations: list[JsonObject]
    activations: list[JsonObject]
    proposed_versions: list[JsonObject]
    accuracy: list[JsonObject]
    learning: JsonObject
    candidates: list[JsonObject]


class ReplayScoreView(ContractModel):
    disagreements: int = Field(strict=True)
    weighted_disagreements: NonNegativeDecimalString
    injected_tokens: int = Field(strict=True)
    share_disagreements: int = Field(default=0, strict=True)
    weighted_share_disagreements: NonNegativeDecimalString = "0"


class RetrainResponse(ContractModel):
    status: Literal["insufficient_data", "not_better", "proposed"]
    incumbent_version: NonBlankString
    proposal_version: NonBlankString | None
    eligible_dispositions: int = Field(strict=True)
    training_dispositions: int = Field(strict=True)
    holdout_dispositions: int = Field(strict=True)
    training_pairs: int = Field(strict=True)
    incumbent: ReplayScoreView | None
    challenger: ReplayScoreView | None
    reason: StrictStr


class ScorerConfigurationView(ContractModel):
    version: NonBlankString
    created_at: datetime
    status: Literal["active", "proposed", "inactive"]
    values: ScorerValues
    replay: JsonObject | None


class CreateScorerConfigRequest(ContractModel):
    event_uid: ULID
    base_version: NonBlankString
    values: ScorerValues
    simulation_digest: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    force: Literal[True]
    actor_class: Literal["human"] = "human"
    machine_id: NonBlankString


class ActivateScorerConfigRequest(ContractModel):
    event_uid: ULID
    actor_class: Literal["human"] = "human"
    machine_id: NonBlankString


class ScorerSimulationRequest(ContractModel):
    principal_id: NonBlankString
    injection_id: UUID | None
    base_version: NonBlankString
    values: ScorerValues
    slice_parameter_id: NonBlankString


class ScorerSimulationResponse(ContractModel):
    simulation_digest: Annotated[StrictStr, Field()]
    base_version: NonBlankString
    values: ScorerValues
    source_boundary: str | None
    holdout_dispositions: int = Field(strict=True)
    accuracy_percent: str | None
    incumbent_accuracy_percent: str | None
    delta_percent: str | None
    instant: JsonObject
    slice: JsonObject


class ScorerAuditionRequest(ContractModel):
    principal_id: NonBlankString
    injection_id: UUID
    proposal_version: NonBlankString


class ScorerAuditionResponse(ContractModel):
    incumbent_version: NonBlankString
    proposal_version: NonBlankString
    instant: JsonObject


class RackScorerForceRequest(ContractModel):
    # WALL Palace writes / A-047: browser intent cannot carry owner provenance.
    model_config = ConfigDict(extra="forbid")
    event_uid: ULID
    base_version: NonBlankString
    values: ScorerValues
    simulation_digest: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    force: Literal[True]


class RackScorerSimulationRequest(ContractModel):
    # WALL Palace writes / A-047: browser intent cannot carry owner provenance.
    model_config = ConfigDict(extra="forbid")
    injection_id: UUID | None = None
    base_version: NonBlankString
    values: ScorerValues
    slice_parameter_id: NonBlankString


class RackScorerAuditionRequest(ContractModel):
    # WALL Palace writes / A-047: browser intent cannot carry owner provenance.
    model_config = ConfigDict(extra="forbid")
    injection_id: UUID
    proposal_version: NonBlankString


class RackScorerActivateRequest(ContractModel):
    # WALL Palace writes / A-047: browser intent cannot carry owner provenance.
    model_config = ConfigDict(extra="forbid")
    event_uid: ULID


class ProblemDetail(BaseModel):
    """RFC 7807 body; extension members are permitted by that standard."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    type: str = "about:blank"
    title: str | None = None
    status: int | None = None
    detail: str | None = None
    instance: str | None = None
    endpoint: str | None = None

class SpineClientError(RuntimeError):
    """Base class for typed failures at the Spine client boundary."""


class SpineOwnershipError(SpineClientError):
    """The requested queue decision is outside the client's principal scope."""


class SpineTransportError(SpineClientError):
    """A request failed before Spine returned an HTTP response."""

    def __init__(self) -> None:
        super().__init__("Spine request failed before receiving a response")


class SpineResponseError(SpineClientError):
    """Spine returned an HTTP response that violates C.4."""

    def __init__(self, response: httpx.Response, message: str) -> None:
        self.response = response
        self.status_code = response.status_code
        super().__init__(f"{message} (HTTP {response.status_code})")


class SpineProblemError(SpineResponseError):
    """Spine returned a valid RFC 7807 problem response."""

    def __init__(self, response: httpx.Response, problem: ProblemDetail) -> None:
        self.problem = problem
        super().__init__(response, "Spine returned an RFC 7807 problem")


class CreateMemoryConflictError(SpineResponseError):
    """Memory creation hit one of C.4's exact domain conflicts."""

    def __init__(self, response: httpx.Response, conflict: CreateMemoryConflict) -> None:
        self.conflict = conflict
        super().__init__(response, "Spine rejected memory creation with a domain conflict")


class PatchMemoryConflictError(SpineResponseError):
    """Memory PATCH hit one of C.4's exact domain conflicts."""

    def __init__(self, response: httpx.Response, conflict: PatchMemoryConflict) -> None:
        self.conflict = conflict
        super().__init__(response, "Spine rejected memory patch with a domain conflict")


_JSON_MEDIA_TYPE = "application/json"
_PROBLEM_MEDIA_TYPE = "application/problem+json"
_PREPARE_RESPONSE = TypeAdapter(InjectPrepareResponse)
_COMMIT_RESPONSE = TypeAdapter(InjectCommitResponse)
_FEEDBACK_RESPONSE = TypeAdapter(FeedbackResponse)
_INJECTION_EVENT_ANNOTATIONS_RESPONSE = TypeAdapter(InjectionEventAnnotationsResponse)
_CREATED_RESPONSE = TypeAdapter(CreatedMemoryResponse)
_SIMILAR_RESPONSE = TypeAdapter(SimilarMemoriesResponse)
_CREATE_CONFLICT = TypeAdapter(CreateMemoryConflict)
_MEMORY_SPLIT_RESPONSE = TypeAdapter(MemorySplitResponse)
_MEMORY_UNIT = TypeAdapter(MemoryUnit)
_PATCH_CONFLICT = TypeAdapter(PatchMemoryConflict)
_MEMORY_LIST_RESPONSE = TypeAdapter(PagedMemoryListResponse)
_SEARCH_RESPONSE = TypeAdapter(SearchResponse)
_SPEND_EVENTS_RESPONSE = TypeAdapter(SpendEventsResponse)
_SPEND_TABLE_SNAPSHOT = TypeAdapter(SpendTableSnapshot)
_VITALS_SNAPSHOT = TypeAdapter(VitalsSnapshot)
_MEMORY_GRAPH_SNAPSHOT = TypeAdapter(MemoryGraphSnapshot)
_SCORER_CONSOLE_SNAPSHOT = TypeAdapter(ScorerConsoleSnapshot)
_RETRAIN_RESPONSE = TypeAdapter(RetrainResponse)
_SCORER_CONFIGURATION = TypeAdapter(ScorerConfigurationView)
_SCORER_SIMULATION = TypeAdapter(ScorerSimulationResponse)
_SCORER_AUDITION = TypeAdapter(ScorerAuditionResponse)
_EXTRACTION_RESPONSE = TypeAdapter(ExtractionResponse)
_SEED_RESPONSE = TypeAdapter(SeedResponse)
_QUEUE_RESPONSE = TypeAdapter(QueueResponse)
_CURATOR_ACTIVITY = TypeAdapter(CuratorActivity)
_STAGE_SYMPHONY_MEMORY_RESPONSE = TypeAdapter(StageSymphonyMemoryResponse)
_SYMPHONY_VISIBILITY_RESPONSE = TypeAdapter(SymphonyVisibilityResponse)
_RESOLVE_SYMPHONY_RUN_RESPONSE = TypeAdapter(ResolveSymphonyRunResponse)
_QUEUE_DECISION_RESPONSE = TypeAdapter(QueueDecisionResponse)
_BATCH_DECISION_RESPONSE = TypeAdapter(BatchDecisionResponse)
_TRANSCRIPT_APPEND_RESPONSE = TypeAdapter(TranscriptAppendResult)
_TRANSCRIPT_LIST_RESPONSE = TypeAdapter(TranscriptList)
_TRANSCRIPT_STATUS_RESPONSE = TypeAdapter(TranscriptStatus)
_PROBLEM_DETAIL = TypeAdapter(ProblemDetail)


class SpineClient:
    """Own one HTTP transport and validate every Spine response by status."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
        principal_id: str | None = None,
    ) -> None:
        normalized_url = _normalize_base_url(base_url)
        self.base_url = str(normalized_url)
        self._principal_id = principal_id
        self._owned_queue_items: set[str] = set()
        self._owned_queue_batches: set[UUID] = set()
        self._client = httpx.AsyncClient(
            base_url=normalized_url,
            headers={
                "Accept": f"{_JSON_MEDIA_TYPE}, {_PROBLEM_MEDIA_TYPE}",
                "Authorization": f"Bearer {token}",
            },
            follow_redirects=False,
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> SpineClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the owned HTTP client and any caller-supplied transport."""

        await self._client.aclose()

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        """Mirror POST /v1/inject/prepare."""

        response = await self._request(
            "POST",
            "v1/inject/prepare",
            json_body=request.model_dump(mode="json", exclude_none=True, exclude_defaults=True),
        )
        return _expect_success(response, status=200, adapter=_PREPARE_RESPONSE)

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        """Mirror POST /v1/inject/commit."""

        response = await self._request(
            "POST",
            "v1/inject/commit",
            json_body=_request_body(request),
        )
        return _expect_success(response, status=200, adapter=_COMMIT_RESPONSE)

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        """Mirror POST /v1/feedback."""

        response = await self._request(
            "POST",
            "v1/feedback",
            json_body=_request_body(request),
        )
        return _expect_success(response, status=200, adapter=_FEEDBACK_RESPONSE)

    async def annotate_injection_events(
        self,
        request: InjectionEventAnnotationsRequest,
    ) -> InjectionEventAnnotationsResponse:
        """Mirror A-053 POST /v1/injection-event-annotations."""

        response = await self._request(
            "POST",
            "v1/injection-event-annotations",
            json_body=_request_body(request),
        )
        return _expect_success(
            response,
            status=200,
            adapter=_INJECTION_EVENT_ANNOTATIONS_RESPONSE,
        )

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        """Mirror POST /v1/memories."""

        response = await self._request(
            "POST",
            "v1/memories",
            json_body=_request_body(request),
        )
        if response.status_code == 201:
            return _decode_json(response, _CREATED_RESPONSE)
        if response.status_code == 200:
            return _decode_json(response, _SIMILAR_RESPONSE)
        if response.status_code == 409 and _media_type(response) == _JSON_MEDIA_TYPE:
            conflict = _decode_json(response, _CREATE_CONFLICT)
            # WALL Palace writes / C.4: propagate a refused create without claiming a save.
            raise CreateMemoryConflictError(response, conflict)
        _raise_problem(response)

    async def create_memory_split(self, request: MemorySplitRequest) -> CreateMemorySplitResponse:
        """Mirror A-049 POST /v1/memory-splits."""

        response = await self._request(
            "POST",
            "v1/memory-splits",
            json_body=_request_body(request),
        )
        if response.status_code == 201:
            return _decode_json(response, _MEMORY_SPLIT_RESPONSE)
        if response.status_code == 200:
            return _decode_json(response, _SIMILAR_RESPONSE)
        if response.status_code == 409 and _media_type(response) == _JSON_MEDIA_TYPE:
            conflict = _decode_json(response, _CREATE_CONFLICT)
            # WALL Palace writes / C.4: propagate a refused create without claiming a save.
            raise CreateMemoryConflictError(response, conflict)
        _raise_problem(response)

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse:
        """Mirror PATCH /v1/memories/{id}."""

        response = await self._request(
            "PATCH",
            f"v1/memories/{memory_id}",
            json_body=_request_body(request),
        )
        if response.status_code == 200:
            return _decode_json(response, _MEMORY_UNIT)
        if response.status_code == 409 and _media_type(response) == _JSON_MEDIA_TYPE:
            conflict = _decode_json(response, _PATCH_CONFLICT)
            # WALL Palace writes / C.4: propagate CAS refusal without claiming an edit.
            raise PatchMemoryConflictError(response, conflict)
        _raise_problem(response)

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        """List heads; daemon-bound clients use the server-scoped graph projection."""

        if self._principal_id is not None:
            # The legacy list is Palace-wide; the graph filters in SQL and
            # carries complete heads, so a daemon never downloads peer memories.
            graph = await self.memory_graph(
                MemoryGraphQuery(principal_id=self._principal_id, memory_ids=None)
            )
            memories = [MemoryUnit.model_validate(node["memory"]) for node in graph.nodes]
            memories = [
                memory for memory in memories
                if memory.principal_id == self._principal_id
                and (params.status is None or memory.status == params.status)
                and (params.project_key is None or memory.project_key == params.project_key)
                and (not params.q or any(params.q.strip().casefold() in value.casefold()
                                         for value in (memory.label, memory.body)))
            ]
            memories.sort(key=lambda memory: str(memory.memory_id))
            memories.sort(key=lambda memory: memory.updated_at, reverse=True)
            return PagedMemoryListResponse(
                items=memories[params.offset:params.offset + params.limit],
                total=len(memories), limit=params.limit, offset=params.offset,
            )

        response = await self._request(
            "GET",
            "v1/memories",
            params=params.model_dump(mode="json", exclude_none=True),
        )
        return _expect_success(response, status=200, adapter=_MEMORY_LIST_RESPONSE)

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Mirror POST /v1/search."""

        response = await self._request(
            "POST",
            "v1/search",
            json_body=_request_body(request),
        )
        return _expect_success(response, status=200, adapter=_SEARCH_RESPONSE)

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        """Synchronously mirror A-027 POST /v1/spend/events."""

        response = await self._request(
            "POST",
            "v1/spend/events",
            json_body=_request_body(request),
        )
        return _expect_success(response, status=200, adapter=_SPEND_EVENTS_RESPONSE)

    async def vitals_snapshot(self) -> VitalsSnapshot:
        """Read A-028's live trailing-hour Palace Vitals snapshot."""

        response = await self._request("GET", "v1/vitals")
        return _expect_success(response, status=200, adapter=_VITALS_SNAPSHOT)

    async def thread_vitals_snapshot(self, thread_id: UUID) -> VitalsSnapshot:
        response = await self._request("GET", f"v1/vitals/threads/{thread_id}")
        return _expect_success(response, status=200, adapter=_VITALS_SNAPSHOT)

    async def spend_table(self, thread_ids: list[UUID] | None = None) -> SpendTableSnapshot | None:
        """Read M3SP's table projection; a 404 is an older Palace, not broken chat."""

        params: JsonObject | None = None
        if thread_ids is not None:
            params = {
                "scope": "threads",
                "thread_id": [str(thread_id) for thread_id in thread_ids],
            }
        response = await self._request("GET", "v1/spend/table", params=params)
        if response.status_code == 404:
            return None
        return _expect_success(response, status=200, adapter=_SPEND_TABLE_SNAPSHOT)

    async def memory_graph(self, request: MemoryGraphQuery) -> MemoryGraphSnapshot:
        response = await self._request(
            "POST",
            "v1/memory-graph/query",
            json_body=request.model_dump(mode="json"),
        )
        return _expect_success(response, status=200, adapter=_MEMORY_GRAPH_SNAPSHOT)

    async def scorer_console(self, request: ScorerConsoleQuery) -> ScorerConsoleSnapshot:
        response = await self._request(
            "POST",
            "v1/scorer-console/query",
            json_body=request.model_dump(mode="json"),
        )
        return _expect_success(response, status=200, adapter=_SCORER_CONSOLE_SNAPSHOT)

    async def retrain(self) -> RetrainResponse:
        """Invoke A-051's existing bodyless manual learner trigger."""

        response = await self._request("POST", "retrain")
        return _expect_success(response, status=200, adapter=_RETRAIN_RESPONSE)

    async def create_scorer_config(
        self, request: CreateScorerConfigRequest
    ) -> ScorerConfigurationView:
        response = await self._request(
            "POST", "v1/scorer-configs", json_body=_request_body(request)
        )
        return _expect_success(response, status=200, adapter=_SCORER_CONFIGURATION)

    async def simulate_scorer(self, request: ScorerSimulationRequest) -> ScorerSimulationResponse:
        response = await self._request(
            "POST",
            "v1/scorer-simulations",
            json_body=request.model_dump(mode="json"),
        )
        return _expect_success(response, status=200, adapter=_SCORER_SIMULATION)

    async def audition_scorer(self, request: ScorerAuditionRequest) -> ScorerAuditionResponse:
        response = await self._request(
            "POST", "v1/scorer-auditions", json_body=_request_body(request)
        )
        return _expect_success(response, status=200, adapter=_SCORER_AUDITION)

    async def activate_scorer_config(
        self, version: str, request: ActivateScorerConfigRequest
    ) -> ScorerConfigurationView:
        response = await self._request(
            "POST",
            f"v1/scorer-configs/{version}/activate",
            json_body=_request_body(request),
        )
        return _expect_success(response, status=200, adapter=_SCORER_CONFIGURATION)

    async def create_extraction(self, request: ExtractionRequest) -> ExtractionResponse:
        response = await self._request("POST", "v1/extractions", json_body=_request_body(request))
        return _expect_success(response, status=200, adapter=_EXTRACTION_RESPONSE)

    async def create_seed(self, request: SeedRequest) -> SeedResponse:
        response = await self._request("POST", "v1/seeds", json_body=_request_body(request))
        return _expect_success(response, status=200, adapter=_SEED_RESPONSE)

    async def approval_queue(
        self,
        principal_id: str,
        *,
        thread_id: UUID | None = None,
        birthplace: Literal["thread", "seed", "symphony", "curator"] | None = None,
    ) -> QueueResponse:
        params: JsonObject = {"principal_id": principal_id}
        if thread_id is not None:
            params["thread_id"] = str(thread_id)
        if birthplace is not None:
            params["birthplace"] = birthplace
        response = await self._request("GET", "v1/approval-queue", params=params)
        result = _expect_success(response, status=200, adapter=_QUEUE_RESPONSE)
        for card in result.cards:
            if card.candidate.principal_id == self._principal_id:
                self._owned_queue_items.add(card.item_uid)
                if card.batch_uid is not None:
                    self._owned_queue_batches.add(card.batch_uid)
        return result

    async def curator_activity(self, principal_id: str) -> CuratorActivity | None:
        """Read curator activity; a 404 is an older Palace, not broken chat."""

        response = await self._request("GET", "v1/curation", params={"principal_id": principal_id})
        if response.status_code == 404:
            return None
        return _expect_success(response, status=200, adapter=_CURATOR_ACTIVITY)

    async def stage_symphony_memory(
        self, request: StageSymphonyMemoryRequest
    ) -> StageSymphonyMemoryResponse:
        response = await self._request(
            "POST", "v1/symphony/memories", json_body=_request_body(request)
        )
        return _expect_success(response, status=201, adapter=_STAGE_SYMPHONY_MEMORY_RESPONSE)

    async def visible_symphony_memories(
        self, request: SymphonyVisibilityRequest
    ) -> SymphonyVisibilityResponse:
        response = await self._request(
            "POST", "v1/symphony/memories/query", json_body=_request_body(request)
        )
        return _expect_success(response, status=200, adapter=_SYMPHONY_VISIBILITY_RESPONSE)

    async def resolve_symphony_run(
        self, run_id: str, request: ResolveSymphonyRunRequest
    ) -> ResolveSymphonyRunResponse:
        response = await self._request(
            "POST", f"v1/symphony/runs/{run_id}/resolve", json_body=_request_body(request)
        )
        return _expect_success(response, status=200, adapter=_RESOLVE_SYMPHONY_RUN_RESPONSE)

    async def decide_queue_item(
        self, item_uid: str, request: QueueDecisionRequest
    ) -> QueueDecisionResponse:
        await self._require_owned_queue(item_uid=item_uid)
        response = await self._request(
            "POST", f"v1/approval-queue/{item_uid}/decisions", json_body=_request_body(request)
        )
        return _expect_success(response, status=200, adapter=_QUEUE_DECISION_RESPONSE)

    async def decide_queue_batch(
        self, batch_uid: UUID, request: QueueDecisionRequest
    ) -> BatchDecisionResponse:
        await self._require_owned_queue(batch_uid=batch_uid)
        response = await self._request(
            "POST",
            f"v1/approval-queue/batches/{batch_uid}/decisions",
            json_body=_request_body(request),
        )
        return _expect_success(response, status=200, adapter=_BATCH_DECISION_RESPONSE)

    async def _require_owned_queue(
        self, *, item_uid: str | None = None, batch_uid: UUID | None = None
    ) -> None:
        if self._principal_id is None:
            return
        if item_uid in self._owned_queue_items or batch_uid in self._owned_queue_batches:
            return
        await self.approval_queue(self._principal_id)
        if item_uid not in self._owned_queue_items and batch_uid not in self._owned_queue_batches:
            # WALL Palace writes / F069, F076: a queue refusal must never be reported as success.
            raise SpineOwnershipError(
                "This queue decision does not belong to this identity. Refresh the queue."
            )

    async def append_transcripts(self, request: AppendTranscriptsRequest) -> TranscriptAppendResult:
        response = await self._request("POST", "v1/transcripts", json_body=_request_body(request))
        return _expect_success(response, status=200, adapter=_TRANSCRIPT_APPEND_RESPONSE)

    async def transcripts(self, principal_id: str) -> TranscriptList:
        response = await self._request(
            "GET", "v1/transcripts", params={"principal_id": principal_id}
        )
        return _expect_success(response, status=200, adapter=_TRANSCRIPT_LIST_RESPONSE)

    async def transcript_status(self, principal_id: str) -> TranscriptStatus:
        response = await self._request(
            "GET", "v1/transcripts/status", params={"principal_id": principal_id}
        )
        return _expect_success(response, status=200, adapter=_TRANSCRIPT_STATUS_RESPONSE)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None = None,
        params: JsonObject | None = None,
    ) -> httpx.Response:
        try:
            return await self._client.request(
                method,
                path,
                json=json_body,
                params=params,
            )
        except httpx.RequestError as exc:
            # INCIDENT F062: typed transport failure lets optional Palace reads fail locally.
            raise SpineTransportError from exc


def _request_body(request: ContractModel) -> JsonObject:
    return request.model_dump(mode="json", exclude_none=True)


def _normalize_base_url(base_url: str) -> httpx.URL:
    raw_url = base_url.strip()
    parsed = httpx.URL(raw_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.userinfo
        or parsed.query
        or b"?" in parsed.raw_path
        or parsed.fragment
        or "#" in raw_url
    ):
        # WALL credentials / ADR015: send the token only to an unambiguous HTTP endpoint.
        raise ValueError(
            "base_url must be absolute HTTP(S) without credentials, query, or fragment"
        )
    return parsed.copy_with(raw_path=parsed.raw_path.rstrip(b"/") + b"/")


def _expect_success[ResponseT](
    response: httpx.Response,
    *,
    status: int,
    adapter: TypeAdapter[ResponseT],
) -> ResponseT:
    if response.status_code != status:
        _raise_problem(response)
    return _decode_json(response, adapter)


def _decode_json[ResponseT](
    response: httpx.Response,
    adapter: TypeAdapter[ResponseT],
) -> ResponseT:
    try:
        return adapter.validate_json(response.content, strict=True)
    except ValueError as exc:
        # INCIDENT F073: retain the HTTP response so busy Palace retries stay distinct from absence.
        raise SpineResponseError(response, "Spine returned a body outside C.4") from exc


def _raise_problem(response: httpx.Response) -> Never:
    problem = _decode_json(response, _PROBLEM_DETAIL)
    # INCIDENT F076: carry the actual Palace refusal to the deciding surface.
    raise SpineProblemError(response, problem)


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").partition(";")[0].strip().lower()
