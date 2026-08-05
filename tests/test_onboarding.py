from __future__ import annotations

import io
import stat
from pathlib import Path

import pytest

from harness import onboarding


def _initialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> onboarding.NocturneConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-openrouter-key")
    onboarding.init_nocturne(home=tmp_path, stdout=io.StringIO())
    return onboarding.load_config(home=tmp_path)


def test_init_prompts_once_and_generates_private_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    prompts: list[str] = []
    output = io.StringIO()

    path = onboarding.init_nocturne(
        home=tmp_path,
        prompt=lambda message: prompts.append(message) or "one-owner-secret",
        stdout=output,
    )
    config = onboarding.load_config(home=tmp_path)

    assert prompts == ["OpenRouter API key: "]
    assert config.openrouter_api_key == "one-owner-secret"
    assert config.spine_token != config.database_password
    assert config.machine_id.startswith("nocturne-")
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "one-owner-secret" not in output.getvalue()
    assert config.spine_token not in output.getvalue()
    assert config.database_password not in output.getvalue()


def test_init_uses_environment_secret_and_existing_config_is_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")

    def unexpected_prompt(_: str) -> str:
        pytest.fail("init must not prompt")

    first = onboarding.init_nocturne(
        home=tmp_path,
        prompt=unexpected_prompt,
        stdout=io.StringIO(),
    )
    original = first.read_bytes()
    second = onboarding.init_nocturne(
        home=tmp_path,
        prompt=unexpected_prompt,
        stdout=io.StringIO(),
    )

    assert second == first
    assert first.read_bytes() == original


def test_load_rejects_group_or_world_readable_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _initialized(tmp_path, monkeypatch)
    config.path.chmod(0o640)

    with pytest.raises(onboarding.OnboardingError, match="insecure config permissions"):
        onboarding.load_config(home=tmp_path)


def test_process_environment_keeps_services_on_the_initialized_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _initialized(tmp_path, monkeypatch)

    environment = config.process_environment({})

    assert environment["NOCTURNE_HOME"] == str(tmp_path)


def test_up_orders_container_migration_services_and_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-042 places a verified receipt before migration while ADR-019 preserves startup order."""
    config = _initialized(tmp_path, monkeypatch)
    events: list[object] = []

    class Process:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def wait(self, timeout: int) -> int:
            del timeout
            return 0

    monkeypatch.setattr(onboarding, "_require_command", lambda command: events.append(command))
    monkeypatch.setattr(onboarding, "_run", lambda command: events.append(tuple(command)))
    monkeypatch.setattr(
        onboarding,
        "_upgrade_database",
        lambda database_url: events.append(("migrate", database_url)),
    )
    monkeypatch.setattr(
        onboarding,
        "create_local_backup",
        lambda config, *, reason, stdout: events.append(("backup", reason, config.home)),
    )
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda factory, *, port, environment: (
            events.append(("start", factory, port, environment["SPINE_TOKEN"])),
            Process(),
        )[1],
    )
    monkeypatch.setattr(
        onboarding,
        "_wait_for_url",
        lambda url, **kwargs: events.append(("wait", url, kwargs.get("token"))),
    )
    monkeypatch.setattr(onboarding, "_supervise", lambda processes: events.append("supervise"))
    monkeypatch.setattr(
        onboarding,
        "_stop_processes",
        lambda processes: events.append(("stop", len(processes))),
    )
    monkeypatch.setattr(
        onboarding,
        "_open_browser",
        lambda url, *, stdout: events.append(("browser", url)),
    )

    assert onboarding.up_nocturne(home=tmp_path, stdout=io.StringIO()) == 0

    docker_commands = [
        event for event in events if isinstance(event, tuple) and event[0] == "docker"
    ]
    assert any("pull" in command and "postgres" in command for command in docker_commands)
    assert any("up" in command and "--wait" in command for command in docker_commands)
    assert all("npm" not in command for command in docker_commands)
    migrate_index = next(index for index, event in enumerate(events) if event[0] == "migrate")
    backup_index = events.index(("backup", "pre_migration", config.home))
    spine_index = events.index(("start", "spine.main:create_app", 8000, config.spine_token))
    harness_index = events.index(("start", "harness.packaged:create_app", 8765, config.spine_token))
    assert backup_index < migrate_index < spine_index < harness_index
    assert ("browser", onboarding.LOCAL_URL) in events
    assert events[-1] == ("stop", 2)


def test_open_requires_reachability_before_launching_browser(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        onboarding,
        "_wait_for_url",
        lambda url, **kwargs: events.append(f"wait:{url}"),
    )
    monkeypatch.setattr(
        onboarding,
        "_open_browser",
        lambda url, *, stdout: events.append(f"open:{url}"),
    )

    assert onboarding.open_nocturne(stdout=io.StringIO()) == 0
    assert events == [f"wait:{onboarding.LOCAL_URL}", f"open:{onboarding.LOCAL_URL}"]
