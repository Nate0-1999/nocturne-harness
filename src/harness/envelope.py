"""Validated models and construction helpers for SPEC C.7 envelopes."""

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from harness.project_path import ArtificialProjectPath
from harness.spine_client import MemoryUnit, RemovedMemory, ScoredMemoryCard

_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


type ULID = StrictStr
type NonBlankString = StrictStr

_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_BASE64_CHARS = 4 * ((_MAX_IMAGE_BYTES + 2) // 3)
type ImageMediaType = Literal["image/png", "image/jpeg", "image/webp", "image/gif"]


def _decode_canonical_image(value: str) -> bytes:
    if len(value) > _MAX_IMAGE_BASE64_CHARS:
        # WALL money / A-052: reject oversize billed images before capturing or sending bytes.
        raise ValueError("image exceeds the 5 MiB decoded limit")
    decoded = base64.b64decode(value, validate=True)
    if len(decoded) > _MAX_IMAGE_BYTES:
        # WALL money / A-052: reject oversize billed images before capturing or sending bytes.
        raise ValueError("image exceeds the 5 MiB decoded limit")
    return decoded


def _matches_image_signature(media_type: ImageMediaType, data: bytes) -> bool:
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


class ImageView(BaseModel):
    """Compact server-authored view of one durable prompt attachment. [A-052]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["image"]
    media_type: ImageMediaType
    byte_count: Annotated[StrictInt, Field(gt=0, le=_MAX_IMAGE_BYTES)]
    sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class ImageInput(BaseModel):
    """The singular validated image accepted by ``prompt.submit``. [A-052]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["image"]
    media_type: ImageMediaType
    data_base64: StrictStr

    @field_validator("data_base64")
    @classmethod
    def validate_data_base64(cls, value: str) -> str:
        _decode_canonical_image(value)
        return value

    @model_validator(mode="after")
    def validate_signature(self) -> "ImageInput":
        if not _matches_image_signature(self.media_type, self.decoded_bytes()):
            # WALL owner files / A-052: capture bytes only under their actual image type.
            raise ValueError("image media_type does not match its file signature")
        return self

    def decoded_bytes(self) -> bytes:
        """Return bytes whose image type and size were validated at construction."""

        return _decode_canonical_image(self.data_base64)

    def view(self) -> ImageView:
        """Derive the only image metadata allowed in messages and server events."""

        decoded = self.decoded_bytes()
        return ImageView(
            kind="image",
            media_type=self.media_type,
            byte_count=len(decoded),
            sha256=hashlib.sha256(decoded).hexdigest(),
        )


class MessageType(StrEnum):
    """Named C.7 types; other non-blank strings remain valid extensions."""

    THREAD_CREATE = "thread.create"
    THREAD_SNAPSHOT = "thread.snapshot"
    PROMPT_SUBMIT = "prompt.submit"
    PROMPT_QUEUED = "prompt.queued"
    GATE_OPEN = "gate.open"
    GATE_COMMIT = "gate.commit"
    GATE_DISMISS = "gate.dismiss"
    RUN_STARTED = "run.started"
    RUN_CANCEL = "run.cancel"
    RUN_DELTA = "run.delta"
    RUN_USAGE = "run.usage"
    RUN_DONE = "run.done"
    MEMORY_PANEL_UPDATE = "memory.panel.update"
    ERROR = "error"

    # Names reserved for later milestones. H7 accepts them but supplies no M1
    # behavior or payload contract for them.
    RUN_STEER = "run.steer"
    PLAN_UPDATE = "plan.update"
    CHECKPOINT_CREATED = "checkpoint.created"
    CHECKPOINT_RESTORE = "checkpoint.restore"
    PRESENCE_UPDATE = "presence.update"


class StopReason(StrEnum):
    """The exhaustive M1 terminal reasons for a run."""

    END_TURN = "end_turn"
    CANCELLED = "cancelled"
    ERROR = "error"
    BUDGET_EXCEEDED = "budget_exceeded"


class _ExtensiblePayload(BaseModel):
    """A minimum C.7 payload whose later JSON fields survive validation."""

    model_config = ConfigDict(extra="allow", frozen=True, allow_inf_nan=False)

    # Typing pydantic's extra store makes extension values obey the JSON wire
    # boundary instead of accepting arbitrary Python objects.
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)


