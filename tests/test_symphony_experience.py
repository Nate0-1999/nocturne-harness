from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    MessageType,
    StopReason,
    SymphonyLaunchPayload,
)
from harness.model_policy import ThreadModelResolution
from harness.run_loop import RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome
from harness.symphony_experience import SymphonyExperience


@dataclass
class RecordingEmitter:
    texts: list[str] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)

    async def text(self, value: str) -> None:
        self.texts.append(value)

    async def thinking(self, value: str) -> None:
        del value

    async def event(self, value: Mapping[str, object]) -> None:
        self.events.append(dict(value))

    async def usage(self, value) -> None:
        del value

    async def open_gate(self, value):
        raise AssertionError(value)

    async def dismiss_gate(self) -> None:
        raise AssertionError("no gate")

    async def error(self, value) -> None:
        raise AssertionError(value)


class ForbiddenRunner:
    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        raise AssertionError((thread_id, prompt, message_history, emit, model_resolution))


@dataclass
class EnvelopeSink:
    messages: list[Envelope] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self, message: Envelope) -> None:
        self.messages.append(message)
        if message.type is MessageType.RUN_DONE:
            self.done.set()


def ids():
    number = 0

    def next_id() -> str:
        nonlocal number
        number += 1
        return f"{number:026d}"

    return next_id


def launch(draft_id: str, **changes: object) -> SymphonyLaunchPayload:
    value: dict[str, object] = {
        "draft_id": draft_id,
        "objective": "Return a tiny proof to this chat",
        "motivation": "Prove deliberation and stack return before expensive work",
        "recipe": [
            {
                "step_id": "proof",
                "title": "Run the bounded proof",
                "done_when": "The separate stack is completed and linked here",
                "search": True,
            }
        ],
        "judge_charters": [
            {
                "seat": "motivation",
                "rubric": ["Preserves the stated reason"],
                "evidence_requirements": ["The signed launch artifact"],
                "metrics": [],
            },
            {
                "seat": "implementation",
                "rubric": ["Uses the ordinary thread and a separate stack"],
                "evidence_requirements": ["Started and result events"],
                "metrics": [],
            },
            {
                "seat": "performance",
                "rubric": ["Completes within the signed walls"],
                "evidence_requirements": ["Completed stack timeline"],
                "metrics": ["one result card", "zero model requests"],
            },
        ],
        "authority": {
            "attempts": 3,
            "spend_wall_usd": "10",
            "max_rounds": 3,
            "depth_cap": 2,
            "children_per_attempt": 4,
            "duration_minutes": 30,
            "signed": True,
        },
    }
    value.update(changes)
    return SymphonyLaunchPayload.model_validate(value)


@pytest.mark.asyncio
async def test_explicit_phrase_opens_uninvented_deliberation_in_the_thread() -> None:
    """SYM10 / ADR-012: escalation opens deliberation, not autonomous criteria."""

    experience = SymphonyExperience(id_factory=ids())
    emitter = RecordingEmitter()
    history = ("prior provider turn",)

    outcome = await experience.run(
        thread_id="thread-a",
        prompt="Take this to a symphony.",
        launch=None,
        message_history=history,
        emit=emitter,
    )

    assert outcome.stop_reason is StopReason.END_TURN
    assert outcome.model_visible is False
    assert outcome.message_history == history
    assert emitter.events[0]["event_kind"] == "symphony_deliberation"
    assert emitter.events[0]["objective"] == ""
    assert emitter.events[0]["motivation"] == ""
    assert emitter.events[0]["authority"]["signed"] is False  # type: ignore[index]


@pytest.mark.asyncio
async def test_signed_deliberation_completes_a_distinct_toy_stack_and_returns_result() -> None:
    """ADR-012 / T2 / R22: signed authority governs a separately identified proof stack."""

    experience = SymphonyExperience(
        id_factory=ids(),
        clock=lambda: datetime(2026, 8, 17, 12, tzinfo=UTC),
    )
    opening = RecordingEmitter()
    await experience.run(
        thread_id="thread-a",
        prompt="take this to a symphony",
        launch=None,
        message_history=(),
        emit=opening,
    )
    draft_id = opening.events[0]["draft_id"]
    assert isinstance(draft_id, str)
    signed = launch(draft_id)
    completed = RecordingEmitter()

    outcome = await experience.run(
        thread_id="thread-a",
        prompt="Launch this symphony.",
        launch=signed,
        message_history=("provider history stays put",),
        emit=completed,
    )

    assert outcome.model_visible is False
    assert outcome.message_history == ("provider history stays put",)
    assert [event["event_kind"] for event in completed.events] == [
        "symphony_started",
        "symphony_result",
    ]
    result = completed.events[1]
    assert result["state"] == "completed"
    assert result["execution_kind"] == "toy"
    assert result["thread_id"] == "thread-a"
    assert result["search_step_ids"] == ["proof"]
    assert len(result["charter_digests"]) == 3  # type: ignore[arg-type]
    stack = await experience.read(str(result["symphony_id"]))
    assert stack is not None
    assert stack.launch.authority.spend_wall_usd == 10
    assert stack.timeline[-1] == "completed"


