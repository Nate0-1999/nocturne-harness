from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness.t3_front_session import FrontSession
from harness.transcript import TranscriptJournal


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rewind", "archive", "fork", "clear"])
async def test_a_stale_window_cannot_start_work_or_reopen_the_journal(tmp_path, change):
    """FL-076 / FL-124 / SD-128: a restart cannot turn a stale window into an accepted prompt."""
    journal = TranscriptJournal(tmp_path)
    earlier = journal.bind_front_prompt("thread", "env", "native", "m1")
    journal.append_message(
        "thread", dict(role="user", message_id=earlier, content="old"), parent_id=None
    )
    if change == "archive":
        journal.append_archive("thread")
    if change == "rewind":
        journal.rewind("thread", None)
    items = [{"item": {"type": "user_message", "messageId": key}} for key in ("m1", "m2")]
    run = dict(
        id="paid",
        status="running",
        providerInstanceId="nocturne",
        userMessageId="m2",
        freshContext=change == "clear",
    )
    projection = dict(
        thread={"forkedFrom": {"type": "run"} if change == "fork" else None},
        runs=[run],
        messages=[{"role": "user", "id": "m2", "text": "next"}],
    )
    client = SimpleNamespace(
        environment_id="env",
        call=AsyncMock(return_value=projection),
        orchestration_get=AsyncMock(return_value={"items": items}),
    )
    loop = AsyncMock()
    loop.request_snapshot.side_effect = AssertionError("stale thread selected")
    session = FrontSession(
        SimpleNamespace(journal=journal, loop=loop, client=AsyncMock(return_value=client)),
        "native",
        None,
        None,
    )
    session.session, session.cwd = "thread", tmp_path
    session.send, session.text = AsyncMock(), AsyncMock()
    before = journal.path_for_thread("thread").read_bytes()
    await session.prompt(7, [{"type": "text", "text": "next"}])
    loop.request_snapshot.assert_not_awaited()
    loop.submit.assert_not_awaited()
    session.text.assert_awaited_once()
    assert "Nocturne" in session.text.await_args.args[0]
    assert journal.path_for_thread("thread").read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,should_cancel", [("steering_restart", False), ("retry", True)])
async def test_window_cancel_preserves_work_only_for_its_own_steering_restart(
    reason, should_cancel
):
    """FL-075: a second message keeps the original task; an explicit Stop still stops it."""
    import asyncio

    projection = {
        "runs": [{"id": "native-run", "activeAttemptId": "next", "rootNodeId": "next-node"}],
        "attempts": [
            {
                "id": "first",
                "runId": "native-run",
                "rootNodeId": "old-node",
                "status": "superseded",
            },
            {"id": "next", "runId": "native-run", "reason": reason},
        ],
    }
    front = SimpleNamespace(
        loop=AsyncMock(),
        client=AsyncMock(return_value=SimpleNamespace(call=AsyncMock(return_value=projection))),
    )
    session = FrontSession(front, "native-thread", None, None)
    session.thread, session.run = "thread", "journal-run"
    session.native_run, session.node = "native-run", "old-node"
    session.events = asyncio.Queue()
    await session.window_cancel()
    if should_cancel:
        front.loop.cancel.assert_awaited_once_with(thread_id="thread", run_id="journal-run")
    else:
        front.loop.cancel.assert_not_awaited()
        assert session.events.get_nowait() is None


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


def test_a_thread_born_in_t3_is_the_open_thread_only_once_the_journal_holds_it(tmp_path):
    """A-104 / SD-124: until then the Stage keeps its own open thread; nothing goes blank."""
    from uuid import NAMESPACE_URL, uuid5

    from harness.t3_front import FrontServer

    journal = TranscriptJournal(tmp_path / "journal")
    front = FrontServer(tmp_path, None, journal, tmp_path)
    front._client = SimpleNamespace(environment_id="env")
    assert front.open_thread() is None  # T3's page has named no thread
    front.through.thread = "native"
    assert front.open_thread() is None  # a T3 thread the journal does not hold yet
    born = str(uuid5(NAMESPACE_URL, "nocturne:t3:env/native"))
    journal.bind_front_prompt(born, "env", "native", "message")
    assert front.open_thread() == born
    journal.append_message(
        "ours", dict(role="user", message_id="1", content="Hello"), parent_id=None
    )
    front.through.thread = "ours"
    assert front.open_thread() is None  # a journal thread with no T3 window is not T3's thread
    journal.bind_front_window("ours", "env")
    assert front.open_thread() == "ours"
