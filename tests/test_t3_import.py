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


def test_reopening_an_imported_thread_reads_memory_scores_without_embedding(tmp_path):
    """A-095, SD-130: opening an adopted conversation with visible memories must cost nothing."""
    from fastapi.testclient import TestClient
    from test_daemon import PanelGateSpine, fixture_resolver, frame, receive_until

    from harness.config import HarnessSettings
    from harness.daemon import create_dev_app

    tid = str(uuid4())
    journal = TranscriptJournal(tmp_path / "transcripts")
    binding = {
        "native_session": str(uuid4()),
        "source": "subscription:codex/fixture",
        "location": str(tmp_path),
    }
    spine = PanelGateSpine()
    spine.restore_injection = AsyncMock(return_value=None)
    settings = HarnessSettings(
        nocturne_home=tmp_path, model_context_tokens=8192, principal_id="principal-test"
    )
    app = create_dev_app(
        tmp_path,
        settings=settings,
        spine=spine,
        transcript_journal=journal,
        model_resolver_override=fixture_resolver(settings),
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        journal.adopt_subscription(tid, binding, str(tmp_path), "Old", [])
        for previous in (None, SimpleNamespace(injected=spine.cards, near_misses=[])):
            spine.restore_injection.return_value = (
                SimpleNamespace(prepared=previous) if previous else None
            )
            socket.send_json(frame("memory.panel.update", {"action": "refresh"}, thread_id=tid))
            panel, _ = receive_until(socket, "memory.panel.update")
            assert [item["score"] for item in panel["payload"]["items"]] == [
                card.score if previous else None for card in spine.cards
            ]
    assert not spine.score_requests


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
    assert all(m["message_id"] == m["run_id"] for m in messages if m["role"] == "assistant")
    # Exercise a journal written by the first M8TN build as well as the current importer.
    messages[-1]["run_id"] = messages[0]["run_id"]
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
    assert all(
        m["message_id"] == m["run_id"] for m in transcript.messages if m["role"] == "assistant"
    )
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
@pytest.mark.parametrize(
    ("tool", "variable"), [("codex", "CODEX_HOME"), ("claudeAgent", "CLAUDE_CONFIG_DIR")]
)
async def test_original_session_uses_the_scanners_provider_home(
    tmp_path, monkeypatch, tool, variable
):
    """A-095, SD-130: a session T3 can find in a nondefault home must resume there."""
    import hashlib

    from harness.t3_client import T3Client
    from harness.t3_server import T3Server

    sid = str(uuid4())
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(variable, str(tmp_path / "from-environment"))
    server = T3Server(tmp_path / "nocturne")
    settings = {
        "providerInstances": {
            "codex": {"config": {"binaryPath": "codex"}},
            "claudeAgent": {"config": {}},
        }
    }
    monkeypatch.setattr(T3Client, "authenticate", AsyncMock())
    client = await server._authenticate(23001, settings, server._home_environment(), "")
    monkeypatch.setattr(server, "client", AsyncMock(return_value=client))
    projection = {"thread": {"activeProviderThreadId": sid, "runtimeMode": "approval-required"}}
    client.call = AsyncMock(
        side_effect=lambda method, _: settings if method == "server.getSettings" else projection
    )
    monkeypatch.setattr("harness.t3_import.resolve_offer", AsyncMock())
    binding = dict(
        tool=tool,
        native_session=sid,
        source="fixture",
        native_thread=sid,
        provider_thread=sid,
        location=str(tmp_path),
        environment=hashlib.sha256(b"").hexdigest(),
    )
    relative = (
        Path("sessions/2026/11/28", f"rollout-test-{sid}.jsonl.zst")
        if tool == "codex"
        else Path("projects/proof", f"{sid}.jsonl")
    )
    for name in ("from-environment", "from-instance", "configured"):
        instance = settings["providerInstances"][tool]
        if name == "from-instance":
            instance["environment"] = [{"name": variable, "value": "~/" + name}]
        elif name == "configured":
            instance["config"]["homePath"] = "~/" + name
        with pytest.raises(T3Error, match="session is missing"):
            await check_original(server, binding, str(tmp_path))
        session = tmp_path / name / relative
        session.parent.mkdir(parents=True)
        session.touch()
        await check_original(server, binding, str(tmp_path))


@pytest.mark.asyncio
async def test_archive_extracts_only_the_turns_written_after_adoption(tmp_path):
    """A-095, SD-130: an archive or idle pass cannot send imported history for extraction."""
    import json

    from test_extraction import FakeAgent, FakeSpine

    from harness.extraction import ExtractionService

    tid = uuid4()
    journal = TranscriptJournal(tmp_path / "journal")
    old = history(
        [
            dict(type=role + "_message", text=text, runId=None, startedAt="2026-11-28T00:00:00Z")
            for role, text in (("user", "Old question"), ("assistant", "Old reply"))
        ]
    )
    journal.adopt_subscription(
        str(tid),
        {"location": str(tmp_path), "source": "fixture"},
        str(tmp_path),
        "Old conversation",
        old,
    )
    agent, spine = FakeAgent(), FakeSpine()
    service = ExtractionService(
        journal=journal, agent=agent, spine=spine, principal_id="fixture", machine_id="fixture"
    )
    result = await service.archive(tid)
    assert result.final_post == "Old reply" and not result.cards
    assert not agent.calls and not spine.requests
    journal.append_message(
        str(tid),
        {"role": "user", "message_id": "01K1M2A0000000000000000001", "content": "New question"},
        parent_id=old[-1]["message_id"],
    )
    await service.archive(tid)
    assert [[m["content"] for m in json.loads(call)] for call in agent.calls] == [["New question"]]
    assert len(journal.read_messages(str(tid))) == 3


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
        call=AsyncMock(return_value={"providerInstances": {}}),
        dispatch=AsyncMock(),
    )
    server = SimpleNamespace(root=tmp_path, client=AsyncMock(return_value=client))
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
    assert all(c.args == ("server.getSettings", {}) for c in client.call.await_args_list)
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
