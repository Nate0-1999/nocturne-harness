"""Local append-only capture for thread messages and daemon events."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import threading
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from errno import ELOOP, ENOENT, ENOTDIR
from pathlib import Path
from typing import Any

from harness.envelope import Envelope


class TranscriptJournalUnavailable(RuntimeError):
    """The mandatory conversation journal cannot safely accept history."""


@dataclass(frozen=True, slots=True)
class HydratedTranscript:
    """One authoritative current thread reconstructed from append-only rows."""

    thread_id: str
    messages: tuple[dict[str, Any], ...]
    resolved_model: str | None


class TranscriptJournal:
    """Durably append self-contained JSON records to one file per thread."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(os.path.abspath(root.expanduser()))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._next_parent_ids: dict[str, str | None] = {}
        self._reject_git_ancestor()
        self._preflight()

    @property
    def root(self) -> Path:
        return self._root

    def path_for_thread(self, thread_id: str) -> Path:
        """Map an opaque thread id to a traversal-safe stable filename."""

        return self._root / self._filename_for_thread(thread_id)

    def append_message(
        self,
        thread_id: str,
        message: Mapping[str, Any],
        *,
        parent_id: str | None,
        advance_tail: bool = True,
    ) -> None:
        """Append one immutable snapshot of a C.7 transcript message."""

        captured = deepcopy(dict(message))
        captured["parentId"] = parent_id
        message_id = self._message_id(captured)
        with self._lock:
            if thread_id not in self._next_parent_ids:
                self._next_parent_ids[thread_id] = self._read_last_tail_id(thread_id)
            tail_message_id = message_id if advance_tail else self._next_parent_ids[thread_id]
            self._append(
                thread_id,
                {
                    "version": 1,
                    "record_type": "message",
                    "message": captured,
                    "tail_message_id": tail_message_id,
                },
            )
            self._next_parent_ids[thread_id] = tail_message_id

    def append_event(self, thread_id: str, envelope: Envelope) -> None:
        """Append one daemon-authored C.7 event, whether or not a client is attached."""

        with self._lock:
            self._append(
                thread_id,
                {
                    "version": 1,
                    "record_type": "event",
                    "event": envelope.model_dump(mode="json"),
                },
            )

    def next_parent_id(self, thread_id: str) -> str | None:
        """Return only the durable tail message id; never hydrate thread state."""

        self._require_thread_id(thread_id)
        with self._lock:
            if thread_id not in self._next_parent_ids:
                self._next_parent_ids[thread_id] = self._read_last_tail_id(thread_id)
            return self._next_parent_ids[thread_id]

    def read_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Read the immutable message snapshots for an extraction pass."""

        self._require_thread_id(thread_id)
        path = self.path_for_thread(thread_id)
        try:
            with path.open("rb") as stream:
                rows = stream.readlines()
        except FileNotFoundError:
            return []
        messages: list[dict[str, Any]] = []
        for raw in rows:
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if row.get("thread_id") != thread_id or row.get("record_type") != "message":
                continue
            message = row.get("message")
            if isinstance(message, dict):
                messages.append(deepcopy(message))
        return messages

    def hydrate_threads(self) -> tuple[HydratedTranscript, ...]:
        """Reconstruct every current transcript branch from durable journal rows."""

        with self._lock:
            try:
                root_descriptor = self._open_root_descriptor()
                try:
                    filenames = sorted(os.listdir(root_descriptor))
                finally:
                    os.close(root_descriptor)
            except TranscriptJournalUnavailable:
                raise
            except OSError as exc:
                raise TranscriptJournalUnavailable(
                    f"Conversation journal cannot be read at {self._root}. "
                    "Fix that directory, then run `nocturne up` again."
                ) from exc

            hydrated: list[HydratedTranscript] = []
            for filename in filenames:
                if not self._is_transcript_filename(filename):
                    continue
                transcript = self._hydrate_file(filename)
                if transcript is not None:
                    hydrated.append(transcript)
            return tuple(hydrated)

    def transcript_tail(self, thread_id: str) -> str | None:
        """Return the durable tail identity used for idempotent archive extraction."""

        return self.next_parent_id(thread_id)

    def append_extraction(
        self,
        thread_id: str,
        *,
        tail_message_id: str,
        working_summary: str,
        open_loops: list[str],
        item_uids: list[str],
    ) -> None:
        """Journal a completed archive extraction against its exact durable tail."""

        with self._lock:
            self._append(
                thread_id,
                {
                    "version": 1,
                    "record_type": "extraction",
                    "tail_message_id": tail_message_id,
                    "working_summary": working_summary,
                    "open_loops": list(open_loops),
                    "item_uids": list(item_uids),
                },
            )

    def extracted_tail(self, thread_id: str) -> str | None:
        """Return the most recently completed extraction tail, if any."""

        path = self.path_for_thread(thread_id)
        try:
            rows = path.read_bytes().splitlines()
        except FileNotFoundError:
            return None
        for raw in reversed(rows):
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if row.get("record_type") == "extraction" and row.get("thread_id") == thread_id:
                tail = row.get("tail_message_id")
                return tail if isinstance(tail, str) and tail else None
        return None

    def idle_thread_ids(self, cutoff: datetime) -> list[str]:
        """List transcript threads whose last captured message predates cutoff."""

        if cutoff.tzinfo is None:
            raise ValueError("idle cutoff must be timezone-aware")
        found: list[str] = []
        if not self._root.exists():
            return found
        for path in sorted(self._root.glob("*.jsonl")):
            try:
                rows = path.read_bytes().splitlines()
            except OSError:
                continue
            thread_id: str | None = None
            last_message_at: datetime | None = None
            for raw in rows:
                try:
                    row = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if row.get("record_type") != "message":
                    continue
                value = row.get("thread_id")
                captured = row.get("captured_at")
                if not isinstance(value, str) or not isinstance(captured, str):
                    continue
                try:
                    instant = datetime.fromisoformat(captured)
                except ValueError:
                    continue
                thread_id = value
                last_message_at = instant
            if (
                thread_id is not None
                and last_message_at is not None
                and last_message_at <= cutoff
                and self.extracted_tail(thread_id) != self.transcript_tail(thread_id)
            ):
                found.append(thread_id)
        return found

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
        descriptor = self._open_append_descriptor(thread_id)
        locked = False
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            file_size = os.fstat(descriptor).st_size
            if file_size and os.pread(descriptor, 1, file_size - 1) != b"\n":
                try:
                    self._write_all(descriptor, b"\n")
                    os.fsync(descriptor)
                    file_size += 1
                except BaseException:
                    os.ftruncate(descriptor, file_size)
                    try:
                        os.fsync(descriptor)
                    except OSError:
                        pass
                    raise
            record_start = file_size
            try:
                self._write_all(descriptor, encoded)
                os.fsync(descriptor)
            except BaseException:
                os.ftruncate(descriptor, record_start)
                try:
                    os.fsync(descriptor)
                except OSError:
                    pass
                raise
        finally:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _preflight(self) -> None:
        filename = f".journal-preflight-{uuid.uuid4().hex}"
        root_descriptor: int | None = None
        descriptor: int | None = None
        created = False
        failure: BaseException | None = None
        try:
            root_descriptor = self._open_root_descriptor()
            descriptor = os.open(
                filename,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_descriptor,
            )
            created = True
            os.fchmod(descriptor, 0o600)
            self._write_all(descriptor, b"nocturne journal preflight\n")
            os.fsync(descriptor)
        except BaseException as exc:
            failure = exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if root_descriptor is not None:
                if created:
                    try:
                        os.unlink(filename, dir_fd=root_descriptor)
                    except BaseException as exc:
                        if failure is None:
                            failure = exc
                    else:
                        try:
                            os.fsync(root_descriptor)
                        except BaseException as exc:
                            if failure is None:
                                failure = exc
                os.close(root_descriptor)
        if failure is not None:
            if not isinstance(failure, Exception):
                raise failure
            raise TranscriptJournalUnavailable(
                f"Conversation journal is not writable at {self._root}. "
                "Fix that directory's permissions, then run `nocturne up` again."
            ) from failure

    def _hydrate_file(self, filename: str) -> HydratedTranscript | None:
        rows = self._read_file_rows(filename)
        thread_id: str | None = None
        latest_messages: dict[str, dict[str, Any]] = {}
        tail_message_id: str | None = None
        saw_tail = False
        resolved_model: str | None = None

        for raw in rows:
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(row, dict):
                continue
            candidate = row.get("thread_id")
            if not isinstance(candidate, str) or self._filename_for_thread(candidate) != filename:
                continue
            if thread_id is None:
                thread_id = candidate
            elif candidate != thread_id:
                continue

            if row.get("record_type") == "message":
                message = row.get("message")
                if not isinstance(message, dict):
                    continue
                try:
                    message_id = self._message_id(message)
                except ValueError:
                    continue
                parent_id = message.get("parentId")
                if parent_id is not None and (not isinstance(parent_id, str) or not parent_id):
                    continue
                latest_messages[message_id] = deepcopy(message)
                if "tail_message_id" in row:
                    candidate_tail = row["tail_message_id"]
                    if candidate_tail is None or isinstance(candidate_tail, str) and candidate_tail:
                        tail_message_id = candidate_tail
                        saw_tail = True
            elif row.get("record_type") == "event":
                event = row.get("event")
                if isinstance(event, dict):
                    resolved_model = self._resolved_model(event, resolved_model)

        if not rows:
            return None
        if thread_id is None or not latest_messages:
            raise TranscriptJournalUnavailable(
                "Conversation journal contains an unreadable transcript. "
                "Restore the journal from a verified backup before starting Nocturne."
            )
        if not saw_tail or tail_message_id is None:
            raise TranscriptJournalUnavailable(
                f"Conversation journal for thread {thread_id} has no durable tail. "
                "Restore the journal from a verified backup before starting Nocturne."
            )

        branch: list[dict[str, Any]] = []
        visited: set[str] = set()
        cursor: str | None = tail_message_id
        while cursor is not None:
            if cursor in visited:
                raise TranscriptJournalUnavailable(
                    f"Conversation journal for thread {thread_id} contains a history cycle. "
                    "Restore the journal from a verified backup before starting Nocturne."
                )
            visited.add(cursor)
            message = latest_messages.get(cursor)
            if message is None:
                raise TranscriptJournalUnavailable(
                    f"Conversation journal for thread {thread_id} is missing a parent message. "
                    "Restore the journal from a verified backup before starting Nocturne."
                )
            branch.append(message)
            parent_id = message.get("parentId")
            cursor = parent_id if isinstance(parent_id, str) else None
        branch.reverse()
        return HydratedTranscript(thread_id, tuple(branch), resolved_model)

    def _read_file_rows(self, filename: str) -> list[bytes]:
        root_descriptor = self._open_root_descriptor()
        try:
            descriptor = os.open(
                filename,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_descriptor,
            )
        except OSError as exc:
            os.close(root_descriptor)
            if exc.errno == ELOOP:
                raise TranscriptJournalUnavailable(
                    "Conversation journal contains a non-file transcript. "
                    "Replace it with a verified journal file, then run `nocturne up` again."
                ) from exc
            raise TranscriptJournalUnavailable(
                f"Conversation journal cannot read {filename}. "
                "Fix that file, then run `nocturne up` again."
            ) from exc
        os.close(root_descriptor)
        locked = False
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise TranscriptJournalUnavailable(
                    "Conversation journal contains a non-file transcript. "
                    "Replace it with a verified journal file, then run `nocturne up` again."
                )
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            locked = True
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
            return b"".join(chunks).splitlines()
        finally:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _open_append_descriptor(self, thread_id: str) -> int:
        root_descriptor = self._open_root_descriptor()
        filename = self._filename_for_thread(thread_id)
        flags = os.O_APPEND | os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(filename, flags, 0o600, dir_fd=root_descriptor)
        except OSError as exc:
            if exc.errno == ELOOP:
                raise ValueError("transcript path must be a regular file") from exc
            raise
        finally:
            os.close(root_descriptor)
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            os.close(descriptor)
            raise ValueError("transcript path must be a regular file")
        try:
            os.fchmod(descriptor, 0o600)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _read_last_tail_id(self, thread_id: str) -> str | None:
        root_descriptor = self._open_root_descriptor()
        filename = self._filename_for_thread(thread_id)
        try:
            descriptor = os.open(
                filename,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_descriptor,
            )
        except OSError as exc:
            if exc.errno == ENOENT:
                return None
            if exc.errno == ELOOP:
                raise ValueError("transcript path must be a regular file") from exc
            raise
        finally:
            os.close(root_descriptor)
        locked = False
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("transcript path must be a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_SH)
            locked = True
            position = os.fstat(descriptor).st_size
            pending = b""
            while position:
                chunk_size = min(position, 8192)
                position -= chunk_size
                pending = os.pread(descriptor, chunk_size, position) + pending
                lines = pending.split(b"\n")
                pending = lines[0]
                for line in reversed(lines[1:]):
                    found, tail_id = self._tail_id_from_line(line)
                    if found:
                        return tail_id
            found, tail_id = self._tail_id_from_line(pending)
            return tail_id if found else None
        finally:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @classmethod
    def _tail_id_from_line(cls, line: bytes) -> tuple[bool, str | None]:
        if not line:
            return False, None
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, None
        if not isinstance(row, dict) or row.get("record_type") != "message":
            return False, None
        if "tail_message_id" in row:
            tail_id = row["tail_message_id"]
            if tail_id is None or isinstance(tail_id, str) and tail_id:
                return True, tail_id
            return False, None
        message = row.get("message")
        if not isinstance(message, dict):
            return False, None
        try:
            return True, cls._message_id(message)
        except ValueError:
            return False, None

    def _open_root_descriptor(self) -> int:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._root, flags)
        except OSError as exc:
            if exc.errno in {ELOOP, ENOTDIR}:
                raise ValueError("transcript root must be a real directory") from exc
            raise
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("transcript root must be a real directory")
        if not os.fstat(descriptor).st_mode & stat.S_IWUSR:
            os.close(descriptor)
            raise PermissionError("transcript root is not owner-writable")
        try:
            os.fchmod(descriptor, 0o700)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _write_all(descriptor: int, value: bytes) -> None:
        remaining = memoryview(value)
        while remaining:
            written = os.write(descriptor, remaining)
            if written == 0:
                raise OSError("incomplete transcript append")
            remaining = remaining[written:]

    @staticmethod
    def _filename_for_thread(thread_id: str) -> str:
        TranscriptJournal._require_thread_id(thread_id)
        digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
        return f"{digest}.jsonl"

    @staticmethod
    def _is_transcript_filename(filename: str) -> bool:
        stem, suffix = os.path.splitext(filename)
        return (
            suffix == ".jsonl"
            and len(stem) == 64
            and all(character in "0123456789abcdef" for character in stem)
        )

    @staticmethod
    def _resolved_model(event: Mapping[str, Any], current: str | None) -> str | None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return current
        direct = payload.get("resolved_model")
        if isinstance(direct, str) and direct:
            current = direct
        nested = payload.get("event")
        if isinstance(nested, dict):
            candidate = nested.get("new_model")
            if (
                nested.get("event_kind") == "model_change"
                and isinstance(candidate, str)
                and candidate
            ):
                current = candidate
        candidate = payload.get("new_model")
        if payload.get("event_kind") == "model_change" and isinstance(candidate, str) and candidate:
            current = candidate
        return current

    @staticmethod
    def _message_id(message: Mapping[str, Any]) -> str:
        message_id = message.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("captured message must have a nonblank message_id")
        return message_id

    def _reject_git_ancestor(self) -> None:
        for candidate in (self._root, *self._root.parents):
            if (candidate / ".git").exists():
                raise ValueError("transcript root must not live inside a git worktree")

    @staticmethod
    def _require_thread_id(thread_id: str) -> None:
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id must not be blank")
