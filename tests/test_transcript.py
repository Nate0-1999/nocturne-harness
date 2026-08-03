from __future__ import annotations

import asyncio
import json
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

import harness.transcript as transcript_module
from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    MessageType,
    StopReason,
    ThreadSnapshotResponsePayload,
)
from harness.model_policy import ThreadModelResolution
from harness.run_loop import RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.transcript import TranscriptJournal


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


class RecordingRunner:
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
        await emit.text("durable answer")
        await emit.thinking("durable thought")
        await emit.event({"event_kind": "tool_result", "ok": True})
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, "complete"),
            UsageSnapshot(requests=1, input_tokens=4, output_tokens=2),
            cacheable_prefix_tokens=6,
        )


class BlockingRunner:
    def __init__(self) -> None:
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

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
        if prompt == "first":
            self.first_started.set()
            await self.release_first.wait()
        return TurnOutcome(StopReason.END_TURN, (*message_history, prompt))


class NeverRunner:
    def __init__(self) -> None:
        self.called = False

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, prompt, message_history, emit, model_resolution
        self.called = True
        raise AssertionError("runner must not start after a transcript failure")


class CatchingRunner:
    def __init__(self) -> None:
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.prompts: list[str] = []

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
        self.prompts.append(prompt)
        if prompt == "first":
            self.first_started.set()
            await self.release_first.wait()
            try:
                await emit.text("capture will fail")
            except RuntimeError:
                pass
        return TurnOutcome(StopReason.END_TURN, (*message_history, prompt))


class PromptOrderRunner:
    def __init__(self) -> None:
        self.prompts: list[str] = []

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
        self.prompts.append(prompt)
        return TurnOutcome(StopReason.END_TURN, (*message_history, prompt))


class Resolver:
    def __init__(self) -> None:
        self.initial = ThreadModelResolution(
            model="openrouter:vendor/initial",
            context_tokens=64_000,
            policy="pinned:openrouter:vendor/initial",
        )
        self.changed = ThreadModelResolution(
            model="openrouter:vendor/changed",
            context_tokens=128_000,
            policy="human_command",
        )

    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        del thread_id
        return self.initial

    async def resolve_named(self, thread_id: str, model: str) -> ThreadModelResolution:
        del thread_id
        assert model == self.changed.model
        return self.changed


class FailingResolver(Resolver):
    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        del thread_id
        raise RuntimeError("model resolution failed")


class BlockingFirstResolver(Resolver):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def resolve(self, thread_id: str) -> ThreadModelResolution:
        del thread_id
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            await self.release_first.wait()
        return self.initial


def factory(ids: Ids) -> EnvelopeFactory:
    return EnvelopeFactory(
        machine_id="machine-1",
        agent_id="agent-1",
        id_factory=ids.next,
        clock=lambda: datetime(2026, 8, 2, 12, tzinfo=UTC),
    )


def records(journal: TranscriptJournal, thread_id: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in journal.path_for_thread(thread_id).read_text(encoding="utf-8").splitlines()
    ]


def test_journal_is_private_append_only_and_path_safe(tmp_path: Path) -> None:
    root = tmp_path / "state" / "transcripts"
    thread_id = "../../not-a-path"
    journal = TranscriptJournal(
        root,
        clock=lambda: datetime(2026, 8, 2, 10, tzinfo=UTC),
    )
    message = {
        "message_id": ulid(1),
        "run_id": ulid(2),
        "role": "user",
        "content": "hello λ",
        "state": "queued",
    }
    journal.append_message(thread_id, message, parent_id=None)
    event = factory(Ids()).create(
        MessageType.ERROR,
        {"code": "example"},
        thread_id=thread_id,
    )
    journal.append_event(thread_id, event)

    reopened = TranscriptJournal(root)
    reopened.append_message(thread_id, {**message, "state": "end_turn"}, parent_id=None)

    path = journal.path_for_thread(thread_id)
    rows = records(journal, thread_id)
    assert path.parent == root.resolve()
    assert list(root.glob("*.jsonl")) == [path]
    assert [row["record_type"] for row in rows] == ["message", "event", "message"]
    assert rows[0]["message"]["content"] == "hello λ"  # type: ignore[index]
    assert rows[0]["message"]["parentId"] is None  # type: ignore[index]
    assert rows[1]["event"]["type"] == "error"  # type: ignore[index]
    assert path.read_bytes().endswith(b"\n")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_journal_refuses_a_git_worktree_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    with pytest.raises(ValueError, match="must not live inside a git worktree"):
        TranscriptJournal(tmp_path / "state" / "transcripts")


