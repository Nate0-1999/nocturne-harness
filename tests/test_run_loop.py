from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic_ai.messages import BinaryContent

from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    GateCommitPayload,
    ImageInput,
    MessageType,
    ProviderErrorPayload,
    StopReason,
    ThreadSnapshotResponsePayload,
    WrongResolution,
)
from harness.model_policy import (
    ModelCatalogUnavailable,
    ModelPolicyResolver,
    NamedModelResolutionError,
    ThreadModelResolution,
)
from harness.run_loop import ProjectBindingConflict, RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.transcript import TranscriptJournal

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


def png_input(data: bytes = b"\x89PNG\r\n\x1a\nrun-loop-image") -> ImageInput:
    return ImageInput(
        kind="image",
        media_type="image/png",
        data_base64=base64.b64encode(data).decode("ascii"),
    )


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


class ImageRecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, BinaryContent, ThreadModelResolution | None]] = []

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        image: BinaryContent,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id
        self.calls.append((prompt, image, model_resolution))
        await emit.text("visual answer")
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, "image:complete"),
            UsageSnapshot(requests=1, input_tokens=5, output_tokens=2),
            assistant_text="visual answer",
        )


class RecordingResolver:
    def __init__(
        self,
        resolutions: Mapping[str, ThreadModelResolution],
        named: Mapping[str, ThreadModelResolution | Exception] | None = None,
    ) -> None:
        self.resolutions = resolutions
        self.named = named or {}
        self.calls: list[str] = []
        self.named_calls: list[tuple[str, str]] = []

    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        self.calls.append(thread_id)
        return self.resolutions[thread_id]

    async def resolve_named(self, thread_id: str, model: str) -> ThreadModelResolution:
        self.named_calls.append((thread_id, model))
        value = self.named[model]
        if isinstance(value, Exception):
            raise value
        return value


class OutageCatalog:
    def __init__(self) -> None:
        self.named_calls: list[str] = []

    async def load(self):
        raise ModelCatalogUnavailable("catalog offline")

    async def load_named_route(self, model_id: str):
        self.named_calls.append(model_id)
        raise ModelCatalogUnavailable("catalog offline")


def seed_hydrated_model(
    journal: TranscriptJournal,
    *,
    thread_id: str,
    model: str,
) -> None:
    prompt_id = ulid(80)
    run_id = ulid(81)
    journal.append_message(
        thread_id,
        {
            "message_id": prompt_id,
            "run_id": run_id,
            "role": "user",
            "content": "Earlier turn",
            "state": "end_turn",
            "model_visible": True,
        },
        parent_id=None,
    )
    journal.append_message(
        thread_id,
        {
            "message_id": run_id,
            "run_id": run_id,
            "role": "assistant",
            "content": "Earlier answer",
            "thinking": "",
            "events": [],
            "partial": False,
        },
        parent_id=prompt_id,
    )
    journal.append_event(
        thread_id,
        factory(Ids(value=900)).create(
            MessageType.RUN_STARTED,
            {
                "run_id": run_id,
                "prompt_id": prompt_id,
                "resolved_model": model,
            },
            thread_id=thread_id,
        ),
    )


