from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    GateCommitPayload,
    MessageType,
    StopReason,
    ThreadSnapshotResponsePayload,
    WrongResolution,
)
from harness.model_policy import ThreadModelResolution
from harness.run_loop import RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot

TEST_TIMEOUT = 1.0
INJECTION_ID = "32345678-1234-5678-1234-567812345678"
INJECTED_ID = "42345678-1234-5678-1234-567812345678"
NEAR_MISS_ID = "52345678-1234-5678-1234-567812345678"


def gate_value() -> dict[str, object]:
    return {
        "injection_id": INJECTION_ID,
        "snapshot_ts": datetime(2026, 7, 21, 12, tzinfo=UTC),
        "scorer_version": "m1-v1",
        "injected": [],
        "near_misses": [],
    }


def card(memory_id: str, rank: int) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "label": f"memory-{rank}",
        "body": f"full body {rank}",
        "kind": "fact",
        "pin": False,
        "score": 0.8,
        "features": {
            "sem": 0.9,
            "kw": 0.8,
            "time": 0.7,
            "proj": 0.6,
            "freq": 0.5,
            "hist": 0.4,
        },
        "rank": rank,
    }


def wrong_unit(*, revision: int = 2) -> dict[str, object]:
    return {
        "memory_id": INJECTED_ID,
        "principal_id": "principal-1",
        "label": "Wrong memory",
        "body": "Current wrong body",
        "kind": "fact",
        "keywords": [],
        "project_key": None,
        "thread_origin": "thread-1",
        "origin_path": None,
        "pin": False,
        "status": "active",
        "revision": revision,
        "stats": {
            "injections": 1,
            "removals": 1,
            "citations": 0,
            "never_kills": 0,
            "last_injected_at": None,
        },
        "bias": 0.0,
        "embedding_model": "test-embedding",
        "created_at": datetime(2026, 7, 20, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 21, tzinfo=UTC),
    }


def ulid(number: int) -> str:
    return f"{number:026d}"


@dataclass
class Ids:
    value: int = 100

    def next(self) -> str:
        self.value += 1
        return ulid(self.value)


@dataclass
class Sink:
    messages: list[Envelope] = field(default_factory=list)

    async def __call__(self, message: Envelope) -> None:
        self.messages.append(message)


@dataclass
class TurnControl:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancellation_seen: asyncio.Event = field(default_factory=asyncio.Event)
    cleanup_release: asyncio.Event = field(default_factory=asyncio.Event)
    stop_reason: StopReason = StopReason.END_TURN
    usage: UsageSnapshot = UsageSnapshot()


class ControlledRunner:
    def __init__(self, controls: Mapping[str, TurnControl]) -> None:
        self.controls = controls
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.emitters: dict[str, RunEmitter] = {}

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del model_resolution
        control = self.controls[prompt]
        self.calls.append((thread_id, prompt, tuple(message_history)))
        self.emitters[prompt] = emit
        control.entered.set()
        try:
            await control.release.wait()
        except asyncio.CancelledError:
            control.cancellation_seen.set()
            await asyncio.wait_for(control.cleanup_release.wait(), TEST_TIMEOUT)
            return TurnOutcome(
                stop_reason=StopReason.CANCELLED,
                message_history=(*message_history, f"{prompt}:cancelled-tool"),
                usage=control.usage,
            )
        return TurnOutcome(
            stop_reason=control.stop_reason,
            message_history=(*message_history, f"{prompt}:{control.stop_reason.value}"),
            usage=control.usage,
        )


class NeverStartsRunner:
    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del model_resolution
        raise AssertionError("an immediately cancelled runner must not start")


class ImmediateHistoryRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, emit, model_resolution
        history = tuple(message_history)
        self.calls.append((prompt, history))
        return TurnOutcome(
            StopReason.END_TURN,
            (*history, f"{prompt}:complete"),
        )


class RecordingResolver:
    def __init__(self, resolutions: Mapping[str, ThreadModelResolution]) -> None:
        self.resolutions = resolutions
        self.calls: list[str] = []

    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        self.calls.append(thread_id)
        return self.resolutions[thread_id]


