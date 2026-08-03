from __future__ import annotations

import asyncio
import json
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.envelope import Envelope, EnvelopeFactory, MessageType, StopReason
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

    restarted = RunLoop(
        RecordingRunner(),
        factory(Ids(value=500)),
        model_resolver=Resolver(),
        transcript_journal=TranscriptJournal(journal.root),
    )
    restart_sink = Sink()
    await restarted.request_snapshot(thread_id, restart_sink)
    await wait_for_type(restart_sink, MessageType.THREAD_SNAPSHOT, 1)
    snapshot = restart_sink.messages[0].payload
    assert snapshot.messages == []  # type: ignore[union-attr]
    assert snapshot.active_run is None  # type: ignore[union-attr]
    await restarted.close()


async def wait_for_done(sink: Sink, count: int) -> None:
    await wait_for_type(sink, MessageType.RUN_DONE, count)


async def wait_for_type(sink: Sink, message_type: MessageType, count: int) -> None:
    for _ in range(100):
        if sum(message.type is message_type for message in sink.messages) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} {message_type} messages")
