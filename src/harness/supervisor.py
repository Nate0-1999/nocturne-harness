"""Durable, process-evidenced liveness authority for Symphony workers."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from harness.envelope import generate_ulid

_WORKER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EVENT_TYPES = frozenset(
    {
        "spawn_intent",
        "process_started",
        "heartbeat",
        "process_exit_observed",
        "launch_failed",
        "death_certified",
        "quarantined",
    }
)


class SupervisorError(RuntimeError):
    """The worker supervisor cannot safely perform the requested transition."""


class SupervisorAlreadyRunning(SupervisorError):
    """Another process already owns the one liveness-authority lock."""


class SupervisorJournalUnavailable(SupervisorError):
    """The durable supervisor journal cannot be trusted."""


class WorkerStillAlive(SupervisorError):
    """Process evidence says the worker is still alive."""


class WorkerStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    EXIT_OBSERVED = "exit_observed"
    LAUNCH_FAILED = "launch_failed"
    CERTIFIED_DEAD = "certified_dead"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class WorkerAttempt:
    worker_id: str
    attempt_id: str
    accepted_commit: str
    location: Path
    command_sha256: str
    recovery_of: str | None
    status: WorkerStatus
    pid: int | None = None
    process_identity: str | None = None
    returncode: int | None = None
    death_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DeathCertificate:
    event_id: str
    worker_id: str
    attempt_id: str
    accepted_commit: str
    process_identity: str | None
    reason: str


@dataclass(slots=True)
class _MutableAttempt:
    worker_id: str
    attempt_id: str
    accepted_commit: str
    location: Path
    command_sha256: str
    recovery_of: str | None
    status: WorkerStatus
    pid: int | None = None
    process_identity: str | None = None
    returncode: int | None = None
    death_reason: str | None = None

    def freeze(self) -> WorkerAttempt:
        return WorkerAttempt(
            worker_id=self.worker_id,
            attempt_id=self.attempt_id,
            accepted_commit=self.accepted_commit,
            location=self.location,
            command_sha256=self.command_sha256,
            recovery_of=self.recovery_of,
            status=self.status,
            pid=self.pid,
            process_identity=self.process_identity,
            returncode=self.returncode,
            death_reason=self.death_reason,
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _process_identity(pid: int) -> str | None:
    """Return an OS birth fingerprint, not merely a reusable PID."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError as exc:
        raise SupervisorError("process evidence is permission-denied, not proof of death") from exc
    if sys.platform.startswith("linux"):
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields_after_name = raw[raw.rfind(")") + 2 :].split()
            if fields_after_name[0] == "Z":
                return None
            start_ticks = fields_after_name[19]
            process_group = fields_after_name[2]
        except FileNotFoundError:
            return None
        except (IndexError, OSError, UnicodeError) as exc:
            raise SupervisorError("process evidence cannot be read safely") from exc
        return f"linux:{pid}:{process_group}:{start_ticks}"
    try:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-o", "lstart=", "-o", "pgid=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SupervisorError("process evidence cannot be read safely") from exc
    line = " ".join(completed.stdout.split())
    if completed.returncode != 0 or not line:
        return None
    if line.startswith("Z"):
        return None
    return f"posix:{pid}:{line}"


