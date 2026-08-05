"""Clone-free local onboarding for the public ``nocturne`` command."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
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
from urllib.parse import quote

from harness.lifecycle import create_local_backup

LOCAL_URL = "http://127.0.0.1:8765"
SPINE_URL = "http://127.0.0.1:8000"
_CONFIG_FILE = "env"
_CONFIG_VERSION = "2"
_DEFAULT_BACKUP_GENERATIONS = 5


class OnboardingError(RuntimeError):
    """A safe, user-actionable onboarding failure."""


@dataclass(frozen=True)
class NocturneConfig:
    """Generated local settings; only the OpenRouter key comes from the user."""

    home: Path
    openrouter_api_key: str
    spine_token: str
    database_password: str
    machine_id: str
    postgres_port: int = 5432
    backup_generations: int = _DEFAULT_BACKUP_GENERATIONS

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

    def process_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        environment = dict(os.environ if base is None else base)
        environment.update(
            {
                "OPENROUTER_API_KEY": self.openrouter_api_key,
                "SPINE_OPENAI_API_KEY": self.openrouter_api_key,
                "SPINE_TOKEN": self.spine_token,
                "SPINE_DATABASE_URL": self.database_url,
                "SPINE_URL": SPINE_URL,
                "NOCTURNE_HOME": str(self.home),
                "PRINCIPAL_ID": "local",
                "MACHINE_ID": self.machine_id,
                "AGENT_ID": "nocturne",
                "NOCTURNE_BACKUP_GENERATIONS": str(self.backup_generations),
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
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    stdout: TextIO = sys.stdout,
) -> Path:
    """Create the local secret file once, prompting for at most one secret."""

    values = os.environ if environ is None else environ
    target_home = home or nocturne_home(values)
    target = target_home / _CONFIG_FILE
    if target.exists():
        load_config(home=target_home)
        print(f"Nocturne is already initialized at {target_home}.", file=stdout)
        return target

    openrouter_key = values.get("OPENROUTER_API_KEY", "").strip()
    if not openrouter_key:
        openrouter_key = prompt("OpenRouter API key: ").strip()
    if not openrouter_key:
        raise OnboardingError("An OpenRouter API key is required.")
    postgres_port = _parse_port(values.get("NOCTURNE_POSTGRES_PORT", "5432"))

    config = NocturneConfig(
        home=target_home,
        openrouter_api_key=openrouter_key,
        spine_token=secrets.token_urlsafe(32),
        database_password=secrets.token_urlsafe(24),
        machine_id=f"nocturne-{uuid.uuid4()}",
        postgres_port=postgres_port,
    )
    _write_config(config)
    print(f"Initialized Nocturne at {target_home}. Run `nocturne up`.", file=stdout)
    return target


def load_config(*, home: Path | None = None) -> NocturneConfig:
    """Load and validate the generated local config without mutating it."""

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
    elif version != _CONFIG_VERSION:
        raise OnboardingError("Unsupported Nocturne config version; reinstall or reinitialize.")
    port = _parse_port(values.get("NOCTURNE_POSTGRES_PORT", "5432"))
    backup_generations = _parse_backup_generations(
        values.get("NOCTURNE_BACKUP_GENERATIONS", str(_DEFAULT_BACKUP_GENERATIONS))
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
        postgres_port=port,
        backup_generations=backup_generations,
    )


def up_nocturne(
    *,
    home: Path | None = None,
    open_browser: bool = True,
    stdout: TextIO = sys.stdout,
) -> int:
    """Start pgvector, migrate, supervise Spine + Harness, and open the browser."""

    config = load_config(home=home)
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


def open_nocturne(*, stdout: TextIO = sys.stdout) -> int:
    """Open the running local Nocturne UI after a bounded reachability check."""

    _wait_for_url(LOCAL_URL, timeout=3.0)
    _open_browser(LOCAL_URL, stdout=stdout)
    return 0


def backup_nocturne(*, home: Path | None = None, stdout: TextIO = sys.stdout) -> Path:
    """Publish one verified local Palace backup generation."""

    config = load_config(home=home)
    _require_command("docker")
    return create_local_backup(config, reason="manual", stdout=stdout)


def _write_config(config: NocturneConfig) -> None:
    config.home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config.home, 0o700)
    values = {
        "NOCTURNE_CONFIG_VERSION": _CONFIG_VERSION,
        "OPENROUTER_API_KEY": config.openrouter_api_key,
        "SPINE_TOKEN": config.spine_token,
        "NOCTURNE_DB_PASSWORD": config.database_password,
        "NOCTURNE_POSTGRES_PORT": str(config.postgres_port),
        "NOCTURNE_BACKUP_GENERATIONS": str(config.backup_generations),
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
    lines[version_lines[0]] = f"NOCTURNE_CONFIG_VERSION={json.dumps(_CONFIG_VERSION)}\n"
    lines.append(f"NOCTURNE_BACKUP_GENERATIONS={json.dumps(str(_DEFAULT_BACKUP_GENERATIONS))}\n")
    _atomic_write_config(path, "".join(lines))


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
