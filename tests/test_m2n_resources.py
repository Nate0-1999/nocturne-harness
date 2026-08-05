from __future__ import annotations

import io
from pathlib import Path

import pytest

from harness import onboarding, resources


def _storage(*, free: int, total: int = 100 * 1024**3) -> resources.LocalStorageSnapshot:
    return resources.LocalStorageSnapshot(
        disk_free_bytes=free,
        disk_total_bytes=total,
        journal_bytes=2048,
        backup_bytes=4096,
    )


def test_resource_watch_enriches_database_truth_with_owner_local_measurements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-044 keeps Spine database truth and Harness process/filesystem truth distinct."""
    clock = iter((100.0, 161.9))
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        resources,
        "local_storage_snapshot",
        lambda home: _storage(free=50 * 1024**3),
    )
    monkeypatch.setattr(resources, "current_rss_bytes", lambda: 128 * 1024**2)

    snapshot = resources.ResourceWatch(tmp_path).snapshot(7_864_320)

    assert snapshot.status == "measured"
    assert snapshot.daemon_rss_bytes == 128 * 1024**2
    assert snapshot.daemon_uptime_seconds == 61
    assert snapshot.disk_free_bytes == 50 * 1024**3
    assert snapshot.database_bytes == 7_864_320
    assert snapshot.journal_bytes == 2048
    assert snapshot.backup_bytes == 4096
    assert snapshot.warning is None


def test_resource_watch_keeps_unavailable_rss_distinct_from_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-044 requires partial resource data to remain visibly unavailable rather than zero."""
    monkeypatch.setattr(resources, "local_storage_snapshot", lambda home: _storage(free=1))
    monkeypatch.setattr(resources, "current_rss_bytes", lambda: None)

    snapshot = resources.ResourceWatch(tmp_path).snapshot(1)

    assert snapshot.status == "partial"
    assert snapshot.daemon_rss_bytes is None
    assert snapshot.warning == "low_disk"


def test_startup_warns_early_without_prompting_or_stopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-044 gives mandatory history an early startup warning without an attention prompt."""
    monkeypatch.setattr(
        onboarding,
        "local_storage_snapshot",
        lambda home: _storage(free=4 * 1024**3),
    )
    output = io.StringIO()

    onboarding._warn_if_low_disk(tmp_path, stdout=output)

    assert output.getvalue() == (
        "Warning: Free disk space is low. Nocturne will continue; "
        "run `nocturne doctor` for details.\n"
    )


def test_directory_size_ignores_symlinked_content(
    tmp_path: Path,
) -> None:
    """A-044 keeps resource measurement inside NOCTURNE_HOME instead of following links."""
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "history.jsonl").write_bytes(b"owned")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside-data")
    (owned / "linked").symlink_to(outside)

    assert resources.directory_size(owned) == len(b"owned")
