from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import lifecycle, onboarding


def _config(tmp_path: Path, *, retention: int = 2) -> onboarding.NocturneConfig:
    path = tmp_path / "env"
    path.write_text('NOCTURNE_CONFIG_VERSION="2"\n', encoding="utf-8")
    path.chmod(0o600)
    return onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="owner-secret",
        spine_token="spine-secret",
        database_password="database-secret",
        machine_id="owner-machine",
        backup_generations=retention,
    )


def _successful_run(command: list[str], **kwargs: object) -> SimpleNamespace:
    if "pg_dump" in command:
        kwargs["stdout"].write(b"PGDMP verified archive")  # type: ignore[union-attr]
        return SimpleNamespace(stdout=None)
    if "pg_restore" in command:
        assert kwargs["stdin"].read() in {  # type: ignore[union-attr]
            b"PGDMP verified archive",
            b"old",
        }
        return SimpleNamespace(stdout=None)
    if "ps" in command and "--services" in command:
        return SimpleNamespace(stdout="postgres\n")
    if "to_regclass" in command[-1]:
        return SimpleNamespace(stdout="alembic_version\n")
    if "version_num" in command[-1]:
        return SimpleNamespace(stdout="0009\n")
    if "pg_database_size" in command[-1]:
        return SimpleNamespace(stdout="1048576\n")
    raise AssertionError(command)


def _old_generation(backups: Path, backup_id: str) -> None:
    generation = backups / backup_id
    generation.mkdir(parents=True)
    backups.chmod(0o700)
    generation.chmod(0o700)
    archive = generation / "palace.pgdump"
    archive.write_bytes(b"old")
    archive.chmod(0o600)
    receipt = generation / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup_id": backup_id,
                "created_at": "2026-08-04T00:00:00+00:00",
                "reason": "manual",
                "database": "spine",
                "alembic_revision": "0009",
                "postgres_image": lifecycle._POSTGRES_IMAGE,
                "archive": "palace.pgdump",
                "archive_bytes": 3,
                "archive_sha256": hashlib.sha256(b"old").hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    receipt.chmod(0o600)


def test_backup_publishes_verified_private_receipt_and_prunes_known_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-042 makes one verified receipt authoritative and prunes only recognized generations."""
    config = _config(tmp_path)
    backups = tmp_path / "backups"
    _old_generation(backups, "01J00000000000000000000000")
    _old_generation(backups, "01J00000000000000000000001")
    unknown = backups / "keep-me"
    unknown.mkdir()
    monkeypatch.setattr(lifecycle.subprocess, "run", _successful_run)
    monkeypatch.setattr(lifecycle, "generate_ulid", lambda: "01J00000000000000000000002")

    output = io.StringIO()
    generation = lifecycle.create_local_backup(config, reason="manual", stdout=output)
    receipt = json.loads((generation / "receipt.json").read_text(encoding="utf-8"))

    assert receipt["backup_id"] == generation.name
    assert receipt["reason"] == "manual"
    assert receipt["alembic_revision"] == "0009"
    assert receipt["archive_bytes"] == len(b"PGDMP verified archive")
    assert receipt["archive_sha256"] == hashlib.sha256(b"PGDMP verified archive").hexdigest()
    assert lifecycle.backup_permissions_are_private(generation)
    assert stat.S_IMODE(backups.stat().st_mode) == 0o700
    assert sorted(path.name for path in backups.iterdir()) == [
        "01J00000000000000000000001",
        "01J00000000000000000000002",
        "keep-me",
    ]
    assert str(generation) in output.getvalue()


def test_failed_dump_publishes_no_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-042 forbids a failed or partial dump from becoming a restore candidate."""
    config = _config(tmp_path)

    def failing_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        if "ps" in command and "--services" in command:
            return SimpleNamespace(stdout="postgres\n")
        if "pg_dump" in command:
            raise subprocess.CalledProcessError(1, command)
        raise AssertionError(command)

    monkeypatch.setattr(lifecycle.subprocess, "run", failing_run)

    with pytest.raises(lifecycle.LifecycleError, match="could not be completed"):
        lifecycle.create_local_backup(config, reason="manual")

    backups = tmp_path / "backups"
    assert not list(backups.iterdir())


def test_doctor_rechecks_resources_and_backup_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-043 warns before disk exhaustion and reuses the complete A-042 backup contract."""
    config = _config(tmp_path)
    tmp_path.chmod(0o700)
    backups = tmp_path / "backups"
    _old_generation(backups, "01J00000000000000000000000")
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "thread.jsonl").write_bytes(b"history")
    monkeypatch.setattr(lifecycle.subprocess, "run", _successful_run)
    monkeypatch.setattr(
        lifecycle.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100 * 1024**3, used=96 * 1024**3, free=4 * 1024**3),
    )

    report = lifecycle.inspect_local_palace(config)

    assert report.status == "warning"
    assert report.exit_code == 1
    assert report.database_bytes == 1024**2
    assert report.journal_bytes == len(b"history")
    assert report.backup_generations == 1
    assert report.warnings == ("Free disk space is below the early warning boundary.",)
    assert report.failures == ()


def test_doctor_fails_closed_on_a_corrupt_recognized_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-043 prevents a damaged A-042 generation from retaining a trusted label."""
    config = _config(tmp_path)
    tmp_path.chmod(0o700)
    backups = tmp_path / "backups"
    _old_generation(backups, "01J00000000000000000000000")
    (backups / "01J00000000000000000000000" / "palace.pgdump").write_bytes(b"changed")
    monkeypatch.setattr(lifecycle.subprocess, "run", _successful_run)
    monkeypatch.setattr(
        lifecycle.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100 * 1024**3, used=50 * 1024**3, free=50 * 1024**3),
    )

    report = lifecycle.inspect_local_palace(config)

    assert report.status == "failed"
    assert report.exit_code == 2
    assert report.backup_generations == 0
    assert report.failures == (
        "Backup 01J00000000000000000000000 failed its receipt or digest check.",
    )
