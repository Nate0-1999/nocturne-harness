"""Typed M2J parameter descriptors and daemon-lifetime replay history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

type ParameterValue = str | float | int | None


class ParameterRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: float | int
    maximum: float | int
    step: float | int | None = None


class ParameterDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str
    type: Literal["model", "number", "integer", "option"]
    range: ParameterRange | None = None
    options: tuple[str, ...] = ()
    default: ParameterValue = None
    scope: Literal["thread"] = "thread"
    authority: Literal["free-journaled", "law-bound"] = "free-journaled"


MODEL_PARAMETER_DESCRIPTORS: tuple[ParameterDescriptor, ...] = (
    ParameterDescriptor(id="model.slug", label="Model", type="model"),
    ParameterDescriptor(
        id="model.temperature",
        label="Temperature",
        type="number",
        range=ParameterRange(minimum=0, maximum=2, step=0.05),
    ),
    ParameterDescriptor(
        id="model.top_p",
        label="Top P",
        type="number",
        range=ParameterRange(minimum=0, maximum=1, step=0.01),
    ),
    ParameterDescriptor(
        id="model.top_k",
        label="Top K",
        type="integer",
        range=ParameterRange(minimum=0, maximum=500, step=1),
    ),
    ParameterDescriptor(
        id="model.max_tokens",
        label="Max tokens",
        type="integer",
        range=ParameterRange(minimum=1, maximum=131_072, step=1),
    ),
    ParameterDescriptor(
        id="model.effort",
        label="Reasoning effort",
        type="option",
        options=("none", "minimal", "low", "medium", "high", "xhigh"),
    ),
)

MODEL_DEVICE_BINDINGS = frozenset(descriptor.id for descriptor in MODEL_PARAMETER_DESCRIPTORS)


class ParameterChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    parameter_id: str
    scope: Literal["thread"] = "thread"
    thread_id: str
    actor: Literal["human"] = "human"
    timestamp: datetime
    old_value: ParameterValue
    new_value: ParameterValue

    @field_validator("timestamp")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("parameter timestamp must be timezone-aware")
        return value


class ParameterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    as_of: datetime
    resolved_model: str
    descriptors: tuple[ParameterDescriptor, ...]
    values: dict[str, ParameterValue]
    changes: tuple[ParameterChange, ...]

    @field_validator("as_of")
    @classmethod
    def require_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("parameter as_of must be timezone-aware")
        return value


class ParameterWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    parameter_id: str = Field(min_length=1)
    value: ParameterValue


@dataclass(slots=True)
class _ThreadParameterHistory:
    initial_values: dict[str, ParameterValue]
    changes: list[ParameterChange] = field(default_factory=list)


class ParameterRegistry:
    """Validate bound writes and replay accepted changes without serving M2D."""

    def __init__(self) -> None:
        self._descriptors = {
            descriptor.id: descriptor for descriptor in MODEL_PARAMETER_DESCRIPTORS
        }
        self._threads: dict[str, _ThreadParameterHistory] = {}

    @property
    def descriptors(self) -> tuple[ParameterDescriptor, ...]:
        return MODEL_PARAMETER_DESCRIPTORS

    def validate_bound_write(
        self,
        *,
        module_id: str,
        parameter_id: str,
        value: object,
    ) -> ParameterValue:
        descriptor = self._descriptors.get(parameter_id)
        if descriptor is None:
            raise ParameterWriteViolation("unknown")
        if module_id != "model_device" or parameter_id not in MODEL_DEVICE_BINDINGS:
            raise ParameterWriteViolation("unbound")
        if descriptor.authority == "law-bound":
            raise ParameterWriteViolation("law_bound")
        return _validate_value(descriptor, value)

    def ensure_thread(self, thread_id: str, values: dict[str, ParameterValue]) -> None:
        self._threads.setdefault(
            thread_id,
            _ThreadParameterHistory(initial_values=dict(values)),
        )

    def record(self, change: ParameterChange) -> None:
        history = self._threads.get(change.thread_id)
        if history is None:
            raise RuntimeError("parameter thread must be initialized before recording")
        history.changes.append(change)

    def snapshot(
        self,
        *,
        thread_id: str,
        as_of: datetime,
    ) -> ParameterSnapshot:
        history = self._threads.get(thread_id)
        if history is None:
            raise KeyError(thread_id)
        changes = tuple(
            sorted(
                (change for change in history.changes if change.timestamp <= as_of),
                key=lambda change: (change.timestamp, change.event_id),
            )
        )
        values = dict(history.initial_values)
        for change in changes:
            values[change.parameter_id] = change.new_value
        resolved = values["model.slug"]
        if not isinstance(resolved, str):
            raise RuntimeError("model.slug must resolve to a string")
        return ParameterSnapshot(
            thread_id=thread_id,
            as_of=as_of,
            resolved_model=resolved,
            descriptors=self.descriptors,
            values=values,
            changes=changes,
        )


class ParameterWriteViolation(ValueError):
    """One stable, journalable registry refusal reason."""

    def __init__(self, reason: Literal["unknown", "unbound", "law_bound", "invalid", "busy"]):
        super().__init__(reason)
        self.reason = reason


def _validate_value(descriptor: ParameterDescriptor, value: object) -> ParameterValue:
    if descriptor.id != "model.slug" and value is None:
        return None
    if descriptor.type == "model":
        if (
            not isinstance(value, str)
            or not value.startswith("openrouter:")
            or not value.removeprefix("openrouter:")
            or value != value.strip()
        ):
            raise ParameterWriteViolation("invalid")
        return value
    if descriptor.type == "option":
        if not isinstance(value, str) or value not in descriptor.options:
            raise ParameterWriteViolation("invalid")
        return value
    if descriptor.type == "integer":
        if type(value) is not int:
            raise ParameterWriteViolation("invalid")
        numeric: float | int = value
    else:
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ParameterWriteViolation("invalid")
        numeric = value
    assert descriptor.range is not None
    if numeric < descriptor.range.minimum or numeric > descriptor.range.maximum:
        raise ParameterWriteViolation("invalid")
    return value  # type: ignore[return-value]
