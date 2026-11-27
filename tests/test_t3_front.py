from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from harness.t3_front_session import FrontSession
from harness.transcript import TranscriptJournal


@pytest.mark.asyncio
async def test_new_window_pairs_with_only_the_permissions_needed_to_chat(tmp_path, monkeypatch):
    """P2.5 / SD-128: a paired window must not act on owner files outside the wall."""
    from harness.t3_front import FrontServer

    front = FrontServer(tmp_path, None, None, tmp_path)
    client = SimpleNamespace(
        origin="http://127.0.0.1",
        session="fixture",
        call=AsyncMock(return_value={"providers": [{"instanceId": "nocturne", "enabled": True}]}),
    )
    monkeypatch.setattr(front, "client", AsyncMock(return_value=client))
    pairing = AsyncMock(return_value=httpx.Response(200, json={"credential": "fixture"}))
    monkeypatch.setattr(httpx.AsyncClient, "post", pairing)
    try:
        await front.browser_url()
        pairing.assert_awaited_once()
        grant = pairing.await_args.kwargs["json"]["scopes"]
        assert set(grant) == {"orchestration:read", "orchestration:operate"}
    finally:
        await front.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected", [("Earlier", "end_turn"), ("Changed", "error")])
async def test_retry_of_mirrored_message_never_runs_or_bills_the_prompt_again(
    tmp_path, text, expected
):
    """P4 / SD-114: a retried cross-window history copy cannot submit a second paid turn."""
    journal = TranscriptJournal(tmp_path)
    journal.append_message(
        "thread",
        {
            "role": "user",
            "message_id": "prompt",
            "content": "Earlier",
            "state": "end_turn",
            "run_id": "run",
        },
        parent_id=None,
    )
    journal.append_message(
        "thread",
        {
            "role": "assistant",
            "message_id": "answer",
            "content": "Settled",
            "partial": False,
            "run_id": "run",
        },
        parent_id="prompt",
    )
    message_id = "nocturne-journal-prompt"
    client = SimpleNamespace(
        call=AsyncMock(
            return_value={
                "runs": [
                    {
                        "status": "running",
                        "providerInstanceId": "nocturne",
                        "userMessageId": message_id,
                    }
                ],
                "messages": [{"id": message_id, "role": "user", "text": text}],
            }
        )
    )
    loop = AsyncMock()
    session = FrontSession(
        SimpleNamespace(client=AsyncMock(return_value=client), loop=loop, journal=journal),
        "thread",
        None,
        None,
    )
    session.session, session.cwd = "thread", tmp_path
    session.send, session.text = AsyncMock(), AsyncMock()
    await session.prompt(7, [{"type": "text", "text": text}])
    loop.submit.assert_not_awaited()
    loop.request_snapshot.assert_not_awaited()
    if expected == "end_turn":
        session.text.assert_awaited_once_with("Settled")
        session.send.assert_awaited_once_with(id=7, result={"stopReason": "end_turn"})
    else:
        assert "error" in session.send.await_args.kwargs
        session.text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("keep", [0, 1])
async def test_rewind_marks_front_list_once_and_waits_for_a_journal_change(tmp_path, keep):
    """P4 / SD-114: a stale window must identify itself and stop fetching an abandoned branch."""
    from harness.t3_front import OUT_OF_STEP, FrontServer

    journal = TranscriptJournal(tmp_path)
    parent = None
    for index in range(2):
        for role in ("user", "assistant"):
            message_id = f"{role}-{index}"
            journal.append_message(
                "thread",
                dict(
                    role=role,
                    message_id=message_id,
                    content=message_id,
                    state="end_turn",
                    run_id=f"run-{index}",
                ),
                parent_id=parent,
            )
            parent = message_id
    journal.bind_front_window("thread", "env")
    journal.rewind("thread", "assistant-0" if keep else None)
    projection = dict(
        thread={"title": "My conversation"},
        runs=[],
        messages=[{"role": "user", "text": f"user-{i}"} for i in range(2)],
    )
    client = SimpleNamespace(
        environment_id="env",
        call=AsyncMock(return_value=projection),
        orchestration_get=AsyncMock(
            return_value={
                "items": [{"item": {"type": "user_message", "text": f"user-{i}"}} for i in range(2)]
            }
        ),
        dispatch=AsyncMock(),
    )
    front = FrontServer(tmp_path, None, journal, tmp_path)
    row = journal.catalog()[0]
    assert await front.sync_thread(client, row)
    client.dispatch.assert_awaited_once_with(
        "thread", "thread.metadata.update", title=OUT_OF_STEP + "My conversation"
    )
    projection["thread"]["title"] = OUT_OF_STEP + "My conversation"
    assert await front.sync_thread(client, row)
    client.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_continues_from_full_transcript_when_projection_drops_old_turns(tmp_path):
    """P4 / SD-114: a short projection must not skip or duplicate a journal prompt."""
    from harness.t3_front import FrontServer

    users = [
        dict(role="user", message_id=str(i), content=f"Prompt {i}", state="end_turn")
        for i in range(12)
    ]
    history = SimpleNamespace(messages=[*users, {"role": "assistant"}])
    journal = SimpleNamespace(current_thread=lambda _: history, front_thread=lambda *_: "thread")
    previous = [dict(role="user", text=m["content"]) for m in users[:-1]]
    client = SimpleNamespace(
        environment_id="env",
        call=AsyncMock(
            return_value=dict(thread={"title": "Long conversation"}, runs=[], messages=previous[1:])
        ),
        orchestration_get=AsyncMock(
            return_value={
                "items": [{"item": {"type": "user_message", "text": m["text"]}} for m in previous]
            }
        ),
        message=AsyncMock(),
        dispatch=AsyncMock(),
    )
    front = FrontServer(tmp_path, None, journal, tmp_path)
    assert not await front.sync_thread(client, SimpleNamespace(thread_id="thread"))
    client.dispatch.assert_not_awaited()
    client.message.assert_awaited_once_with(
        "thread", "nocturne-journal-11", "Prompt 11", {"instanceId": "nocturne", "model": "default"}
    )
