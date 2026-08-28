"""One-turn proposed-response blocks and their append-only fire provenance."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

BLOCK_OPEN = "<nocturne-proposed-response>"
BLOCK_CLOSE = "</nocturne-proposed-response>"
MAX_PROPOSED_RESPONSE_CHARS = 2_000
MAX_FIRED_RESPONSE_CHARS = 4_000

PROPOSED_RESPONSE_INSTRUCTION = f"""
Finish every ordinary owner-facing answer with exactly one structured proposed-response
block. This block is part of this same model turn; do not make another call for it.
Write the useful answer first, then append:

{BLOCK_OPEN}
{{"primary":"the most likely useful reply in the owner's voice","alternatives":[]}}
{BLOCK_CLOSE}

`primary` must be a nonblank reply the owner could send as written and no longer than
{MAX_PROPOSED_RESPONSE_CHARS} characters. `alternatives` is optional and may contain up
to three distinct nonblank alternatives. Do not mention or explain the block in the
visible answer. Never auto-send on the owner's behalf.
""".strip()


class _ProposalBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: StrictStr = Field(min_length=1, max_length=MAX_PROPOSED_RESPONSE_CHARS)
    alternatives: tuple[StrictStr, ...] = Field(default=(), max_length=3)

    @field_validator("primary")
    @classmethod
    def normalize_primary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("primary must not be blank")
        return normalized

    @field_validator("alternatives")
    @classmethod
    def normalize_alternatives(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("alternatives must not be blank")
        if any(len(value) > MAX_PROPOSED_RESPONSE_CHARS for value in normalized):
            raise ValueError("alternatives exceed the proposed-response limit")
        if len(set(normalized)) != len(normalized):
            raise ValueError("alternatives must be distinct")
        return normalized


@dataclass(frozen=True, slots=True)
class ProposedResponse:
    primary: str
    alternatives: tuple[str, ...]


def parse_proposed_response_output(value: str) -> tuple[str, ProposedResponse | None]:
    """Split one terminal structured block from the visible answer.

    A malformed block is kept out of the owner surface and yields no actionable card.
    Missing blocks leave ordinary text unchanged, so provider failures stay readable.
    """

    start = value.rfind(BLOCK_OPEN)
    if start < 0:
        return value, None
    visible = value[:start]
    close = value.find(BLOCK_CLOSE, start + len(BLOCK_OPEN))
    if close < 0 or value[close + len(BLOCK_CLOSE) :].strip():
        return visible, None
    raw = value[start + len(BLOCK_OPEN) : close].strip()
    try:
        block = _ProposalBlock.model_validate(json.loads(raw))
    except (ValueError, TypeError, json.JSONDecodeError):
        return visible, None
    if block.primary in block.alternatives:
        return visible, None
    return visible, ProposedResponse(block.primary, block.alternatives)


def proposed_response_event(
    proposal: ProposedResponse,
    *,
    run_id: str,
    created_at: datetime,
) -> dict[str, object]:
    """Create the durable card projection emitted by the same model turn."""

    return {
        "event_kind": "proposed_response",
        "proposal_run_id": run_id,
        "primary": proposal.primary,
        "alternatives": list(proposal.alternatives),
        "created_at": created_at.isoformat(),
    }


def find_proposed_response(
    messages: Sequence[Mapping[str, Any]], proposal_run_id: str
) -> tuple[Mapping[str, Any], ProposedResponse] | None:
    """Resolve a proposal only from its immutable assistant message."""

    for message in messages:
        if message.get("role") != "assistant" or message.get("run_id") != proposal_run_id:
            continue
        events = message.get("events")
        if not isinstance(events, list):
            return None
        for event in events:
            if not isinstance(event, Mapping):
                continue
            if (
                event.get("event_kind") != "proposed_response"
                or event.get("proposal_run_id") != proposal_run_id
            ):
                continue
            primary = event.get("primary")
            alternatives = event.get("alternatives", [])
            if (
                not isinstance(primary, str)
                or not primary.strip()
                or not isinstance(alternatives, list)
                or not all(isinstance(item, str) and item.strip() for item in alternatives)
            ):
                return None
            return message, ProposedResponse(primary.strip(), tuple(alternatives))
    return None


def proposal_was_fired(messages: Sequence[Mapping[str, Any]], proposal_run_id: str) -> bool:
    """Treat the append-only user message as the sole resolution authority."""

    return any(
        message.get("role") == "user"
        and isinstance(message.get("proposed_response"), Mapping)
        and message["proposed_response"].get("proposal_run_id") == proposal_run_id
        for message in messages
    )


def proposed_response_fire_record(
    *,
    source_message: Mapping[str, Any],
    proposal: ProposedResponse,
    proposal_run_id: str,
    fired_text: str,
    fired_at: datetime,
) -> dict[str, object]:
    """Record exact proposed-to-fired text without rewriting judge provenance."""

    fired = fired_text.strip()
    if not fired:
        raise ValueError("fired proposed response must not be blank")
    if len(fired) > MAX_FIRED_RESPONSE_CHARS:
        raise ValueError("fired proposed response exceeds the 4000-character limit")
    events = source_message.get("events")
    judge_provenance = [
        dict(event)
        for event in (events if isinstance(events, list) else [])
        if isinstance(event, Mapping)
        if event.get("event_kind") in {"judge_result", "symphony_result"}
    ]
    record: dict[str, object] = {
        "proposal_run_id": proposal_run_id,
        "proposed_text": proposal.primary,
        "fired_text": fired,
        "edit_distance": levenshtein_distance(proposal.primary, fired),
        "provenance": "owner_authored_with_assist",
        "fired_at": fired_at.isoformat(),
    }
    if judge_provenance:
        record["judge_provenance"] = judge_provenance
    return record


def levenshtein_distance(left: str, right: str) -> int:
    """Return exact character edit distance with linear memory."""

    if left == right:
        return 0
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for right_index, right_char in enumerate(right, start=1):
        current = [right_index]
        for left_index, left_char in enumerate(left, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[left_index] + 1,
                    previous[left_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
