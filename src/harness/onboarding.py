"""Clone-free local onboarding for the public ``nocturne`` command."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TextIO
from urllib.parse import quote, urlsplit

from harness.lifecycle import (
    DoctorReport,
    PreparedRestore,
    activate_local_restore,
    create_local_backup,
    discard_prepared_restore,
    inspect_local_palace,
    prepare_local_restore,
)
from harness.resources import local_storage_snapshot

LOCAL_URL = "http://127.0.0.1:8765"
SPINE_URL = "http://127.0.0.1:8000"
_CONFIG_FILE = "env"
_CONFIG_VERSION = "4"
_DEFAULT_BACKUP_GENERATIONS = 5
_LOWER_ULID_PATTERN = re.compile(r"[0-7][0-9a-hjkmnp-tv-z]{25}\Z")


class OnboardingError(RuntimeError):
    """A safe, user-actionable onboarding failure."""


@dataclass(frozen=True)
class NocturneConfig:
    """Private settings for one local daemon and its selected Palace rung."""

    home: Path
    openrouter_api_key: str
    spine_token: str
    database_password: str
    machine_id: str
    palace_mode: str = "local"
    spine_url: str = SPINE_URL
    postgres_port: int = 5432
    backup_generations: int = _DEFAULT_BACKUP_GENERATIONS
    postgres_volume: str | None = None

    @property
    def path(self) -> Path:
        return self.home / _CONFIG_FILE

    @property
    def database_url(self) -> str:
        password = quote(self.database_password, safe="")
        return f"postgresql+asyncpg://spine:{password}@127.0.0.1:{self.postgres_port}/spine"

    @property
    def compose_project(self) -> str:
        return _compose_project(self.home)

    @property
    def active_postgres_volume(self) -> str:
        return self.postgres_volume or _default_postgres_volume(self.home)

    def process_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        environment = dict(os.environ if base is None else base)
        environment.update(
            {
                "OPENROUTER_API_KEY": self.openrouter_api_key,
                "SPINE_OPENAI_API_KEY": self.openrouter_api_key,
                "SPINE_TOKEN": self.spine_token,
                "SPINE_URL": self.spine_url,
                "NOCTURNE_HOME": str(self.home),
                "PRINCIPAL_ID": "local",
                "MACHINE_ID": self.machine_id,
                "AGENT_ID": "nocturne",
            }
        )
        if self.palace_mode == "local":
            environment.update(
                {
                    "SPINE_DATABASE_URL": self.database_url,
                    "NOCTURNE_BACKUP_GENERATIONS": str(self.backup_generations),
                    "NOCTURNE_POSTGRES_VOLUME": self.active_postgres_volume,
                }
            )
        return environment


def nocturne_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the one overridable install-state root."""

    values = os.environ if environ is None else environ
    override = values.get("NOCTURNE_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".nocturne"


def init_nocturne(
    *,
    remote: str | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    stdout: TextIO = sys.stdout,
) -> Path:
    """Create one private config for a local or remote Palace."""

    values = os.environ if environ is None else environ
    target_home = home or nocturne_home(values)
    target = target_home / _CONFIG_FILE
    if target.exists():
        load_config(home=target_home)
        print(f"Nocturne is already initialized at {target_home}.", file=stdout)
        return target

    palace_mode = "remote" if remote is not None else "local"
    spine_url = _parse_remote_url(remote) if remote is not None else SPINE_URL
    openrouter_key = values.get("OPENROUTER_API_KEY", "").strip()
    if not openrouter_key:
        openrouter_key = prompt("OpenRouter API key: ").strip()
    if not openrouter_key:
        raise OnboardingError("An OpenRouter API key is required.")
    spine_token = secrets.token_urlsafe(32)
    if palace_mode == "remote":
        spine_token = prompt("Palace bearer: ").strip()
        if not spine_token:
            raise OnboardingError("A Palace bearer is required for a remote Palace.")
    postgres_port = _parse_port(values.get("NOCTURNE_POSTGRES_PORT", "5432"))

    config = NocturneConfig(
        home=target_home,
        openrouter_api_key=openrouter_key,
        spine_token=spine_token,
        database_password=secrets.token_urlsafe(24),
        machine_id=f"nocturne-{uuid.uuid4()}",
        palace_mode=palace_mode,
        spine_url=spine_url,
        postgres_port=postgres_port,
    )
    _write_config(config)
    print(f"Initialized Nocturne at {target_home}. Run `nocturne up`.", file=stdout)
    return target


def load_config(*, home: Path | None = None) -> NocturneConfig:
    """Load, preserve-upgrade, and validate the generated local config."""

    target_home = home or nocturne_home()
    path = target_home / _CONFIG_FILE
    if not path.is_file():
        raise OnboardingError("Nocturne is not initialized. Run `nocturne init` first.")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise OnboardingError(
            f"Refusing insecure config permissions {mode:o}; run `chmod 600 {path}`."
        )
    values = _parse_config(path)
    version = values.get("NOCTURNE_CONFIG_VERSION")
    if version == "1":
        _upgrade_v1_config(path)
        values = _parse_config(path)
        version = values.get("NOCTURNE_CONFIG_VERSION")
    if version == "2":
        _upgrade_v2_config(path, target_home)
        values = _parse_config(path)
        version = values.get("NOCTURNE_CONFIG_VERSION")
    if version == "3":
        _upgrade_v3_config(path)
        values = _parse_config(path)
        version = values.get("NOCTURNE_CONFIG_VERSION")
    if version != _CONFIG_VERSION:
        raise OnboardingError("Unsupported Nocturne config version; reinstall or reinitialize.")
    port = _parse_port(values.get("NOCTURNE_POSTGRES_PORT", "5432"))
    backup_generations = _parse_backup_generations(
        values.get("NOCTURNE_BACKUP_GENERATIONS", str(_DEFAULT_BACKUP_GENERATIONS))
    )
    postgres_volume = _parse_postgres_volume(
        values.get("NOCTURNE_POSTGRES_VOLUME", ""), target_home
    )
    palace_mode = _parse_palace_mode(values.get("NOCTURNE_PALACE_MODE", ""))
    spine_url = (
        SPINE_URL if palace_mode == "local" else _parse_remote_url(values.get("SPINE_URL", ""))
    )
    required = ("OPENROUTER_API_KEY", "SPINE_TOKEN", "NOCTURNE_DB_PASSWORD", "MACHINE_ID")
    missing = [name for name in required if not values.get(name, "").strip()]
    if missing:
        raise OnboardingError(f"Nocturne config is missing required fields: {', '.join(missing)}")
    return NocturneConfig(
        home=target_home,
        openrouter_api_key=values["OPENROUTER_API_KEY"],
        spine_token=values["SPINE_TOKEN"],
        database_password=values["NOCTURNE_DB_PASSWORD"],
        machine_id=values["MACHINE_ID"],
        palace_mode=palace_mode,
        spine_url=spine_url,
        postgres_port=port,
        backup_generations=backup_generations,
        postgres_volume=postgres_volume,
    )


def up_nocturne(
    *,
    home: Path | None = None,
    open_browser: bool = True,
    stdout: TextIO = sys.stdout,
) -> int:
    """Start pgvector, migrate, supervise Spine + Harness, and open the browser."""

    config = load_config(home=home)
    _warn_if_low_disk(config.home, stdout=stdout)
    if config.palace_mode == "remote":
        return _up_remote(config, open_browser=open_browser, stdout=stdout)
    _require_command("docker")
    with resources.as_file(
        resources.files("harness").joinpath("resources", "docker-compose.yml")
    ) as compose_file:
        compose = [
            "docker",
            "compose",
            "--project-name",
            _compose_project(config.home),
            "--env-file",
            str(config.path),
            "--file",
            str(compose_file),
        ]
        _run([*compose, "pull", "postgres"])
        _run([*compose, "up", "--detach", "--wait", "postgres"])

    create_local_backup(config, reason="pre_migration", stdout=stdout)
    _upgrade_database(config.database_url)
    environment = config.process_environment()
    spine = _start_service(
        "spine.main:create_app",
        port=8000,
        environment=environment,
    )
    harness: subprocess.Popen[str] | None = None
    try:
        _wait_for_url(f"{SPINE_URL}/healthz", token=config.spine_token, process=spine)
        harness = _start_service(
            "harness.packaged:create_app",
            port=8765,
            environment=environment,
        )
        _wait_for_url(LOCAL_URL, process=harness)
        print(f"Nocturne is running at {LOCAL_URL}. Press Ctrl-C to stop it.", file=stdout)
        if open_browser:
            _open_browser(LOCAL_URL, stdout=stdout)
        _supervise((spine, harness))
        return 0
    finally:
        _stop_processes(tuple(process for process in (harness, spine) if process is not None))


def _up_remote(
    config: NocturneConfig,
    *,
    open_browser: bool,
    stdout: TextIO,
) -> int:
    """Start only the local daemon against an owner-operated remote Palace."""

    _wait_for_url(f"{config.spine_url}/health", token=config.spine_token)
    harness = _start_service(
        "harness.packaged:create_app",
        port=8765,
        environment=config.process_environment(),
    )
    try:
        _wait_for_url(LOCAL_URL, process=harness)
        print(f"Nocturne is running at {LOCAL_URL}. Press Ctrl-C to stop it.", file=stdout)
        if open_browser:
            _open_browser(LOCAL_URL, stdout=stdout)
        _supervise((harness,))
        return 0
    finally:
        _stop_processes((harness,))


def open_nocturne(*, stdout: TextIO = sys.stdout) -> int:
    """Open the running local Nocturne UI after a bounded reachability check."""

    _wait_for_url(LOCAL_URL, timeout=3.0)
    _open_browser(LOCAL_URL, stdout=stdout)
    return 0


def backup_nocturne(*, home: Path | None = None, stdout: TextIO = sys.stdout) -> Path:
    """Publish one verified local Palace backup generation."""

    config = load_config(home=home)
    _require_local_palace(config, operation="Backup")
    _require_command("docker")
    return create_local_backup(config, reason="manual", stdout=stdout)


def restore_nocturne(
    backup_id: str,
    *,
    home: Path | None = None,
    prompt: Callable[[str], str] = input,
    stdout: TextIO = sys.stdout,
) -> int:
    """Prepare an informed side-by-side restore and switch only after confirmation."""

    config = load_config(home=home)
    _require_local_palace(config, operation="Restore")
    _require_command("docker")
    if _service_reachable(LOCAL_URL) or _service_reachable(
        f"{SPINE_URL}/healthz", token=config.spine_token
    ):
        raise OnboardingError("Stop `nocturne up` before restoring the local Palace.")

    prepared = prepare_local_restore(config, backup_id)
    switched = False
    try:
        _print_rollback_manifest(prepared, stdout=stdout)
        expected = f"RESTORE {backup_id}"
        answer = prompt(f"Type {expected} to switch Palaces: ").strip()
        if answer != expected:
            print("Restore cancelled. The live Palace was not changed.", file=stdout)
            return 1
        receipt = activate_local_restore(
            config,
            prepared,
            set_active_volume=lambda volume: _set_active_postgres_volume(config, volume),
        )
        switched = True
        print(f"Restore complete. Rollback receipt: {receipt}.", file=stdout)
        return 0
    finally:
        if not switched:
            discard_prepared_restore(prepared)


def doctor_nocturne(*, home: Path | None = None, stdout: TextIO = sys.stdout) -> int:
    """Print a safe, read-only health report for the selected Palace rung."""

    config = load_config(home=home)
    if config.palace_mode == "remote":
        return _doctor_remote(config, stdout=stdout)
    report = inspect_local_palace(config)
    _print_doctor_report(report, stdout=stdout)
    return report.exit_code


def _doctor_remote(config: NocturneConfig, *, stdout: TextIO) -> int:
    """Inspect the remote service plus the durable state still owned by this daemon."""

    storage = local_storage_snapshot(config.home)
    remote_healthy = True
    try:
        _wait_for_url(f"{config.spine_url}/health", token=config.spine_token)
    except OnboardingError:
        remote_healthy = False
    low_disk = storage.low_disk
    status = "failed" if not remote_healthy else "warning" if low_disk else "healthy"
    print(f"Palace doctor: {status}", file=stdout)
    print(
        f"Remote Palace: {'healthy' if remote_healthy else 'unreachable'} at {config.spine_url}",
        file=stdout,
    )
    print(f"Conversation journal: {_human_bytes(storage.journal_bytes)}", file=stdout)
    print(
        f"Disk: {_human_bytes(storage.disk_free_bytes)} free of "
        f"{_human_bytes(storage.disk_total_bytes)}",
        file=stdout,
    )
    print("Local database and backup checks are skipped for a remote Palace.", file=stdout)
    if low_disk:
        print("Warning: Free disk space is below the early warning boundary.", file=stdout)
    return 2 if not remote_healthy else 1 if low_disk else 0


def _print_doctor_report(report: DoctorReport, *, stdout: TextIO) -> None:
    database = (
        "unavailable" if report.database_bytes is None else _human_bytes(report.database_bytes)
    )
    print(f"Palace doctor: {report.status}", file=stdout)
    print(f"Database: {database}", file=stdout)
    print(f"Conversation journal: {_human_bytes(report.journal_bytes)}", file=stdout)
    print(
        f"Backups: {report.backup_generations} verified, {_human_bytes(report.backup_bytes)}",
        file=stdout,
    )
    print(
        f"Disk: {_human_bytes(report.disk_free_bytes)} free of "
        f"{_human_bytes(report.disk_total_bytes)}",
        file=stdout,
    )
    for warning in report.warnings:
        print(f"Warning: {warning}", file=stdout)
    for failure in report.failures:
        print(f"Problem: {failure}", file=stdout)


def _print_rollback_manifest(prepared: PreparedRestore, *, stdout: TextIO) -> None:
    manifest = prepared.manifest
    print(f"Rollback manifest for backup {prepared.backup_id}", file=stdout)
    for heading, memories in (
        ("Memories lost", manifest.memories_lost),
        ("Edits reverted", manifest.edits_reverted),
        ("Pins undone", manifest.pins_undone),
    ):
        print(f"{heading}: {len(memories)}", file=stdout)
        for memory in memories:
            suffix = (
                ""
                if memory.candidate_revision is None
                else f" (revision {memory.current_revision} -> {memory.candidate_revision})"
            )
            print(f"  - {memory.label} [{memory.memory_id}]{suffix}", file=stdout)
    print("Event counts (current -> restored, delta):", file=stdout)
    for count in manifest.event_counts:
        print(
            f"  - {count.table}: {count.current} -> {count.candidate} "
            f"({count.candidate - count.current:+d})",
            file=stdout,
        )


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def _warn_if_low_disk(home: Path, *, stdout: TextIO) -> None:
    if local_storage_snapshot(home).low_disk:
        print(
            "Warning: Free disk space is low. Nocturne will continue; run `nocturne doctor` "
            "for details.",
            file=stdout,
        )


def _write_config(config: NocturneConfig) -> None:
    config.home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config.home, 0o700)
    values = {
        "NOCTURNE_CONFIG_VERSION": _CONFIG_VERSION,
        "NOCTURNE_PALACE_MODE": config.palace_mode,
        "SPINE_URL": config.spine_url,
        "OPENROUTER_API_KEY": config.openrouter_api_key,
        "SPINE_TOKEN": config.spine_token,
        "NOCTURNE_DB_PASSWORD": config.database_password,
        "NOCTURNE_POSTGRES_PORT": str(config.postgres_port),
        "NOCTURNE_BACKUP_GENERATIONS": str(config.backup_generations),
        "NOCTURNE_POSTGRES_VOLUME": config.active_postgres_volume,
        "MACHINE_ID": config.machine_id,
    }
    content = "".join(f"{name}={json.dumps(value)}\n" for name, value in values.items())
    _atomic_write_config(config.path, content)


