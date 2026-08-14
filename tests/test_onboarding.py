from __future__ import annotations

import io
import stat
import urllib.error
from dataclasses import asdict
from pathlib import Path

import pytest

from harness import onboarding
from harness.deploy import DeployError
from harness.transcript import TranscriptJournal


class _HealthResponse:
    def __enter__(self) -> _HealthResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"health"


class _PrivateVersionTripwire(dict[str, object]):
    def _guard(self, key: object) -> None:
        if key in {"schema_version", "version"}:
            pytest.fail(f"client compatibility read private {key}")

    def __contains__(self, key: object) -> bool:
        self._guard(key)
        return super().__contains__(key)

    def __getitem__(self, key: str) -> object:
        self._guard(key)
        return super().__getitem__(key)

    def get(self, key: str, default: object = None) -> object:
        self._guard(key)
        return super().get(key, default)


def _stub_remote_health(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(onboarding.json, "loads", lambda raw: payload)
    monkeypatch.setattr(
        onboarding.urllib.request,
        "urlopen",
        lambda request, timeout: (
            pytest.fail(f"unexpected health timeout {timeout}")
            if timeout != onboarding.PALACE_PROBE_TIMEOUT_SECONDS
            else _HealthResponse()
        ),
    )


def _ready_preflight() -> onboarding.DaemonPreflight:
    return onboarding.DaemonPreflight(
        existing=False,
        web_assets="ready",
        port="available",
        toolchain="not required",
        failures=(),
    )


def _initialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> onboarding.NocturneConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-openrouter-key")
    onboarding.init_nocturne(home=tmp_path, prompt=lambda _: "n", stdout=io.StringIO())
    return onboarding.load_config(home=tmp_path)


def test_init_prompts_once_and_generates_private_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 and A-057 are defended by verifying that init asks the backup choice and
    generates private config;
    this prevents drift in the private local owner onboarding contract.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    prompts: list[str] = []
    output = io.StringIO()

    path = onboarding.init_nocturne(
        home=tmp_path,
        prompt=lambda message: prompts.append(message)
        or ("one-owner-secret" if message == "OpenRouter API key: " else "n"),
        stdout=output,
    )
    config = onboarding.load_config(home=tmp_path)

    assert prompts == [
        "OpenRouter API key: ",
        "Back up conversation transcripts to your cloud Palace? [y/N] ",
    ]
    assert config.openrouter_api_key == "one-owner-secret"
    assert config.spine_token != config.database_password
    assert config.machine_id.startswith("nocturne-")
    assert config.transcript_backup is False
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "one-owner-secret" not in output.getvalue()
    assert config.spine_token not in output.getvalue()
    assert config.database_password not in output.getvalue()


def test_init_persists_the_a057_transcript_backup_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-057 makes transcript backup an explicit, default-off owner choice."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    monkeypatch.setattr(onboarding.shutil, "which", lambda _: None)

    onboarding.init_nocturne(
        home=tmp_path,
        prompt=lambda message: "yes" if "Back up conversation" in message else "",
        stdout=io.StringIO(),
    )

    config = onboarding.load_config(home=tmp_path)
    assert config.transcript_backup is True
    assert config.process_environment({})["NOCTURNE_TRANSCRIPT_BACKUP"] == "true"


def test_a057_discovery_accepts_only_one_spine_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-057 finds one owner Palace without remembering or mutating cloud state."""

    monkeypatch.setattr(onboarding.shutil, "which", lambda _: "/usr/bin/gcloud")

    def result(arguments: list[str], environ) -> object:
        del environ
        if arguments[:2] == ["auth", "list"]:
            return [{"account": "owner@example.test"}]
        if arguments[:3] == ["config", "get", "project"]:
            return "owner-project"
        return [
            {
                "metadata": {
                    "name": "nocturne-spine",
                    "labels": {"cloud.googleapis.com/location": "us-central1"},
                },
                "status": {"url": "https://spine.example.test"},
            }
        ]

    monkeypatch.setattr(onboarding, "_gcloud_json", result)
    assert onboarding._discover_cloud_palace({}) == (
        "owner-project",
        "us-central1",
        "https://spine.example.test",
    )


def test_a057_fresh_home_restores_palace_transcripts_before_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-057 tier 2 restores exact Palace rows into an empty home."""

    source = TranscriptJournal(tmp_path / "source")
    thread_id = "00000000-0000-0000-0000-000000005702"
    source.append_message(
        thread_id,
        {
            "message_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
            "role": "user",
            "content": "resurrect",
            "state": "complete",
        },
        parent_id=None,
    )
    records = source.cloud_records()
    config = onboarding.NocturneConfig(
        home=tmp_path / "fresh",
        openrouter_api_key="key",
        spine_token="token",
        database_password="password",
        machine_id="machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
        transcript_backup=True,
    )
    monkeypatch.setattr(
        onboarding,
        "_palace_json",
        lambda candidate, path: {
            "principal_id": "local",
            "records": [
                {
                    **asdict(record),
                    "received_at": "2026-08-14T12:00:00Z",
                }
                for record in records
            ],
        },
    )

    assert onboarding._restore_transcripts_from_palace(config) == 1
    restored = TranscriptJournal(config.home / "transcripts")
    assert restored.cloud_records() == records

    monkeypatch.setattr(
        onboarding,
        "_palace_json",
        lambda candidate, path: pytest.fail("existing journal must never be overwritten"),
    )
    assert onboarding._restore_transcripts_from_palace(config) == 0


def test_init_uses_environment_secret_and_existing_config_is_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 is defended by verifying that init uses environment secret and existing config
    is inert; this prevents drift in the private local owner onboarding contract.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")

    prompts: list[str] = []

    def backup_prompt(message: str) -> str:
        prompts.append(message)
        return "n"

    first = onboarding.init_nocturne(
        home=tmp_path,
        prompt=backup_prompt,
        stdout=io.StringIO(),
    )
    original = first.read_bytes()
    second = onboarding.init_nocturne(
        home=tmp_path,
        prompt=lambda _: pytest.fail("existing config must not prompt"),
        stdout=io.StringIO(),
    )

    assert second == first
    assert prompts == ["Back up conversation transcripts to your cloud Palace? [y/N] "]
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
        prompt=lambda message: prompts.append(message)
        or ("remote-bearer" if message == "Your Palace access token: " else "n"),
        stdout=io.StringIO(),
    )
    config = onboarding.load_config(home=tmp_path)

    assert prompts == [
        "Your Palace access token: ",
        "Back up conversation transcripts to your cloud Palace? [y/N] ",
    ]
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
    """ADR-019 keeps remote setup bounded to one explicit Palace service origin."""

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
    monkeypatch.setattr(onboarding, "_daemon_preflight", lambda candidate: _ready_preflight())

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
    """ADR-019, A-056, M2Z9, and SPEC B.6 rule 12 keep a same-minor Palace
    prompt-free while remote mode starts only the Rack.
    """

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    events: list[object] = []
    monkeypatch.setattr(
        onboarding,
        "_remote_api_contract_version",
        lambda service_url, token: "0.1.7",
    )
    monkeypatch.setattr(onboarding, "_daemon_preflight", lambda config: _ready_preflight())

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

    output = io.StringIO()
    assert (
        onboarding.up_nocturne(
            home=tmp_path,
            prompt=lambda message: pytest.fail(f"compatible contract prompted: {message}"),
            stdout=output,
        )
        == 0
    )
    assert events == [
        ("start", "harness.packaged:create_app", 8765, "https://spine.example.test"),
        ("wait", onboarding.LOCAL_URL, None),
        ("browser", onboarding.LOCAL_URL),
        ("supervise", 1),
        ("stop", 1),
    ]
    assert output.getvalue().splitlines()[0] == onboarding.PALACE_CHECKING_LINE