class ResolutionRecordingRunner:
    def __init__(self, *, cacheable_prefix_tokens: int = 0) -> None:
        self.resolutions: list[ThreadModelResolution | None] = []
        self.histories: list[tuple[object, ...]] = []
        self.cacheable_prefix_tokens = cacheable_prefix_tokens

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
        self.histories.append(tuple(message_history))
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, f"{prompt}:complete"),
            cacheable_prefix_tokens=self.cacheable_prefix_tokens,
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
    """SPEC C.7 is defended by verifying that run loop rejects invalid resolved model; this
    prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()

    with pytest.raises(ValueError, match="resolved_model"):
        RunLoop(
            ImmediateHistoryRunner(),
            factory(ids),
            resolved_model=resolved_model,
        )


@pytest.mark.asyncio
async def test_project_binding_is_journaled_once_and_becomes_authoritative(
    tmp_path: Path,
) -> None:
    """F028, SPEC C.3/C.4, ADR-005, and B.6 r12 require one trusted current project;
    this proves an idempotent pristine bind is durable before its snapshot is exposed.
    """

    journal = TranscriptJournal(tmp_path / "transcripts")
    loop = RunLoop(
        ImmediateHistoryRunner(),
        factory(Ids()),
        transcript_journal=journal,
    )
    first = Sink()
    await loop.request_snapshot("thread-1", first, project_key="build-test/api")
    await _wait_for_type_count(first, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = first.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.project_key == "build-test/api"
    assert loop.project_key("thread-1") == "build-test/api"

    second = Sink()
    await loop.request_snapshot("thread-1", second, project_key="build-test/api")
    rows = journal.path_for_thread("thread-1").read_text(encoding="utf-8")
    assert rows.count('"record_type":"thread_context"') == 1

    with pytest.raises(ProjectBindingConflict) as raised:
        await loop.request_snapshot("thread-1", Sink(), project_key="another-project")
    assert raised.value.existing == "build-test/api"
    assert loop.project_key("thread-1") == "build-test/api"
    await loop.close()


@pytest.mark.asyncio
async def test_legacy_nonempty_thread_cannot_be_silently_reprojected() -> None:
    """F028 and ADR-005 forbid treating legacy None as a global project match; this proves a
    nonempty unscoped thread must remain unscoped instead of changing Spine identity.
    """

    control = TurnControl()
    loop = RunLoop(ControlledRunner({"legacy": control}), factory(Ids()))
    sink = Sink()
    await loop.submit(
        thread_id="thread-legacy",
        prompt_id=ulid(1),
        prompt="legacy",
        sink=sink,
    )
    await asyncio.wait_for(control.entered.wait(), TEST_TIMEOUT)

    with pytest.raises(ProjectBindingConflict) as raised:
        await loop.request_snapshot(
            "thread-legacy",
            Sink(),
            project_key="build-test",
        )
    assert raised.value.existing is None
    assert loop.project_key("thread-legacy") is None

    control.release.set()
    await _wait_for_done_count(sink, 1)
    await loop.close()


@pytest.mark.asyncio
async def test_static_resolved_model_is_authoritative_on_start_and_snapshot() -> None:
    """SPEC C.7 is defended by verifying that static resolved model is authoritative on start
    and snapshot; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that policy resolution occurs once at first run and is
    thread authoritative; this prevents drift in the single authoritative run-loop contract.
    """
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
async def test_model_command_commits_one_journaled_epoch_without_calling_runner() -> None:
    """SPEC C.7 is defended by verifying that model command commits one journaled epoch without
    calling runner; this prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()
    initial = ThreadModelResolution(
        model="openrouter:vendor/initial",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/initial",
    )
    candidate = ThreadModelResolution(
        model="openrouter:vendor/next",
        context_tokens=262_144,
        policy="human_command",
    )
    resolver = RecordingResolver(
        {"thread-1": initial},
        {candidate.model: candidate},
    )
    runner = ResolutionRecordingRunner(cacheable_prefix_tokens=123)
    loop = RunLoop(
        runner,
        factory(ids),
        model_resolver=resolver,
        clock=lambda: datetime(2026, 7, 31, 9, 30, tzinfo=UTC),
    )
    sink = Sink()

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)
    command_run = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt=f"/model {candidate.model}",
        sink=sink,
    )
    await _wait_for_done_count(sink, 2)

    assert len(runner.resolutions) == 1
    assert resolver.named_calls == [("thread-1", candidate.model)]
    command_started = next(
        message
        for message in sink.messages
        if message.type is MessageType.RUN_STARTED and payload(message)["run_id"] == command_run
    )
    assert payload(command_started)["resolved_model"] == initial.model
    command_event_payloads = [
        payload(message)
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA
        and payload(message)["run_id"] == command_run
        and payload(message)["kind"] == "event"
    ]
    assert command_event_payloads == [
        {
            "run_id": command_run,
            "kind": "event",
            "resolved_model": candidate.model,
            "event": {
                "event_kind": "model_change",
                "old_model": initial.model,
                "new_model": candidate.model,
                "reason": "human_command",
                "timestamp": "2026-07-31T09:30:00+00:00",
                "stickiness_epoch": 1,
                "sacrificed_cached_prefix_tokens": 123,
                "context_tokens": 262_144,
            },
        }
    ]
    command_events = [item["event"] for item in command_event_payloads]

    snapshot_sink = Sink()
    await loop.request_snapshot("thread-1", snapshot_sink)
    await _wait_for_type_count(snapshot_sink, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = snapshot_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.resolved_model == candidate.model
    command_assistant = next(
        message
        for message in snapshot.messages
        if message["run_id"] == command_run and message["role"] == "assistant"
    )
    assert command_assistant["events"] == command_events
    assert "Context window: 262144 tokens" in command_assistant["content"]

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt="after switch",
        sink=sink,
    )
    await _wait_for_done_count(sink, 3)
    assert runner.resolutions == [initial, replace(candidate, stickiness_epoch=1)]
    assert runner.histories[1] == ("hello:complete",)
    await loop.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "failure", "expected_text"),
    [
        ("", None, "add an OpenRouter model string"),
        (
            "openrouter:vendor/unknown",
            NamedModelResolutionError("unknown OpenRouter model: vendor/unknown"),
            "unknown OpenRouter model",
        ),
        (
            "openrouter:vendor/down",
            ModelCatalogUnavailable("offline"),
            "model catalog is unavailable",
        ),
    ],
)
async def test_model_command_failures_are_visible_and_preserve_epoch_and_prefix(
    target: str,
    failure: Exception | None,
    expected_text: str,
) -> None:
    """SPEC C.7 is defended by verifying that model command failures are visible and preserve
    epoch and prefix; this prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()
    initial = ThreadModelResolution(
        model="openrouter:vendor/initial",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/initial",
    )
    next_model = ThreadModelResolution(
        model="openrouter:vendor/next",
        context_tokens=100_000,
        policy="human_command",
    )
    named: dict[str, ThreadModelResolution | Exception] = {
        next_model.model: next_model,
    }
    if target:
        assert isinstance(failure, Exception)
        named[target] = failure
    resolver = RecordingResolver({"thread-1": initial}, named)
    runner = ResolutionRecordingRunner(cacheable_prefix_tokens=77)
    loop = RunLoop(runner, factory(ids), model_resolver=resolver)
    sink = Sink()

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="hello",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)
    command = "/model" if not target else f"/model {target}"
    failed_run = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt=command,
        sink=sink,
    )
    await _wait_for_done_count(sink, 2)

    failed_deltas = [
        payload(message)
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA and payload(message)["run_id"] == failed_run
    ]
    assert not [item for item in failed_deltas if item["kind"] == "event"]
    assert expected_text in "".join(
        str(item["text"]) for item in failed_deltas if item["kind"] == "text"
    )

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt=f"/model {next_model.model}",
        sink=sink,
    )
    await _wait_for_done_count(sink, 3)
    successful_event = next(
        payload(message)["event"]
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA and payload(message)["kind"] == "event"
    )
    assert successful_event["stickiness_epoch"] == 1
    assert successful_event["sacrificed_cached_prefix_tokens"] == 77
    await loop.close()


@pytest.mark.asyncio
async def test_current_model_command_refreshes_context_and_starts_new_epoch() -> None:
    """SPEC C.7 is defended by verifying that current model command refreshes context and
    starts new epoch; this prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()
    initial = ThreadModelResolution(
        model="openrouter:vendor/current",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/current",
    )
    refreshed = ThreadModelResolution(
        model=initial.model,
        context_tokens=128_000,
        policy="human_command",
    )
    resolver = RecordingResolver({"thread-1": initial}, {initial.model: refreshed})
    runner = ResolutionRecordingRunner(cacheable_prefix_tokens=33)
    loop = RunLoop(runner, factory(ids), model_resolver=resolver)
    sink = Sink()

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="before",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)
    command_run = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt=f"/model {initial.model}",
        sink=sink,
    )
    await _wait_for_done_count(sink, 2)

    command_event = next(
        payload(message)["event"]
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA
        and payload(message)["run_id"] == command_run
        and payload(message)["kind"] == "event"
    )
    assert command_event["old_model"] == initial.model
    assert command_event["new_model"] == initial.model
    assert command_event["stickiness_epoch"] == 1
    assert command_event["context_tokens"] == 128_000
    assert command_event["sacrificed_cached_prefix_tokens"] == 33

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt="after",
        sink=sink,
    )
    await _wait_for_done_count(sink, 3)
    assert runner.resolutions == [initial, replace(refreshed, stickiness_epoch=1)]
    await loop.close()


