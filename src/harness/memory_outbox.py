"""M4BW (SD-082, FL-165): Palace writes made while the cloud Palace was unreachable.

Each write is one file under the Nocturne home, named in queue order, so nothing is lost on a
restart. On reconnect they go to the Palace oldest first, through its own write law; the first
that cannot reach it stops the push and keeps itself and everything after it. A write the
Palace refuses comes back as a card with its words, never a silent drop. No merge happens here:
the Palace decides every write.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, JsonValue

from harness.envelope import EnvelopeFactory
from harness.spine_client import (
    SpineClientError,
    SpineProblemError,
    SpineResponseError,
    SpineTransportError,
)

type OutboxKind = Literal["delete", "remember", "extraction"]


class QueuedForPalace(Exception):  # noqa: N818 - a signal, not a failure
    """A write the Palace never received now waits in the outbox; the reply says so."""

    def __init__(self, waiting: int) -> None:
        self.waiting = waiting
        super().__init__(
            f"Saved on this machine: the Palace is unreachable. {waiting} waiting for the "
            "Palace; they go to it in order when it is back."
        )


class QueuedWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: str
    kind: OutboxKind
    label: str
    queued_at: datetime
    payload: dict[str, JsonValue]


class ReturnedWrite(BaseModel):
    """A queued write the Palace did not accept, shown as a card until dismissed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: str
    kind: OutboxKind
    label: str
    reason: str
    returned_at: datetime


def never_reached_palace(exc: SpineClientError) -> bool:
    """True only when the cloud Palace provably did not process the request.

    A refused or failed connection, or a cloud front-end answer that is not the Palace's own
    (no RFC 7807 body) — so queueing it can never make the Palace count a write twice.
    """

    if isinstance(exc, SpineTransportError):
        return isinstance(exc.__cause__, (httpx.ConnectError, httpx.ConnectTimeout))
    return (
        isinstance(exc, SpineResponseError)
        and not isinstance(exc, SpineProblemError)
        and exc.status_code in {403, 404, 503}
    )


def palace_refused(exc: SpineClientError) -> bool:
    """The Palace itself answered no: a C.4 problem other than busy or unavailable."""

    return (
        isinstance(exc, SpineProblemError)
        and 400 <= exc.status_code < 500
        and exc.status_code != 429
    )


class MemoryOutbox:
    def __init__(
        self,
        root: Path,
        *,
        ids: EnvelopeFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.root = root
        self._ids = ids
        self._clock = clock

    def enqueue(self, kind: OutboxKind, label: str, payload: dict[str, JsonValue]) -> QueuedWrite:
        item = QueuedWrite(
            uid=self._ids.new_id(), kind=kind, label=label, queued_at=self._clock(), payload=payload
        )
        # Queue order is the file name: ids minted in one millisecond are not ordered.
        paths = self._paths()
        sequence = int(paths[-1].name.partition("-")[0]) + 1 if paths else 1
        self._write(self.root / f"{sequence:012d}-{item.uid}.json", item.model_dump_json())
        return item

    def waiting(self) -> list[QueuedWrite]:
        return [QueuedWrite.model_validate_json(path.read_text("utf-8")) for path in self._paths()]

    def returned(self) -> list[ReturnedWrite]:
        return [
            ReturnedWrite.model_validate_json(path.read_text("utf-8"))
            for path in sorted((self.root / "returned").glob("*.json"))
        ]

    def pending_delete_ids(self) -> frozenset[UUID]:
        return frozenset(
            UUID(str(item.payload["memory_id"])) for item in self.waiting() if item.kind == "delete"
        )

    def dismiss(self, uid: str) -> bool:
        for path in (self.root / "returned").glob(f"*-{uid}.json"):
            path.unlink()
            return True
        return False

    async def flush(self, push: Callable[[QueuedWrite], Awaitable[str | None]]) -> int:
        """Push oldest first; return how many left the queue (accepted or returned)."""

        done = 0
        for path in self._paths():
            item = QueuedWrite.model_validate_json(path.read_text("utf-8"))
            try:
                refusal = await push(item)
            except SpineClientError as exc:
                if not palace_refused(exc):
                    break
                refusal = exc.problem.detail or exc.problem.title or "The Palace refused it."
            if refusal is not None:
                card = ReturnedWrite(
                    uid=item.uid,
                    kind=item.kind,
                    label=item.label,
                    reason=refusal,
                    returned_at=self._clock(),
                )
                self._write(self.root / "returned" / path.name, card.model_dump_json())
            path.unlink()
            done += 1
        return done

    def _paths(self) -> list[Path]:
        return sorted(self.root.glob("*.json"))

    def _write(self, path: Path, encoded: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".outbox.", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


__all__ = [
    "MemoryOutbox",
    "QueuedForPalace",
    "QueuedWrite",
    "ReturnedWrite",
    "never_reached_palace",
    "palace_refused",
]
