import json
from pathlib import Path

import pytest

from harness.t3_client import RunTransitions, T3Error
from harness.t3_server import T3Server


@pytest.mark.asyncio
async def test_supervisor_passes_only_native_session_and_private_runtime_settings(
    tmp_path, monkeypatch
):
    """A-095: Claude needs USER for Max, but inheriting API keys risks billing the wrong account."""

    class SpawnObserved(Exception):
        pass

    async def inspect_spawn(*args, env, **kwargs):
        assert set(env) == {
            "HOME",
            "USER",
            "SHELL",
            "PATH",
            "TMPDIR",
            "T3CODE_HOME",
            "T3CODE_LAN",
            "T3CODE_TAILSCALE_SERVE",
            "T3CODE_TELEMETRY_ENABLED",
            "T3CODE_LOG_WS_EVENTS",
            "T3CODE_CODEX_PROBE_TIMEOUT_MS",
            "T3CODE_AUTO_BOOTSTRAP_PROJECT_FROM_CWD",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "DISABLE_AUTOUPDATER",
            "DISABLE_TELEMETRY",
            "NO_COLOR",
            "GIT_TERMINAL_PROMPT",
        }
        assert env["USER"] == "verification-user"
        raise SpawnObserved

    monkeypatch.setenv("USER", "verification-user")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-marker")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "test-marker")
    monkeypatch.setattr("asyncio.create_subprocess_exec", inspect_spawn)
    with pytest.raises(SpawnObserved):
        await T3Server(tmp_path)._start()


def test_recorded_interrupt_closes_once_even_after_replay():
    """A-095: a native interrupt replay must close the Nocturne run once."""
    frames = json.loads((Path(__file__).parent / "fixtures/t3/terminal-replay.json").read_text())
    reducer = RunTransitions()
    transitions = [reducer.terminal(frame["event"]) for frame in frames + frames]
    assert [value for value in transitions if value] == ["interrupted"]


@pytest.mark.asyncio
async def test_optional_server_starts_only_on_request_and_names_missing_install(tmp_path):
    """F256: ordinary conversations work without installing the optional model loop."""
    server = T3Server(tmp_path)
    assert not server.root.exists()
    await server.close()
    with pytest.raises(T3Error, match="nocturne t3 install"):
        await server.client()
    assert not server.root.exists()


def test_inventory_keeps_private_auth_and_untrusted_labels_out_of_source_rows():
    """A-095: status can include the native account email; Nocturne exposes only public fields."""
    from harness.t3_sources import project_sources

    account_email = "person" + "@" + "example.test"
    provider = {
        "instanceId": "codex",
        "installed": True,
        "status": "ready",
        "version": "1.2.3",
        "auth": {
            "status": "authenticated",
            "type": "chatgpt",
            "workspaceId": "account-one",
            "email": account_email,
            "label": account_email,
        },
        "models": [{"slug": "gpt-model", "name": account_email}, {"slug": account_email}],
        "usageLimits": {
            "windows": [
                {"modelIds": ["gpt-model"], "usedPercent": 100, "resetsAt": "2026-11-22T23:00:00Z"}
            ]
        },
        "message": account_email,
    }
    rows = project_sources([provider])
    assert account_email not in json.dumps(rows) and "account-one" not in json.dumps(rows)
    assert rows[0]["availability"] == "available"
    assert rows[0]["models"][0]["availability"] == "limited"
    assert rows[0]["models"][0]["limited_until"] == "2026-11-22T23:00:00+00:00"
    provider["auth"]["type"] = "apiKey"
    assert project_sources([provider])[0]["availability"] == "unknown"


@pytest.mark.asyncio
async def test_native_stream_uses_only_completed_words_and_declines_once():
    """A-095: a split account address and duplicate native request must stay out of the journal."""
    from unittest.mock import AsyncMock

    from harness.t3_turn import NativeTurn

    client, emit = AsyncMock(), AsyncMock()
    turn = NativeTurn(client, "thread", "prompt", emit)
    turn.run = "run"
    message = {"id": "msg", "role": "assistant", "runId": "run", "streaming": True}
    await turn.update({**message, "text": "Hi person"})
    await turn.update({**message, "text": "Hi person" + "@" + "example.test now"}, final=True)
    assert turn.answer == "Hi [address withheld] now"
    await turn.request({"id": "request", "status": "pending"})
    await turn.request({"id": "request", "status": "pending"})
    client.decline.assert_awaited_once_with("thread", "request")
    assert "declined" in emit.text.await_args.args[0]


@pytest.mark.asyncio
async def test_replaced_runtime_cannot_execute_just_because_its_filename_exists(tmp_path):
    """A-095: a missing installation receipt must prevent startup before executing the file."""
    server = T3Server(tmp_path)
    server.binary.parent.mkdir(parents=True)
    server.binary.write_text("unverified")
    with pytest.raises(T3Error, match="failed verification"):
        await server.client()


def test_failed_archive_digest_prevents_installation(tmp_path, monkeypatch):
    """A-095: a corrupt download must not become an executable subscription server."""
    import httpx

    from harness import t3_install

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"bad"))
    )
    monkeypatch.setattr(
        t3_install.httpx, "stream", lambda method, url, **kwargs: client.stream(method, url)
    )
    with client, pytest.raises(t3_install.InstallError, match="integrity check"):
        t3_install.install(tmp_path)
    assert not (tmp_path / "t3" / "install" / t3_install.VERSION).exists()


def test_authenticated_claude_ultra_survives_failed_usage_probe():
    """A-095: a missing usage reading hid a real Max login; API billing must stay ineligible."""
    from harness.t3_sources import offers, project_sources

    provider = {
        "instanceId": "claudeAgent",
        "installed": True,
        "status": "ready",
        "auth": {"status": "authenticated", "type": "Claude Ultra", "workspaceId": "test-id"},
        "usageLimits": {"unavailable": {"reason": "probeFailed"}},
        "models": [{"slug": "test-model"}],
    }
    rows = project_sources([provider])
    assert rows[1]["availability"] == "available"
    assert rows[1]["usage_known"] is False
    assert len(list(offers(rows))) == 1
    for billing in ("apiKey", "console"):
        provider["auth"]["type"] = billing
        assert not list(offers(project_sources([provider])))
