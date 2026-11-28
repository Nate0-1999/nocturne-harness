import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from harness.run_loop import RunLoop
from harness.t3_client import T3Error
from harness.t3_import import check_original, history
from harness.transcript import TranscriptJournal


def test_raced_and_restarted_adoptions_keep_only_visible_history(tmp_path):
    """A-095, SD-130: reopening cannot resend a prompt, grant permission or book a turn."""
    tid = str(uuid4())
    items = [
        dict(
            type=kind,
            text=text,
            message=text,
            ordinal=index,
            runId=None,
            startedAt="2026-11-28T00:00:00Z",
        )
        for index, (kind, text) in enumerate(
            [
                ("system_notice", "Earlier messages were omitted."),
                ("user_message", "Old prompt"),
                ("runtime_request", "allowed_thread"),
                ("assistant_message", "Old reply"),
            ]
        )
    ]
    messages = history(items)
    binding = {
        "source": "subscription:codex/example/fixture",
        "location": str(tmp_path),
        "native_session": str(uuid4()),
    }
    root = tmp_path / "journal"

    def adopt(_):
        return TranscriptJournal(root).adopt_subscription(
            tid, binding, str(tmp_path), "A title", messages
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(adopt, range(8))) == 1
    restarted = TranscriptJournal(root)
    path = restarted.path_for_thread(tid)
    before = path.read_bytes()
    assert not adopt(None) and path.read_bytes() == before
    transcript = restarted.current_thread(tid)
    assert transcript.conversation_title() == "A title"
    assert [m["content"] for m in transcript.messages] == [
        "Earlier messages were omitted.",
        "Old prompt",
        "Old reply",
    ]
    assert RunLoop._rehydrate_model_history(transcript) == ()
    assert "permission" not in restarted.subscription_binding(tid)
    assert b"allowed_thread" not in before and b"subscription.turn" not in before


@pytest.mark.asyncio
async def test_first_new_prompt_waits_for_review_after_an_import(tmp_path):
    """A-095, SD-130: the first new prompt must pause before any provider receives it."""
    from test_memory_gate import (
        THREAD_ID,
        RecordingDelegate,
        RecordingEmitter,
        RecordingSpine,
        context_factory,
        decision,
    )

    from harness.memory_gate import MemoryGateTurnRunner

    journal = TranscriptJournal(tmp_path / "journal")
    messages = history(
        [
            dict(
                type="user_message",
                text="Before adoption",
                runId=None,
                startedAt="2026-11-28T00:00:00Z",
            )
        ]
    )
    journal.adopt_subscription(
        THREAD_ID,
        {"location": str(tmp_path), "source": "subscription:codex/fixture"},
        str(tmp_path),
        "Old conversation",
        messages,
    )
    history_for_model = RunLoop._rehydrate_model_history(journal.current_thread(THREAD_ID))
    spine, delegate, emitter = RecordingSpine(), RecordingDelegate(), RecordingEmitter()
    runner = MemoryGateTurnRunner(
        delegate, spine, context_factory(spine), model_context_tokens=8192
    )
    turn = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="First new question",
            message_history=history_for_model,
            emit=emitter,
        )
    )
    await asyncio.wait_for(emitter.opened.wait(), 1)
    assert not delegate.calls and spine.prepare_requests[0].prompt == "First new question"
    emitter.decision.set_result(decision())
    await asyncio.wait_for(turn, 1)
    assert [(c[1], c[2]) for c in delegate.calls] == [("First new question", ())]


@pytest.mark.asyncio
async def test_missing_session_moved_directory_and_unavailable_model_stop_before_dispatch(
    tmp_path, monkeypatch
):
    """A-095, SD-130: a broken binding cannot redirect a new message to another session."""
    import hashlib

    sid = str(uuid4())
    client = SimpleNamespace(
        environment_id="fixture",
        native_env={"HOME": str(tmp_path)},
        call=AsyncMock(),
        dispatch=AsyncMock(),
    )
    server = SimpleNamespace(client=AsyncMock(return_value=client))
    binding = dict(
        tool="claudeAgent",
        native_session=sid,
        location=str(tmp_path),
        source="subscription:claudeAgent/fixture/model",
        native_thread="fixture",
        environment=hashlib.sha256(b"fixture").hexdigest(),
    )
    with pytest.raises(T3Error, match="folder has moved"):
        await check_original(server, binding, str(tmp_path / "moved"))
    server.client.assert_not_awaited()
    with pytest.raises(T3Error, match="session is missing"):
        await check_original(server, binding, str(tmp_path))
    session = Path(tmp_path, ".claude", "projects", "fixture", sid + ".jsonl")
    session.parent.mkdir(parents=True)
    session.touch()
    monkeypatch.setattr(
        "harness.t3_import.resolve_offer", AsyncMock(side_effect=T3Error("model unavailable"))
    )
    with pytest.raises(T3Error, match="model unavailable"):
        await check_original(server, binding, str(tmp_path))
    client.call.assert_not_awaited()
    client.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_imported_codex_resumes_once_without_replaying_or_archiving(tmp_path, monkeypatch):
    """A-095, SD-130: continuing a native session must preserve the owner's history."""
    import hashlib

    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from harness.model_policy import ThreadModelResolution
    from harness.t3_turn import NativeTurn, SubscriptionTurns

    key = "subscription:codex/account/fixture"
    resolution = ThreadModelResolution(
        model=key, policy="pinned", price_sorted=False, context_tokens=8192
    )
    binding = dict(
        source=key,
        environment=hashlib.sha256(b"local").hexdigest(),
        location=str(tmp_path),
        native_thread="imported-id",
        native_session=str(uuid4()),
    )
    journal = TranscriptJournal(tmp_path / "journal")
    journal.bind_subscription("imported", binding)
    projection = dict(thread={"archivedAt": None}, runs=[])
    client = SimpleNamespace(
        environment_id="local",
        call=AsyncMock(return_value=projection),
        message=AsyncMock(return_value={"sequence": 1}),
        launch=AsyncMock(),
        archive_codex=AsyncMock(),
    )
    server = SimpleNamespace(client=AsyncMock(return_value=client))
    monkeypatch.setattr(
        "harness.t3_turn.resolve_offer",
        AsyncMock(return_value=(key, {"tool": "codex", "name": "Codex"}, {"id": "fixture"})),
    )

    async def completed(observer, after):
        observer.answer = "New answer"
        observer.transitions.finished = True
        return "completed"

    monkeypatch.setattr(NativeTurn, "observe", completed)
    await SubscriptionTurns(None, server, journal, lambda _: tmp_path).run(
        thread_id="imported",
        prompt="New question",
        message_history=(ModelRequest(parts=[UserPromptPart("Old question")]),),
        emit=AsyncMock(),
        model_resolution=resolution,
    )
    assert client.message.await_args.args[0] == "imported-id"
    assert client.message.await_args.args[2] == "New question"
    client.launch.assert_not_awaited()
    client.archive_codex.assert_not_awaited()
