from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import lifecycle, onboarding, resources


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
        resources.shutil,
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
        resources.shutil,
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


def _inventory(memories: list[dict[str, object]], *, base_count: int) -> dict[str, object]:
    return {
        "memories": memories,
        "event_counts": {
            table: base_count + index for index, table in enumerate(lifecycle._EVENT_TABLES)
        },
    }


def test_rollback_manifest_names_loss_reversion_pins_and_event_deltas() -> None:
    """A-045 makes the destructive consequence inspectable before confirmation."""
    current = _inventory(
        [
            {"id": "a", "label": "Born later", "revision": 1, "pin": True},
            {"id": "b", "label": "Edited", "revision": 3, "pin": False},
            {"id": "c", "label": "Unpinned there", "revision": 2, "pin": True},
        ],
        base_count=10,
    )
    candidate = _inventory(
        [
            {"id": "b", "label": "Edited", "revision": 1, "pin": False},
            {"id": "c", "label": "Unpinned there", "revision": 2, "pin": False},
        ],
        base_count=4,
    )

    manifest = lifecycle._rollback_manifest(current, candidate)

    assert [item.memory_id for item in manifest.memories_lost] == ["a"]
    assert [item.memory_id for item in manifest.edits_reverted] == ["b", "c"]
    assert [item.memory_id for item in manifest.pins_undone] == ["a", "c"]
    assert all(count.candidate - count.current == -6 for count in manifest.event_counts)


def _prepared_restore(tmp_path: Path) -> lifecycle.PreparedRestore:
    manifest = lifecycle.RollbackManifest(
        memories_lost=(lifecycle.ManifestMemory("a", "Born later", 1, None),),
        edits_reverted=(lifecycle.ManifestMemory("b", "Edited", 3, 1),),
        pins_undone=(),
        event_counts=tuple(lifecycle.EventCount(table, 10, 4) for table in lifecycle._EVENT_TABLES),
    )
    return lifecycle.PreparedRestore(
        restore_id="01J00000000000000000000009",
        backup_id="01J00000000000000000000000",
        former_volume="nocturne_old",
        candidate_volume="nocturne_candidate",
        manifest=manifest,
    )


def test_restore_cancellation_prints_manifest_and_discards_only_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-045 treats every response except the exact typed phrase as no authority to switch."""
    config = _config(tmp_path)
    prepared = _prepared_restore(tmp_path)
    discarded: list[lifecycle.PreparedRestore] = []
    monkeypatch.setattr(onboarding, "load_config", lambda **kwargs: config)
    monkeypatch.setattr(onboarding, "_require_command", lambda command: None)
    monkeypatch.setattr(onboarding, "_service_reachable", lambda *args, **kwargs: False)
    monkeypatch.setattr(onboarding, "prepare_local_restore", lambda *args: prepared)
    monkeypatch.setattr(onboarding, "discard_prepared_restore", discarded.append)
    output = io.StringIO()

    result = onboarding.restore_nocturne(
        prepared.backup_id,
        prompt=lambda message: "no",
        stdout=output,
    )

    assert result == 1
    assert discarded == [prepared]
    assert "Memories lost: 1" in output.getvalue()
    assert "Born later [a]" in output.getvalue()
    assert "memory_revision: 10 -> 4 (-6)" in output.getvalue()
    assert "live Palace was not changed" in output.getvalue()


def test_failed_candidate_switch_restores_the_former_config_and_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-045 mechanically returns to the former Palace when candidate startup fails."""
    config = _config(tmp_path)
    prepared = _prepared_restore(tmp_path)
    active = {"volume": prepared.former_volume}
    changes: list[str] = []

    @contextmanager
    def compose(current: object):
        yield ["compose", str(getattr(current, "active_postgres_volume"))]

    def set_volume(volume: str) -> object:
        active["volume"] = volume
        changes.append(volume)
        return SimpleNamespace(active_postgres_volume=volume)

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        del kwargs
        if "up" in command and prepared.candidate_volume in command:
            raise lifecycle.LifecycleError("candidate failed")
        if "ps" in command:
            return SimpleNamespace(stdout="postgres\n")
        return SimpleNamespace(stdout=None)

    monkeypatch.setattr(lifecycle, "_compose_command", compose)
    monkeypatch.setattr(lifecycle, "_run", run)

    with pytest.raises(lifecycle.LifecycleError, match="former Palace was restored"):
        lifecycle.activate_local_restore(config, prepared, set_active_volume=set_volume)

    assert changes == [prepared.candidate_volume, prepared.former_volume]
    assert active["volume"] == prepared.former_volume


def test_candidate_credential_file_is_private_and_docker_env_compatible(tmp_path: Path) -> None:
    """A-045 keeps the isolated restore credential private without changing its value."""
    config = _config(tmp_path)

    path = lifecycle._candidate_env_file(config)
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_text(encoding="utf-8").splitlines() == [
            "POSTGRES_DB=spine",
            "POSTGRES_USER=spine",
            "POSTGRES_PASSWORD=database-secret",
        ]
    finally:
        path.unlink()


def test_exact_restore_confirmation_switches_and_retains_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-045 grants switch authority only through the exact backup-bound phrase."""
    config = _config(tmp_path)
    prepared = _prepared_restore(tmp_path)
    activated: list[lifecycle.PreparedRestore] = []
    discarded: list[lifecycle.PreparedRestore] = []
    receipt = tmp_path / "rollback-volumes" / "receipt.json"
    monkeypatch.setattr(onboarding, "load_config", lambda **kwargs: config)
    monkeypatch.setattr(onboarding, "_require_command", lambda command: None)
    monkeypatch.setattr(onboarding, "_service_reachable", lambda *args, **kwargs: False)
    monkeypatch.setattr(onboarding, "prepare_local_restore", lambda *args: prepared)
    monkeypatch.setattr(onboarding, "discard_prepared_restore", discarded.append)
    monkeypatch.setattr(
        onboarding,
        "activate_local_restore",
        lambda config, candidate, **kwargs: activated.append(candidate) or receipt,
    )

    result = onboarding.restore_nocturne(
        prepared.backup_id,
        prompt=lambda message: f"RESTORE {prepared.backup_id}",
        stdout=io.StringIO(),
    )

    assert result == 0
    assert activated == [prepared]
    assert discarded == []


def test_restore_refuses_while_owner_services_can_still_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-045 prevents the manifest from racing writes by a running owner app."""
    config = _config(tmp_path)
    monkeypatch.setattr(onboarding, "load_config", lambda **kwargs: config)
    monkeypatch.setattr(onboarding, "_require_command", lambda command: None)
    monkeypatch.setattr(onboarding, "_service_reachable", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        onboarding,
        "prepare_local_restore",
        lambda *args: pytest.fail("a live owner app must stop restore before preparation"),
    )

    with pytest.raises(onboarding.OnboardingError, match="Stop `nocturne up`"):
        onboarding.restore_nocturne(
            "01J00000000000000000000000",
            prompt=lambda message: pytest.fail("restore must not ask while writes are possible"),
            stdout=io.StringIO(),
        )