class ResolutionRecordingRunner:
    def __init__(self) -> None:
        self.resolutions: list[ThreadModelResolution | None] = []

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, emit
        self.resolutions.append(model_resolution)
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, f"{prompt}:complete"),
        )


class GateRunner:
    def __init__(self) -> None:
        self.accepted = asyncio.Event()
        self.allow_dismiss = asyncio.Event()
        self.decision: GateCommitPayload | None = None

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, model_resolution
        self.decision = await emit.open_gate(
            {
                **gate_value(),
                "injected": [card(INJECTED_ID, 1)],
                "near_misses": [card(NEAR_MISS_ID, 2)],
            }
        )
        self.accepted.set()
        await self.allow_dismiss.wait()
        await emit.dismiss_gate()
        await emit.text("model started")
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, f"{prompt}:complete"),
        )


class WrongResolutionGateRunner:
    def __init__(self) -> None:
        self.review: GateCommitPayload | None = None
        self.resolution: GateCommitPayload | None = None

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, model_resolution
        self.review = await emit.open_gate(
            {
                **gate_value(),
                "injected": [card(INJECTED_ID, 1)],
            }
        )
        self.resolution = await emit.open_gate(
            {
                **gate_value(),
                "stage": "wrong_resolution",
                "wrong_removed": [wrong_unit()],
            }
        )
        await emit.dismiss_gate()
        await emit.text("model started")
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, f"{prompt}:complete"),
        )


class InvalidGateRunner:
    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, prompt, message_history, model_resolution
        invalid = card(INJECTED_ID, 0)
        await emit.open_gate(
            {
                **gate_value(),
                "injected": [invalid],
                "near_misses": [invalid],
            }
        )
        raise AssertionError("invalid gate unexpectedly opened")


class FinishBarrierLoop(RunLoop):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.finish_entered = asyncio.Event()
        self.release_finish = asyncio.Event()
        self._finish_count = 0

    async def _finish(
        self,
        thread_id: str,
        active: Any,
        outcome: TurnOutcome | None,
        stop_reason: StopReason,
    ) -> None:
        self._finish_count += 1
        if self._finish_count == 1:
            self.finish_entered.set()
            await self.release_finish.wait()
        await super()._finish(thread_id, active, outcome, stop_reason)


@dataclass
class BlockingSink:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    calls: int = 0

    async def __call__(self, message: Envelope) -> None:
        del message
        self.calls += 1
        self.entered.set()
        await self.release.wait()


def factory(ids: Ids) -> EnvelopeFactory:
    return EnvelopeFactory(
        machine_id="machine-1",
        agent_id="agent-1",
        id_factory=ids.next,
        clock=lambda: datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )


def types(sink: Sink) -> list[MessageType | str]:
    return [message.type for message in sink.messages]


def payload(message: Envelope) -> dict[str, object]:
    value = message.payload
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("resolved_model", ["", " \t", " model "])
def test_run_loop_rejects_invalid_resolved_model(resolved_model: str) -> None:
    ids = Ids()

    with pytest.raises(ValueError, match="resolved_model"):
        RunLoop(
            ImmediateHistoryRunner(),
            factory(ids),
            resolved_model=resolved_model,
        )


