"""Validated models and construction helpers for SPEC C.7 envelopes."""

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
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

from harness.spine_client import MemoryUnit, RemovedMemory, ScoredMemoryCard

# A ULID is 128 bits encoded as 26 Crockford Base32 characters. The leading
# character is limited to 0–7 so the 130-bit textual space cannot overflow.
_ULID_PATTERN = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$", re.IGNORECASE)
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _require_ulid(value: str) -> str:
    if not _ULID_PATTERN.fullmatch(value):
        raise ValueError("value must be a ULID")
    return value


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


type ULID = Annotated[StrictStr, AfterValidator(_require_ulid)]
type NonBlankString = Annotated[StrictStr, AfterValidator(_require_non_blank)]
type NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


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


class PromptSubmitPayload(_ExtensiblePayload):
    prompt: NonBlankString


class RunStartedPayload(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID


class RunCancelPayload(_ExtensiblePayload):
    run_id: ULID


class PromptQueuedPayload(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID


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


type RunDeltaPayload = Annotated[
    RunDeltaTextPayload | RunDeltaThinkingPayload | RunDeltaEventPayload,
    Field(discriminator="kind"),
]


class UsagePayload(_ExtensiblePayload):
    """Cumulative run usage without the enclosing run correlation field."""

    requests: NonNegativeInt
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt


class RunUsagePayload(UsagePayload):
    run_id: ULID


class RunDonePayload(_ExtensiblePayload):
    run_id: ULID
    stop_reason: StopReason
    partial: StrictBool

    @model_validator(mode="after")
    def require_consistent_partial_marker(self) -> "RunDonePayload":
        expected = self.stop_reason is not StopReason.END_TURN
        if self.partial is not expected:
            raise ValueError("partial must be false exactly for end_turn")
        return self


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

    @model_validator(mode="after")
    def require_stage_membership(self) -> "GateOpenPayload":
        memory_ids = [card.memory_id for card in (*self.injected, *self.near_misses)]
        if len(set(memory_ids)) != len(memory_ids):
            raise ValueError("gate cards must have unique memory_id values")
        if self.stage == "review":
            if self.wrong_removed:
                raise ValueError("review gate must not carry wrong_removed")
        elif self.injected or self.near_misses or len(self.wrong_removed) != 1:
            raise ValueError("wrong_resolution gate requires one wrong_removed and no scored cards")
        return self


class WrongResolution(_ExtensiblePayload):
    memory_id: UUID
    expected_revision: Annotated[StrictInt, Field(ge=1)]
    action: Literal["edit", "expire"]
    body: StrictStr | None = None

    @model_validator(mode="after")
    def require_action_body(self) -> "WrongResolution":
        if self.action == "edit":
            if self.body is None or not self.body.strip():
                raise ValueError("edit resolution requires a nonblank body")
        elif self.body is not None:
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


class ActiveRunSnapshot(_ExtensiblePayload):
    run_id: ULID
    prompt_id: ULID
    state: Literal["running", "waiting_gate", "cancelling"]
    usage: UsagePayload
    queued: list[QueuedPromptSnapshot]


class ThreadSnapshotRequestPayload(_ExtensiblePayload):
    request: Literal[True]


class ThreadSnapshotResponsePayload(_ExtensiblePayload):
    messages: list[dict[str, JsonValue]]
    open_gate: GateOpenPayload | None
    active_run: ActiveRunSnapshot | None


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

    @field_validator("v", mode="before")
    @classmethod
    def reject_boolean_version(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("v must be the numeric literal 1")
        return value

    @field_validator("type", mode="before")
    @classmethod
    def require_string_type(cls, value: object) -> object:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("type must be a non-blank string")
        return value

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
        } or (
            self.type is MessageType.THREAD_SNAPSHOT
            and isinstance(payload, ThreadSnapshotRequestPayload)
        )
        if requires_thread and (self.thread_id is None or not self.thread_id.strip()):
            raise ValueError(f"{self.type} requires a non-blank outer thread_id")
        return self


def generate_ulid(timestamp: datetime | None = None) -> str:
    """Generate a Crockford Base32 ULID using a UTC millisecond timestamp."""

    instant = timestamp or datetime.now(UTC)
    timestamp_ms = int(instant.timestamp() * 1000)
    if not 0 <= timestamp_ms < 2**48:
        raise ValueError("ULID timestamp is outside the 48-bit range")

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
        """Allocate and validate a fresh ULID for an envelope or correlated run."""

        return _require_ulid(self.id_factory())

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
