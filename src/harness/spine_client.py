"""Typed asynchronous client for the enacted Spine HTTP API."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Never
from uuid import UUID

import httpx
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

type JsonObject = dict[str, Any]

_ULID_PATTERN = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$", re.IGNORECASE)


def _require_ulid(value: str) -> str:
    if not _ULID_PATTERN.fullmatch(value):
        raise ValueError("value must be a ULID")
    return value.upper()


def _require_nonblank(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("value must be nonblank without surrounding whitespace")
    return value


def _require_nonnegative_decimal_string(value: str) -> str:
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ValueError("value must be a non-negative decimal string")
    return value


type ULID = Annotated[StrictStr, AfterValidator(_require_ulid)]
type NonBlankString = Annotated[StrictStr, AfterValidator(_require_nonblank)]
type NonNegativeDecimalString = Annotated[
    StrictStr,
    AfterValidator(_require_nonnegative_decimal_string),
]


class ContractModel(BaseModel):
    """Closed JSON object for a body whose fields are fixed by Spine law."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROCEDURE = "procedure"
    PROJECT_NOTE = "project_note"
    PERSONA = "persona"
    PINNED = "pinned"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
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
type RawFeatureScore = Annotated[float, Field(strict=True, ge=0, le=1)]
type PositiveRank = Annotated[int, Field(strict=True, ge=1)]


class MemoryFeatures(ContractModel):
    sem: RawFeatureScore
    kw: RawFeatureScore
    time: RawFeatureScore
    proj: RawFeatureScore
    freq: RawFeatureScore
    hist: RawFeatureScore


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
    origin_path: str | None
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
    agent_kind: str | None = None
    prompt: str
    model_context_tokens: int = Field(gt=0)
    mode: Literal["gate", "autonomous"] = "gate"
    current_memory_ids: list[UUID] = Field(default_factory=list)
    confirmed_memory_ids: list[UUID] = Field(default_factory=list)
    excluded_memory_ids: list[UUID] = Field(default_factory=list)


class InjectPrepareResponse(ContractModel):
    injection_id: UUID
    snapshot_ts: datetime
    scorer_version: str
    injected: list[ScoredMemoryCard]
    near_misses: list[ScoredMemoryCard]
    final_block: str | None


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


class CreateMemoryRequest(ContractModel):
    principal_id: str
    label: str
    body: str
    kind: MemoryKind
    keywords: list[str] | None = None
    project_key: str | None = None
    thread_origin: str | None = None
    origin_path: str | None = None
    editor: str
    machine_id: str
    force: bool = False


class CreatedMemoryResponse(ContractModel):
    created: MemoryUnit


class SimilarMemoriesResponse(ContractModel):
    created: None
    similar: list[SimilarityMemoryCard]


type CreateMemoryResponse = CreatedMemoryResponse | SimilarMemoriesResponse


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
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class PagedMemoryListResponse(ContractModel):
    items: list[MemoryUnit]
    total: int
    limit: int
    offset: int


class SearchRequest(ContractModel):
    principal_id: str
    query: str
    k: int = Field(default=10, strict=True, ge=1, le=50)
    project_key: str | None = None


class SearchResponse(ContractModel):
    results: list[SimilarityMemoryCard]


class SpendEvent(ContractModel):
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

    @field_validator("ts")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ts must include a UTC offset")
        return value


class SpendEventsRequest(ContractModel):
    events: list[SpendEvent] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_event_ids(self) -> SpendEventsRequest:
        ids = [event.event_uid for event in self.events]
        if len(set(ids)) != len(ids):
            raise ValueError("events must have unique event_uid values")
        return self


class SpendEventsResponse(ContractModel):
    accepted: int = Field(strict=True, ge=1)