class SymphonyRecipeStepPayload(BaseModel):
    """One human-authored recipe step frozen by Symphony deliberation. [ADR-012]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    step_id: NonBlankString
    title: NonBlankString
    done_when: NonBlankString
    search: StrictBool


class SymphonyJudgeCharterPayload(BaseModel):
    """One human-fixed judge charter at the chat-to-Symphony boundary. [D.2 102]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    seat: Literal["motivation", "implementation", "performance"]
    rubric: tuple[NonBlankString, ...] = Field(min_length=1)
    evidence_requirements: tuple[NonBlankString, ...] = Field(min_length=1)
    metrics: tuple[NonBlankString, ...] = ()

    @model_validator(mode="after")
    def require_performance_metrics_only(self) -> "SymphonyJudgeCharterPayload":
        if self.seat == "performance" and not self.metrics:
            # WALL money / T2: a paid performance judge needs the owner-approved metric charter.
            raise ValueError("the performance charter requires precalculated metrics")
        if self.seat != "performance" and self.metrics:
            # WALL attention / T2: preserve the distinct authority of each judge charter.
            raise ValueError("precalculated metrics belong only to performance")
        return self


class SymphonyAuthorityPayload(BaseModel):
    """The plainly signed T2 authority wall for one Symphony stack. [T2, R22]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    # WALL money / T2: preserve the signed purchase and delegation limits.
    attempts: StrictInt = Field(ge=1)
    spend_wall_usd: Decimal = Field(gt=0)
    max_rounds: StrictInt = Field(ge=1)
    depth_cap: StrictInt = Field(ge=0)
    children_per_attempt: StrictInt = Field(ge=0)
    duration_minutes: StrictInt = Field(gt=0)
    signed: Literal[True]


class SymphonyLaunchPayload(BaseModel):
    """A ratified deliberation artifact; auto mode cannot synthesize it. [ADR-012]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    draft_id: ULID
    objective: NonBlankString
    motivation: NonBlankString
    recipe: tuple[SymphonyRecipeStepPayload, ...]
    # WALL money / T2: the signed charter assigns exactly one judge to each of three seats.
    judge_charters: tuple[SymphonyJudgeCharterPayload, ...] = Field(min_length=3, max_length=3)
    authority: SymphonyAuthorityPayload
    hold_for_steering: StrictBool = False

    @model_validator(mode="after")
    def require_fixed_deliberation_shape(self) -> "SymphonyLaunchPayload":
        step_ids = tuple(step.step_id for step in self.recipe)
        if len(set(step_ids)) != len(step_ids):
            # WALL owner files / T2: duplicate step identities would share a worktree target.
            raise ValueError("recipe step ids must be unique")
        seats = tuple(charter.seat for charter in self.judge_charters)
        if seats != ("motivation", "implementation", "performance"):
            # WALL money / T2: do not purchase judges outside the signed three-seat charter.
            raise ValueError("judge charters must fix motivation, implementation, performance")
        return self


class SymphonyClarificationPayload(BaseModel):
    """A logged follow-up inside the immutable deliberation boundary. [G19a]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["clarification"]
    symphony_id: ULID
    attempt_id: NonBlankString
    instruction: NonBlankString


class SymphonyCancelAttemptPayload(BaseModel):
    """A cooperative attempt cancellation already authorized by T2. [G19b/G20]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["cancel_attempt"]
    symphony_id: ULID
    attempt_id: NonBlankString


class SymphonyCharterForkPayload(BaseModel):
    """A fresh signed deliberation that forks instead of rewriting a charter. [G19c]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["charter_change"]
    symphony_id: ULID
    charter: SymphonyJudgeCharterPayload
    fork_signed: Literal[True]


class SymphonyCompletePayload(BaseModel):
    """Let a held toy proof finish after its steering exercise."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["complete"]
    symphony_id: ULID


type SymphonyInterventionPayload = Annotated[
    SymphonyClarificationPayload
    | SymphonyCancelAttemptPayload
    | SymphonyCharterForkPayload
    | SymphonyCompletePayload,
    Field(discriminator="kind"),
]


