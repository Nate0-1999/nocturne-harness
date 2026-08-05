from __future__ import annotations

import io

import pytest

from harness import cli
from harness.onboarding import NocturneConfig, OnboardingError


def test_parser_exposes_onboarding_and_lifecycle_commands() -> None:
    """ADR-019, A-042, and A-045 keep owner lifecycle commands explicit and inspectable."""
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, cli.argparse._SubParsersAction)
    )

    assert set(subparsers.choices) == {
        "init",
        "up",
        "deploy",
        "open",
        "backup",
        "restore",
        "doctor",
    }


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["init"], ("init",)),
        (["up"], ("up", True)),
        (["up", "--no-open"], ("up", False)),
        (["open"], ("open",)),
        (["backup"], ("backup",)),
        (["restore", "01J00000000000000000000000"], ("restore",)),
        (["doctor"], ("doctor",)),
    ],
)
def test_local_commands_dispatch(
    argv: list[str], expected: tuple[object, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019, A-042, and A-045 route each local command to one owner-facing operation."""
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli, "init_nocturne", lambda **kwargs: calls.append(("init",)))
    monkeypatch.setattr(
        cli,
        "up_nocturne",
        lambda *, open_browser, stdout: calls.append(("up", open_browser)),
    )
    monkeypatch.setattr(cli, "open_nocturne", lambda **kwargs: calls.append(("open",)))
    monkeypatch.setattr(cli, "backup_nocturne", lambda **kwargs: calls.append(("backup",)))
    monkeypatch.setattr(
        cli,
        "restore_nocturne",
        lambda backup_id, **kwargs: calls.append(("restore",)) or 0,
    )
    monkeypatch.setattr(
        cli,
        "doctor_nocturne",
        lambda **kwargs: calls.append(("doctor",)) or 0,
    )

    assert cli.main(argv, stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert calls == [expected]


def test_deploy_loads_initialized_key_and_forwards_dry_run(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 keeps cloud deployment on the initialized owner's private home and key."""

    config = NocturneConfig(
        home=tmp_path,
        openrouter_api_key="owner-secret",
        spine_token="generated-token",
        database_password="generated-password",
        machine_id="generated-machine",
    )
    calls: list[tuple[bool, str, object]] = []
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(
        cli,
        "_run_cloud_deploy",
        lambda *, dry_run, openrouter_key, home: calls.append((dry_run, openrouter_key, home)),
    )

    output = io.StringIO()
    assert cli.main(["deploy", "--dry-run"], stdout=output, stderr=output) == 0
    assert calls == [(True, "owner-secret", tmp_path)]
    assert "owner-secret" not in output.getvalue()


def test_safe_command_error_has_no_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: (_ for _ in ()).throw(OnboardingError("run `nocturne init` first")),
    )
    error = io.StringIO()

    assert cli.main(["deploy", "--dry-run"], stdout=io.StringIO(), stderr=error) == 2
    assert error.getvalue() == "nocturne: run `nocturne init` first\n"


def test_unknown_command_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(["status"])
