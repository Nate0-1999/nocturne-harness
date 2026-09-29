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
        "palace",
        "jobs",
        "export",
        "import",
        "update",
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
    monkeypatch.setattr(cli, "update_nocturne", lambda **kwargs: False)
    monkeypatch.setattr(
        cli,
        "init_nocturne",
        lambda *, remote, verification, stdout, **kwargs: calls.append(("init", remote)),
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


def test_palace_subcommands_say_what_they_do(capsys: pytest.CaptureFixture[str]) -> None:
    """M3EX-25 / P4: `palace --help` describes new, use and drop, not only list."""
    with pytest.raises(SystemExit):
        cli.main(["palace", "--help"])
    help_text = capsys.readouterr().out
    for summary in ("create a new Palace", "choose the Palace", "delete a Palace"):
        assert summary in help_text


def test_export_into_a_missing_folder_names_the_folder(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3EX-25 / A-071: an export path that cannot be written says why before any Palace call."""
    monkeypatch.setattr(cli, "load_config", lambda: None)
    monkeypatch.setattr(
        cli.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("reached the Palace")
    )
    error = io.StringIO()
    target = tmp_path / "missing" / "memories.json"

    assert cli.main(["export", str(target)], stdout=io.StringIO(), stderr=error) == 2
    assert f"There is no folder at {target.parent}" in error.getvalue()
    target = tmp_path / "taken.json"
    target.write_text("{}")
    assert cli.main(["export", str(target)], stdout=io.StringIO(), stderr=error) == 2
    assert f"{target} already exists" in error.getvalue()


def test_update_says_when_already_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3EX-25 / P4: `nocturne update` answers when nothing is newer; `up` stays quiet."""
    calls = []
    monkeypatch.setattr(cli, "update_nocturne", lambda **kwargs: calls.append(kwargs) or False)

    assert cli.main(["update"], stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert calls[0]["announce_current"] is True


def test_jobs_list_prints_one_line_per_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3EX-25 / A-069: `nocturne jobs list` reads like the Jobs module, not raw JSON."""
    from harness import jobs_cli

    snapshot = {
        "jobs": [
            {
                "job_id": "01JOB",
                "enabled": False,
                "definition": {"name": "Nightly tests", "cron": "0 3 * * *", "trigger": None},
            }
        ],
        "runs": [
            {
                "job_id": "01JOB",
                "started_at": "2026-09-28T01:00:00Z",
                "state": "done",
                "verdict": "Run ended: error.",
            },
            {
                "job_id": "01JOB",
                "started_at": "2026-09-28T02:00:00Z",
                "state": "done",
                "verdict": "Run ended: complete.",
            },
        ],
        "scheduler_error": None,
    }
    monkeypatch.setattr(jobs_cli, "_request", lambda *_args: snapshot)
    output = io.StringIO()

    assert cli.main(["jobs", "list"], stdout=output, stderr=io.StringIO()) == 0
    assert output.getvalue() == (
        "01JOB  Nightly tests  0 3 * * * UTC (paused)  done — Run ended: complete.\n"
    )
    snapshot["jobs"] = []
    output = io.StringIO()
    assert cli.main(["jobs", "list"], stdout=output, stderr=io.StringIO()) == 0
    assert output.getvalue().startswith("No saved jobs.")