def _atomic_write_config(path: Path, content: str) -> None:
    """Replace one private config durably without exposing a partial write."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _upgrade_v1_config(path: Path) -> None:
    """Apply the sole enacted config transition while retaining all secret lines."""

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    version_lines = [
        index for index, line in enumerate(lines) if line.startswith("NOCTURNE_CONFIG_VERSION=")
    ]
    if len(version_lines) != 1:
        raise OnboardingError("Nocturne config has an invalid version field.")
    lines[version_lines[0]] = 'NOCTURNE_CONFIG_VERSION="2"\n'
    lines.append(f"NOCTURNE_BACKUP_GENERATIONS={json.dumps(str(_DEFAULT_BACKUP_GENERATIONS))}\n")
    _atomic_write_config(path, "".join(lines))


def _upgrade_v2_config(path: Path, home: Path) -> None:
    """Add the preserving active-volume pointer required for side-by-side restore."""

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    version_lines = [
        index for index, line in enumerate(lines) if line.startswith("NOCTURNE_CONFIG_VERSION=")
    ]
    if len(version_lines) != 1:
        raise OnboardingError("Nocturne config has an invalid version field.")
    if any(line.startswith("NOCTURNE_POSTGRES_VOLUME=") for line in lines):
        raise OnboardingError("Nocturne version 2 config has an unexpected volume field.")
    lines[version_lines[0]] = 'NOCTURNE_CONFIG_VERSION="3"\n'
    lines.append(f"NOCTURNE_POSTGRES_VOLUME={json.dumps(_default_postgres_volume(home))}\n")
    _atomic_write_config(path, "".join(lines))


def _upgrade_v3_config(path: Path) -> None:
    """Make the formerly implicit local Palace mode explicit without changing secrets."""

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    version_lines = [
        index for index, line in enumerate(lines) if line.startswith("NOCTURNE_CONFIG_VERSION=")
    ]
    if len(version_lines) != 1:
        raise OnboardingError("Nocturne config has an invalid version field.")
    if any(line.startswith(("NOCTURNE_PALACE_MODE=", "SPINE_URL=")) for line in lines):
        raise OnboardingError("Nocturne version 3 config has unexpected Palace fields.")
    lines[version_lines[0]] = f"NOCTURNE_CONFIG_VERSION={json.dumps(_CONFIG_VERSION)}\n"
    lines.append('NOCTURNE_PALACE_MODE="local"\n')
    lines.append(f"SPINE_URL={json.dumps(SPINE_URL)}\n")
    _atomic_write_config(path, "".join(lines))


def _set_active_postgres_volume(config: NocturneConfig, volume: str) -> NocturneConfig:
    _parse_postgres_volume(volume, config.home)
    lines = config.path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = [
        index for index, line in enumerate(lines) if line.startswith("NOCTURNE_POSTGRES_VOLUME=")
    ]
    if len(matches) != 1:
        raise OnboardingError("Nocturne config has an invalid database volume field.")
    lines[matches[0]] = f"NOCTURNE_POSTGRES_VOLUME={json.dumps(volume)}\n"
    _atomic_write_config(config.path, "".join(lines))
    return load_config(home=config.home)


def _parse_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw or raw.startswith("#"):
            continue
        name, separator, encoded = raw.partition("=")
        if not separator or not name.isidentifier():
            raise OnboardingError(f"Invalid config line {line_number}.")
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise OnboardingError(f"Invalid config value on line {line_number}.") from exc
        if not isinstance(value, str):
            raise OnboardingError(f"Config value on line {line_number} must be a string.")
        values[name] = value
    return values


def _require_command(command: str) -> None:
    if shutil.which(command) is None:
        raise OnboardingError(f"{command} is required. Install Docker Desktop or Colima first.")


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise OnboardingError("NOCTURNE_POSTGRES_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise OnboardingError("NOCTURNE_POSTGRES_PORT must be between 1 and 65535.")
    return port


def _parse_backup_generations(value: str) -> int:
    try:
        generations = int(value)
    except ValueError as exc:
        raise OnboardingError("NOCTURNE_BACKUP_GENERATIONS must be an integer.") from exc
    if not 1 <= generations <= 50:
        raise OnboardingError("NOCTURNE_BACKUP_GENERATIONS must be between 1 and 50.")
    return generations


def _parse_palace_mode(value: str) -> str:
    if value not in {"local", "remote"}:
        raise OnboardingError("NOCTURNE_PALACE_MODE must be local or remote.")
    return value


def _parse_remote_url(value: str | None) -> str:
    candidate = "" if value is None else value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise OnboardingError("Remote Palace URL must be an http(s) service origin.")
    return candidate


def _require_local_palace(config: NocturneConfig, *, operation: str) -> None:
    if config.palace_mode != "local":
        raise OnboardingError(f"{operation} is available only for a local Palace.")


def _default_postgres_volume(home: Path) -> str:
    return f"{_compose_project(home)}_nocturne_postgres"


def _parse_postgres_volume(value: str, home: Path) -> str:
    project = _compose_project(home)
    default = f"{project}_nocturne_postgres"
    restore_prefix = f"{project}_restore_"
    suffix = value[len(restore_prefix) :] if value.startswith(restore_prefix) else ""
    if value != default and _LOWER_ULID_PATTERN.fullmatch(suffix) is None:
        raise OnboardingError("NOCTURNE_POSTGRES_VOLUME is not managed by this Nocturne home.")
    return value


def _service_reachable(url: str, *, token: str | None = None) -> bool:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=0.5).close()
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError):
        return False
    return True


def _compose_project(home: Path) -> str:
    if home == Path.home() / ".nocturne":
        return "nocturne"
    suffix = hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:8]
    return f"nocturne-{suffix}"


def _upgrade_database(database_url: str) -> None:
    from spine.db.migrate import upgrade_head

    upgrade_head(database_url)


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise OnboardingError(f"Command failed: {' '.join(command[:3])}") from exc


def _start_service(
    factory: str,
    *,
    port: int,
    environment: Mapping[str, str],
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            factory,
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=dict(environment),
        text=True,
    )


def _wait_for_url(
    url: str,
    *,
    token: str | None = None,
    process: subprocess.Popen[str] | None = None,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise OnboardingError(f"Service exited before becoming ready: {url}")
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=1.0
            ) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.2)
    raise OnboardingError(f"Timed out waiting for {url}")


def _open_browser(url: str, *, stdout: TextIO) -> None:
    if not webbrowser.open(url, new=2):
        print(f"Open {url} in a browser.", file=stdout)


def _supervise(processes: tuple[subprocess.Popen[str], ...]) -> None:
    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    raise OnboardingError(f"Nocturne service exited with status {return_code}.")
            time.sleep(0.25)
    except KeyboardInterrupt:
        return


def _stop_processes(processes: tuple[subprocess.Popen[str], ...]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