@pytest.mark.asyncio
async def test_static_resolved_model_is_authoritative_on_start_and_snapshot() -> None:
    ids = Ids()
    model = "openrouter:minimax/minimax-m3"
    runner = ResolutionRecordingRunner()
    loop = RunLoop(
        runner,
        factory(ids),
        resolved_model=model,
    )
    sink = Sink()
    await loop.attach(sink)

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)
    started = next(message for message in sink.messages if message.type is MessageType.RUN_STARTED)
    assert payload(started)["resolved_model"] == model

    snapshot_sink = Sink()
    await loop.request_snapshot("thread-1", snapshot_sink)
    await _wait_for_type_count(snapshot_sink, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = snapshot_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.resolved_model == model
    assert runner.resolutions == [None]

    await loop.close()


@pytest.mark.asyncio
async def test_policy_resolution_occurs_once_at_first_run_and_is_thread_authoritative() -> None:
    ids = Ids()
    thread_one = ThreadModelResolution(
        model="openrouter:vendor/one",
        context_tokens=131_072,
        policy="elbow",
        price_sorted=True,
    )
    thread_two = ThreadModelResolution(
        model="openrouter:vendor/two",
        context_tokens=262_144,
        policy="max",
        price_sorted=True,
    )
    resolver = RecordingResolver({"thread-1": thread_one, "thread-2": thread_two})
    runner = ResolutionRecordingRunner()
    loop = RunLoop(runner, factory(ids), model_resolver=resolver)

    before = Sink()
    await loop.request_snapshot("thread-1", before)
    await _wait_for_type_count(before, MessageType.THREAD_SNAPSHOT, 1)
    initial = before.messages[0].payload
    assert isinstance(initial, ThreadSnapshotResponsePayload)
    assert initial.resolved_model is None

    first_sink = Sink()
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="first",
        sink=first_sink,
    )
    await _wait_for_done_count(first_sink, 1)
    started = next(
        message for message in first_sink.messages if message.type is MessageType.RUN_STARTED
    )
    assert payload(started)["resolved_model"] == thread_one.model
    assert runner.resolutions == [thread_one]

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt="second",
        sink=first_sink,
    )
    await _wait_for_done_count(first_sink, 2)

    second_sink = Sink()
    await loop.submit(
        thread_id="thread-2",
        prompt_id=ulid(3),
        prompt="other",
        sink=second_sink,
    )
    await _wait_for_done_count(second_sink, 1)

    assert resolver.calls == ["thread-1", "thread-2"]
    assert runner.resolutions == [thread_one, thread_one, thread_two]

    after = Sink()
    await loop.request_snapshot("thread-1", after)
    await _wait_for_type_count(after, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = after.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.resolved_model == thread_one.model
    await loop.close()


@pytest.mark.asyncio
async def test_cancel_awaits_cleanup_preserves_partial_and_coalesces_duplicates() -> None:
    ids = Ids()
    control = TurnControl(usage=UsageSnapshot(1, 12, 3))
    runner = ControlledRunner({"hello": control})
    loop = RunLoop(runner, factory(ids))
    sink = Sink()
    await loop.attach(sink)

    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait(control.entered)
    emit = runner.emitters["hello"]
    await emit.text("kept text")
    await emit.thinking("kept thought")
    await emit.event({"tool": "started"})
    await emit.usage(UsageSnapshot(1, 12, 3))
    gate_wait = asyncio.create_task(emit.open_gate(gate_value()))
    await _wait_for_type_count(sink, MessageType.GATE_OPEN, 1)

    first = asyncio.create_task(loop.cancel(thread_id=None, run_id=run_id, sink=sink))
    await _wait(control.cancellation_seen)
    duplicate = asyncio.create_task(loop.cancel(thread_id="thread-1", run_id=run_id, sink=sink))
    await asyncio.gather(first, duplicate)
    assert MessageType.RUN_DONE not in types(sink)
    assert MessageType.ERROR not in types(sink)

    control.cleanup_release.set()
    await _wait_for_done_count(sink, 1)
    with pytest.raises(asyncio.CancelledError):
        await gate_wait

    message_types = types(sink)
    assert message_types.count(MessageType.RUN_DONE) == 1
    assert message_types.index(MessageType.GATE_DISMISS) < message_types.index(MessageType.RUN_DONE)
    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert payload(done) == {
        "run_id": run_id,
        "stop_reason": StopReason.CANCELLED,
        "partial": True,
    }

    event_count = len(sink.messages)
    await emit.text("too late")
    await emit.usage(UsageSnapshot(2, 20, 4))
    assert len(sink.messages) == event_count

    await loop.detach(sink)
    reconnected = Sink()
    await loop.attach(reconnected)
    await _wait_for_type_count(reconnected, MessageType.THREAD_SNAPSHOT, 1)
    assert types(reconnected) == [MessageType.THREAD_SNAPSHOT]
    snapshot = reconnected.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.active_run is None
    assistant = next(message for message in snapshot.messages if message["role"] == "assistant")
    assert assistant["content"] == "kept text"
    assert assistant["thinking"] == "kept thought"
    assert assistant["events"] == [{"tool": "started"}]
    assert assistant["partial"] is True
    await loop.close()


@pytest.mark.asyncio
async def test_gate_blocks_reconnects_validates_once_and_resumes_only_after_dismiss() -> None:
    ids = Ids()
    runner = GateRunner()
    loop = RunLoop(runner, factory(ids))
    original = Sink()
    await loop.attach(original)
    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=original,
    )
    await _wait_for_type_count(original, MessageType.GATE_OPEN, 1)
    assert MessageType.RUN_DELTA not in types(original)

    await loop.detach(original)
    reconnected = Sink()
    await loop.attach(reconnected)
    await _wait_for_type_count(reconnected, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = reconnected.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.open_gate is not None
    assert snapshot.open_gate.injection_id == UUID(INJECTION_ID)
    assert snapshot.active_run is not None
    assert snapshot.active_run.state == "waiting_gate"

    invalid = [
        (
            "wrong-thread",
            GateCommitPayload(
                run_id=run_id,
                injection_id=INJECTION_ID,
                removed=[],
                added_back=[],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=ulid(999),
                injection_id=INJECTION_ID,
                removed=[],
                added_back=[],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=run_id,
                injection_id="62345678-1234-5678-1234-567812345678",
                removed=[],
                added_back=[],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=run_id,
                injection_id=INJECTION_ID,
                removed=[
                    {
                        "memory_id": "72345678-1234-5678-1234-567812345678",
                        "reason": "wrong",
                    }
                ],
                added_back=[],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=run_id,
                injection_id=INJECTION_ID,
                removed=[
                    {
                        "memory_id": NEAR_MISS_ID,
                        "reason": "wrong",
                    }
                ],
                added_back=[],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=run_id,
                injection_id=INJECTION_ID,
                removed=[
                    {
                        "memory_id": NEAR_MISS_ID,
                        "reason": "not_relevant",
                    }
                ],
                added_back=[],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=run_id,
                injection_id=INJECTION_ID,
                removed=[
                    {
                        "memory_id": NEAR_MISS_ID,
                        "reason": "never",
                    }
                ],
                added_back=[NEAR_MISS_ID],
            ),
        ),
        (
            "thread-1",
            GateCommitPayload(
                run_id=run_id,
                injection_id=INJECTION_ID,
                removed=[],
                added_back=[NEAR_MISS_ID, NEAR_MISS_ID],
            ),
        ),
    ]
    for count, (thread_id, decision) in enumerate(invalid, start=1):
        await loop.commit_gate(thread_id=thread_id, decision=decision, sink=reconnected)
        await _wait_for_type_count(reconnected, MessageType.ERROR, count)
        assert not runner.accepted.is_set()

    decision = GateCommitPayload(
        run_id=run_id,
        injection_id=INJECTION_ID,
        removed=[
            {"memory_id": INJECTED_ID, "reason": "not_relevant"},
            {"memory_id": NEAR_MISS_ID, "reason": "never"},
        ],
        added_back=[],
    )
    await loop.commit_gate(thread_id="thread-1", decision=decision, sink=reconnected)
    await _wait(runner.accepted)
    assert runner.decision == decision
    assert MessageType.GATE_DISMISS not in types(reconnected)
    assert MessageType.RUN_DELTA not in types(reconnected)

    await loop.commit_gate(thread_id="thread-1", decision=decision, sink=reconnected)
    await _wait_for_type_count(reconnected, MessageType.ERROR, len(invalid) + 1)

    await loop.request_snapshot("thread-1", reconnected)
    await _wait_for_type_count(reconnected, MessageType.THREAD_SNAPSHOT, 2)
    in_flight = reconnected.messages[-1].payload
    assert isinstance(in_flight, ThreadSnapshotResponsePayload)
    assert in_flight.open_gate is not None
    assert in_flight.active_run is not None
    assert in_flight.active_run.state == "waiting_gate"

    runner.allow_dismiss.set()
    await _wait_for_done_count(reconnected, 1)
    resumed_types = types(reconnected)
    assert resumed_types.index(MessageType.GATE_DISMISS) < resumed_types.index(
        MessageType.RUN_DELTA
    )
    assert resumed_types.index(MessageType.RUN_DELTA) < resumed_types.index(MessageType.RUN_DONE)
    assert all(
        payload(message) == {"code": "gate_not_committable", "run_id": expected.run_id}
        for message, (_, expected) in zip(
            [message for message in reconnected.messages if message.type is MessageType.ERROR],
            [*invalid, ("thread-1", decision)],
            strict=True,
        )
    )
    await loop.close()


@pytest.mark.asyncio
async def test_wrong_resolution_replaces_gate_and_validates_current_revision() -> None:
    ids = Ids()
    runner = WrongResolutionGateRunner()
    loop = RunLoop(runner, factory(ids))
    sink = Sink()
    await loop.attach(sink)
    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait_for_type_count(sink, MessageType.GATE_OPEN, 1)

    review = GateCommitPayload(
        run_id=run_id,
        injection_id=INJECTION_ID,
        removed=[{"memory_id": INJECTED_ID, "reason": "wrong"}],
        added_back=[],
    )
    await loop.commit_gate(thread_id="thread-1", decision=review, sink=sink)
    await _wait_for_type_count(sink, MessageType.GATE_OPEN, 2)
    replacement = [message for message in sink.messages if message.type is MessageType.GATE_OPEN][
        -1
    ].payload
    assert replacement.stage == "wrong_resolution"
    assert replacement.wrong_removed[0].revision == 2
    assert MessageType.GATE_DISMISS not in types(sink)
    assert MessageType.RUN_DELTA not in types(sink)

    stale = GateCommitPayload(
        run_id=run_id,
        injection_id=INJECTION_ID,
        removed=[],
        added_back=[],
        wrong_resolution=WrongResolution(
            memory_id=INJECTED_ID,
            expected_revision=1,
            action="edit",
            body="Corrected body",
        ),
    )
    await loop.commit_gate(thread_id="thread-1", decision=stale, sink=sink)
    await _wait_for_type_count(sink, MessageType.ERROR, 1)
    assert runner.resolution is None

    resolution = stale.model_copy(
        update={
            "wrong_resolution": WrongResolution(
                memory_id=INJECTED_ID,
                expected_revision=2,
                action="expire",
            )
        }
    )
    await loop.commit_gate(thread_id="thread-1", decision=resolution, sink=sink)
    await _wait_for_done_count(sink, 1)

    assert runner.review == review
    assert runner.resolution == resolution
    event_types = types(sink)
    assert event_types.count(MessageType.GATE_OPEN) == 2
    assert event_types.index(MessageType.GATE_DISMISS) < event_types.index(MessageType.RUN_DELTA)
    await loop.close()


@pytest.mark.asyncio
async def test_invalid_gate_payload_ends_the_run_instead_of_stranding_the_ui() -> None:
    ids = Ids()
    loop = RunLoop(InvalidGateRunner(), factory(ids))
    sink = Sink()
    await loop.attach(sink)

    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)

    assert MessageType.GATE_OPEN not in types(sink)
    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert payload(done) == {
        "run_id": run_id,
        "stop_reason": StopReason.ERROR,
        "partial": True,
    }
    await loop.close()