def test_remote_doctor_checks_spine_journal_and_disk_without_local_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019, A-056, M2Z9, and SPEC B.6 rule 12 require remote doctor to report its
    skipped local checks and the same API-contract range used by up.
    """

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    checks: list[tuple[str, str]] = []
    monkeypatch.setattr(
        onboarding,
        "_remote_api_contract_version",
        lambda service_url, token: (checks.append((service_url, token)), "0.1.7")[1],
    )
    monkeypatch.setattr(onboarding, "_daemon_preflight", lambda config: _ready_preflight())
    output = io.StringIO()

    assert onboarding.doctor_nocturne(home=tmp_path, stdout=output) == 0
    assert checks == [("https://spine.example.test", "remote-bearer")]
    rendered = output.getvalue()
    assert "Remote Palace: healthy" in rendered
    assert "Conversation journal:" in rendered
    assert "Disk:" in rendered
    assert "Palace API contract: 0.1.7 (app supports >=0.1.0,<0.2.0)" in rendered
    assert "Local database and backup checks are skipped for a remote Palace." in rendered


def test_remote_up_keeps_running_with_a_visible_notice_when_update_is_declined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-056, M2Z9, SPEC D.2 093, and SPEC B.6 rule 12 keep an older-contract Palace
    usable when its plain offered update is declined.
    """

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

    output = io.StringIO()
    probes: list[str] = []

    def palace_status(candidate: onboarding.NocturneConfig) -> tuple[str, str]:
        assert output.getvalue() == f"{onboarding.PALACE_CHECKING_LINE}\n"
        probes.append("health")
        return "0.0.9", "older"

    def release_guard(**kwargs: object) -> object:
        assert output.getvalue() == f"{onboarding.PALACE_CHECKING_LINE}\n"
        probes.append("guard")
        return type("Preflight", (), {"blocked": False})()

    monkeypatch.setattr(onboarding, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_remote_palace_status", palace_status)
    monkeypatch.setattr("harness.deploy.preflight_release_guard", release_guard)
    monkeypatch.setattr(onboarding, "_start_service", lambda *args, **kwargs: Process())
    monkeypatch.setattr(onboarding, "_supervise", lambda processes: None)
    monkeypatch.setattr(onboarding, "_stop_processes", lambda processes: None)
    prompts: list[str] = []

    assert (
        onboarding._up_remote(
            config,
            open_browser=False,
            prompt=lambda message: prompts.append(message) or "no",
            stdout=output,
        )
        == 0
    )
    assert "update was postponed" in output.getvalue()
    assert "Nocturne is running" in output.getvalue()
    assert output.getvalue().splitlines()[0] == onboarding.PALACE_CHECKING_LINE
    assert prompts == [
        "Your Palace needs an update to work with this version of Nocturne. Update now? "
        "Nocturne backs it up first; this takes a few minutes. [y/N] "
    ]
    assert "schema" not in prompts[0].lower()
    assert ">=" not in prompts[0]
    assert probes == ["health", "guard"]


def test_remote_up_acceptance_runs_full_deploy_with_the_same_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-056, M2Z9, SPEC D.2 093, and SPEC B.6 rule 12 make an older-contract update
    one plain `nocturne up` consent path.
    """

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
    monkeypatch.setattr(
        onboarding,
        "_remote_palace_status",
        lambda config: ("0.0.9", "older"),
    )
    monkeypatch.setattr(
        "harness.deploy.preflight_release_guard",
        lambda **kwargs: type("Preflight", (), {"blocked": False})(),
    )
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


def test_remote_up_refuses_when_the_narrow_release_guard_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2LC2, SPEC D.2 112, and B.6 rule 12 fail closed with the full dry-run
    remedy when the one startup guard fact cannot be observed.
    """

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )
    monkeypatch.setattr(
        onboarding,
        "_remote_palace_status",
        lambda candidate: ("0.0.9", "older"),
    )
    monkeypatch.setattr(
        "harness.deploy.preflight_release_guard",
        lambda **kwargs: (_ for _ in ()).throw(DeployError("offline")),
    )
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda *args, **kwargs: pytest.fail("blocked deploy started the daemon"),
    )

    with pytest.raises(onboarding.OnboardingError) as error:
        onboarding._up_remote(
            config,
            open_browser=False,
            prompt=lambda message: pytest.fail(f"blocked deploy prompted: {message}"),
            stdout=io.StringIO(),
        )

    assert "update guard could not be checked" in str(error.value)
    assert "`nocturne deploy --dry-run`" in str(error.value)
    assert "`nocturne up` again" in str(error.value)


