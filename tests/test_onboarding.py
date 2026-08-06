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
    """ADR-019 is defended by verifying that init prompts once and generates private config;
    this prevents drift in the private local owner onboarding contract.
    """
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
    """ADR-019 is defended by verifying that init uses environment secret and existing config
    is inert; this prevents drift in the private local owner onboarding contract.
    """
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


def test_remote_init_records_one_palace_origin_and_prompts_only_for_its_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2S and ADR-019 require remote rung setup to fit the same two-command surface."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    prompts: list[str] = []

    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test/",
        prompt=lambda message: prompts.append(message) or "remote-bearer",
        stdout=io.StringIO(),
    )
    config = onboarding.load_config(home=tmp_path)

    assert prompts == ["Your Palace access token: "]
    assert config.palace_mode == "remote"
    assert config.spine_url == "https://spine.example.test"
    assert config.spine_token == "remote-bearer"
    environment = config.process_environment({})
    assert environment["SPINE_URL"] == config.spine_url
    assert "SPINE_DATABASE_URL" not in environment
    assert "NOCTURNE_POSTGRES_VOLUME" not in environment


@pytest.mark.parametrize(
    "remote",
    ["", "spine.example.test", "https://user:secret@spine.example.test", "https://x/y"],
)
def test_remote_init_rejects_values_that_are_not_service_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: str
) -> None:
    """M2S keeps remote setup bounded to one explicit Palace service origin."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    with pytest.raises(onboarding.OnboardingError, match="service origin"):
        onboarding.init_nocturne(home=tmp_path, remote=remote, stdout=io.StringIO())


def test_load_rejects_group_or_world_readable_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 is defended by verifying that load rejects group or world readable secret file;
    this prevents drift in the private local owner onboarding contract.
    """
    config = _initialized(tmp_path, monkeypatch)
    config.path.chmod(0o640)

    with pytest.raises(onboarding.OnboardingError, match="insecure config permissions"):
        onboarding.load_config(home=tmp_path)


def test_process_environment_keeps_services_on_the_initialized_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 is defended by verifying that process environment keeps services on the
    initialized home; this prevents drift in the private local owner onboarding contract.
    """
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


def test_remote_up_starts_only_the_daemon_and_opens_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2S requires remote mode to skip local containers and Spine while retaining the Rack."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    events: list[object] = []
    monkeypatch.setattr(onboarding, "_expected_schema_version", lambda: "0009_fixture")
    monkeypatch.setattr(
        onboarding, "_remote_schema_version", lambda service_url, token: "0009_fixture"
    )

    class Process:
        def poll(self) -> None:
            return None

    monkeypatch.setattr(
        onboarding,
        "_require_command",
        lambda command: pytest.fail(f"remote startup required {command}"),
    )
    monkeypatch.setattr(
        onboarding,
        "_run",
        lambda command: pytest.fail(f"remote startup ran {command}"),
    )
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda factory, *, port, environment: (
            events.append(("start", factory, port, environment["SPINE_URL"])),
            Process(),
        )[1],
    )
    monkeypatch.setattr(
        onboarding,
        "_wait_for_url",
        lambda url, **kwargs: events.append(("wait", url, kwargs.get("token"))),
    )
    monkeypatch.setattr(
        onboarding, "_supervise", lambda processes: events.append(("supervise", len(processes)))
    )
    monkeypatch.setattr(
        onboarding, "_stop_processes", lambda processes: events.append(("stop", len(processes)))
    )
    monkeypatch.setattr(
        onboarding, "_open_browser", lambda url, *, stdout: events.append(("browser", url))
    )

    assert onboarding.up_nocturne(home=tmp_path, stdout=io.StringIO()) == 0
    assert events == [
        ("wait", "https://spine.example.test/health", "remote-bearer"),
        ("start", "harness.packaged:create_app", 8765, "https://spine.example.test"),
        ("wait", onboarding.LOCAL_URL, None),
        ("browser", onboarding.LOCAL_URL),
        ("supervise", 1),
        ("stop", 1),
    ]


def test_remote_doctor_checks_spine_journal_and_disk_without_local_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2S requires remote doctor output to state exactly which local checks are skipped."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    checks: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        onboarding,
        "_wait_for_url",
        lambda url, **kwargs: checks.append((url, kwargs.get("token"))),
    )
    output = io.StringIO()

    assert onboarding.doctor_nocturne(home=tmp_path, stdout=output) == 0
    assert checks == [("https://spine.example.test/health", "remote-bearer")]
    rendered = output.getvalue()
    assert "Remote Palace: healthy" in rendered
    assert "Conversation journal:" in rendered
    assert "Disk:" in rendered
    assert "Local database and backup checks are skipped for a remote Palace." in rendered


def test_remote_up_keeps_running_with_a_visible_notice_when_update_is_declined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC v2.50 keeps an older remote Palace usable when its offered update is declined."""

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )

    class Process:
        def poll(self) -> None:
            return None

    monkeypatch.setattr(onboarding, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_remote_schema_version", lambda *args: "0002")
    monkeypatch.setattr(onboarding, "_expected_schema_version", lambda: "0009")
    monkeypatch.setattr(onboarding, "_start_service", lambda *args, **kwargs: Process())
    monkeypatch.setattr(onboarding, "_supervise", lambda processes: None)
    monkeypatch.setattr(onboarding, "_stop_processes", lambda processes: None)
    output = io.StringIO()

    assert (
        onboarding._up_remote(
            config,
            open_browser=False,
            prompt=lambda message: "no",
            stdout=output,
        )
        == 0
    )
    assert "update was postponed" in output.getvalue()
    assert "Nocturne is running" in output.getvalue()


def test_remote_up_acceptance_runs_full_deploy_with_the_same_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC v2.50 makes remote update a single `nocturne up` yes, including alignment consent."""

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )

    class Process:
        def poll(self) -> None:
            return None

    deploy_calls: list[dict[str, object]] = []
    monkeypatch.setattr(onboarding, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_remote_schema_version", lambda *args: "0002")
    monkeypatch.setattr(onboarding, "_expected_schema_version", lambda: "0009")
    monkeypatch.setattr(onboarding, "_start_service", lambda *args, **kwargs: Process())
    monkeypatch.setattr(onboarding, "_supervise", lambda processes: None)
    monkeypatch.setattr(onboarding, "_stop_processes", lambda processes: None)
    monkeypatch.setattr(
        "harness.deploy.run_cloud_deploy", lambda **kwargs: deploy_calls.append(kwargs)
    )

    assert (
        onboarding._up_remote(
            config,
            open_browser=False,
            prompt=lambda message: "yes",
            stdout=io.StringIO(),
        )
        == 0
    )
    assert deploy_calls == [
        {
            "dry_run": False,
            "openrouter_key": config.openrouter_api_key,
            "home": config.home,
            "credential_alignment_consent": True,
        }
    ]


def test_open_requires_reachability_before_launching_browser(monkeypatch) -> None:
    """ADR-019 is defended by verifying that open requires reachability before launching
    browser; this prevents drift in the private local owner onboarding contract.
    """
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
