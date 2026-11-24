from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness.t3_front_session import FrontSession
from harness.transcript import TranscriptJournal


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
        environment_id="env", call=AsyncMock(return_value=projection), dispatch=AsyncMock()
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
