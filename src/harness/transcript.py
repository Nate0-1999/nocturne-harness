"""Local append-only capture for thread messages and daemon events."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.envelope import Envelope


class TranscriptJournal:
    """Durably append self-contained JSON records to one file per thread."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root.expanduser().resolve()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._reject_git_ancestor()

    @property
    def root(self) -> Path:
        return self._root

    def path_for_thread(self, thread_id: str) -> Path:
        """Map an opaque thread id to a traversal-safe stable filename."""

        self._require_thread_id(thread_id)
        digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.jsonl"

    def append_message(
        self,
        thread_id: str,
        message: Mapping[str, Any],
        *,
        parent_id: str | None,
    ) -> None:
        """Append one immutable snapshot of a C.7 transcript message."""

        captured = deepcopy(dict(message))
        captured["parentId"] = parent_id
        self._append(
            thread_id,
            {
                "version": 1,
                "record_type": "message",
                "message": captured,
            },
        )

    def append_event(self, thread_id: str, envelope: Envelope) -> None:
        """Append one daemon-authored C.7 event, whether or not a client is attached."""

        self._append(
            thread_id,
            {
                "version": 1,
                "record_type": "event",
                "event": envelope.model_dump(mode="json"),
            },
        )

    def _append(self, thread_id: str, record: dict[str, object]) -> None:
        captured_at = self._clock()
        if captured_at.tzinfo is None:
            raise ValueError("transcript clock must return an aware datetime")
        row = {
            **record,
            "captured_at": captured_at.isoformat(),
            "thread_id": thread_id,
        }
        encoded = (
            json.dumps(
                row,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)
        path = self.path_for_thread(thread_id)
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise OSError("incomplete transcript append")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _reject_git_ancestor(self) -> None:
        for candidate in (self._root, *self._root.parents):
            if (candidate / ".git").exists():
                raise ValueError("transcript root must not live inside a git worktree")

    @staticmethod
    def _require_thread_id(thread_id: str) -> None:
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id must not be blank")