def test_remote_up_refuses_newer_contract_without_offering_a_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-056, M2Z9, SPEC D.2 099, and SPEC B.6 rule 12 make newer-contract skew name
    the stale app plainly and refuse a Palace downgrade.
    """

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )
    monkeypatch.setattr(
        onboarding,
        "_remote_palace_status",
        lambda config: ("0.2.0", "newer"),
    )

    with pytest.raises(onboarding.OnboardingError) as error:
        onboarding._up_remote(
            config,
            open_browser=False,
            prompt=lambda message: pytest.fail("reverse skew offered a deployment"),
            stdout=io.StringIO(),
        )

    assert str(error.value) == (
        "This Nocturne app is older than your Palace. Upgrade Nocturne, then run nocturne up again."
    )
    assert "schema" not in str(error.value).lower()
    assert ">=" not in str(error.value)


@pytest.mark.parametrize(
    ("remote_contract", "relation"),
    [
        (None, "older"),
        ("0.0.9", "older"),
        ("0.1.0", "compatible"),
        ("0.1.9", "compatible"),
        ("0.2.0", "newer"),
        ("1.0.0", "newer"),
    ],
)
def test_api_contract_range_is_pre_one_same_minor_only(
    remote_contract: str | None, relation: str
) -> None:
    """M2Z9, A-055, and SPEC B.6 rule 12 bridge only absence, allow 0.1 patches, and
    explicitly withhold every minor-skew window, including at 1.0.
    """

    assert onboarding._api_contract_relation(remote_contract) == relation


def test_remote_contract_probe_never_reads_private_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2Z9, A-055, and SPEC B.6 rule 12 make product and schema-only changes
    behaviorally invisible to the contract-aware client.
    """

    payload = _PrivateVersionTripwire(
        api_contract_version="0.1.8",
        schema_version="9999_fixture",
        version="9.9.9",
    )
    _stub_remote_health(monkeypatch, payload)

    remote = onboarding._remote_api_contract_version("https://spine.example.test", "token")

    assert remote == "0.1.8"
    assert onboarding._api_contract_relation(remote) == "compatible"


