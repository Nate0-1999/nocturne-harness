from __future__ import annotations

import io
import json

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
        "seed",
        "doctor",
    }


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["init"], ("init", None)),
        (
            ["init", "--remote", "https://spine.example.test"],
            ("init", "https://spine.example.test"),
        ),
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
    monkeypatch.setattr(
        cli,
        "init_nocturne",
        lambda *, remote, stdout: calls.append(("init", remote)),
    )
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


def test_seed_command_posts_each_markdown_file_to_the_running_owner_pipeline(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLAN M2CI/P4 and B.6 rule 12 keep seed order independent of host glob order."""

    first = tmp_path / "first.md"
    second = tmp_path / "second.markdown"
    first.write_text("# First\n\nOne durable claim.")
    second.write_text("# Second\n\nAnother durable claim.")
    requests: list[dict[str, object]] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"cards":[{},{}]}'

    def open_request(request, timeout):
        assert timeout == 120.0
        requests.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(
        cli.glob,
        "glob",
        lambda *_args, **_kwargs: [str(second), str(first)],
    )
    monkeypatch.setattr(cli.urllib.request, "urlopen", open_request)
    output = io.StringIO()

    assert cli.main(["seed", str(tmp_path / "*")], stdout=output) == 0
    assert [request["source_name"] for request in requests] == ["first.md", "second.markdown"]
    assert len({request["batch_uid"] for request in requests}) == 2
    assert output.getvalue().count("waiting for review") == 2

    cli.seed_nocturne([str(first)], stdout=output)
    assert requests[0]["batch_uid"] == requests[2]["batch_uid"]


def test_seed_command_refuses_non_markdown_before_contacting_the_daemon(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 clause 4 and B.6 rule 12 keep the CLI on the Markdown-only seed contract."""

    source = tmp_path / "notes.txt"
    source.write_text("This must not enter the seed pipeline.")
    monkeypatch.setattr(
        cli.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("invalid input reached the daemon"),
    )
    error = io.StringIO()

    assert cli.main(["seed", str(source)], stdout=io.StringIO(), stderr=error) == 2
    assert error.getvalue() == "nocturne: notes.txt is not a Markdown file.\n"


def test_safe_command_error_has_no_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """P3 is defended by verifying that safe command error has no traceback; this prevents
    drift in the safe owner CLI boundary.
    """
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: (_ for _ in ()).throw(OnboardingError("run `nocturne init` first")),
    )
    error = io.StringIO()

    assert cli.main(["deploy", "--dry-run"], stdout=io.StringIO(), stderr=error) == 2
    assert error.getvalue() == "nocturne: run `nocturne init` first\n"


def test_unknown_command_is_rejected_by_argparse() -> None:
    """P3 is defended by verifying that unknown command is rejected by argparse; this prevents
    drift in the safe owner CLI boundary.
    """
    with pytest.raises(SystemExit, match="2"):
        cli.main(["status"])