@pytest.mark.asyncio
async def test_cancel_before_run_task_first_step_still_confirms_once() -> None:
    ids = Ids()
    loop = RunLoop(NeverStartsRunner(), factory(ids))
    sink = Sink()
    await loop.attach(sink)

    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="cancel immediately",
        sink=sink,
    )
    await loop.cancel(thread_id="thread-1", run_id=run_id, sink=sink)
    await loop.cancel(thread_id=None, run_id=run_id, sink=sink)
    await _wait_for_done_count(sink, 1)

    assert types(sink).count(MessageType.RUN_DONE) == 1
    assert MessageType.ERROR not in types(sink)
    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert payload(done) == {
        "run_id": run_id,
        "stop_reason": StopReason.CANCELLED,
        "partial": True,
    }
    await loop.close()


@pytest.mark.asyncio
async def test_cancel_racing_completed_model_preserves_outcome_for_queued_turn() -> None:
    ids = Ids()
    runner = ImmediateHistoryRunner()
    loop = FinishBarrierLoop(runner, factory(ids))
    sink = Sink()
    await loop.attach(sink)

    first_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="first",
        sink=sink,
    )
    await _wait(loop.finish_entered)
    second_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt="second",
        sink=sink,
    )

    await loop.cancel(thread_id=None, run_id=first_id, sink=sink)
    loop.release_finish.set()
    await _wait_for_done_count(sink, 2)

    assert runner.calls == [
        ("first", ()),
        ("second", ("first:complete",)),
    ]
    indexed = [(message.type, payload(message).get("run_id")) for message in sink.messages]
    assert indexed.index((MessageType.RUN_DONE, first_id)) < indexed.index(
        (MessageType.RUN_STARTED, second_id)
    )
    first_done = next(
        message
        for message in sink.messages
        if message.type is MessageType.RUN_DONE and payload(message)["run_id"] == first_id
    )
    assert payload(first_done)["stop_reason"] is StopReason.CANCELLED
    await loop.close()


