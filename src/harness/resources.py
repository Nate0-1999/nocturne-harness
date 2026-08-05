"""Passive owner-local resource measurements for startup and Palace Vitals."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from harness.spine_client import VitalsResources

_EARLY_WARNING_BYTES = 5 * 1024**3


@dataclass(frozen=True)
class LocalStorageSnapshot:
    disk_free_bytes: int
    disk_total_bytes: int
    journal_bytes: int
    backup_bytes: int

    @property
    def low_disk(self) -> bool:
        return self.disk_free_bytes <= max(_EARLY_WARNING_BYTES, self.disk_total_bytes // 10)


def directory_size(path: Path) -> int:
    """Count regular file bytes without following links outside an owned directory."""

    if not path.exists() or path.is_symlink():
        return 0
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in files:
            candidate = Path(root) / name
            if not candidate.is_symlink():
                try:
                    total += candidate.stat().st_size
                except OSError:
                    continue
    return total


def local_storage_snapshot(home: Path) -> LocalStorageSnapshot:
    """Measure the filesystem and the two owner-local durable stores."""

    usage = shutil.disk_usage(home)
    return LocalStorageSnapshot(
        disk_free_bytes=usage.free,
        disk_total_bytes=usage.total,
        journal_bytes=directory_size(home / "transcripts"),
        backup_bytes=directory_size(home / "backups"),
    )


class ResourceWatch:
    """Add process and local storage truth to Spine's database observation."""

    def __init__(self, home: Path) -> None:
        self._home = home
        self._started_at = time.monotonic()

    def snapshot(self, database_bytes: int) -> VitalsResources:
        storage = local_storage_snapshot(self._home)
        rss = current_rss_bytes()
        return VitalsResources(
            status="measured" if rss is not None else "partial",
            daemon_rss_bytes=rss,
            daemon_uptime_seconds=max(0, int(time.monotonic() - self._started_at)),
            disk_free_bytes=storage.disk_free_bytes,
            disk_total_bytes=storage.disk_total_bytes,
            database_bytes=database_bytes,
            journal_bytes=storage.journal_bytes,
            backup_bytes=storage.backup_bytes,
            warning="low_disk" if storage.low_disk else None,
        )


def current_rss_bytes() -> int | None:
    """Read current resident memory from the host process table."""

    try:
        completed = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            check=True,
            capture_output=True,
            text=True,
        )
        kibibytes = int(completed.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    return kibibytes * 1024 if kibibytes >= 0 else None


__all__ = [
    "LocalStorageSnapshot",
    "ResourceWatch",
    "current_rss_bytes",
    "directory_size",
    "local_storage_snapshot",
]