@pytest.mark.asyncio
async def test_draft_cannot_be_launched_from_a_different_conversation() -> None:
    """SYM10 / ADR-012: a deliberation artifact remains bound to its source chat."""

    experience = SymphonyExperience(id_factory=ids())
    opening = RecordingEmitter()
    await experience.run(
        thread_id="thread-a",
        prompt="take this to a symphony",
        launch=None,
        message_history=(),
        emit=opening,
    )

    with pytest.raises(ValueError, match="does not belong"):
        await experience.run(
            thread_id="thread-b",
            prompt="Launch this symphony.",
            launch=launch(str(opening.events[0]["draft_id"])),
            message_history=(),
            emit=RecordingEmitter(),
        )


@pytest.mark.asyncio
async def test_durable_thread_event_reopens_launch_after_daemon_restart() -> None:
    """ADR-012: reloading the same conversation must not strand its open deliberation."""

    draft_id = "00000000000000000000000044"
    restarted = SymphonyExperience(id_factory=ids())
    emitter = RecordingEmitter()

    await restarted.run(
        thread_id="thread-a",
        prompt="Launch this symphony.",
        launch=launch(draft_id),
        accepted_draft_ids=(draft_id,),
        message_history=(),
        emit=emitter,
    )

    assert emitter.events[-1]["event_kind"] == "symphony_result"


def test_launch_requires_core_charter_order_performance_metrics_and_signature() -> None:
    """ADR-012 / D.2 102 / T2: auto mode cannot omit judgment or authority acceptance."""

    valid = launch("00000000000000000000000001").model_dump(mode="json")
    valid["judge_charters"][2]["metrics"] = []
    with pytest.raises(ValidationError, match="performance charter"):
        SymphonyLaunchPayload.model_validate(valid)

    valid = launch("00000000000000000000000001").model_dump(mode="json")
    valid["authority"]["signed"] = False
    with pytest.raises(ValidationError, match="literal_error"):
        SymphonyLaunchPayload.model_validate(valid)


@pytest.mark.asyncio
async def test_run_loop_routes_both_symphony_turns_locally_and_keeps_fifo_events() -> None:
    """ADR-012: the escalation protocol lives in the ordinary journaled run lifecycle."""

    next_id = ids()
    factory = EnvelopeFactory(
        machine_id="machine",
        agent_id="agent",
        id_factory=next_id,
    )
    experience = SymphonyExperience(id_factory=next_id)
    loop = RunLoop(
        ForbiddenRunner(),
        factory,
        run_id_factory=next_id,
        symphony_experience=experience,
    )
    sink = EnvelopeSink()
    thread_id = "12345678-1234-5678-1234-567812345678"
    await loop.attach(sink)
    await loop.submit(
        thread_id=thread_id,
        prompt_id="00000000000000000000000090",
        prompt="take this to a symphony",
        sink=sink,
    )
    await asyncio.wait_for(sink.done.wait(), 1)
    draft_event = next(
        message.payload.event
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA
        and getattr(message.payload, "kind", None) == "event"
        and message.payload.event.get("event_kind") == "symphony_deliberation"
    )

    sink.done.clear()
    await loop.submit(
        thread_id=thread_id,
        prompt_id="00000000000000000000000091",
        prompt="Launch this symphony.",
        symphony=launch(str(draft_event["draft_id"])),
        sink=sink,
    )
    await asyncio.wait_for(sink.done.wait(), 1)
    result_event = next(
        message.payload.event
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA
        and getattr(message.payload, "kind", None) == "event"
        and message.payload.event.get("event_kind") == "symphony_result"
    )

    assert result_event["thread_id"] == thread_id
    assert result_event["state"] == "completed"
    assert sum(message.type is MessageType.RUN_DONE for message in sink.messages) == 2
    await loop.close()
