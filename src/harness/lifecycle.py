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
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import IO, TextIO
from urllib.parse import quote

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
_EVENT_TABLES = (
    "memory_revision",
    "injection_event",
    "spend_event",
    "approval_decision",
    "scorer_activation",
    "spend_reconciliation",
)
_INVENTORY_SQL = """
SELECT json_build_object(
  'memories', COALESCE((
    SELECT json_agg(json_build_object(
      'id', id::text, 'label', label, 'pin', pin, 'revision', revision,
      'digest', md5(to_jsonb(memory_unit)::text)
    ) ORDER BY id) FROM memory_unit
  ), '[]'::json),
  'event_counts', json_build_object(
    'memory_revision', (SELECT count(*) FROM memory_revision),
    'injection_event', (SELECT count(*) FROM injection_event),
    'spend_event', (SELECT count(*) FROM spend_event),
    'approval_decision', (SELECT count(*) FROM approval_decision),
    'scorer_activation', (SELECT count(*) FROM scorer_activation),
    'spend_reconciliation', (SELECT count(*) FROM spend_reconciliation)
  )
)::text
""".strip()


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


@dataclass(frozen=True)
class ManifestMemory:
    memory_id: str
    label: str
    current_revision: int
    candidate_revision: int | None


@dataclass(frozen=True)
class EventCount:
    table: str
    current: int
    candidate: int


@dataclass(frozen=True)
class RollbackManifest:
    memories_lost: tuple[ManifestMemory, ...]
    edits_reverted: tuple[ManifestMemory, ...]
    pins_undone: tuple[ManifestMemory, ...]
    event_counts: tuple[EventCount, ...]


@dataclass(frozen=True)
class PreparedRestore:
    restore_id: str
    backup_id: str
    former_volume: str
    candidate_volume: str
    manifest: RollbackManifest


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
        raise LifecycleError(
            "The local Palace lifecycle operation could not be completed."
        ) from exc


def _cleanup_command(command: list[str]) -> None:
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


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


def prepare_local_restore(config: object, backup_id: str) -> PreparedRestore:
    """Restore one verified generation beside the live Palace and compute its manifest."""

    if _ULID_PATTERN.fullmatch(backup_id) is None:
        raise LifecycleError("That backup ID is not a recognized local generation.")
    home = Path(getattr(config, "home"))
    generation = home / "backups" / backup_id
    if _read_valid_receipt(generation, verify_digest=True) is None:
        raise LifecycleError("That backup failed its receipt or integrity check.")

    project = str(getattr(config, "compose_project"))
    former_volume = str(getattr(config, "active_postgres_volume"))
    candidate_volume = f"{project}_restore_{backup_id.lower()}"
    restore_id = generate_ulid()
    container = f"{project}-restore-{restore_id.lower()}"
    archive = generation / _ARCHIVE_NAME
    volume_created = False
    container_created = False
    env_path: Path | None = None
    try:
        if _docker_volume_exists(candidate_volume):
            raise LifecycleError("A restore candidate for that backup already exists.")
        with _compose_command(config) as compose:
            _require_running_postgres(compose)
            with archive.open("rb") as archive_handle:
                _run(
                    [*compose, "exec", "--no-TTY", "postgres", "pg_restore", "--list"],
                    stdin=archive_handle,
                    stdout=subprocess.DEVNULL,
                )
            current_inventory = _database_inventory([*compose, "exec", "--no-TTY", "postgres"])

        _run(
            [
                "docker",
                "volume",
                "create",
                "--label",
                "io.nocturne.managed=true",
                "--label",
                f"io.nocturne.restore={restore_id}",
                candidate_volume,
            ],
            stdout=subprocess.DEVNULL,
        )
        volume_created = True
        env_path = _candidate_env_file(config)
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--env-file",
                str(env_path),
                "--publish",
                "127.0.0.1::5432",
                "--volume",
                f"{candidate_volume}:/var/lib/postgresql/data",
                _POSTGRES_IMAGE,
            ],
            stdout=subprocess.DEVNULL,
        )
        container_created = True
        _wait_for_postgres(["docker", "exec", container])
        with archive.open("rb") as archive_handle:
            _run(
                [
                    "docker",
                    "exec",
                    "--interactive",
                    container,
                    "pg_restore",
                    "--username",
                    "spine",
                    "--dbname",
                    "spine",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                ],
                stdin=archive_handle,
                stdout=subprocess.DEVNULL,
            )
        _upgrade_restore_candidate(config, container)
        candidate_inventory = _database_inventory(["docker", "exec", container])
        manifest = _rollback_manifest(current_inventory, candidate_inventory)
        _run(["docker", "rm", "--force", container], stdout=subprocess.DEVNULL)
        container_created = False
        return PreparedRestore(
            restore_id=restore_id,
            backup_id=backup_id,
            former_volume=former_volume,
            candidate_volume=candidate_volume,
            manifest=manifest,
        )
    except Exception:
        if container_created:
            _cleanup_command(["docker", "rm", "--force", container])
        if volume_created:
            _cleanup_command(["docker", "volume", "rm", candidate_volume])
        raise
    finally:
        if env_path is not None:
            env_path.unlink(missing_ok=True)