def test_journal_refuses_a_symlinked_thread_file(tmp_path: Path) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    journal.root.mkdir(parents=True)
    target = tmp_path / "target.txt"
    target.write_text("do not touch", encoding="utf-8")
    journal.path_for_thread("thread-1").symlink_to(target)

    with pytest.raises(ValueError, match="must be a regular file"):
        journal.append_message(
            "thread-1",
            {"message_id": ulid(1), "role": "user"},
            parent_id=None,
        )

    assert target.read_text(encoding="utf-8") == "do not touch"


def test_journal_refuses_root_replaced_by_a_directory_symlink(tmp_path: Path) -> None:
    root = tmp_path / "transcripts"
    journal = TranscriptJournal(root)
    target = tmp_path / "target-worktree"
    (target / ".git").mkdir(parents=True)
    root.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="root must be a real directory"):
        journal.append_message(
            "thread-1",
            {"message_id": ulid(1), "role": "user"},
            parent_id=None,
        )

    assert list(target.glob("*.jsonl")) == []


def test_failed_partial_append_is_rolled_back(tmp_path: Path, monkeypatch) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    real_write = transcript_module.os.write
    calls = 0

    def fail_after_partial(descriptor: int, value: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, value[: max(1, len(value) // 2)])
        raise OSError("disk full")

    monkeypatch.setattr(transcript_module.os, "write", fail_after_partial)
    with pytest.raises(OSError, match="disk full"):
        journal.append_message(
            "thread-1",
            {"message_id": ulid(1), "role": "user"},
            parent_id=None,
        )
    monkeypatch.setattr(transcript_module.os, "write", real_write)

    path = journal.path_for_thread("thread-1")
    assert path.read_bytes() == b""
    journal.append_message(
        "thread-1",
        {"message_id": ulid(1), "role": "user"},
        parent_id=None,
    )
    assert len(records(journal, "thread-1")) == 1


def test_preexisting_incomplete_tail_is_separated_from_new_records(tmp_path: Path) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    journal.root.mkdir(parents=True)
    path = journal.path_for_thread("thread-1")
    path.write_bytes(b'{"incomplete":')

    journal.append_message(
        "thread-1",
        {"message_id": ulid(1), "role": "user"},
        parent_id=None,
    )

    lines = path.read_bytes().splitlines()
    assert lines[0] == b'{"incomplete":'
    assert json.loads(lines[1])["record_type"] == "message"


def test_restart_scans_past_an_incomplete_tail_to_the_last_valid_message(
    tmp_path: Path,
) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    journal.append_message(
        "thread-1",
        {"message_id": ulid(1), "role": "user"},
        parent_id=None,
    )
    path = journal.path_for_thread("thread-1")
    with path.open("ab") as transcript:
        transcript.write(b'{"incomplete":')

    reopened = TranscriptJournal(journal.root)

    assert reopened.next_parent_id("thread-1") == ulid(1)


def test_non_tail_revisions_do_not_move_restart_continuity_backward(tmp_path: Path) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    for number in range(1, 5):
        journal.append_message(
            "thread-1",
            {"message_id": ulid(number), "role": "user"},
            parent_id=ulid(number - 1) if number > 1 else None,
        )
    journal.append_message(
        "thread-1",
        {"message_id": ulid(100), "role": "assistant"},
        parent_id=ulid(2),
        advance_tail=False,
    )
    journal.append_message(
        "thread-1",
        {"message_id": ulid(3), "role": "user"},
        parent_id=ulid(100),
        advance_tail=False,
    )

    assert journal.next_parent_id("thread-1") == ulid(4)
    assert TranscriptJournal(journal.root).next_parent_id("thread-1") == ulid(4)
    assert records(journal, "thread-1")[-1]["tail_message_id"] == ulid(4)


def test_complete_record_is_fsynced_before_append_returns(tmp_path: Path, monkeypatch) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    real_fsync = transcript_module.os.fsync
    synced: list[int] = []

    def recording_fsync(descriptor: int) -> None:
        synced.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(transcript_module.os, "fsync", recording_fsync)
    journal.append_message(
        "thread-1",
        {"message_id": ulid(1), "role": "user"},
        parent_id=None,
    )

    assert synced


@pytest.mark.asyncio
async def test_prompt_is_captured_before_model_resolution_failure(tmp_path: Path) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    loop = RunLoop(
        RecordingRunner(),
        factory(Ids()),
        model_resolver=FailingResolver(),
        transcript_journal=journal,
    )

    with pytest.raises(RuntimeError, match="model resolution failed"):
        await loop.submit(
            thread_id="thread-1",
            prompt_id=ulid(1),
            prompt="persist me first",
        )

    rows = records(journal, "thread-1")
    assert len(rows) == 1
    assert rows[0]["record_type"] == "message"
    assert rows[0]["message"]["content"] == "persist me first"  # type: ignore[index]
    await loop.close()


@pytest.mark.asyncio
async def test_capture_failure_poison_stops_unjournaled_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")

    def fail_event(thread_id: str, envelope: Envelope) -> None:
        del thread_id, envelope
        raise OSError("read-only filesystem")

    monkeypatch.setattr(journal, "append_event", fail_event)
    runner = NeverRunner()
    loop = RunLoop(runner, factory(Ids()), transcript_journal=journal)
    sink = Sink()

    with pytest.raises(RuntimeError, match="transcript capture failed"):
        await loop.submit(
            thread_id="thread-1",
            prompt_id=ulid(1),
            prompt="first",
            sink=sink,
        )
    with pytest.raises(RuntimeError, match="unavailable after transcript capture failure"):
        await loop.submit(
            thread_id="thread-1",
            prompt_id=ulid(2),
            prompt="must not queue",
        )

    assert runner.called is False
    assert sink.messages == []
    await loop.close()


@pytest.mark.asyncio
async def test_in_run_capture_poison_cannot_be_caught_to_start_queued_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    append_event = journal.append_event
    failed = False

    def fail_first_delta(thread_id: str, envelope: Envelope) -> None:
        nonlocal failed
        if not failed and envelope.type is MessageType.RUN_DELTA:
            failed = True
            raise OSError("transient disk failure")
        append_event(thread_id, envelope)

    monkeypatch.setattr(journal, "append_event", fail_first_delta)
    runner = CatchingRunner()
    sink = Sink()
    loop = RunLoop(runner, factory(Ids()), transcript_journal=journal)
    await loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt="first", sink=sink)
    await asyncio.wait_for(runner.first_started.wait(), 1)
    await loop.submit(thread_id="thread-1", prompt_id=ulid(2), prompt="second", sink=sink)

    runner.release_first.set()
    for _ in range(100):
        if loop._capture_failure is not None:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("capture failure did not poison the run loop")
    for _ in range(10):
        await asyncio.sleep(0)

    assert runner.prompts == ["first"]
    assert all(
        message.payload.kind != "text"
        for message in sink.messages
        if message.type is MessageType.RUN_DELTA
    )  # type: ignore[union-attr]
    with pytest.raises(RuntimeError, match="unavailable after transcript capture failure"):
        await loop.submit(thread_id="thread-1", prompt_id=ulid(3), prompt="third")
    await loop.close()


@pytest.mark.asyncio
async def test_same_thread_resolution_is_serialized_in_capture_order(tmp_path: Path) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    resolver = BlockingFirstResolver()
    runner = PromptOrderRunner()
    loop = RunLoop(
        runner,
        factory(Ids()),
        model_resolver=resolver,
        transcript_journal=journal,
    )

    first = asyncio.create_task(
        loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt="first")
    )
    await asyncio.wait_for(resolver.first_started.wait(), 1)
    second = asyncio.create_task(
        loop.submit(thread_id="thread-1", prompt_id=ulid(2), prompt="second")
    )
    for _ in range(10):
        await asyncio.sleep(0)

    captured = [
        row["message"] for row in records(journal, "thread-1") if row["record_type"] == "message"
    ]
    assert [message["message_id"] for message in captured] == [ulid(1), ulid(2)]
    assert captured[1]["parentId"] == ulid(1)  # type: ignore[index]
    assert resolver.calls == 1

    resolver.release_first.set()
    first_run, _ = await asyncio.gather(first, second)
    for _ in range(100):
        final_rows = records(journal, "thread-1")
        done_count = sum(
            row["record_type"] == "event" and row["event"]["type"] == "run.done"  # type: ignore[index]
            for row in final_rows
        )
        if runner.prompts == ["first", "second"] and done_count == 2:
            break
        await asyncio.sleep(0)
    assert runner.prompts == ["first", "second"]
    second_versions = [
        row["message"]
        for row in final_rows
        if row["record_type"] == "message" and row["message"]["message_id"] == ulid(2)  # type: ignore[index]
    ]
    assert second_versions[-1]["parentId"] == first_run  # type: ignore[index]
    await loop.close()


@pytest.mark.asyncio
async def test_fifo_capture_has_no_dangling_parent_links(tmp_path: Path) -> None:
    journal = TranscriptJournal(tmp_path / "transcripts")
    runner = BlockingRunner()
    loop = RunLoop(runner, factory(Ids()), transcript_journal=journal)

    first_run = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(1),
        prompt="first",
    )
    await asyncio.wait_for(runner.first_started.wait(), 1)
    second_run = await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(2),
        prompt="second",
    )
    await loop.submit(
        thread_id="thread-1",
        prompt_id=ulid(3),
        prompt="third",
    )

    before_release = records(journal, "thread-1")
    messages = [row["message"] for row in before_release if row["record_type"] == "message"]
    second = [message for message in messages if message["message_id"] == ulid(2)]
    third = [message for message in messages if message["message_id"] == ulid(3)]
    assert {message["parentId"] for message in second} == {first_run}
    assert {message["parentId"] for message in third} == {ulid(2)}
    captured_ids = {message["message_id"] for message in messages}
    assert all(
        message["parentId"] is None or message["parentId"] in captured_ids for message in messages
    )

    runner.release_first.set()
    for _ in range(100):
        after_release = records(journal, "thread-1")
        if (
            sum(
                row["record_type"] == "event" and row["event"]["type"] == "run.done"  # type: ignore[index]
                for row in after_release
            )
            == 3
        ):
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("queued runs did not finish")
    final_third = [
        row["message"]
        for row in after_release
        if row["record_type"] == "message" and row["message"]["message_id"] == ulid(3)  # type: ignore[index]
    ]
    assert final_third[-1]["parentId"] == second_run  # type: ignore[index]
    await loop.close()