@pytest.mark.asyncio
async def test_close_does_not_interrupt_cancellation_cleanup_a_second_time() -> None:
    ids = Ids()
    control = TurnControl()
    loop = RunLoop(ControlledRunner({"hello": control}), factory(ids))
    sink = Sink()
    await loop.attach(sink)
    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait(control.entered)
    await loop.cancel(thread_id="thread-1", run_id=run_id, sink=sink)
    await _wait(control.cancellation_seen)

    closing = asyncio.create_task(loop.close())
    await asyncio.sleep(0)
    assert not closing.done()
    control.cleanup_release.set()
    await asyncio.wait_for(closing, TEST_TIMEOUT)

    assert loop._threads["thread-1"].message_history == ("hello:cancelled-tool",)


@pytest.mark.asyncio
async def test_slow_sink_is_bounded_without_one_task_per_delta() -> None:
    ids = Ids()
    control = TurnControl()
    runner = ControlledRunner({"hello": control})
    loop = RunLoop(runner, factory(ids))
    sink = BlockingSink()
    overflow_count = 0

    def record_overflow() -> None:
        nonlocal overflow_count
        overflow_count += 1

    await loop.attach(sink, on_overflow=record_overflow)
    # H4 selects its local thread immediately after connecting. The overflow
    # callback must survive that authoritative snapshot re-subscription.
    sink.release.set()
    await loop.request_snapshot("thread-1", sink)
    sink.release.clear()
    sink.entered.clear()
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait(control.entered)
    await _wait(sink.entered)

    emitter = runner.emitters["hello"]
    for _ in range(1_000):
        await emitter.text("x")
    await asyncio.sleep(0)

    delivery_tasks = [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "harness-envelope-delivery" and not task.done()
    ]
    assert len(delivery_tasks) <= 1
    assert sink.calls == 2
    assert loop._subscriptions == []
    assert overflow_count == 1

    control.release.set()
    for _ in range(100):
        if loop._threads["thread-1"].active is None:
            break
        await asyncio.sleep(0)
    assert loop._threads["thread-1"].active is None
    await loop.close()