def discard_prepared_restore(prepared: PreparedRestore) -> None:
    """Remove only an unselected restore candidate volume."""

    _cleanup_command(["docker", "volume", "rm", prepared.candidate_volume])


def activate_local_restore(
    config: object,
    prepared: PreparedRestore,
    *,
    set_active_volume: Callable[[str], object],
) -> Path:
    """Switch Compose to a verified candidate and roll back mechanically on failure."""

    pointer_changed = False
    live_stopped = False
    try:
        with _compose_command(config) as compose:
            _run([*compose, "stop", "postgres"], stdout=subprocess.DEVNULL)
        live_stopped = True
        new_config = set_active_volume(prepared.candidate_volume)
        pointer_changed = True
        with _compose_command(new_config) as compose:
            _run([*compose, "up", "--detach", "--wait", "postgres"], stdout=subprocess.DEVNULL)
            _require_running_postgres(compose)
        return _write_rollback_receipt(config, prepared)
    except Exception as exc:
        if live_stopped:
            try:
                old_config = (
                    set_active_volume(prepared.former_volume) if pointer_changed else config
                )
                with _compose_command(old_config) as compose:
                    _run(
                        [*compose, "up", "--detach", "--wait", "postgres"],
                        stdout=subprocess.DEVNULL,
                    )
                    _require_running_postgres(compose)
            except Exception as rollback_exc:
                raise LifecycleError(
                    "The restored Palace could not start, and the former Palace needs "
                    "manual restart."
                ) from rollback_exc
        raise LifecycleError(
            "The restored Palace could not start; the former Palace was restored."
        ) from exc