def test_remote_palace_status_is_exactly_one_health_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M2LC2, SPEC D.2 112, and B.6 rule 12 make Palace compatibility one
    authenticated health probe rather than a readiness request followed by the same read.
    """

    calls: list[tuple[str, str]] = []
    config = onboarding.NocturneConfig(
        home=Path("/tmp/nocturne-m2lc2"),
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )
    monkeypatch.setattr(
        onboarding,
        "_remote_api_contract_version",
        lambda service_url, token: (calls.append((service_url, token)), "0.1.7")[1],
    )
    monkeypatch.setattr(
        onboarding,
        "_wait_for_url",
        lambda *args, **kwargs: pytest.fail("status performed a second health request"),
    )

    assert onboarding._remote_palace_status(config) == ("0.1.7", "compatible")
    assert calls == [("https://spine.example.test", "palace-token")]


def test_absent_contract_member_is_the_only_legacy_update_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-055, M2Z9, and SPEC B.6 rule 12 map an absent contract member to older without
    consulting the health body's product or schema versions.
    """

    payload = _PrivateVersionTripwire(schema_version="0012", version="0.1.2")
    _stub_remote_health(monkeypatch, payload)

    remote = onboarding._remote_api_contract_version("https://spine.example.test", "token")

    assert remote is None
    assert onboarding._api_contract_relation(remote) == "older"


@pytest.mark.parametrize("declared_contract", [None, "", " 0.1.0", "0.1", 101])
def test_present_invalid_api_contract_refuses_before_prompt_or_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared_contract: object,
) -> None:
    """A-055, M2Z9, SPEC D.2 095, and SPEC B.6 rule 12 refuse every present malformed
    contract without offering deploy and name the Palace-update plus doctor remedy.
    """

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )
    _stub_remote_health(monkeypatch, {"api_contract_version": declared_contract})
    monkeypatch.setattr(onboarding, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda *args, **kwargs: pytest.fail("invalid contract started the daemon"),
    )

    with pytest.raises(onboarding.OnboardingError) as error:
        onboarding._up_remote(
            config,
            open_browser=False,
            prompt=lambda message: pytest.fail(f"invalid contract prompted: {message}"),
            stdout=io.StringIO(),
        )

    assert "invalid API contract version" in str(error.value)
    assert "Update the Palace software" in str(error.value)
    assert "`nocturne doctor` again" in str(error.value)