@pytest.mark.asyncio
async def test_queued_model_command_changes_only_the_following_turn() -> None:
    """SPEC C.7 is defended by verifying that queued model command changes only the following
    turn; this prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()
    initial = ThreadModelResolution(
        model="openrouter:vendor/initial",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/initial",
    )
    candidate = ThreadModelResolution(
        model="openrouter:vendor/next",
        context_tokens=100_000,
        policy="human_command",
    )

    class QueueRunner:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.prompts: list[str] = []
            self.resolutions: list[ThreadModelResolution | None] = []
            self.histories: list[tuple[object, ...]] = []

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
            self.prompts.append(prompt)
            self.resolutions.append(model_resolution)
            self.histories.append(tuple(message_history))
            if prompt == "old turn":
                self.entered.set()
                await self.release.wait()
            return TurnOutcome(
                StopReason.END_TURN,
                (*message_history, f"{prompt}:complete"),
                cacheable_prefix_tokens=50,
            )

    runner = QueueRunner()
    resolver = RecordingResolver(
        {"thread-1": initial},
        {candidate.model: candidate},
    )
    loop = RunLoop(runner, factory(ids), model_resolver=resolver)
    sink = Sink()
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="old turn",
        sink=sink,
    )
    await _wait(runner.entered)
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt=f"/model {candidate.model}",
        sink=sink,
    )
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt="new turn",
        sink=sink,
    )

    assert runner.prompts == ["old turn"]
    runner.release.set()
    await _wait_for_done_count(sink, 3)

    assert runner.prompts == ["old turn", "new turn"]
    assert runner.resolutions == [initial, replace(candidate, stickiness_epoch=1)]
    assert runner.histories == [(), ("old turn:complete",)]
    model_event = next(
        payload(message)["event"]
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA and payload(message)["kind"] == "event"
    )
    assert model_event["sacrificed_cached_prefix_tokens"] == 50
    await loop.close()


@pytest.mark.asyncio
async def test_model_lookup_starts_at_fifo_boundary_after_immediate_queue_ack() -> None:
    """SPEC C.7 is defended by verifying that model lookup starts at fifo boundary after
    immediate queue ack; this prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()
    initial = ThreadModelResolution(
        model="openrouter:vendor/initial",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/initial",
    )
    candidate = ThreadModelResolution(
        model="openrouter:vendor/next",
        context_tokens=100_000,
        policy="human_command",
    )

    class DelayedResolver(RecordingResolver):
        def __init__(self) -> None:
            super().__init__({"thread-1": initial}, {candidate.model: candidate})
            self.named_entered = asyncio.Event()
            self.named_release = asyncio.Event()

        async def resolve_named(self, thread_id: str, model: str) -> ThreadModelResolution:
            self.named_entered.set()
            await self.named_release.wait()
            return await super().resolve_named(thread_id, model)

    class DelayedRunner:
        def __init__(self) -> None:
            self.old_entered = asyncio.Event()
            self.old_release = asyncio.Event()
            self.prompts: list[str] = []
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
            self.prompts.append(prompt)
            self.resolutions.append(model_resolution)
            if prompt == "old turn":
                self.old_entered.set()
                await self.old_release.wait()
            return TurnOutcome(
                StopReason.END_TURN,
                (*message_history, f"{prompt}:complete"),
            )

    resolver = DelayedResolver()
    runner = DelayedRunner()
    loop = RunLoop(runner, factory(ids), model_resolver=resolver)
    sink = Sink()
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="old turn",
        sink=sink,
    )
    await _wait(runner.old_entered)

    command_run = await asyncio.wait_for(
        loop.submit(
            thread_id="thread-1",
            prompt_id=ulid(2),
            prompt=f"/model {candidate.model}",
            sink=sink,
        ),
        timeout=0.25,
    )
    next_run = await asyncio.wait_for(
        loop.submit(
            thread_id="thread-1",
            prompt_id=ulid(3),
            prompt="new turn",
            sink=sink,
        ),
        timeout=0.25,
    )
    await _wait_for_type_count(sink, MessageType.PROMPT_QUEUED, 2)
    queued = [
        payload(message)["run_id"]
        for message in sink.messages
        if message.type is MessageType.PROMPT_QUEUED
    ]
    assert queued == [command_run, next_run]
    assert not resolver.named_entered.is_set()

    runner.old_release.set()
    await _wait(resolver.named_entered)
    assert runner.prompts == ["old turn"]
    assert not any(
        message.type is MessageType.RUN_STARTED and payload(message)["run_id"] == next_run
        for message in sink.messages
    )

    resolver.named_release.set()
    await _wait_for_done_count(sink, 3)
    assert runner.prompts == ["old turn", "new turn"]
    assert runner.resolutions == [initial, replace(candidate, stickiness_epoch=1)]
    await loop.close()