def _docker_volume_exists(volume: str) -> bool:
    try:
        completed = subprocess.run(
            ["docker", "volume", "inspect", volume],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise LifecycleError("Docker is unavailable for the restore operation.") from exc
    return completed.returncode == 0


def _candidate_env_file(config: object) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".restore-env-", dir=Path(getattr(config, "home")))
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            password = str(getattr(config, "database_password"))
            if "\n" in password or "\r" in password:
                raise LifecycleError("The database credential cannot be passed to Docker safely.")
            handle.write("POSTGRES_DB=spine\n")
            handle.write("POSTGRES_USER=spine\n")
            handle.write(f"POSTGRES_PASSWORD={password}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    return path


def _wait_for_postgres(prefix: list[str]) -> None:
    for _ in range(60):
        try:
            _run(
                [*prefix, "pg_isready", "--username", "spine", "--dbname", "spine"],
                stdout=subprocess.DEVNULL,
            )
            return
        except LifecycleError:
            time.sleep(0.5)
    raise LifecycleError("The restored Palace database did not become ready.")


def _require_running_postgres(compose: list[str]) -> None:
    running = _run(
        [*compose, "ps", "--status", "running", "--services"],
        stdout=subprocess.PIPE,
        text=True,
    )
    if "postgres" not in str(running.stdout).splitlines():
        raise LifecycleError("The local Palace is not running. Run `nocturne up` first.")


def _upgrade_restore_candidate(config: object, container: str) -> None:
    published = _run(["docker", "port", container, "5432/tcp"], stdout=subprocess.PIPE, text=True)
    port_text = str(published.stdout).strip().rsplit(":", 1)[-1]
    try:
        port = int(port_text)
    except ValueError:
        raise LifecycleError("The restored Palace database port could not be resolved.") from None
    password = quote(str(getattr(config, "database_password")), safe="")
    database_url = f"postgresql+asyncpg://spine:{password}@127.0.0.1:{port}/spine"
    try:
        from spine.db.migrate import upgrade_head

        upgrade_head(database_url)
    except Exception as exc:
        raise LifecycleError("The restored Palace could not be upgraded safely.") from exc


def _database_inventory(prefix: list[str]) -> dict[str, object]:
    result = _run(
        [
            *prefix,
            "psql",
            "--username",
            "spine",
            "--dbname",
            "spine",
            "--tuples-only",
            "--no-align",
            "--command",
            _INVENTORY_SQL,
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        inventory = json.loads(str(result.stdout).strip())
    except (TypeError, json.JSONDecodeError):
        raise LifecycleError("The rollback manifest could not be computed safely.") from None
    if not isinstance(inventory, dict):
        raise LifecycleError("The rollback manifest could not be computed safely.")
    return inventory


def _rollback_manifest(
    current: dict[str, object], candidate: dict[str, object]
) -> RollbackManifest:
    current_rows = {str(row["id"]): row for row in current["memories"]}  # type: ignore[index]
    candidate_rows = {str(row["id"]): row for row in candidate["memories"]}  # type: ignore[index]

    def item(row: dict[str, object], other: dict[str, object] | None) -> ManifestMemory:
        return ManifestMemory(
            memory_id=str(row["id"]),
            label=" ".join(str(row["label"]).split()) or "(untitled)",
            current_revision=int(row["revision"]),
            candidate_revision=None if other is None else int(other["revision"]),
        )

    lost = tuple(
        item(row, None)
        for memory_id, row in sorted(current_rows.items())
        if memory_id not in candidate_rows
    )
    edits = tuple(
        item(row, candidate_rows[memory_id])
        for memory_id, row in sorted(current_rows.items())
        if memory_id in candidate_rows and row != candidate_rows[memory_id]
    )
    pins = tuple(
        item(row, candidate_rows.get(memory_id))
        for memory_id, row in sorted(current_rows.items())
        if bool(row["pin"])
        and (memory_id not in candidate_rows or not bool(candidate_rows[memory_id]["pin"]))
    )
    current_counts = current["event_counts"]
    candidate_counts = candidate["event_counts"]
    if not isinstance(current_counts, dict) or not isinstance(candidate_counts, dict):
        raise LifecycleError("The rollback manifest could not be computed safely.")
    counts = tuple(
        EventCount(
            table=table,
            current=int(current_counts[table]),
            candidate=int(candidate_counts[table]),
        )
        for table in _EVENT_TABLES
    )
    return RollbackManifest(
        memories_lost=lost,
        edits_reverted=edits,
        pins_undone=pins,
        event_counts=counts,
    )


def _write_rollback_receipt(config: object, prepared: PreparedRestore) -> Path:
    directory = Path(getattr(config, "home")) / "rollback-volumes"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / f"{prepared.restore_id}.json"
    payload = {
        "schema_version": 1,
        "restore_id": prepared.restore_id,
        "backup_id": prepared.backup_id,
        "switched_at": datetime.now(UTC).isoformat(),
        "former_volume": prepared.former_volume,
        "active_volume": prepared.candidate_volume,
        "manifest": {
            "memories_lost": len(prepared.manifest.memories_lost),
            "edits_reverted": len(prepared.manifest.edits_reverted),
            "pins_undone": len(prepared.manifest.pins_undone),
            "event_counts": {
                count.table: {"current": count.current, "candidate": count.candidate}
                for count in prepared.manifest.event_counts
            },
        },
    }
    _write_receipt(path, payload)
    _fsync_directory(directory)
    return path
