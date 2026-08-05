"""Private local Palace backup artifacts and receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import IO, TextIO

from harness.envelope import generate_ulid
from harness.resources import local_storage_snapshot

_ARCHIVE_NAME = "palace.pgdump"
_RECEIPT_NAME = "receipt.json"
_POSTGRES_IMAGE = (
    "pgvector/pgvector:pg16@sha256:a36250871de0833b8757561c72f2477ef1ddd1101afa4e617fb552e0de514c6b"
)
_ULID_PATTERN = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_FIELDS = {
    "schema_version",
    "backup_id",
    "created_at",
    "reason",
    "database",
    "alembic_revision",
    "postgres_image",
    "archive",
    "archive_bytes",
    "archive_sha256",
}


class LifecycleError(RuntimeError):
    """A safe lifecycle failure suitable for the public CLI."""


@dataclass(frozen=True)
class DoctorReport:
    """Safe measurements and findings from one read-only Palace inspection."""

    database_bytes: int | None
    journal_bytes: int
    backup_bytes: int
    backup_generations: int
    disk_free_bytes: int
    disk_total_bytes: int
    warnings: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def status(self) -> str:
        if self.failures:
            return "failed"
        if self.warnings:
            return "warning"
        return "healthy"

    @property
    def exit_code(self) -> int:
        return {"healthy": 0, "warning": 1, "failed": 2}[self.status]


@contextmanager
def _compose_command(config: object) -> Iterator[list[str]]:
    compose_project = getattr(config, "compose_project")
    config_path = getattr(config, "path")
    with resources.as_file(
        resources.files("harness").joinpath("resources", "docker-compose.yml")
    ) as compose_file:
        yield [
            "docker",
            "compose",
            "--project-name",
            compose_project,
            "--env-file",
            str(config_path),
            "--file",
            str(compose_file),
        ]


def _run(
    command: list[str],
    *,
    stdin: IO[bytes] | None = None,
    stdout: IO[bytes] | int | None = None,
    text: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            check=True,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LifecycleError("The local Palace backup could not be completed.") from exc


def _database_revision(compose: list[str]) -> str | None:
    table = _run(
        [
            *compose,
            "exec",
            "--no-TTY",
            "postgres",
            "psql",
            "--username",
            "spine",
            "--dbname",
            "spine",
            "--tuples-only",
            "--no-align",
            "--command",
            "SELECT to_regclass('public.alembic_version')",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    if not str(table.stdout).strip():
        return None
    revision = _run(
        [
            *compose,
            "exec",
            "--no-TTY",
            "postgres",
            "psql",
            "--username",
            "spine",
            "--dbname",
            "spine",
            "--tuples-only",
            "--no-align",
            "--command",
            "SELECT version_num FROM alembic_version LIMIT 1",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    return str(revision.stdout).strip() or None


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_valid_receipt(candidate: Path, *, verify_digest: bool) -> dict[str, object] | None:
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    try:
        if {path.name for path in candidate.iterdir()} != {_ARCHIVE_NAME, _RECEIPT_NAME}:
            return None
        receipt_path = candidate / _RECEIPT_NAME
        archive_path = candidate / _ARCHIVE_NAME
        if (
            receipt_path.is_symlink()
            or archive_path.is_symlink()
            or not receipt_path.is_file()
            or not archive_path.is_file()
        ):
            return None
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(str(receipt["created_at"]))
        valid_receipt = all(
            (
                isinstance(receipt, dict),
                set(receipt) == _RECEIPT_FIELDS,
                receipt["schema_version"] == 1,
                receipt["backup_id"] == candidate.name,
                _ULID_PATTERN.fullmatch(candidate.name) is not None,
                created_at.tzinfo is not None,
                created_at.utcoffset() == UTC.utcoffset(created_at),
                receipt["reason"] in {"manual", "pre_migration"},
                receipt["database"] == "spine",
                receipt["alembic_revision"] is None or isinstance(receipt["alembic_revision"], str),
                receipt["postgres_image"] == _POSTGRES_IMAGE,
                receipt["archive"] == _ARCHIVE_NAME,
                receipt["archive_bytes"] == archive_path.stat().st_size,
                isinstance(receipt["archive_sha256"], str)
                and _SHA256_PATTERN.fullmatch(receipt["archive_sha256"]) is not None,
                backup_permissions_are_private(candidate),
            )
        )
        if not valid_receipt:
            return None
        if verify_digest and receipt["archive_sha256"] != _sha256_file(archive_path):
            return None
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return receipt


def _valid_generations(backups: Path) -> list[Path]:
    valid: list[Path] = []
    for candidate in backups.iterdir():
        if _read_valid_receipt(candidate, verify_digest=False) is not None:
            valid.append(candidate)
    return sorted(valid, key=lambda path: path.name)


def inspect_local_palace(config: object) -> DoctorReport:
    """Inspect local lifecycle health without changing the Palace."""

    home = Path(getattr(config, "home"))
    warnings: list[str] = []
    failures: list[str] = []
    database_bytes: int | None = None

    try:
        home_mode = stat.S_IMODE(home.stat().st_mode)
        config_mode = stat.S_IMODE(Path(getattr(config, "path")).stat().st_mode)
        if home_mode != 0o700:
            failures.append(f"Nocturne home permissions are {home_mode:o}; expected 700.")
        if config_mode != 0o600:
            failures.append(f"Nocturne config permissions are {config_mode:o}; expected 600.")
        storage = local_storage_snapshot(home)
    except OSError:
        raise LifecycleError("Doctor could not inspect the local Nocturne home.") from None

    journal_bytes = storage.journal_bytes
    backup_bytes = storage.backup_bytes
    backups = home / "backups"
    valid_generations: list[Path] = []
    verified_generations: list[Path] = []
    recognized_generations: list[Path] = []
    if backups.is_dir() and not backups.is_symlink():
        if stat.S_IMODE(backups.stat().st_mode) != 0o700:
            failures.append("Backup directory permissions are not private; expected 700.")
        recognized_generations = sorted(
            (
                path
                for path in backups.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and _ULID_PATTERN.fullmatch(path.name) is not None
            ),
            key=lambda path: path.name,
        )
        for generation in recognized_generations:
            if _read_valid_receipt(generation, verify_digest=True) is None:
                failures.append(f"Backup {generation.name} failed its receipt or digest check.")
            else:
                valid_generations.append(generation)

    compose: list[str] | None = None
    try:
        with _compose_command(config) as command:
            compose = command
            running = _run(
                [*compose, "ps", "--status", "running", "--services"],
                stdout=subprocess.PIPE,
                text=True,
            )
            if "postgres" not in str(running.stdout).splitlines():
                failures.append("The local Palace database is not running.")
            else:
                measured = _run(
                    [
                        *compose,
                        "exec",
                        "--no-TTY",
                        "postgres",
                        "psql",
                        "--username",
                        "spine",
                        "--dbname",
                        "spine",
                        "--tuples-only",
                        "--no-align",
                        "--command",
                        "SELECT pg_database_size(current_database())",
                    ],
                    stdout=subprocess.PIPE,
                    text=True,
                )
                database_bytes = int(str(measured.stdout).strip())
    except (LifecycleError, ValueError):
        failures.append("Doctor could not reach the local Palace database.")

    if compose is not None and database_bytes is not None:
        for generation in valid_generations:
            try:
                with (generation / _ARCHIVE_NAME).open("rb") as archive_handle:
                    _run(
                        [*compose, "exec", "--no-TTY", "postgres", "pg_restore", "--list"],
                        stdin=archive_handle,
                        stdout=subprocess.DEVNULL,
                    )
                verified_generations.append(generation)
            except (LifecycleError, OSError):
                failures.append(f"Backup {generation.name} failed its archive check.")

    if storage.low_disk:
        warnings.append("Free disk space is below the early warning boundary.")

    return DoctorReport(
        database_bytes=database_bytes,
        journal_bytes=journal_bytes,
        backup_bytes=backup_bytes,
        backup_generations=len(verified_generations),
        disk_free_bytes=storage.disk_free_bytes,
        disk_total_bytes=storage.disk_total_bytes,
        warnings=tuple(warnings),
        failures=tuple(failures),
    )


def _prune_generations(backups: Path, retention: int) -> None:
    generations = _valid_generations(backups)
    for expired in generations[:-retention]:
        shutil.rmtree(expired)
    _fsync_directory(backups)


def create_local_backup(
    config: object,
    *,
    reason: str,
    stdout: TextIO | None = None,
) -> Path:
    """Create, verify, publish, and prune one local PostgreSQL backup."""

    if reason not in {"manual", "pre_migration"}:
        raise ValueError("unsupported backup reason")
    home = Path(getattr(config, "home"))
    retention = int(getattr(config, "backup_generations"))
    backups = home / "backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backups, 0o700)
    backup_id = generate_ulid()
    published = backups / backup_id
    temporary = Path(tempfile.mkdtemp(prefix=".backup-", dir=backups))
    os.chmod(temporary, 0o700)
    archive = temporary / _ARCHIVE_NAME
    try:
        with _compose_command(config) as compose:
            running = _run(
                [*compose, "ps", "--status", "running", "--services"],
                stdout=subprocess.PIPE,
                text=True,
            )
            if "postgres" not in str(running.stdout).splitlines():
                raise LifecycleError("The local Palace is not running. Run `nocturne up` first.")
            with archive.open("wb") as archive_handle:
                os.fchmod(archive_handle.fileno(), 0o600)
                _run(
                    [
                        *compose,
                        "exec",
                        "--no-TTY",
                        "postgres",
                        "pg_dump",
                        "--username",
                        "spine",
                        "--dbname",
                        "spine",
                        "--format=custom",
                        "--no-owner",
                        "--no-privileges",
                    ],
                    stdout=archive_handle,
                )
                archive_handle.flush()
                os.fsync(archive_handle.fileno())
            if archive.stat().st_size == 0:
                raise LifecycleError("The local Palace backup was empty and was not saved.")
            with archive.open("rb") as archive_handle:
                _run(
                    [*compose, "exec", "--no-TTY", "postgres", "pg_restore", "--list"],
                    stdin=archive_handle,
                    stdout=subprocess.DEVNULL,
                )
            revision = _database_revision(compose)

        digest = _sha256_file(archive)
        receipt = {
            "schema_version": 1,
            "backup_id": backup_id,
            "created_at": datetime.now(UTC).isoformat(),
            "reason": reason,
            "database": "spine",
            "alembic_revision": revision,
            "postgres_image": _POSTGRES_IMAGE,
            "archive": _ARCHIVE_NAME,
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": digest,
        }
        _write_receipt(temporary / _RECEIPT_NAME, receipt)
        _fsync_directory(temporary)
        os.replace(temporary, published)
        _fsync_directory(backups)
        _prune_generations(backups, retention)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    if stdout is not None:
        print(f"Backup ready at {published}.", file=stdout)
    return published


def backup_permissions_are_private(path: Path) -> bool:
    """Return whether a published generation retains the enacted private modes."""

    return (
        stat.S_IMODE(path.stat().st_mode) == 0o700
        and stat.S_IMODE((path / _ARCHIVE_NAME).stat().st_mode) == 0o600
        and stat.S_IMODE((path / _RECEIPT_NAME).stat().st_mode) == 0o600
    )