@pytest.mark.asyncio
async def test_cancelling_model_lookup_preserves_current_model_and_epoch() -> None:
    """SPEC C.7 is defended by verifying that cancelling model lookup preserves current model
    and epoch; this prevents drift in the single authoritative run-loop contract.
    """
    ids = Ids()
    initial = ThreadModelResolution(
        model="openrouter:vendor/initial",
        context_tokens=64_000,
        policy="pinned:openrouter:vendor/initial",
    )
    candidate = ThreadModelResolution(
        model="openrouter:vendor/next",
        context_tokens=100_000,
        policy="human_command",
    )

    class BlockingResolver(RecordingResolver):
        def __init__(self) -> None:
            super().__init__({"thread-1": initial}, {candidate.model: candidate})
            self.named_entered = asyncio.Event()
            self.never_release = asyncio.Event()

        async def resolve_named(self, thread_id: str, model: str) -> ThreadModelResolution:
            self.named_entered.set()
            await self.never_release.wait()
            return await super().resolve_named(thread_id, model)

    resolver = BlockingResolver()
    runner = ResolutionRecordingRunner(cacheable_prefix_tokens=91)
    loop = RunLoop(runner, factory(ids), model_resolver=resolver)
    sink = Sink()
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="before",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)
    command_run = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt=f"/model {candidate.model}",
        sink=sink,
    )
    await _wait(resolver.named_entered)

    await loop.cancel(thread_id="thread-1", run_id=command_run, sink=sink)
    await _wait_for_done_count(sink, 2)
    command_done = next(
        message
        for message in sink.messages
        if message.type is MessageType.RUN_DONE and payload(message)["run_id"] == command_run
    )
    assert payload(command_done)["stop_reason"] == StopReason.CANCELLED
    assert not any(
        message.type is MessageType.RUN_DELTA
        and payload(message)["run_id"] == command_run
        and payload(message)["kind"] == "event"
        for message in sink.messages
    )

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt="after",
        sink=sink,
    )
    await _wait_for_done_count(sink, 3)
    assert runner.resolutions == [initial, initial]
    snapshot_sink = Sink()
    await loop.request_snapshot("thread-1", snapshot_sink)
    await _wait_for_type_count(snapshot_sink, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = snapshot_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.resolved_model == initial.model
    await loop.close()


@pytest.mark.asyncio
async def test_cancel_awaits_cleanup_preserves_partial_and_coalesces_duplicates() -> None:
    """SPEC C.7 is defended by verifying that cancel awaits cleanup preserves partial and
    coalesces duplicates; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that gate blocks reconnects validates once and resumes
    only after dismiss; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that wrong resolution replaces gate and validates
    current revision; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that invalid gate payload ends the run instead of
    stranding the ui; this prevents drift in the single authoritative run-loop contract.
    """
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
async def test_f034_run_loop_preserves_provider_error_in_terminal_envelope_and_transcript(
    tmp_path: Path,
) -> None:
    """F034 and v2.52 are defended by verifying that the run loop publishes and journals one
    typed plain provider refusal instead of collapsing it into a generic runtime error.
    """
    detail = ProviderErrorPayload(
        classification="context_length",
        message="maximum context length exceeded",
        model="openrouter:provider/model",
        status_code=400,
        code="context_length_exceeded",
    )

    class ProviderRefusalRunner:
        async def run(
            self,
            *,
            thread_id: str,
            prompt: str,
            message_history: Sequence[object],
            emit: RunEmitter,
            model_resolution: ThreadModelResolution | None = None,
        ) -> TurnOutcome:
            del thread_id, prompt, model_resolution
            await emit.event(
                {"event_kind": "provider_refusal", **detail.model_dump(exclude_none=True)}
            )
            await emit.text(
                "This thread has reached the model's context limit. "
                "Archive it, then continue in a fresh thread."
            )
            return TurnOutcome(
                StopReason.ERROR,
                tuple(message_history),
                provider_error=detail,
            )

    ids = Ids()
    journal = TranscriptJournal(tmp_path / "transcripts")
    loop = RunLoop(ProviderRefusalRunner(), factory(ids), transcript_journal=journal)
    sink = Sink()
    await loop.attach(sink)

    run_id = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="cross the limit",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)

    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert payload(done) == {
        "run_id": run_id,
        "stop_reason": StopReason.ERROR,
        "partial": True,
        "provider_error": detail.model_dump(),
    }
    snapshot_sink = Sink()
    await loop.request_snapshot("thread-1", snapshot_sink)
    snapshot = snapshot_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assistant = snapshot.messages[-1]
    assert assistant["content"].endswith("continue in a fresh thread.")
    assert assistant["events"] == [
        {"event_kind": "provider_refusal", **detail.model_dump(exclude_none=True)}
    ]
    await loop.close()

    hydrated = TranscriptJournal(journal.root).hydrate_threads()
    durable = next(item for item in hydrated if item.thread_id == "thread-1")
    assert durable.messages[-1]["events"] == assistant["events"]
    assert durable.messages[-1]["content"] == assistant["content"]