@pytest.mark.parametrize(
    ("remote_contract", "relation", "exit_code", "message"),
    [
        ("0.0.9", "older", 1, "accept the offered update"),
        ("0.2.0", "newer", 2, "This Nocturne app is older than your Palace"),
    ],
)
def test_remote_doctor_matches_up_contract_skew_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_contract: str,
    relation: str,
    exit_code: int,
    message: str,
) -> None:
    """A-056, M2Z9, SPEC D.2 099, and SPEC B.6 rule 12 require doctor and up to share
    the contract-only update or refusal decision.
    """

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    monkeypatch.setattr(
        onboarding,
        "_daemon_preflight",
        lambda config: _ready_preflight(),
    )
    monkeypatch.setattr(
        onboarding,
        "_remote_palace_status",
        lambda config: (remote_contract, relation),
    )
    output = io.StringIO()

    assert onboarding.doctor_nocturne(home=tmp_path, stdout=output) == exit_code
    assert message in output.getvalue()


def test_remote_doctor_reports_malformed_contract_without_calling_palace_unreachable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-055, M2Z9, and SPEC B.6 rule 12 keep a reachable malformed-contract Palace
    reachable while doctor reports the exact fail-closed update remedy.
    """

    config = onboarding.NocturneConfig(
        home=tmp_path,
        openrouter_api_key="openrouter-fixture",
        spine_token="palace-token",
        database_password="unused-local-password",
        machine_id="fixture-machine",
        palace_mode="remote",
        spine_url="https://spine.example.test",
    )
    monkeypatch.setattr(onboarding, "_wait_for_url", lambda *args, **kwargs: None)
    _stub_remote_health(monkeypatch, {"api_contract_version": None})
    output = io.StringIO()

    assert onboarding._doctor_remote(config, preflight=_ready_preflight(), stdout=output) == 2
    rendered = output.getvalue()
    assert "Remote Palace: healthy" in rendered
    assert "Palace API contract: invalid" in rendered
    assert "Update the Palace software" in rendered
    assert "`nocturne doctor` again" in rendered
    assert "Remote Palace is unreachable" not in rendered


def test_up_adopts_an_existing_nocturne_without_starting_a_second_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 099 makes an occupied Nocturne port an ordinary adopt-existing path."""

    _initialized(tmp_path, monkeypatch)
    preflight = onboarding.DaemonPreflight(
        existing=True,
        web_assets="served",
        port="owned by Nocturne",
        toolchain="already running",
        failures=(),
    )
    monkeypatch.setattr(onboarding, "_daemon_preflight", lambda config: preflight)
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda *args, **kwargs: pytest.fail("adoption started another daemon"),
    )
    opened: list[str] = []
    monkeypatch.setattr(onboarding, "_open_browser", lambda url, *, stdout: opened.append(url))
    output = io.StringIO()

    assert onboarding.up_nocturne(home=tmp_path, stdout=output) == 0
    assert "already running" in output.getvalue()
    assert opened == [onboarding.LOCAL_URL]


def test_up_and_doctor_share_every_daemon_preflight_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 099 requires doctor's startup dependency checks to be an up superset."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    refusal = (
        "Port 8765 is occupied by another process; stop that process, then run `nocturne up` again."
    )
    preflight = onboarding.DaemonPreflight(
        existing=False,
        web_assets="ready",
        port="occupied",
        toolchain="ready",
        failures=(refusal,),
    )
    monkeypatch.setattr(onboarding, "_daemon_preflight", lambda config: preflight)
    monkeypatch.setattr(
        onboarding,
        "_remote_palace_status",
        lambda config: ("0.1.0", "compatible"),
    )

    with pytest.raises(onboarding.OnboardingError, match="Port 8765"):
        onboarding.up_nocturne(home=tmp_path, stdout=io.StringIO())
    output = io.StringIO()
    assert onboarding.doctor_nocturne(home=tmp_path, stdout=output) == 2
    assert f"Problem: {refusal}" in output.getvalue()