class WorkerSupervisor:
    """One restartable authority over local worker process liveness."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        identity_reader: Callable[[int], str | None] = _process_identity,
    ) -> None:
        if os.name != "posix":
            raise SupervisorError("Symphony worker supervision currently requires POSIX processes.")
        self._root = Path(os.path.abspath(root.expanduser()))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._identity_reader = identity_reader
        self._thread_lock = threading.RLock()
        self._children: dict[str, subprocess.Popen[bytes]] = {}
        self._closed = False
        self._prepare_root()
        self._lock_descriptor = self._acquire_authority_lock()
        self._journal_path = self._root / "events.jsonl"
        try:
            self._load_attempts()
        except Exception:
            self.close()
            raise

    @property
    def root(self) -> Path:
        return self._root

    def close(self) -> None:
        """Release authority without terminating workers that a restart must recover."""

        if self._closed:
            return
        self._closed = True
        fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)
        os.close(self._lock_descriptor)

    def __enter__(self) -> WorkerSupervisor:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def attempts(self, worker_id: str | None = None) -> tuple[WorkerAttempt, ...]:
        """Return the journal-derived registry in append order."""

        with self._thread_lock:
            attempts = self._load_attempts()
        values = tuple(item.freeze() for item in attempts.values())
        if worker_id is None:
            return values
        self._validate_worker_id(worker_id)
        return tuple(item for item in values if item.worker_id == worker_id)

    def latest(self, worker_id: str) -> WorkerAttempt:
        """Return one worker's latest attempt."""

        attempts = self.attempts(worker_id)
        if not attempts:
            raise SupervisorError(f"worker {worker_id!r} has no registered attempt")
        return attempts[-1]

    def spawn(
        self,
        worker_id: str,
        command: Sequence[str],
        *,
        location: Path,
        accepted_commit: str,
    ) -> WorkerAttempt:
        """Start a first attempt after journaling its accepted checkpoint."""

        self._validate_worker_id(worker_id)
        if self.attempts(worker_id):
            raise SupervisorError("an existing worker must recover through an explicit certificate")
        return self._spawn(
            worker_id,
            command,
            location=location,
            accepted_commit=accepted_commit,
            recovery_of=None,
        )

    def heartbeat(self, worker_id: str) -> bool:
        """Journal supervisor-observed liveness; workers never heartbeat themselves."""

        with self._thread_lock:
            attempt = self._refresh_latest(worker_id)
            if attempt.status is not WorkerStatus.RUNNING:
                return False
            if self._identity_reader(attempt.pid or -1) != attempt.process_identity:
                return False
            self._append_event(
                "heartbeat",
                worker_id=attempt.worker_id,
                attempt_id=attempt.attempt_id,
                process_identity=attempt.process_identity,
            )
            return True

    def certify_dead(self, worker_id: str) -> DeathCertificate:
        """Certify death only from absent or mismatched OS process evidence."""

        with self._thread_lock:
            attempt = self._refresh_latest(worker_id)
            if attempt.status in {WorkerStatus.CERTIFIED_DEAD, WorkerStatus.QUARANTINED}:
                event = self._death_event(attempt.attempt_id)
                return self._certificate_from_event(attempt, event)
            if attempt.status is WorkerStatus.RUNNING:
                observed = self._identity_reader(attempt.pid or -1)
                if observed == attempt.process_identity:
                    raise WorkerStillAlive(
                        f"worker {worker_id!r} still matches its recorded process identity"
                    )
                reason = "process_absent" if observed is None else "process_identity_mismatch"
            elif attempt.status is WorkerStatus.EXIT_OBSERVED:
                returncode = attempt.returncode
                reason = f"signal:{-returncode}" if returncode is not None and returncode < 0 else (
                    f"exit:{returncode}"
                )
            elif attempt.status is WorkerStatus.STARTING:
                reason = "launch_incomplete"
            elif attempt.status is WorkerStatus.LAUNCH_FAILED:
                reason = "launch_failed"
            else:  # pragma: no cover - enum closure protects this branch
                raise SupervisorError(f"worker {worker_id!r} cannot be death-certified")
            event = self._append_event(
                "death_certified",
                worker_id=attempt.worker_id,
                attempt_id=attempt.attempt_id,
                accepted_commit=attempt.accepted_commit,
                process_identity=attempt.process_identity,
                reason=reason,
            )
            refreshed = self.latest(worker_id)
            return self._certificate_from_event(refreshed, event)

    def recover(
        self,
        worker_id: str,
        command: Sequence[str],
        *,
        location: Path,
        accepted_commit: str,
    ) -> WorkerAttempt:
        """Start an explicit successor from accepted truth in a fresh location."""

        with self._thread_lock:
            previous = self.latest(worker_id)
            if previous.status is not WorkerStatus.CERTIFIED_DEAD:
                raise SupervisorError("recovery requires a process-evidence death certificate")
            canonical_location = self._validate_location(location)
            if canonical_location in {item.location for item in self.attempts(worker_id)}:
                raise SupervisorError(
                    "recovery requires a fresh location; dead residue stays quarantined"
                )
            checkpoint = self._validate_checkpoint(accepted_commit)
            self._append_event(
                "quarantined",
                worker_id=worker_id,
                attempt_id=previous.attempt_id,
                location=str(previous.location),
                successor_checkpoint=checkpoint,
            )
            return self._spawn(
                worker_id,
                command,
                location=canonical_location,
                accepted_commit=checkpoint,
                recovery_of=previous.attempt_id,
            )

    def _spawn(
        self,
        worker_id: str,
        command: Sequence[str],
        *,
        location: Path,
        accepted_commit: str,
        recovery_of: str | None,
    ) -> WorkerAttempt:
        canonical_location = self._validate_location(location)
        checkpoint = self._validate_checkpoint(accepted_commit)
        normalized_command = self._validate_command(command)
        command_digest = hashlib.sha256(
            json.dumps(normalized_command, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        attempt_id = generate_ulid()
        with self._thread_lock:
            self._append_event(
                "spawn_intent",
                worker_id=worker_id,
                attempt_id=attempt_id,
                accepted_commit=checkpoint,
                location=str(canonical_location),
                command_sha256=command_digest,
                recovery_of=recovery_of,
            )
            read_descriptor, write_descriptor = os.pipe()
            process: subprocess.Popen[bytes] | None = None
            try:
                process = subprocess.Popen(
                    (
                        sys.executable,
                        "-m",
                        "harness._supervised_worker",
                        str(read_descriptor),
                        *normalized_command,
                    ),
                    cwd=canonical_location,
                    pass_fds=(read_descriptor,),
                    start_new_session=True,
                )
                os.close(read_descriptor)
                read_descriptor = -1
                identity = self._identity_reader(process.pid)
                if identity is None:
                    raise SupervisorError("worker launch produced no stable process identity")
                self._children[attempt_id] = process
                self._append_event(
                    "process_started",
                    worker_id=worker_id,
                    attempt_id=attempt_id,
                    pid=process.pid,
                    process_identity=identity,
                )
                os.write(write_descriptor, b"1")
            except Exception as exc:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                self._append_event(
                    "launch_failed",
                    worker_id=worker_id,
                    attempt_id=attempt_id,
                    reason=type(exc).__name__,
                )
                raise
            finally:
                if read_descriptor >= 0:
                    os.close(read_descriptor)
                os.close(write_descriptor)
            return self.latest(worker_id)

    def _refresh_latest(self, worker_id: str) -> WorkerAttempt:
        attempt = self.latest(worker_id)
        if attempt.status is not WorkerStatus.RUNNING:
            return attempt
        child = self._children.get(attempt.attempt_id)
        if child is None:
            return attempt
        returncode = child.poll()
        if returncode is None:
            return attempt
        self._append_event(
            "process_exit_observed",
            worker_id=worker_id,
            attempt_id=attempt.attempt_id,
            returncode=returncode,
        )
        return self.latest(worker_id)

    def _prepare_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._root.is_symlink() or not self._root.is_dir():
            raise SupervisorJournalUnavailable("supervisor state root must be a real directory")
        self._root.chmod(0o700)

    def _acquire_authority_lock(self) -> int:
        path = self._root / "authority.lock"
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise SupervisorAlreadyRunning("another supervisor owns worker liveness") from exc
        except OSError as exc:
            if "descriptor" in locals():
                os.close(descriptor)
            raise SupervisorJournalUnavailable("supervisor authority lock is unavailable") from exc
        return descriptor

    def _append_event(self, event_type: str, **payload: object) -> dict[str, Any]:
        if self._closed:
            raise SupervisorError("supervisor authority is closed")
        attempts, events = self._load_attempts(include_events=True)
        del attempts
        event: dict[str, Any] = {
            "version": 1,
            "sequence": len(events) + 1,
            "event_id": generate_ulid(),
            "ts": self._clock().astimezone(UTC).isoformat(),
            "event": event_type,
            **payload,
        }
        encoded = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self._journal_path, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:  # pragma: no cover - os.write either writes or raises
                        raise OSError("journal write made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        except OSError as exc:
            raise SupervisorJournalUnavailable("supervisor event could not be journaled") from exc
        self._load_attempts()
        return event

    def _load_attempts(
        self,
        *,
        include_events: bool = False,
    ) -> dict[str, _MutableAttempt] | tuple[dict[str, _MutableAttempt], list[dict[str, Any]]]:
        events = self._read_events()
        attempts: dict[str, _MutableAttempt] = {}
        for event in events:
            event_type = event["event"]
            attempt_id = event.get("attempt_id")
            if event_type == "spawn_intent":
                if not isinstance(attempt_id, str) or attempt_id in attempts:
                    raise SupervisorJournalUnavailable("duplicate or missing spawn attempt")
                attempts[attempt_id] = _MutableAttempt(
                    worker_id=self._required_string(event, "worker_id"),
                    attempt_id=attempt_id,
                    accepted_commit=self._required_string(event, "accepted_commit"),
                    location=Path(self._required_string(event, "location")),
                    command_sha256=self._required_string(event, "command_sha256"),
                    recovery_of=self._optional_string(event, "recovery_of"),
                    status=WorkerStatus.STARTING,
                )
                continue
            if not isinstance(attempt_id, str) or attempt_id not in attempts:
                raise SupervisorJournalUnavailable("event references an unknown attempt")
            attempt = attempts[attempt_id]
            if event_type == "process_started":
                if attempt.status is not WorkerStatus.STARTING:
                    raise SupervisorJournalUnavailable("process start follows an invalid state")
                attempt.pid = self._required_int(event, "pid")
                attempt.process_identity = self._required_string(event, "process_identity")
                attempt.status = WorkerStatus.RUNNING
            elif event_type == "heartbeat":
                if attempt.status is not WorkerStatus.RUNNING:
                    raise SupervisorJournalUnavailable("heartbeat follows a terminal transition")
            elif event_type == "process_exit_observed":
                if attempt.status is not WorkerStatus.RUNNING:
                    raise SupervisorJournalUnavailable("process exit follows an invalid state")
                attempt.returncode = self._required_int(event, "returncode")
                attempt.status = WorkerStatus.EXIT_OBSERVED
            elif event_type == "launch_failed":
                if attempt.status not in {WorkerStatus.STARTING, WorkerStatus.RUNNING}:
                    raise SupervisorJournalUnavailable("launch failure follows an invalid state")
                attempt.status = WorkerStatus.LAUNCH_FAILED
            elif event_type == "death_certified":
                if attempt.status not in {
                    WorkerStatus.STARTING,
                    WorkerStatus.RUNNING,
                    WorkerStatus.EXIT_OBSERVED,
                    WorkerStatus.LAUNCH_FAILED,
                }:
                    raise SupervisorJournalUnavailable("death certificate follows an invalid state")
                if event.get("accepted_commit") != attempt.accepted_commit:
                    raise SupervisorJournalUnavailable("death certificate changes its checkpoint")
                attempt.death_reason = self._required_string(event, "reason")
                attempt.status = WorkerStatus.CERTIFIED_DEAD
            elif event_type == "quarantined":
                if attempt.status is not WorkerStatus.CERTIFIED_DEAD:
                    raise SupervisorJournalUnavailable("quarantine lacks a death certificate")
                attempt.status = WorkerStatus.QUARANTINED
        if include_events:
            return attempts, events
        return attempts

    def _read_events(self) -> list[dict[str, Any]]:
        try:
            rows = self._journal_path.read_bytes().splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise SupervisorJournalUnavailable("supervisor journal cannot be read") from exc
        events: list[dict[str, Any]] = []
        ids: set[str] = set()
        for sequence, raw in enumerate(rows, start=1):
            try:
                event = json.loads(raw, parse_constant=_reject_json_constant)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise SupervisorJournalUnavailable(
                    "supervisor journal contains invalid JSON"
                ) from exc
            if not isinstance(event, dict):
                raise SupervisorJournalUnavailable("supervisor journal row is not an object")
            event_id = event.get("event_id")
            if (
                event.get("version") != 1
                or event.get("sequence") != sequence
                or event.get("event") not in _EVENT_TYPES
                or not isinstance(event_id, str)
                or event_id in ids
            ):
                raise SupervisorJournalUnavailable("supervisor journal sequence is invalid")
            ids.add(event_id)
            events.append(event)
        return events

    def _death_event(self, attempt_id: str) -> dict[str, Any]:
        events = self._read_events()
        for event in reversed(events):
            if event.get("event") == "death_certified" and event.get("attempt_id") == attempt_id:
                return event
        raise SupervisorJournalUnavailable("certified worker has no death-certificate event")

    @staticmethod
    def _certificate_from_event(
        attempt: WorkerAttempt,
        event: dict[str, Any],
    ) -> DeathCertificate:
        return DeathCertificate(
            event_id=str(event["event_id"]),
            worker_id=attempt.worker_id,
            attempt_id=attempt.attempt_id,
            accepted_commit=attempt.accepted_commit,
            process_identity=attempt.process_identity,
            reason=str(event["reason"]),
        )

    @staticmethod
    def _required_string(event: dict[str, Any], key: str) -> str:
        value = event.get(key)
        if not isinstance(value, str) or not value:
            raise SupervisorJournalUnavailable(f"supervisor event lacks {key}")
        return value

    @staticmethod
    def _required_int(event: dict[str, Any], key: str) -> int:
        value = event.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise SupervisorJournalUnavailable(f"supervisor event lacks {key}")
        return value

    @staticmethod
    def _optional_string(event: dict[str, Any], key: str) -> str | None:
        value = event.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise SupervisorJournalUnavailable(f"supervisor event has invalid {key}")
        return value

    @staticmethod
    def _validate_worker_id(worker_id: str) -> None:
        if _WORKER_ID.fullmatch(worker_id) is None:
            raise ValueError("worker_id must be a compact stable identity")

    @staticmethod
    def _validate_checkpoint(value: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError("accepted_commit must name the last conductor-accepted checkpoint")
        return value

    @staticmethod
    def _validate_location(value: Path) -> Path:
        location = Path(os.path.abspath(value.expanduser()))
        if not location.is_dir():
            raise ValueError("worker location must be an existing directory")
        return location.resolve(strict=True)

    @staticmethod
    def _validate_command(command: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(command)
        if not normalized or any(not isinstance(item, str) or not item for item in normalized):
            raise ValueError("worker command must contain nonblank string arguments")
        return normalized