@pytest.mark.asyncio
async def test_cancel_before_run_task_first_step_still_confirms_once() -> None:
    """SPEC C.7 is defended by verifying that cancel before run task first step still confirms
    once; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that cancel racing completed model preserves outcome
    for queued turn; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that close does not interrupt cancellation cleanup a
    second time; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that slow sink is bounded without one task per delta;
    this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that direct error worker is owned until loop close;
    this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that fifo runs once and survives error and budget
    terminals; this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that attach snapshot is atomic before new live delta;
    this prevents drift in the single authoritative run-loop contract.
    """
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
    """SPEC C.7 is defended by verifying that cancel without outer thread finds run after
    selection changes; this prevents drift in the single authoritative run-loop contract.
    """
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


@pytest.mark.asyncio
async def test_supported_image_reaches_only_image_runner_with_compact_public_views(
    tmp_path: Path,
) -> None:
    """A-052 is defended by sending exact BinaryContent only after positive route capability;
    this keeps full bytes out of messages, snapshots, queued payloads, and run events.
    """
    image = png_input()
    resolution = ThreadModelResolution(
        model="openrouter:vendor/vision",
        context_tokens=100_000,
        policy="pinned:openrouter:vendor/vision",
        input_modalities=frozenset({"text", "image"}),
    )
    runner = ImageRecordingRunner()
    journal = TranscriptJournal(tmp_path / "transcripts")
    loop = RunLoop(
        runner,  # type: ignore[arg-type]
        factory(Ids()),
        model_resolver=RecordingResolver({"thread-1": resolution}),
        transcript_journal=journal,
    )
    sink = Sink()

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="Inspect this screenshot",
        image=image,
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)

    assert len(runner.calls) == 1
    prompt, binary, used_resolution = runner.calls[0]
    assert prompt == "Inspect this screenshot"
    assert binary.data == image.decoded_bytes()
    assert binary.media_type == "image/png"
    assert used_resolution == resolution
    assert all(
        "data_base64" not in json.dumps(item.model_dump(mode="json")) for item in sink.messages
    )
    rows = journal.path_for_thread("thread-1").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["record_type"] == "attachment"
    assert sum("data_base64" in row for row in rows) == 1
    await loop.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "modalities", "reason"),
    [
        ("Inspect this", frozenset({"text"}), "unsupported"),
        ("Inspect this", None, "unknown"),
        ("/model openrouter:vendor/vision", frozenset({"text", "image"}), "model_command"),
        ("/remember keep this", frozenset({"text", "image"}), "remember_command"),
    ],
)
async def test_image_refusal_is_local_plain_zero_usage_and_never_calls_runner(
    tmp_path: Path,
    prompt: str,
    modalities: frozenset[str] | None,
    reason: str,
) -> None:
    """A-052 is defended by completing unsupported, unknown, and command images locally;
    this prevents MemoryGate, Spine, provider history, or spend from seeing refused bytes.
    """
    resolution = ThreadModelResolution(
        model="openrouter:vendor/text",
        context_tokens=100_000,
        policy="pinned:openrouter:vendor/text",
        input_modalities=modalities,
    )
    journal = TranscriptJournal(tmp_path / reason / "transcripts")
    resolver = RecordingResolver({"thread-1": resolution})
    loop = RunLoop(
        NeverStartsRunner(),
        factory(Ids()),
        model_resolver=resolver,
        transcript_journal=journal,
    )
    sink = Sink()

    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt=prompt,
        image=png_input(),
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)

    event = next(
        payload(message)["event"]
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA and payload(message).get("kind") == "event"
    )
    assert isinstance(event, dict)
    assert event == {
        "event_kind": "image_refusal",
        "reason": reason,
        "model": "openrouter:vendor/text",
    }
    done = next(message for message in sink.messages if message.type is MessageType.RUN_DONE)
    assert payload(done)["stop_reason"] is StopReason.END_TURN
    usage = next(message for message in sink.messages if message.type is MessageType.RUN_USAGE)
    usage_value = payload(usage)
    assert usage_value["requests"] == 0
    assert usage_value["input_tokens"] == 0
    assert usage_value["output_tokens"] == 0
    assert usage_value.get("cache_read_tokens", 0) == 0
    assert usage_value.get("cache_write_tokens", 0) == 0
    assert any(
        message.type is MessageType.RUN_DELTA
        and payload(message).get("kind") == "text"
        and "resend" in str(payload(message).get("text"))
        for message in sink.messages
    )
    if reason == "model_command":
        text_deltas = [
            message
            for message in sink.messages
            if message.type is MessageType.RUN_DELTA and payload(message).get("kind") == "text"
        ]
        assert len(text_deltas) == 1
        assert "Model unchanged" not in str(payload(text_deltas[0]).get("text"))
        assert resolver.named_calls == []
    await loop.close()


