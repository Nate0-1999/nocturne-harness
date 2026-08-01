"""Typed asynchronous client for the enacted Spine HTTP API."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
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


type ULID = Annotated[StrictStr, AfterValidator(_require_ulid)]
type NonBlankString = Annotated[StrictStr, AfterValidator(_require_nonblank)]


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


class InjectPrepareResponse(ContractModel):
    injection_id: UUID
    snapshot_ts: datetime
    scorer_version: str
    injected: list[ScoredMemoryCard]
    near_misses: list[ScoredMemoryCard]


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
            json_body=_request_body(request),
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