def test_up_refuses_a_read_only_journal_before_starting_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F030, ADR-016, and B.6 rule 12 require the owner command to state the journal remedy
    before any service starts; this prevents a generic child-process failure after startup.
    """
    _initialized(tmp_path, monkeypatch)
    transcript_root = tmp_path / "transcripts"
    transcript_root.mkdir(mode=0o500)
    monkeypatch.setattr(
        onboarding,
        "_daemon_preflight",
        lambda config: onboarding.DaemonPreflight(
            existing=False,
            web_assets="ready",
            port="available",
            toolchain="ready",
            failures=(),
        ),
    )
    monkeypatch.setattr(
        onboarding,
        "_start_service",
        lambda *args, **kwargs: pytest.fail("journal refusal started a service"),
    )

    try:
        with pytest.raises(onboarding.OnboardingError) as raised:
            onboarding.up_nocturne(home=tmp_path, stdout=io.StringIO())
    finally:
        transcript_root.chmod(0o700)

    assert "Conversation journal is not writable" in str(raised.value)
    assert "Fix that directory's permissions" in str(raised.value)
    assert "`nocturne up`" in str(raised.value)


def test_remote_backup_uses_the_verified_owner_cloud_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 099 makes Rung 2 backup a verified on-demand Cloud SQL backup."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    onboarding.init_nocturne(
        home=tmp_path,
        remote="https://spine.example.test",
        prompt=lambda _: "remote-bearer",
        stdout=io.StringIO(),
    )
    receipt = tmp_path / "cloud-backups" / "manual.json"
    commands: list[str] = []
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(onboarding, "_require_command", commands.append)
    monkeypatch.setattr(
        "harness.deploy.create_owner_cloud_backup",
        lambda **kwargs: calls.append(kwargs) or receipt,
    )
    output = io.StringIO()

    assert onboarding.backup_nocturne(home=tmp_path, stdout=output) == receipt
    assert commands == ["gcloud"]
    assert calls == [{"openrouter_key": "environment-secret", "home": tmp_path}]
    assert "Cloud SQL backup verified" in output.getvalue()


def test_open_requires_reachability_before_launching_browser(monkeypatch) -> None:
    """SPEC D.2 099 opens only a daemon identified as Nocturne."""
    events: list[str] = []
    monkeypatch.setattr(onboarding, "_existing_nocturne", lambda: True)
    monkeypatch.setattr(
        onboarding,
        "_open_browser",
        lambda url, *, stdout: events.append(f"open:{url}"),
    )

    assert onboarding.open_nocturne(stdout=io.StringIO()) == 0
    assert events == [f"open:{onboarding.LOCAL_URL}"]


def test_open_on_a_down_daemon_names_the_one_startup_remedy(monkeypatch) -> None:
    """SPEC D.2 099 and 095 require the down-daemon refusal to name its next action."""

    monkeypatch.setattr(onboarding, "_existing_nocturne", lambda: False)
    with pytest.raises(onboarding.OnboardingError) as error:
        onboarding.open_nocturne(stdout=io.StringIO())

    assert str(error.value) == "Nocturne isn't running — run `nocturne up`."


def test_readiness_stops_on_the_first_plain_web_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC D.2 095 prevents a permanent 503 from becoming a wall of readiness polling."""

    calls = 0

    def refuse(request, timeout):
        nonlocal calls
        del timeout
        calls += 1
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b"Nocturne's web app is missing. Install Node.js, then run the web build."),
        )

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(
        onboarding.time,
        "sleep",
        lambda _: pytest.fail("a permanent refusal must not be polled again"),
    )

    with pytest.raises(onboarding.OnboardingError) as error:
        onboarding._wait_for_url(onboarding.LOCAL_URL, stop_on_refusal=True)

    assert calls == 1
    assert str(error.value) == (
        "Nocturne's web app is missing. Install Node.js, then run the web build."
    )
