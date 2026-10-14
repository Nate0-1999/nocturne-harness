"""ADR-003 / A-038-style proofs for the M4BW outbox of writes made while the Palace was away."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from harness.envelope import EnvelopeFactory
from harness.memory_outbox import (
    MemoryOutbox,
    QueuedWrite,
    never_reached_palace,
    palace_refused,
)
from harness.spine_client import (
    ProblemDetail,
    SpineProblemError,
    SpineResponseError,
    SpineTransportError,
)


def outbox(root: Path) -> MemoryOutbox:
    return MemoryOutbox(root, ids=EnvelopeFactory(machine_id="machine"))


def transport(cause: Exception) -> SpineTransportError:
    error = SpineTransportError()
    error.__cause__ = cause
    return error


def response(status: int, content_type: str) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": content_type}, content=b"{}")


def problem(status: int, detail: str) -> SpineProblemError:
    return SpineProblemError(
        response(status, "application/problem+json"),
        ProblemDetail(type="about:blank", title="Refused", status=status, detail=detail),
    )


@pytest.mark.asyncio
async def test_writes_survive_a_restart_and_push_oldest_first_until_the_palace_is_lost(
    tmp_path: Path,
) -> None:
    """ADR-003: queued writes upload on reconnect in order; the first lost push keeps the rest."""
    first = outbox(tmp_path)
    for label in ("one", "two", "three"):
        first.enqueue("delete", label, {"memory_id": "00000000-0000-4000-8000-000000000001"})
    pushed: list[str] = []

    async def push(item: QueuedWrite) -> str | None:
        if item.label == "two":
            raise transport(httpx.ConnectError("refused"))
        pushed.append(item.label)
        return None

    assert await outbox(tmp_path).flush(push) == 1
    assert pushed == ["one"]
    assert [item.label for item in outbox(tmp_path).waiting()] == ["two", "three"]


@pytest.mark.asyncio
async def test_a_write_the_palace_refuses_comes_back_as_a_card_never_a_silent_drop(
    tmp_path: Path,
) -> None:
    """ADR-003: the Palace decides each queued write; a refusal returns with its own words."""
    queue = outbox(tmp_path)
    queue.enqueue("delete", "refused", {"memory_id": "00000000-0000-4000-8000-000000000001"})
    queue.enqueue("delete", "gone", {"memory_id": "00000000-0000-4000-8000-000000000002"})

    async def push(item: QueuedWrite) -> str | None:
        if item.label == "refused":
            raise problem(409, "This memory changed while you were away.")
        return "It was no longer active in the Palace, so nothing was deleted."

    assert await queue.flush(push) == 2
    cards = queue.returned()
    assert [(card.label, card.reason) for card in cards] == [
        ("refused", "This memory changed while you were away."),
        ("gone", "It was no longer active in the Palace, so nothing was deleted."),
    ]
    assert queue.waiting() == []
    assert queue.dismiss(cards[0].uid) and len(queue.returned()) == 1


def test_only_a_request_the_palace_never_processed_counts_as_unreached() -> None:
    """ADR-003 / F175: an outbox may hold a write only if resending it cannot count twice."""
    assert never_reached_palace(transport(httpx.ConnectError("refused")))
    assert never_reached_palace(transport(httpx.ConnectTimeout("no route")))
    assert not never_reached_palace(transport(httpx.ReadTimeout("sent, no answer")))
    assert never_reached_palace(SpineResponseError(response(404, "text/html"), "front end"))
    assert not never_reached_palace(problem(422, "refused"))
    assert palace_refused(problem(422, "refused")) and not palace_refused(problem(429, "busy"))