class ProposedResponseFirePayload(BaseModel):
    """Reference one server-authored Deck proposal; fired text is the prompt itself. [M3DK]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    proposal_run_id: ULID


class PromptSubmitPayload(_ExtensiblePayload):
    prompt: NonBlankString
    image: ImageInput | None = Field(default=None, exclude_if=lambda value: value is None)
    symphony: SymphonyLaunchPayload | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    symphony_intervention: SymphonyInterventionPayload | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    proposed_response: ProposedResponseFirePayload | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def require_one_specialized_input(self) -> "PromptSubmitPayload":
        specialized = sum(
            value is not None for value in (self.image, self.symphony, self.symphony_intervention)
        )
        if specialized > 1:
            # WALL attention / A-052: never silently discard part of the submitted owner input.
            raise ValueError("image, Symphony launch, and Symphony steering are mutually exclusive")
        if self.proposed_response is not None and specialized:
            # WALL attention / M3DK, G19: a proposal click authorizes only its displayed text.
            raise ValueError("a proposed response must be an ordinary text prompt")
        return self


class RunStartedPayload(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID
    resolved_model: NonBlankString | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    image: ImageView | None = Field(default=None, exclude_if=lambda value: value is None)


class RunCancelPayload(_ExtensiblePayload):
    run_id: ULID


class PromptQueuedPayload(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID
    image: ImageView | None = Field(default=None, exclude_if=lambda value: value is None)


class RunDeltaTextPayload(_ExtensiblePayload):
    run_id: ULID
    kind: Literal["text"]
    text: StrictStr


class RunDeltaThinkingPayload(_ExtensiblePayload):
    run_id: ULID
    kind: Literal["thinking"]
    text: StrictStr


class RunDeltaEventPayload(_ExtensiblePayload):
    run_id: ULID
    kind: Literal["event"]
    event: dict[str, JsonValue]
    resolved_model: NonBlankString | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


type RunDeltaPayload = Annotated[
    RunDeltaTextPayload | RunDeltaThinkingPayload | RunDeltaEventPayload,
    Field(discriminator="kind"),
]


class UsagePayload(_ExtensiblePayload):
    """Cumulative run usage without the enclosing run correlation field."""

    requests: StrictInt
    input_tokens: StrictInt
    output_tokens: StrictInt
    cache_read_tokens: StrictInt = Field(
        default=0,
        exclude_if=lambda value: value == 0,
    )
    cache_write_tokens: StrictInt = Field(
        default=0,
        exclude_if=lambda value: value == 0,
    )


class RunUsagePayload(UsagePayload):
    run_id: ULID


class ProviderErrorPayload(BaseModel):
    """Bounded structured provider refusal preserved by the runtime. [A-054]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    # INCIDENT F034: preserve bounded structured provider evidence for the context-limit remedy.
    classification: Literal["context_length", "provider_refusal"]
    message: NonBlankString = Field(max_length=1_000)
    model: NonBlankString = Field(max_length=256)
    status_code: StrictInt | None = Field(default=None, ge=100, le=599)
    code: NonBlankString | None = Field(default=None, max_length=128)
    provider_code: NonBlankString | None = Field(default=None, max_length=128)


class RunDonePayload(_ExtensiblePayload):
    run_id: ULID
    stop_reason: StopReason
    partial: StrictBool
    error_message: NonBlankString | None = Field(
        default=None,
        max_length=1000,  # INCIDENT F034: bounded public failure evidence, including after reload.
        exclude_if=lambda value: value is None,
    )
    provider_error: ProviderErrorPayload | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

class GateOpenPayload(_ExtensiblePayload):
    run_id: ULID
    kind: Literal["memory_gate"]
    stage: Literal["review", "wrong_resolution"] = "review"
    injection_id: UUID
    snapshot_ts: datetime
    scorer_version: NonBlankString
    injected: list[ScoredMemoryCard]
    near_misses: list[ScoredMemoryCard]
    wrong_removed: list[MemoryUnit] = Field(default_factory=list)
    resolution_error: StrictStr | None = None

class WrongResolution(_ExtensiblePayload):
    memory_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=1)]
    action: Literal["edit", "expire"]
    body: StrictStr | None = None

    @model_validator(mode="after")
    def require_action_body(self) -> "WrongResolution":
        if self.action == "edit":
            if self.body is None or not self.body.strip():
                # WALL Palace writes / A-023: an edit decision must contain the replacement body.
                raise ValueError("edit resolution requires a nonblank body")
        elif self.body is not None:
            # WALL Palace writes / A-023: expiration cannot silently carry an ignored edit.
            raise ValueError("expire resolution must not carry a body")
        return self