@pytest.mark.asyncio
async def test_direct_error_worker_is_owned_until_loop_close() -> None:
    ids = Ids()
    loop = RunLoop(ImmediateHistoryRunner(), factory(ids))
    sink = Sink()

    await loop.cancel(thread_id=None, run_id=ulid(1), sink=sink)
    await _wait_for_type_count(sink, MessageType.ERROR, 1)
    workers = [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "harness-envelope-delivery" and not task.done()
    ]
    assert len(workers) == 1
    assert len(loop._subscriptions) == 1
    assert loop._subscriptions[0].thread_id is None

    await loop.close()

    assert loop._subscriptions == []
    assert all(worker.done() for worker in workers)


@pytest.mark.asyncio
async def test_fifo_runs_once_and_survives_error_and_budget_terminals() -> None:
    ids = Ids()
    first = TurnControl(stop_reason=StopReason.ERROR)
    second = TurnControl(
        stop_reason=StopReason.BUDGET_EXCEEDED,
        usage=UsageSnapshot(2, 30, 8),
    )
    third = TurnControl(stop_reason=StopReason.END_TURN)
    runner = ControlledRunner({"first": first, "second": second, "third": third})
    loop = RunLoop(runner, factory(ids))
    sink = Sink()
    await loop.attach(sink)

    first_id = await loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt="first", sink=sink)
    await _wait(first.entered)
    second_id = await loop.submit(
        thread_id="thread-1", prompt_id=ulid(2), prompt="second", sink=sink
    )
    third_id = await loop.submit(thread_id="thread-1", prompt_id=ulid(3), prompt="third", sink=sink)
    await _wait_for_type_count(sink, MessageType.PROMPT_QUEUED, 2)
    assert [
        payload(message)["run_id"]
        for message in sink.messages
        if message.type is MessageType.PROMPT_QUEUED
    ] == [second_id, third_id]
    queued_snapshot_sink = Sink()
    await loop.request_snapshot("thread-1", queued_snapshot_sink)
    await _wait_for_type_count(queued_snapshot_sink, MessageType.THREAD_SNAPSHOT, 1)
    queued_snapshot = queued_snapshot_sink.messages[0].payload
    assert isinstance(queued_snapshot, ThreadSnapshotResponsePayload)
    assert queued_snapshot.active_run is not None
    assert [item.run_id for item in queued_snapshot.active_run.queued] == [
        second_id,
        third_id,
    ]
    queued_user_content = [
        message["content"] for message in queued_snapshot.messages if message["role"] == "user"
    ]
    assert queued_user_content == ["first", "second", "third"]

    first.release.set()
    await _wait(second.entered)
    second.release.set()
    await _wait(third.entered)
    third.release.set()
    await _wait_for_done_count(sink, 3)

    starts = [
        payload(message)["run_id"]
        for message in sink.messages
        if message.type is MessageType.RUN_STARTED
    ]
    assert starts == [first_id, second_id, third_id]
    done = [payload(message) for message in sink.messages if message.type is MessageType.RUN_DONE]
    assert [item["stop_reason"] for item in done] == [
        StopReason.ERROR,
        StopReason.BUDGET_EXCEEDED,
        StopReason.END_TURN,
    ]
    indexed = [(message.type, payload(message).get("run_id")) for message in sink.messages]
    assert indexed.index((MessageType.RUN_DONE, first_id)) < indexed.index(
        (MessageType.RUN_STARTED, second_id)
    )
    assert indexed.index((MessageType.RUN_DONE, second_id)) < indexed.index(
        (MessageType.RUN_STARTED, third_id)
    )
    assert [prompt for _, prompt, _ in runner.calls] == ["first", "second", "third"]
    assert runner.calls[0][2] == ()
    assert runner.calls[1][2] == ("first:error",)
    assert runner.calls[2][2] == (
        "first:error",
        "second:budget_exceeded",
    )

    snapshot_sink = Sink()
    await loop.request_snapshot("thread-1", snapshot_sink)
    await _wait_for_type_count(snapshot_sink, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = snapshot_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert [message["role"] for message in snapshot.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert snapshot.active_run is None
    await loop.close()


@dataclass
class SnapshotBarrierSink(Sink):
    snapshot_entered: asyncio.Event = field(default_factory=asyncio.Event)
    release_snapshot: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self, message: Envelope) -> None:
        self.messages.append(message)
        if message.type is MessageType.THREAD_SNAPSHOT:
            self.snapshot_entered.set()
            await self.release_snapshot.wait()


@pytest.mark.asyncio
async def test_attach_snapshot_is_atomic_before_new_live_delta() -> None:
    ids = Ids()
    control = TurnControl()
    runner = ControlledRunner({"hello": control})
    loop = RunLoop(runner, factory(ids))
    original = Sink()
    await loop.attach(original)
    await loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt="hello", sink=original)
    await _wait(control.entered)
    await loop.detach(original)

    reconnect = SnapshotBarrierSink()
    attach = asyncio.create_task(loop.attach(reconnect))
    await _wait(reconnect.snapshot_entered)
    await runner.emitters["hello"].text("after snapshot")
    await asyncio.sleep(0)
    assert types(reconnect) == [MessageType.THREAD_SNAPSHOT]

    reconnect.release_snapshot.set()
    await attach
    await _wait_for_type_count(reconnect, MessageType.RUN_DELTA, 1)
    assert types(reconnect) == [MessageType.THREAD_SNAPSHOT, MessageType.RUN_DELTA]
    assert MessageType.RUN_STARTED not in types(reconnect)
    control.release.set()
    await _wait_for_done_count(reconnect, 1)
    await loop.close()