@pytest.mark.asyncio
async def test_refused_image_pair_remains_visible_but_is_skipped_after_restart(
    tmp_path: Path,
) -> None:
    """A-052 is defended by journaling a complete image refusal while excluding its pair from
    rehydrated provider history; this prevents a refused image from being sent after restart.
    """
    journal = TranscriptJournal(tmp_path / "transcripts")
    resolution = ThreadModelResolution(
        model="openrouter:vendor/text",
        context_tokens=100_000,
        policy="pinned:openrouter:vendor/text",
        input_modalities=frozenset({"text"}),
    )
    first = RunLoop(
        NeverStartsRunner(),
        factory(Ids()),
        model_resolver=RecordingResolver({"thread-1": resolution}),
        transcript_journal=journal,
    )
    sink = Sink()
    await first.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="Inspect this",
        image=png_input(),
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)
    await first.close()

    runner = ImmediateHistoryRunner()
    restarted = RunLoop(
        runner,
        factory(Ids(value=500)),
        transcript_journal=TranscriptJournal(journal.root),
    )
    restart_sink = Sink()
    await restarted.request_snapshot("thread-1", restart_sink)
    snapshot = restart_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert len(snapshot.messages) == 2
    assert snapshot.messages[0]["model_visible"] is False
    await restarted.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt="Continue",
        sink=restart_sink,
    )
    await _wait_for_done_count(restart_sink, 1)
    assert runner.calls == [("Continue", ())]
    await restarted.close()