class GateCommitPayload(_ExtensiblePayload):
    run_id: ULID
    injection_id: UUID
    removed: list[RemovedMemory]
    added_back: list[UUID]
    wrong_resolution: WrongResolution | None = None


class GateDismissPayload(_ExtensiblePayload):
    run_id: ULID


class QueuedPromptSnapshot(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID
    prompt: NonBlankString
    image: ImageView | None = Field(default=None, exclude_if=lambda value: value is None)


class ActiveRunSnapshot(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID
    state: Literal["running", "waiting_gate", "cancelling"]
    usage: UsagePayload
    queued: list[QueuedPromptSnapshot]


class ThreadSnapshotRequestPayload(_ExtensiblePayload):
    request: Literal[True]
    project_key: ArtificialProjectPath | None = None
    workspace_root: NonBlankString | None = None
    project_label: NonBlankString | None = None


class ThreadSnapshotResponsePayload(_ExtensiblePayload):
    messages: list[dict[str, JsonValue]]
    open_gate: GateOpenPayload | None
    active_run: ActiveRunSnapshot | None
    project_key: ArtificialProjectPath | None
    project_label: NonBlankString | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    workspace_root: NonBlankString | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    current_location: NonBlankString | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    request_id: ULID | None = Field(default=None, exclude_if=lambda value: value is None)
    resolved_model: NonBlankString | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class _MemoryPanelPayload(BaseModel):
    """Closed H6 payload: browser extensions cannot smuggle trusted identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class MemoryPanelRefreshPayload(_MemoryPanelPayload):
    action: Literal["refresh"]


class MemoryPanelAddPayload(_MemoryPanelPayload):
    action: Literal["add"]
    memory_id: UUID


class MemoryPanelRemovePayload(_MemoryPanelPayload):
    action: Literal["remove"]
    memory_id: UUID


class MemoryPanelEditPayload(_MemoryPanelPayload):
    action: Literal["edit"]
    memory_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=1)]
    body: StrictStr


class MemoryPanelPinPayload(_MemoryPanelPayload):
    action: Literal["pin"]
    memory_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=1)]
    pin: StrictBool


class MemoryPanelItem(_MemoryPanelPayload):
    memory: MemoryUnit
    in_context: StrictBool
    thread_excluded: StrictBool


class MemoryPanelStatePayload(_MemoryPanelPayload):
    action: Literal["state"]
    request_id: ULID
    result: Literal["refreshed", "added", "removed", "edited", "pin_changed", "rescored"]
    items: list[MemoryPanelItem]
    total: StrictInt


class MemoryPanelConflictPayload(_MemoryPanelPayload):
    action: Literal["conflict"]
    request_id: ULID
    operation: Literal["edit", "pin"]
    memory: MemoryUnit
    message: NonBlankString


class MemoryPanelErrorPayload(_MemoryPanelPayload):
    action: Literal["error"]
    request_id: ULID
    operation: Literal["refresh", "add", "remove", "edit", "pin"]
    code: NonBlankString
    message: NonBlankString


type MemoryPanelPayload = Annotated[
    MemoryPanelRefreshPayload
    | MemoryPanelAddPayload
    | MemoryPanelRemovePayload
    | MemoryPanelEditPayload
    | MemoryPanelPinPayload
    | MemoryPanelStatePayload
    | MemoryPanelConflictPayload
    | MemoryPanelErrorPayload,
    Field(discriminator="action"),
]


type ThreadSnapshotPayload = Annotated[
    ThreadSnapshotRequestPayload | ThreadSnapshotResponsePayload,
    Field(union_mode="left_to_right"),
]

type KnownPayload = (
    PromptSubmitPayload
    | RunStartedPayload
    | RunCancelPayload
    | PromptQueuedPayload
    | RunDeltaPayload
    | RunUsagePayload
    | RunDonePayload
    | GateOpenPayload
    | GateCommitPayload
    | GateDismissPayload
    | ThreadSnapshotPayload
    | MemoryPanelPayload
)

_PAYLOAD_ADAPTERS: dict[MessageType, TypeAdapter[Any]] = {
    MessageType.PROMPT_SUBMIT: TypeAdapter(PromptSubmitPayload),
    MessageType.PROMPT_QUEUED: TypeAdapter(PromptQueuedPayload),
    MessageType.RUN_STARTED: TypeAdapter(RunStartedPayload),
    MessageType.RUN_CANCEL: TypeAdapter(RunCancelPayload),
    MessageType.RUN_DELTA: TypeAdapter(RunDeltaPayload),
    MessageType.RUN_USAGE: TypeAdapter(RunUsagePayload),
    MessageType.RUN_DONE: TypeAdapter(RunDonePayload),
    MessageType.GATE_OPEN: TypeAdapter(GateOpenPayload),
    MessageType.GATE_COMMIT: TypeAdapter(GateCommitPayload),
    MessageType.GATE_DISMISS: TypeAdapter(GateDismissPayload),
    MessageType.THREAD_SNAPSHOT: TypeAdapter(ThreadSnapshotPayload),
    MessageType.MEMORY_PANEL_UPDATE: TypeAdapter(MemoryPanelPayload),
}
_JSON_ADAPTER = TypeAdapter(JsonValue, config=ConfigDict(allow_inf_nan=False))


class Envelope(BaseModel):
    """A daemon↔browser message, relay-shaped from day one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    v: Literal[1]
    id: ULID
    ts: datetime
    machine_id: str
    agent_id: str | None = None
    thread_id: str | None = None
    type: MessageType | str
    payload: Any

    @field_validator("type")
    @classmethod
    def identify_named_type(cls, value: MessageType | str) -> MessageType | str:
        if isinstance(value, MessageType):
            return value
        try:
            return MessageType(value)
        except ValueError:
            return value

    @model_validator(mode="after")
    def validate_type_payload_contract(self) -> "Envelope":
        raw_payload = _JSON_ADAPTER.validate_python(self.payload)
        adapter = _PAYLOAD_ADAPTERS.get(self.type) if isinstance(self.type, MessageType) else None
        if adapter is not None:
            payload = adapter.validate_python(raw_payload)
        else:
            payload = raw_payload
        object.__setattr__(self, "payload", payload)

        requires_thread = self.type in {
            MessageType.PROMPT_SUBMIT,
            MessageType.GATE_COMMIT,
            MessageType.MEMORY_PANEL_UPDATE,
        } or (
            self.type is MessageType.THREAD_SNAPSHOT
            and isinstance(payload, ThreadSnapshotRequestPayload)
        )
        if requires_thread and (self.thread_id is None or not self.thread_id.strip()):
            # WALL Palace writes / H7: owner input and decisions must identify their target thread.
            raise ValueError(f"{self.type} requires a non-blank outer thread_id")
        return self


def generate_ulid(timestamp: datetime | None = None) -> str:
    """Generate a Crockford Base32 ULID using a UTC millisecond timestamp."""

    instant = timestamp or datetime.now(UTC)
    timestamp_ms = int(instant.timestamp() * 1000)

    value = (timestamp_ms << 80) | secrets.randbits(80)
    encoded = ["0"] * 26
    for index in range(25, -1, -1):
        value, digit = divmod(value, 32)
        encoded[index] = _ULID_ALPHABET[digit]
    return "".join(encoded)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class EnvelopeFactory:
    """Create daemon envelopes with injectable fresh IDs, time, and identity."""

    machine_id: str
    agent_id: str | None = None
    id_factory: Callable[[], str] = generate_ulid
    clock: Callable[[], datetime] = _utc_now

    def new_id(self) -> str:
        """Allocate a fresh ULID for an envelope or correlated run."""

        return self.id_factory()

    def create(
        self,
        message_type: MessageType | str,
        payload: JsonValue | BaseModel,
        *,
        thread_id: str | None = None,
    ) -> Envelope:
        """Create one validated envelope, allocating a new outer ID and timestamp."""

        raw_payload: JsonValue = (
            payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        )
        return Envelope.model_validate(
            {
                "v": 1,
                "id": self.new_id(),
                "ts": self.clock(),
                "machine_id": self.machine_id,
                "agent_id": self.agent_id,
                "thread_id": thread_id,
                "type": message_type,
                "payload": raw_payload,
            }
        )