@pytest.mark.asyncio
async def test_capture_does_not_depend_on_a_live_subscriber(tmp_path: Path) -> None:
    thread_id = "detached-thread"
    journal = TranscriptJournal(tmp_path / "transcripts")
    loop = RunLoop(
        RecordingRunner(),
        factory(Ids()),
        transcript_journal=journal,
    )

    await loop.submit(
        thread_id=thread_id,
        prompt_id=ulid(1),
        prompt="continue while detached",
    )
    for _ in range(100):
        rows = records(journal, thread_id)
        if any(
            row["record_type"] == "event" and row["event"]["type"] == "run.done"  # type: ignore[index]
            for row in rows
        ):
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("detached run was not durably terminalized")

    assert any(row["record_type"] == "message" for row in rows)
    assert any(
        row["record_type"] == "event" and row["event"]["type"] == "run.delta"  # type: ignore[index]
        for row in rows
    )
    await loop.close()


@pytest.mark.asyncio
async def test_run_loop_captures_messages_events_model_change_without_serving_on_restart(
    tmp_path: Path,
) -> None:
    thread_id = "thread/with/path-separators"
    prompt_id = ulid(1)
    command_prompt_id = ulid(2)
    ids = Ids()
    journal = TranscriptJournal(
        tmp_path / "transcripts",
        clock=lambda: datetime(2026, 8, 2, 11, tzinfo=UTC),
    )
    resolver = Resolver()
    loop = RunLoop(
        RecordingRunner(),
        factory(ids),
        model_resolver=resolver,
        clock=lambda: datetime(2026, 8, 2, 11, 30, tzinfo=UTC),
        transcript_journal=journal,
    )
    sink = Sink()

    first_run = await loop.submit(
        thread_id=thread_id,
        prompt_id=prompt_id,
        prompt="hello",
        sink=sink,
    )
    await wait_for_done(sink, 1)
    command_run = await loop.submit(
        thread_id=thread_id,
        prompt_id=command_prompt_id,
        prompt=f"/model {resolver.changed.model}",
        sink=sink,
    )
    await wait_for_done(sink, 2)
    await loop.close()

    rows = records(journal, thread_id)
    message_rows = [row for row in rows if row["record_type"] == "message"]
    event_rows = [row for row in rows if row["record_type"] == "event"]
    assert message_rows
    assert all("parentId" in row["message"] for row in message_rows)  # type: ignore[operator]
    assert all(row["thread_id"] == thread_id for row in rows)
    assert {row["version"] for row in rows} == {1}

    by_message: dict[str, list[dict[str, object]]] = {}
    for row in message_rows:
        message = row["message"]
        assert isinstance(message, dict)
        by_message.setdefault(str(message["message_id"]), []).append(message)
    assert {message["parentId"] for message in by_message[prompt_id]} == {None}
    assert {message["parentId"] for message in by_message[first_run]} == {prompt_id}
    assert {message["parentId"] for message in by_message[command_prompt_id]} == {first_run}
    assert {message["parentId"] for message in by_message[command_run]} == {command_prompt_id}
    assert by_message[first_run][-1]["content"] == "durable answer"
    assert by_message[first_run][-1]["thinking"] == "durable thought"
    assert by_message[first_run][-1]["partial"] is False

    event_types = [row["event"]["type"] for row in event_rows]  # type: ignore[index]
    assert [row["event"]["id"] for row in event_rows] == [  # type: ignore[index]
        message.id for message in sink.messages
    ]
    assert "run.started" in event_types
    assert "run.usage" in event_types
    assert event_types.count("run.done") == 2
    nested_events = [
        row["event"]["payload"]["event"]  # type: ignore[index]
        for row in event_rows
        if row["event"]["type"] == "run.delta"  # type: ignore[index]
        and row["event"]["payload"]["kind"] == "event"  # type: ignore[index]
    ]
    assert {event["event_kind"] for event in nested_events} == {
        "tool_result",
        "model_change",
    }
    delta_kinds = {
        row["event"]["payload"]["kind"]  # type: ignore[index]
        for row in event_rows
        if row["event"]["type"] == "run.delta"  # type: ignore[index]
    }
    assert delta_kinds == {"text", "thinking", "event"}

    restarted = RunLoop(
        RecordingRunner(),
        factory(Ids(value=500)),
        model_resolver=Resolver(),
        transcript_journal=TranscriptJournal(journal.root),
    )
    restart_sink = Sink()
    before_snapshot = journal.path_for_thread(thread_id).read_bytes()
    await restarted.request_snapshot(thread_id, restart_sink)
    await wait_for_type(restart_sink, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = restart_sink.messages[0].payload
    assert isinstance(snapshot, ThreadSnapshotResponsePayload)
    assert snapshot.messages == []
    assert snapshot.active_run is None
    assert journal.path_for_thread(thread_id).read_bytes() == before_snapshot

    await restarted.submit(
        thread_id=thread_id,
        prompt_id=ulid(3),
        prompt="after restart",
        sink=restart_sink,
    )
    await wait_for_done(restart_sink, 1)
    restarted_rows = records(journal, thread_id)
    continued = [
        row["message"]
        for row in restarted_rows
        if row["record_type"] == "message" and row["message"]["message_id"] == ulid(3)  # type: ignore[index]
    ]
    assert {message["parentId"] for message in continued} == {command_run}  # type: ignore[index]
    await restarted.close()


async def wait_for_done(sink: Sink, count: int) -> None:
    await wait_for_type(sink, MessageType.RUN_DONE, count)


async def wait_for_type(sink: Sink, message_type: MessageType, count: int) -> None:
    for _ in range(100):
        if sum(message.type is message_type for message in sink.messages) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} {message_type} messages")