@pytest.mark.asyncio
async def test_restarted_image_catalog_outage_finishes_as_durable_unknown_refusal(
    tmp_path: Path,
) -> None:
    """A-052 is defended by converting a hydrated-model catalog outage into one durable
    unknown image refusal; this prevents a pre-run lookup from stranding a queued attachment.
    """
    thread_id = "thread-1"
    hydrated_model = "openrouter:vendor/owner-choice"
    journal = TranscriptJournal(tmp_path / "transcripts")
    seed_hydrated_model(journal, thread_id=thread_id, model=hydrated_model)
    catalog = OutageCatalog()
    resolver = ModelPolicyResolver(
        policy="pinned:openrouter:vendor/default",
        static_model="openrouter:vendor/default",
        static_context_tokens=64_000,
        catalog=catalog,  # type: ignore[arg-type]
    )
    loop = RunLoop(
        NeverStartsRunner(),
        factory(Ids(value=1_000)),
        model_resolver=resolver,
        transcript_journal=TranscriptJournal(journal.root),
    )
    sink = Sink()
    prompt_id = ulid(82)

    await loop.submit(
        thread_id=thread_id,
        prompt_id=prompt_id,
        prompt="Inspect this",
        image=png_input(),
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)

    refusal = next(
        payload(message)["event"]
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA and payload(message).get("kind") == "event"
    )
    assert refusal == {
        "event_kind": "image_refusal",
        "reason": "unknown",
        "model": hydrated_model,
    }
    usage = next(
        payload(message) for message in sink.messages if message.type is MessageType.RUN_USAGE
    )
    assert usage["requests"] == 0
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage.get("cache_read_tokens", 0) == 0
    assert usage.get("cache_write_tokens", 0) == 0
    done = next(
        payload(message) for message in sink.messages if message.type is MessageType.RUN_DONE
    )
    assert done["stop_reason"] is StopReason.END_TURN
    assert done["partial"] is False
    hydrated = TranscriptJournal(journal.root).hydrate_threads()[0]
    durable_user, durable_assistant = hydrated.messages[-2:]
    assert durable_user["message_id"] == prompt_id
    assert durable_user["state"] == StopReason.END_TURN.value
    assert durable_user["model_visible"] is False
    assert durable_assistant["partial"] is False
    assert durable_assistant["events"] == [refusal]
    attachment_rows = [
        row
        for row in journal.path_for_thread(thread_id).read_text(encoding="utf-8").splitlines()
        if json.loads(row).get("record_type") == "attachment"
        and json.loads(row).get("prompt_id") == prompt_id
    ]
    assert len(attachment_rows) == 1
    assert catalog.named_calls
    assert set(catalog.named_calls) == {"vendor/owner-choice"}
    await loop.close()


