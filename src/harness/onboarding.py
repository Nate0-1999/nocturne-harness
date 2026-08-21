"""Clone-free local onboarding for the public ``nocturne`` command."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
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

from harness.browser_runtime import (
    BrowserRuntimeError,
    browser_runtime_is_ready,
    browser_runtime_path,
    ensure_browser_runtime,
)
from harness.lifecycle import (
    DoctorReport,
    PreparedRestore,
    activate_local_restore,
    create_local_backup,
    discard_prepared_restore,
    inspect_local_palace,
    prepare_local_restore,
)
from harness.pi_runtime import (
    PiRuntimeError,
    ensure_pi_runtime,
    installed_pi_is_ready,
    installed_pi_path,
    pi_runtime_is_ready,
)
from harness.resources import local_storage_snapshot
from harness.transcript import JournalCloudRecord, TranscriptJournal, TranscriptJournalUnavailable

LOCAL_URL = "http://127.0.0.1:8765"
SPINE_URL = "http://127.0.0.1:8000"
_CONFIG_FILE = "env"
_CONFIG_VERSION = "5"
_DEFAULT_BACKUP_GENERATIONS = 5
_LOWER_ULID_PATTERN = re.compile(r"[0-7][0-9a-hjkmnp-tv-z]{25}\Z")
_API_CONTRACT_SEMVER_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
API_CONTRACT_MIN_VERSION = "0.1.0"
API_CONTRACT_MAX_VERSION = "0.2.0"
API_CONTRACT_RANGE = f">={API_CONTRACT_MIN_VERSION},<{API_CONTRACT_MAX_VERSION}"
PALACE_CHECKING_LINE = "Checking your Palace — a few seconds…"
PALACE_WARMING_LINE = "warming up your Palace — a few more seconds…"
STARTUP_SPEAKING_BUDGET_SECONDS = 2.0
PALACE_PROBE_TIMEOUT_SECONDS = 4.0
PALACE_COLD_PROBE_TIMEOUT_SECONDS = 30.0


class OnboardingError(RuntimeError):
    """A safe, user-actionable onboarding failure."""


class _ApiContractVersionError(OnboardingError):
    """A reachable Palace declared a malformed public API contract version."""


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
    transcript_backup: bool = False

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
                "NOCTURNE_TRANSCRIPT_BACKUP": "true" if self.transcript_backup else "false",
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
        pi_command = installed_pi_path(self.home)
        if installed_pi_is_ready(self.home):
            environment["NOCTURNE_PI_COMMAND"] = str(pi_command)
        if browser_runtime_is_ready(self.home):
            environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_runtime_path(self.home))
        return environment


@dataclass(frozen=True, slots=True)
class DaemonPreflight:
    """Read-only startup dependencies shared by ``up`` and ``doctor``."""

    existing: bool
    web_assets: str
    port: str
    toolchain: str
    failures: tuple[str, ...]


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
        _ensure_tool_runtimes(target_home, stdout=stdout)
        print(f"Nocturne is already initialized at {target_home}.", file=stdout)
        return target

    discovered = None if remote is not None else _discover_cloud_palace(values)
    if discovered is not None:
        project, region, discovered_url = discovered
        answer = prompt(f"Found your Palace ({project}, {region}) — reconnect? [y/N] ").strip()
        if answer.lower() in {"y", "yes"}:
            remote = discovered_url
            discovered_token = _read_discovered_palace_token(project, values)
        else:
            discovered_token = None
    else:
        discovered_token = None
    palace_mode = "remote" if remote is not None else "local"
    spine_url = _parse_remote_url(remote) if remote is not None else SPINE_URL
    openrouter_key = values.get("OPENROUTER_API_KEY", "").strip()
    if not openrouter_key:
        openrouter_key = prompt("OpenRouter API key: ").strip()
    if not openrouter_key:
        raise OnboardingError("An OpenRouter API key is required.")
    spine_token = secrets.token_urlsafe(32)
    if palace_mode == "remote":
        spine_token = discovered_token or prompt("Your Palace access token: ").strip()
        if not spine_token:
            raise OnboardingError("Your Palace access token is required for a remote Palace.")
    postgres_port = _parse_port(values.get("NOCTURNE_POSTGRES_PORT", "5432"))
    transcript_backup = prompt(
        "Back up conversation transcripts to your cloud Palace? [y/N] "
    ).strip().lower() in {"y", "yes"}

    config = NocturneConfig(
        home=target_home,
        openrouter_api_key=openrouter_key,
        spine_token=spine_token,
        database_password=secrets.token_urlsafe(24),
        machine_id=f"nocturne-{uuid.uuid4()}",
        palace_mode=palace_mode,
        spine_url=spine_url,
        postgres_port=postgres_port,
        transcript_backup=transcript_backup,
    )
    _write_config(config)
    _ensure_tool_runtimes(target_home, stdout=stdout)
    print(f"Initialized Nocturne at {target_home}. Run `nocturne up`.", file=stdout)
    return target


def _ensure_tool_runtimes(home: Path, *, stdout: TextIO) -> None:
    if not pi_runtime_is_ready(home):
        print("Preparing Nocturne's pinned workspace tools…", file=stdout, flush=True)
    try:
        ensure_pi_runtime(home)
    except PiRuntimeError as exc:
        raise OnboardingError(str(exc)) from exc
    if not browser_runtime_is_ready(home):
        print("Preparing Nocturne's headless browser…", file=stdout, flush=True)
    try:
        ensure_browser_runtime(home)
    except BrowserRuntimeError as exc:
        raise OnboardingError(str(exc)) from exc


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
    if version == "4":
        _upgrade_v4_config(path)
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
    transcript_backup = _parse_bool(
        values.get("NOCTURNE_TRANSCRIPT_BACKUP", "false"),
        "NOCTURNE_TRANSCRIPT_BACKUP",
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
        transcript_backup=transcript_backup,
    )


def up_nocturne(
    *,
    home: Path | None = None,
    open_browser: bool = True,
    prompt: Callable[[str], str] = input,
    stdout: TextIO = sys.stdout,
) -> int:
    """Start pgvector, migrate, supervise Spine + Harness, and open the browser."""

    config = load_config(home=home)
    _warn_if_low_disk(config.home, stdout=stdout)
    preflight = _daemon_preflight(config)
    if preflight.existing:
        print(f"Nocturne is already running at {LOCAL_URL}; using it.", file=stdout)
        if open_browser:
            _open_browser(LOCAL_URL, stdout=stdout)
        return 0
    if preflight.failures:
        raise OnboardingError(preflight.failures[0])
    _require_writable_journal(config.home)
    if config.palace_mode == "remote":
        return _up_remote(config, open_browser=open_browser, prompt=prompt, stdout=stdout)
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
        _restore_transcripts_from_palace(config, stdout=stdout)
        harness = _start_service(
            "harness.packaged:create_app",
            port=8765,
            environment=environment,
        )
        _wait_for_url(LOCAL_URL, process=harness, stop_on_refusal=True)
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
    prompt: Callable[[str], str],
    stdout: TextIO,
) -> int:
    """Start only the local daemon against an owner-operated remote Palace."""

    print(PALACE_CHECKING_LINE, file=stdout, flush=True)
    _, relation = _remote_palace_status(config, stdout=stdout)
    if relation == "newer":
        raise OnboardingError(_app_older_refusal())
    if relation == "older":
        from harness.deploy import DeployError, preflight_release_guard

        try:
            release_guard = preflight_release_guard(
                openrouter_key=config.openrouter_api_key,
            )
        except DeployError as exc:
            raise OnboardingError(
                "The Palace update guard could not be checked. Run "
                "`nocturne deploy --dry-run`, fix the reported problem, then run "
                "`nocturne up` again."
            ) from exc
        if release_guard.blocked:
            print(
                "Your app includes unreleased changes; your Palace is compatible; "
                "Nocturne will start normally.",
                file=stdout,
            )
        else:
            answer = prompt(
                "Your Palace needs an update to work with this version of Nocturne. Update now? "
                "Nocturne backs it up first; this takes a few minutes. [y/N] "
            ).strip()
            if answer.lower() in {"y", "yes"}:
                from harness.deploy import run_cloud_deploy

                run_cloud_deploy(
                    dry_run=False,
                    openrouter_key=config.openrouter_api_key,
                    home=config.home,
                    credential_alignment_consent=True,
                )
            else:
                print(
                    "Your Palace update was postponed; some newer screens may be unavailable.",
                    file=stdout,
                )
    _restore_transcripts_from_palace(config, stdout=stdout)
    harness = _start_service(
        "harness.packaged:create_app",
        port=8765,
        environment=config.process_environment(),
    )
    try:
        _wait_for_url(LOCAL_URL, process=harness, stop_on_refusal=True)
        print(f"Nocturne is running at {LOCAL_URL}. Press Ctrl-C to stop it.", file=stdout)
        if open_browser:
            _open_browser(LOCAL_URL, stdout=stdout)
        _supervise((harness,))
        return 0
    finally:
        _stop_processes((harness,))


def _read_palace_json(
    request: urllib.request.Request,
    *,
    stdout: TextIO,
    failure_message: str,
) -> object:
    """Read one Palace response, allowing exactly one scale-to-zero warm-up retry."""

    def read_once(timeout: float) -> object:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    try:
        return read_once(PALACE_PROBE_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        raise OnboardingError(failure_message) from exc
    except OSError:
        print(PALACE_WARMING_LINE, file=stdout, flush=True)
        try:
            return read_once(PALACE_COLD_PROBE_TIMEOUT_SECONDS)
        except (OSError, ValueError) as exc:
            raise OnboardingError(failure_message) from exc
    except ValueError as exc:
        raise OnboardingError(failure_message) from exc


def _remote_api_contract_version(
    service_url: str,
    token: str,
    *,
    stdout: TextIO = sys.stdout,
) -> str | None:
    request = urllib.request.Request(
        f"{service_url.rstrip('/')}/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = _read_palace_json(
        request,
        stdout=stdout,
        failure_message=(
            "The remote Palace API contract could not be read; check its health and try again."
        ),
    )
    if not isinstance(payload, Mapping):
        raise OnboardingError(
            "The remote Palace API contract could not be read; check its health and try again."
        )
    if "api_contract_version" not in payload:
        return None
    value = payload["api_contract_version"]
    if not isinstance(value, str):
        raise _invalid_api_contract_version()
    _api_contract_semver(value)
    return value


def _invalid_api_contract_version() -> _ApiContractVersionError:
    return _ApiContractVersionError(
        "The remote Palace reported an invalid API contract version. Update the Palace "
        "software, then run `nocturne doctor` again."
    )


def _api_contract_semver(value: str) -> tuple[int, int, int]:
    match = _API_CONTRACT_SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise _invalid_api_contract_version()
    return tuple(int(part) for part in match.groups())


def _api_contract_relation(remote_contract: str | None) -> str:
    """Classify one Palace against the pinned pre-1.0 same-minor range."""

    if remote_contract is None:
        return "older"
    remote = _api_contract_semver(remote_contract)
    minimum = _api_contract_semver(API_CONTRACT_MIN_VERSION)
    maximum = _api_contract_semver(API_CONTRACT_MAX_VERSION)
    if remote < minimum:
        return "older"
    return "compatible" if remote < maximum else "newer"


def _remote_palace_status(
    config: NocturneConfig,
    *,
    stdout: TextIO = sys.stdout,
) -> tuple[str | None, str]:
    """Probe the remote Palace and compare only its public API contract."""

    remote_contract = _remote_api_contract_version(
        config.spine_url,
        config.spine_token,
        stdout=stdout,
    )
    return remote_contract, _api_contract_relation(remote_contract)


def _app_older_refusal() -> str:
    return (
        "This Nocturne app is older than your Palace. Upgrade Nocturne, then run nocturne up again."
    )


def open_nocturne(*, stdout: TextIO = sys.stdout) -> int:
    """Open the running local Nocturne UI after a bounded reachability check."""

    if not _existing_nocturne():
        raise OnboardingError("Nocturne isn't running — run `nocturne up`.")
    _open_browser(LOCAL_URL, stdout=stdout)
    return 0


def backup_nocturne(*, home: Path | None = None, stdout: TextIO = sys.stdout) -> Path:
    """Publish one verified backup generation for the selected Palace rung."""

    config = load_config(home=home)
    if config.palace_mode == "remote":
        _require_command("gcloud")
        from harness.deploy import create_owner_cloud_backup

        receipt = create_owner_cloud_backup(
            openrouter_key=config.openrouter_api_key,
            home=config.home,
        )
        print(f"Cloud SQL backup verified. Receipt: {receipt}", file=stdout)
        return receipt
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
    preflight = _daemon_preflight(config)
    print(
        f"Conversation transcript backup: {'on' if config.transcript_backup else 'off'}",
        file=stdout,
    )
    if config.transcript_backup:
        _print_transcript_backup_status(config, stdout=stdout)
    if config.palace_mode == "remote":
        return _doctor_remote(config, preflight=preflight, stdout=stdout)
    report = inspect_local_palace(config)
    _print_doctor_report(report, preflight=preflight, stdout=stdout)
    return 2 if preflight.failures else report.exit_code


def _doctor_remote(
    config: NocturneConfig,
    *,
    preflight: DaemonPreflight,
    stdout: TextIO,
) -> int:
    """Inspect the remote service plus the durable state still owned by this daemon."""

    storage = local_storage_snapshot(config.home)
    remote_healthy = True
    contract_warning: str | None = None
    contract_failure: str | None = None
    remote_contract: str | None = None
    contract_display = "not reported"
    try:
        remote_contract, relation = _remote_palace_status(config, stdout=stdout)
        contract_display = remote_contract or "not reported"
        if relation == "older":
            contract_warning = (
                f"Remote Palace API contract {remote_contract or 'not reported'} is older than "
                f"this app's supported range {API_CONTRACT_RANGE}; run `nocturne up` and "
                "accept the offered update."
            )
        elif relation == "newer":
            contract_failure = _app_older_refusal()
    except _ApiContractVersionError as exc:
        contract_display = "invalid"
        contract_failure = str(exc)
    except OnboardingError:
        remote_healthy = False
    low_disk = storage.low_disk
    failed = not remote_healthy or contract_failure is not None or bool(preflight.failures)
    warned = low_disk or contract_warning is not None
    status = "failed" if failed else "warning" if warned else "healthy"
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
    _print_daemon_preflight(preflight, stdout=stdout)
    print("Local database and backup checks are skipped for a remote Palace.", file=stdout)
    if remote_healthy:
        print(
            f"Palace API contract: {contract_display} (app supports {API_CONTRACT_RANGE})",
            file=stdout,
        )
    if not remote_healthy:
        print(
            "Problem: Remote Palace is unreachable; check its URL and access token, then run "
            "`nocturne doctor` again.",
            file=stdout,
        )
    if contract_failure is not None:
        print(f"Problem: {contract_failure}", file=stdout)
    if contract_warning is not None:
        print(f"Warning: {contract_warning}", file=stdout)
    if low_disk:
        print("Warning: Free disk space is below the early warning boundary.", file=stdout)
    return 2 if failed else 1 if warned else 0


def _print_doctor_report(
    report: DoctorReport,
    *,
    preflight: DaemonPreflight,
    stdout: TextIO,
) -> None:
    database = (
        "unavailable" if report.database_bytes is None else _human_bytes(report.database_bytes)
    )
    status = "failed" if preflight.failures else report.status
    print(f"Palace doctor: {status}", file=stdout)
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
    _print_daemon_preflight(preflight, stdout=stdout)
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
        "NOCTURNE_TRANSCRIPT_BACKUP": "true" if config.transcript_backup else "false",
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
    lines[version_lines[0]] = 'NOCTURNE_CONFIG_VERSION="4"\n'
    lines.append('NOCTURNE_PALACE_MODE="local"\n')
    lines.append(f"SPINE_URL={json.dumps(SPINE_URL)}\n")
    _atomic_write_config(path, "".join(lines))


def _upgrade_v4_config(path: Path) -> None:
    """Add the owner-controlled transcript backup choice, preserving opt-in."""

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    version_lines = [
        index for index, line in enumerate(lines) if line.startswith("NOCTURNE_CONFIG_VERSION=")
    ]
    if len(version_lines) != 1:
        raise OnboardingError("Nocturne config has an invalid version field.")
    if any(line.startswith("NOCTURNE_TRANSCRIPT_BACKUP=") for line in lines):
        raise OnboardingError("Nocturne version 4 config has an unexpected transcript field.")
    lines[version_lines[0]] = f"NOCTURNE_CONFIG_VERSION={json.dumps(_CONFIG_VERSION)}\n"
    lines.append('NOCTURNE_TRANSCRIPT_BACKUP="false"\n')
    _atomic_write_config(path, "".join(lines))


def set_transcript_backup(config: NocturneConfig, enabled: bool) -> NocturneConfig:
    """Atomically persist the settings-gear transcript choice."""

    lines = config.path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = [
        index for index, line in enumerate(lines) if line.startswith("NOCTURNE_TRANSCRIPT_BACKUP=")
    ]
    if len(matches) != 1:
        raise OnboardingError("Nocturne config has an invalid transcript backup field.")
    lines[matches[0]] = f"NOCTURNE_TRANSCRIPT_BACKUP={json.dumps('true' if enabled else 'false')}\n"
    _atomic_write_config(config.path, "".join(lines))
    return load_config(home=config.home)


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


def _parse_bool(value: str, name: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise OnboardingError(f"{name} must be true or false.")


def _gcloud_json(arguments: list[str], environ: Mapping[str, str]) -> object:
    try:
        completed = subprocess.run(
            ["gcloud", *arguments, "--format=json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env=dict(environ),
        )
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise OnboardingError(
            "Google Cloud discovery could not safely read your account. Run `gcloud auth list` "
            "and `gcloud config get project`, fix the reported problem, then retry."
        ) from exc


def _discover_cloud_palace(environ: Mapping[str, str]) -> tuple[str, str, str] | None:
    """Return one unambiguous owner Palace using read-only ambient gcloud state."""

    if shutil.which("gcloud") is None:
        return None
    if any(
        environ.get(name, "").strip()
        for name in (
            "GOOGLE_APPLICATION_CREDENTIALS",
            "CLOUDSDK_AUTH_ACCESS_TOKEN",
            "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        )
    ):
        raise OnboardingError(
            "Palace discovery refuses credential overrides. Clear the Google credential "
            "override and use one signed-in gcloud owner account."
        )
    accounts = _gcloud_json(["auth", "list", "--filter=status:ACTIVE"], environ)
    if accounts == []:
        return None
    if not isinstance(accounts, list) or len(accounts) != 1:
        raise OnboardingError(
            "Palace discovery needs exactly one active gcloud owner account. Run `gcloud auth "
            "list` and select one account, then retry."
        )
    account = accounts[0]
    if not isinstance(account, dict) or not isinstance(account.get("account"), str):
        raise OnboardingError("Palace discovery received an unreadable gcloud account response.")
    if account["account"].endswith(".gserviceaccount.com"):
        raise OnboardingError(
            "Palace discovery requires a signed-in human owner, not a service account. "
            "Run `gcloud auth login`, select that account, then retry."
        )
    project_result = _gcloud_json(["config", "get", "project"], environ)
    project = project_result if isinstance(project_result, str) else None
    if project is None or not project.strip():
        raise OnboardingError(
            "Palace discovery needs one active gcloud project. Run `gcloud config set project "
            "PROJECT_ID`, then retry."
        )
    try:
        services = _gcloud_json(
            ["run", "services", "list", "--project", project, "--platform=managed"], environ
        )
    except OnboardingError:
        return None
    if not isinstance(services, list):
        raise OnboardingError("Palace discovery received an unreadable Cloud Run response.")
    matches: list[tuple[str, str]] = []
    for service in services:
        if not isinstance(service, dict):
            continue
        metadata = service.get("metadata")
        status_value = service.get("status")
        if not isinstance(metadata, dict) or not isinstance(status_value, dict):
            continue
        name = metadata.get("name")
        if not isinstance(name, str) or not name.endswith("-spine"):
            continue
        labels = metadata.get("labels")
        url = status_value.get("url")
        region = labels.get("cloud.googleapis.com/location") if isinstance(labels, dict) else None
        if not isinstance(url, str) or not isinstance(region, str) or not region.strip():
            raise OnboardingError("Palace discovery found a malformed Cloud Run service.")
        try:
            matches.append((region, _parse_remote_url(url)))
        except OnboardingError as exc:
            raise OnboardingError("Palace discovery found a malformed Cloud Run service.") from exc
    if not matches:
        return None
    if len(matches) != 1:
        return None
    return project, matches[0][0], matches[0][1]


def _read_discovered_palace_token(project: str, environ: Mapping[str, str]) -> str:
    try:
        completed = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                "--secret=spine-token",
                "--project",
                project,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env=dict(environ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OnboardingError(
            "Your Palace was selected, but its access token could not be read. Confirm Secret "
            "Manager access with gcloud, then retry."
        ) from exc
    token = completed.stdout.strip()
    if not token:
        raise OnboardingError("Your Palace access token secret is empty.")
    return token


def _palace_json(
    config: NocturneConfig,
    path: str,
    *,
    stdout: TextIO = sys.stdout,
) -> object:
    request = urllib.request.Request(
        f"{config.spine_url.rstrip('/')}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {config.spine_token}"},
    )
    return _read_palace_json(
        request,
        stdout=stdout,
        failure_message=(
            "Conversation backup could not reach the Palace transcript service. Update the "
            "Palace if offered, then run `nocturne doctor` and try again."
        ),
    )


def _restore_transcripts_from_palace(
    config: NocturneConfig,
    *,
    stdout: TextIO = sys.stdout,
) -> int:
    if not config.transcript_backup:
        return 0
    journal = TranscriptJournal(config.home / "transcripts")
    if journal.cloud_records():
        return 0
    payload = _palace_json(
        config,
        "/v1/transcripts?principal_id=local",
        stdout=stdout,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise OnboardingError("The Palace returned an unreadable transcript backup.")
    records: list[JournalCloudRecord] = []
    try:
        for raw in payload["records"]:
            if not isinstance(raw, dict):
                raise ValueError
            records.append(
                JournalCloudRecord(
                    thread_id=str(uuid.UUID(raw["thread_id"])),
                    sequence=int(raw["sequence"]),
                    journal_line=raw["journal_line"],
                    sha256=raw["sha256"],
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise OnboardingError("The Palace returned an unreadable transcript backup.") from exc
    try:
        return journal.restore_cloud_records(tuple(records))
    except TranscriptJournalUnavailable as exc:
        raise OnboardingError(str(exc)) from exc


def _print_transcript_backup_status(config: NocturneConfig, *, stdout: TextIO) -> None:
    try:
        payload = _palace_json(
            config,
            "/v1/transcripts/status?principal_id=local",
            stdout=stdout,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("record_count"), int):
            raise OnboardingError("The Palace returned an unreadable transcript status.")
        print(f"Palace transcript records: {payload['record_count']}", file=stdout)
    except OnboardingError:
        print(
            "Palace transcript records: waiting — check Palace reachability and run "
            "`nocturne doctor` again.",
            file=stdout,
        )


def _require_command(command: str) -> None:
    if shutil.which(command) is None:
        if command == "docker":
            remedy = "Install Docker Desktop or Colima first"
        elif command == "gcloud":
            remedy = "Install the Google Cloud CLI and sign in first"
        else:
            remedy = f"Install {command} first"
        raise OnboardingError(f"{command} is required. {remedy}, then run the command again.")


def _daemon_preflight(config: NocturneConfig) -> DaemonPreflight:
    """Inspect every local daemon startup dependency without mutating it."""

    if _existing_nocturne():
        return DaemonPreflight(
            existing=True,
            web_assets="served by the running Nocturne daemon",
            port="8765 is owned by the running Nocturne daemon",
            toolchain="already running",
            failures=(),
        )

    from harness.packaged import inspect_runtime_web_assets

    assets = inspect_runtime_web_assets()
    failures: list[str] = []
    if assets.ready:
        web_assets = f"ready at {assets.path}"
    elif assets.buildable:
        web_assets = "buildable with npm at startup"
    else:
        web_assets = "not ready"
        failures.append(
            assets.refusal
            or "Nocturne's web app is unavailable; reinstall Nocturne, then run `nocturne up`."
        )

    if _port_available(8765):
        port = "8765 is available"
    else:
        port = "8765 is occupied by another process"
        failures.append(
            "Port 8765 is occupied by another process; stop that process, then run "
            "`nocturne up` again."
        )

    if config.palace_mode == "local":
        if shutil.which("docker") is None:
            toolchain = "Docker is unavailable"
            failures.append(
                "docker is required. Install Docker Desktop or Colima first, then run "
                "`nocturne up` again."
            )
        else:
            toolchain = "Docker is available"
    else:
        toolchain = "no local Palace toolchain is required"

    return DaemonPreflight(
        existing=False,
        web_assets=web_assets,
        port=port,
        toolchain=toolchain,
        failures=tuple(failures),
    )


def _require_writable_journal(home: Path) -> None:
    """Prove the mandatory journal before starting either Palace rung."""

    try:
        TranscriptJournal(home / "transcripts")
    except TranscriptJournalUnavailable as exc:
        raise OnboardingError(str(exc)) from exc


def _print_daemon_preflight(preflight: DaemonPreflight, *, stdout: TextIO) -> None:
    print(f"Web app: {preflight.web_assets}", file=stdout)
    print(f"Port: {preflight.port}", file=stdout)
    print(f"Startup toolchain: {preflight.toolchain}", file=stdout)
    for failure in preflight.failures:
        print(f"Problem: {failure}", file=stdout)


def _port_available(port: int) -> bool:
    try:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def _existing_nocturne() -> bool:
    request = urllib.request.Request(f"{LOCAL_URL}/openapi.json")
    try:
        with urllib.request.urlopen(request, timeout=0.5) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return False
    info = payload.get("info") if isinstance(payload, Mapping) else None
    return isinstance(info, Mapping) and info.get("title") == "NOCTURNE"


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
    stop_on_refusal: bool = False,
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
        except urllib.error.HTTPError as exc:
            if stop_on_refusal and exc.code == 503:
                body = exc.read(4096).decode("utf-8", errors="replace")
                message = " ".join(body.split())
                if message:
                    raise OnboardingError(message) from exc
                raise OnboardingError(
                    "Nocturne could not start its web app. Run `nocturne doctor`, then try "
                    "`nocturne up` again."
                ) from exc
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