class VitalsSpendPoint(ContractModel):
    minute: datetime
    cost_usd: NonNegativeDecimalString | None
    receipt_lines: int = Field(strict=True, ge=0)
    unpriced_lines: int = Field(strict=True, ge=0)

    @field_validator("minute")
    @classmethod
    def require_aware_minute(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def require_honest_price_state(self) -> VitalsSpendPoint:
        if self.unpriced_lines > self.receipt_lines:
            raise ValueError("Vitals unpriced_lines cannot exceed receipt_lines")
        all_unpriced = self.unpriced_lines == self.receipt_lines
        if all_unpriced and self.cost_usd is not None:
            raise ValueError("an all-unpriced Vitals point must have a null cost")
        if not all_unpriced and self.cost_usd is None:
            raise ValueError("a Vitals point with priced lines must carry known cost")
        return self


class VitalsSpendLane(ContractModel):
    dimension: Literal["total", "purpose", "model"]
    key: NonBlankString | None
    label: NonBlankString
    points: list[VitalsSpendPoint]

    @model_validator(mode="after")
    def require_dimension_key(self) -> VitalsSpendLane:
        if self.dimension == "total" and self.key is not None:
            raise ValueError("the total Vitals lane must have a null key")
        if self.dimension != "total" and self.key is None:
            raise ValueError("purpose and model Vitals lanes require a key")
        if (
            self.dimension == "model"
            and self.key == "unreported"
            and self.label != "Model not reported"
        ):
            raise ValueError("the unreported model lane requires its stable human label")
        if self.dimension == "model" and self.key is not None and self.key.startswith("~"):
            if self.key == "~unreported":
                expected_label = "unreported"
            elif self.key.startswith("~~"):
                expected_label = self.key.removeprefix("~")
            else:
                raise ValueError("a Vitals model lane used a noncanonical key escape")
            if self.label != expected_label:
                raise ValueError("a Vitals model lane key does not match its A-029 label")
        minutes = [point.minute for point in self.points]
        if any(left >= right for left, right in zip(minutes, minutes[1:], strict=False)):
            raise ValueError("Vitals lane points must be uniquely ordered by minute")
        return self


class VitalsSpend(ContractModel):
    source_view: Literal["v_spend_rate"]
    latest_minute: datetime | None
    lanes: list[VitalsSpendLane]

    @field_validator("latest_minute")
    @classmethod
    def require_aware_latest_minute(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware_timestamp(value)

    @model_validator(mode="after")
    def require_canonical_lanes(self) -> VitalsSpend:
        identities = [(lane.dimension, lane.key) for lane in self.lanes]
        if len(identities) != len(set(identities)):
            raise ValueError("Vitals spend lanes must be unique")
        if not self.lanes or sum(lane.dimension == "total" for lane in self.lanes) != 1:
            raise ValueError("Vitals spend requires exactly one total lane")
        if self.lanes != sorted(self.lanes, key=_vitals_lane_sort_key):
            raise ValueError("Vitals spend lanes are outside canonical order")
        if any(lane.dimension != "total" and not lane.points for lane in self.lanes):
            raise ValueError("a dimensioned Vitals lane must contain at least one point")

        all_minutes = [point.minute for lane in self.lanes for point in lane.points]
        expected_latest = max(all_minutes) if all_minutes else None
        if self.latest_minute != expected_latest:
            raise ValueError("Vitals latest_minute does not match the lane points")

        total = _aggregate_vitals_lanes([lane for lane in self.lanes if lane.dimension == "total"])
        for dimension in ("purpose", "model"):
            dimension_total = _aggregate_vitals_lanes(
                [lane for lane in self.lanes if lane.dimension == dimension]
            )
            if dimension_total != total:
                raise ValueError(f"Vitals {dimension} lanes do not conserve the total lane")
        return self


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

_VITALS_LIFECYCLE_CONTRACT = (
    ("created", "measured"),
    ("reinforced", "not_recorded"),
    ("superseded", "not_recorded"),
    ("merged", "not_recorded"),
    ("quarantined", "not_recorded"),
    ("tombstoned", "not_recorded"),
    ("add_backs", "not_recorded"),
)
_VITALS_PALACE_CONTRACT = (
    ("active_units", "measured"),
    ("pinned_units", "measured"),
    ("candidates_pending", "not_recorded"),
    ("edges", "not_recorded"),
    ("staged_units", "not_recorded"),
    ("queue_depth", "placeholder"),
)


class VitalsLifecycleRate(ContractModel):
    metric: VitalsLifecycleMetric
    status: VitalsGaugeStatus
    per_hour: int | None = Field(strict=True, ge=0)
    source: NonBlankString | None

    @model_validator(mode="after")
    def require_honest_measurement(self) -> VitalsLifecycleRate:
        _require_gauge_value(self.status, self.per_hour, self.source)
        return self


class VitalsPalaceCount(ContractModel):
    metric: VitalsPalaceMetric
    status: VitalsGaugeStatus
    count: int | None = Field(strict=True, ge=0)
    source: NonBlankString | None

    @model_validator(mode="after")
    def require_honest_measurement(self) -> VitalsPalaceCount:
        _require_gauge_value(self.status, self.count, self.source)
        return self


class VitalsSnapshot(ContractModel):
    as_of: datetime
    window_minutes: Literal[60]
    spend: VitalsSpend
    lifecycle_rates: list[VitalsLifecycleRate]
    palace_counts: list[VitalsPalaceCount]

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        return _require_aware_timestamp(value)

    @model_validator(mode="after")
    def require_exact_snapshot(self) -> VitalsSnapshot:
        lifecycle_contract = tuple((gauge.metric, gauge.status) for gauge in self.lifecycle_rates)
        if lifecycle_contract != _VITALS_LIFECYCLE_CONTRACT:
            raise ValueError("Vitals lifecycle gauges are outside the A-028 contract")
        palace_contract = tuple((gauge.metric, gauge.status) for gauge in self.palace_counts)
        if palace_contract != _VITALS_PALACE_CONTRACT:
            raise ValueError("Vitals palace gauges are outside the A-028 contract")

        window_start = self.as_of - timedelta(minutes=self.window_minutes)
        for lane in self.spend.lanes:
            for point in lane.points:
                if not window_start < point.minute <= self.as_of:
                    raise ValueError("Vitals point is outside the live trailing-hour window")
        return self


class ProblemDetail(BaseModel):
    """RFC 7807 body; extension members are permitted by that standard."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    type: str = "about:blank"
    title: str | None = None
    status: int | None = None
    detail: str | None = None
    instance: str | None = None
    endpoint: str | None = None

    @field_validator("title", "status", "detail", "instance", mode="before")
    @classmethod
    def reject_explicit_null_standard_member(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("an RFC 7807 member cannot be null when present")
        return value


class SpineClientError(RuntimeError):
    """Base class for typed failures at the Spine client boundary."""


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
_CREATED_RESPONSE = TypeAdapter(CreatedMemoryResponse)
_SIMILAR_RESPONSE = TypeAdapter(SimilarMemoriesResponse)
_CREATE_CONFLICT = TypeAdapter(CreateMemoryConflict)
_MEMORY_UNIT = TypeAdapter(MemoryUnit)
_PATCH_CONFLICT = TypeAdapter(PatchMemoryConflict)
_MEMORY_LIST_RESPONSE = TypeAdapter(PagedMemoryListResponse)
_SEARCH_RESPONSE = TypeAdapter(SearchResponse)
_SPEND_EVENTS_RESPONSE = TypeAdapter(SpendEventsResponse)
_VITALS_SNAPSHOT = TypeAdapter(VitalsSnapshot)
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
    ) -> None:
        normalized_url = _normalize_base_url(base_url)
        if not token.strip():
            raise ValueError("token must not be blank")
        if token != token.strip():
            raise ValueError("token must not contain surrounding whitespace")
        self.base_url = str(normalized_url)
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

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        """Mirror POST /v1/memories."""

        response = await self._request(
            "POST",
            "v1/memories",
            json_body=_request_body(request),
        )
        if response.status_code == 201:
            return _decode_json(response, _CREATED_RESPONSE, _JSON_MEDIA_TYPE)
        if response.status_code == 200:
            return _decode_json(response, _SIMILAR_RESPONSE, _JSON_MEDIA_TYPE)
        if response.status_code == 409 and _media_type(response) == _JSON_MEDIA_TYPE:
            conflict = _decode_json(response, _CREATE_CONFLICT, _JSON_MEDIA_TYPE)
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
            return _decode_json(response, _MEMORY_UNIT, _JSON_MEDIA_TYPE)
        if response.status_code == 409 and _media_type(response) == _JSON_MEDIA_TYPE:
            conflict = _decode_json(response, _PATCH_CONFLICT, _JSON_MEDIA_TYPE)
            raise PatchMemoryConflictError(response, conflict)
        _raise_problem(response)

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        """Mirror GET /v1/memories."""

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
            raise SpineTransportError from exc


def _request_body(request: ContractModel) -> JsonObject:
    return request.model_dump(mode="json", exclude_none=True)


def _require_aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value


def _require_gauge_value(
    status: VitalsGaugeStatus,
    value: int | None,
    source: str | None,
) -> None:
    if status == "measured":
        if value is None or source is None:
            raise ValueError("a measured Vitals gauge requires a value and source")
        return
    if value is not None or source is not None:
        raise ValueError("a non-measured Vitals gauge must have a null value and source")


def _vitals_lane_sort_key(lane: VitalsSpendLane) -> tuple[int, str]:
    dimension_order = {"total": 0, "purpose": 1, "model": 2}
    return dimension_order[lane.dimension], lane.key or ""


def _aggregate_vitals_lanes(
    lanes: list[VitalsSpendLane],
) -> dict[datetime, tuple[Decimal | None, int, int]]:
    accumulators: dict[datetime, tuple[Decimal, bool, int, int]] = {}
    for lane in lanes:
        for point in lane.points:
            cost, has_priced, receipt_lines, unpriced_lines = accumulators.get(
                point.minute,
                (Decimal(0), False, 0, 0),
            )
            if point.cost_usd is not None:
                cost += Decimal(point.cost_usd)
                has_priced = True
            accumulators[point.minute] = (
                cost,
                has_priced,
                receipt_lines + point.receipt_lines,
                unpriced_lines + point.unpriced_lines,
            )
    return {
        minute: (cost if has_priced else None, receipt_lines, unpriced_lines)
        for minute, (cost, has_priced, receipt_lines, unpriced_lines) in accumulators.items()
    }


def _normalize_base_url(base_url: str) -> httpx.URL:
    raw_url = base_url.strip()
    if not raw_url:
        raise ValueError("base_url must not be blank")
    try:
        parsed = httpx.URL(raw_url)
    except httpx.InvalidURL as exc:
        raise ValueError("base_url must be an absolute HTTP(S) URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.userinfo
        or parsed.query
        or b"?" in parsed.raw_path
        or parsed.fragment
        or "#" in raw_url
    ):
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
    return _decode_json(response, adapter, _JSON_MEDIA_TYPE)


def _decode_json[ResponseT](
    response: httpx.Response,
    adapter: TypeAdapter[ResponseT],
    expected_media_type: str,
) -> ResponseT:
    if _media_type(response) != expected_media_type:
        raise SpineResponseError(response, "Spine returned an unexpected media type")
    try:
        json.loads(
            response.content,
            parse_constant=_reject_non_finite_json,
            parse_float=_parse_finite_json_float,
        )
        return adapter.validate_json(response.content, strict=True)
    except ValueError as exc:
        raise SpineResponseError(response, "Spine returned a body outside C.4") from exc


def _raise_problem(response: httpx.Response) -> Never:
    if response.status_code < 400:
        raise SpineResponseError(response, "Spine returned an unexpected non-error status")
    problem = _decode_json(response, _PROBLEM_DETAIL, _PROBLEM_MEDIA_TYPE)
    if problem.status is not None and problem.status != response.status_code:
        raise SpineResponseError(response, "Spine problem status disagrees with HTTP status")
    raise SpineProblemError(response, problem)


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").partition(";")[0].strip().lower()


def _reject_non_finite_json(value: str) -> Never:
    raise ValueError(f"non-standard JSON constant {value}")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number is outside the finite float range")
    return parsed
