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