@pytest.mark.asyncio
async def test_cancel_without_outer_thread_finds_run_after_selection_changes() -> None:
    ids = Ids()
    control = TurnControl()
    runner = ControlledRunner({"hello": control})
    loop = RunLoop(runner, factory(ids))
    sink = Sink()
    await loop.attach(sink)
    run_id = await loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt="hello", sink=sink)
    await _wait(control.entered)

    await loop.select("thread-2", sink)
    await loop.cancel(thread_id=None, run_id=run_id, sink=sink)
    await _wait(control.cancellation_seen)
    control.cleanup_release.set()
    await _wait_for_done_count(sink, 1)

    assert MessageType.ERROR not in types(sink)
    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert done.thread_id == "thread-1"
    assert payload(done)["stop_reason"] is StopReason.CANCELLED
    await loop.close()


class RegressiveUsageRunner:
    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, prompt, message_history, model_resolution
        await emit.usage(UsageSnapshot(2, 20, 4, 12, 3))
        await emit.usage(UsageSnapshot(2, 20, 4, 11, 3))
        raise AssertionError("regression must fail before this line")


@pytest.mark.asyncio
async def test_usage_regression_terminalizes_as_error_and_stale_cancel_is_scoped() -> None:
    ids = Ids()
    loop = RunLoop(RegressiveUsageRunner(), factory(ids))
    sink = Sink()
    await loop.attach(sink)
    run_id = await loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt="hello", sink=sink)
    await _wait_for_done_count(sink, 1)

    usage = [message for message in sink.messages if message.type is MessageType.RUN_USAGE]
    assert len(usage) == 1
    assert payload(usage[0]) == {
        "requests": 2,
        "input_tokens": 20,
        "output_tokens": 4,
        "cache_read_tokens": 12,
        "cache_write_tokens": 3,
        "run_id": run_id,
    }
    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert payload(done)["stop_reason"] is StopReason.ERROR

    before = len(sink.messages)
    await loop.cancel(thread_id=None, run_id=run_id, sink=sink)
    await _wait_for_type_count(sink, MessageType.ERROR, 1)
    assert len(sink.messages) == before + 1
    assert sink.messages[-1].type is MessageType.ERROR
    assert payload(sink.messages[-1]) == {"code": "run_not_active", "run_id": run_id}
    await loop.close()


async def _wait_for_done_count(sink: Sink, expected: int) -> None:
    await _wait_for_type_count(sink, MessageType.RUN_DONE, expected)


async def _wait_for_type_count(
    sink: Sink,
    message_type: MessageType,
    expected: int,
) -> None:
    for _ in range(100):
        if types(sink).count(message_type) >= expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {expected} {message_type} messages")


async def _wait(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), TEST_TIMEOUT)