@pytest.mark.asyncio
async def test_restarted_text_catalog_outage_keeps_hydrated_model_and_runs(
    tmp_path: Path,
) -> None:
    """A-052 and A-021 are defended by retaining the hydrated owner model during catalog
    outage for text; this prevents image fail-closed behavior from breaking text fail-open.
    """
    thread_id = "thread-1"
    hydrated_model = "openrouter:vendor/owner-choice"
    journal = TranscriptJournal(tmp_path / "transcripts")
    seed_hydrated_model(journal, thread_id=thread_id, model=hydrated_model)
    catalog = OutageCatalog()
    resolver = ModelPolicyResolver(
        policy="pinned:openrouter:vendor/default",
        static_model="openrouter:vendor/default",
        static_context_tokens=64_000,
        catalog=catalog,  # type: ignore[arg-type]
    )
    runner = ResolutionRecordingRunner()
    loop = RunLoop(
        runner,
        factory(Ids(value=1_100)),
        model_resolver=resolver,
        transcript_journal=TranscriptJournal(journal.root),
    )
    sink = Sink()

    await loop.submit(
        thread_id=thread_id,
        prompt_id=ulid(82),
        prompt="Continue with text",
        sink=sink,
    )
    await _wait_for_done_count(sink, 1)

    assert len(runner.resolutions) == 1
    resolution = runner.resolutions[0]
    assert resolution is not None
    assert resolution.model == hydrated_model
    assert resolution.context_tokens == 64_000
    assert resolution.input_modalities is None
    assert resolution.policy == "hydrated_unverified"
    done = next(
        payload(message) for message in sink.messages if message.type is MessageType.RUN_DONE
    )
    assert done["stop_reason"] is StopReason.END_TURN
    assert catalog.named_calls == ["vendor/owner-choice"]
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
    """SPEC C.7 is defended by verifying that usage regression terminalizes as error and stale
    cancel is scoped; this prevents drift in the single authoritative run-loop contract.
    """
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
