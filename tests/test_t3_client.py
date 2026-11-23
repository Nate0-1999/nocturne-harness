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
@pytest.mark.parametrize(
    "tool,later_status,reason",
    [
        ("codex", "completed", "end_turn"),
        ("codex", "failed", "error"),
        ("claudeAgent", "completed", "end_turn"),
    ],
)
async def test_terminal_archives_only_the_bound_codex_thread(
    tool, later_status, reason, monkeypatch, caplog
):
    """A-095: preserve resume after an interrupt and preserve the outcome if archive fails."""
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from harness import t3_turn
    from harness.t3_client import T3Client

    frames = json.loads((Path(__file__).parent / "fixtures/t3/terminal-replay.json").read_text())
    client = T3Client(23001, codex_binary="codex", native_env={"TMPDIR": "/unused"})
    client.environment_id = "environment"
    model = f"subscription:{tool}/account/model"
    journal = Mock()
    journal.subscription_binding.return_value = {
        "source": model,
        "environment": hashlib.sha256(b"environment").hexdigest(),
        "native_thread": "thread",
    }
    runner = t3_turn.SubscriptionTurns(
        None, SimpleNamespace(client=AsyncMock(return_value=client)), journal
    )
    option, level, wire_value = (
        ("reasoningEffort", "ultra", "ultra") if tool == "codex" else ("thinking", "off", False)
    )
    offer = {"id": "model", "thinking": {"id": option, "levels": [level]}}
    monkeypatch.setattr(
        t3_turn, "resolve_offer", AsyncMock(return_value=(model, {"tool": tool}, offer))
    )
    commands = []
    runs = []
    messages = []

    async def call(method, args):
        if method == "orchestration.getThreadProjection":
            return {
                "thread": {"archivedAt": None},
                "providerThreads": [
                    {
                        "id": pid,
                        "providerSessionId": "writer",
                        "appThreadId": "thread",
                        "nativeThreadRef": {"driver": tool, "nativeId": nid},
                    }
                    for pid, nid in (("other-provider", "unrelated"), ("provider", "bound-native"))
                ],
                "runs": runs,
                "messages": [],
                "runtimeRequests": [],
            }
        assert method == "orchestration.dispatchCommand"
        command = args["type"]
        commands.append(command)
        if command == "message.dispatch":
            assert args["modelSelection"] == {
                "instanceId": tool,
                "model": "model",
                "options": [{"id": option, "value": wire_value}],
            }
            messages.append(args["messageId"])
        else:
            assert command == "provider-session.detach" and args["providerSessionId"] == "writer"
        return {"sequence": 0}

    async def spawn(*argv, **options):
        assert argv[:4] == ("codex", "app-server", "--listen", "stdio://")
        proc = Mock(wait=AsyncMock())
        proc.stdin.drain = AsyncMock()
        proc.stdout.readline = AsyncMock(
            side_effect=[
                b'{"id":1,"result":{}}\n',
                b'{"id":2,"result":{}}\n'
                if len(messages) == 1
                else b'{"id":2,"error":{"code":-1}}\n',
            ]
        )

        def write(raw):
            frame = json.loads(raw)
            if frame["method"] == "thread/archive":
                assert frame["params"] == {"threadId": "bound-native"}
                assert runs[-1]["status"] in {"interrupted", "completed", "failed"}
            commands.append(frame["method"])

        proc.stdin.write.side_effect = write
        return proc

    async def events(thread, after):
        # The recorded handshake retained status and id. Reattach this submission's message id.
        for frame in frames:
            run = dict(
                frame["event"]["payload"], userMessageId=messages[-1], providerThreadId="provider"
            )
            if len(messages) == 2:
                run.update(id="later-run", status=later_status)
            runs[:] = [run]
            yield {"sequence": frame["sequence"], "event": {"type": "run.updated", "payload": run}}

    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr(client, "events", events)
    monkeypatch.setattr(t3_turn.asyncio, "create_subprocess_exec", spawn)
    args = dict(
        thread_id="local-thread",
        prompt="Hello",
        emit=AsyncMock(),
        model_resolution=SimpleNamespace(
            model=model, request_parameters=SimpleNamespace(effort=level)
        ),
        message_history=(),
    )
    assert (await runner.run(**args)).stop_reason.value == "cancelled"
    outcome = await runner.run(**args)
    assert outcome.stop_reason.value == reason
    assert outcome.error_message == (
        "The native turn failed." if later_status == "failed" else None
    )
    expected = ["message.dispatch"]
    if tool == "codex":
        expected += ["provider-session.detach", "initialize", "initialized", "thread/archive"]
    assert commands == expected * 2
    assert ("Could not archive native Codex thread" in caplog.text) == (tool == "codex")


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
    assert "@" not in json.dumps(rows) and "account-one" not in json.dumps(rows)
    assert rows[0]["availability"] == "available"
    assert rows[0]["models"][0]["availability"] == "limited"
    assert rows[0]["models"][0]["limited_until"] == "2026-11-22T23:00:00+00:00"
    provider["auth"]["type"] = "apiKey"
    assert project_sources([provider])[0]["availability"] == "unknown"


@pytest.mark.asyncio
async def test_native_stream_emits_partial_words_and_declines_once():
    """A-095: emit each new character promptly and decline a repeated native request once."""
    from unittest.mock import AsyncMock

    from harness.t3_turn import NativeTurn

    client, emit = AsyncMock(), AsyncMock()
    turn = NativeTurn(client, "thread", "prompt", emit)
    turn.run = "run"
    message = {"id": "msg", "role": "assistant", "runId": "run", "streaming": True}
    await turn.update({**message, "text": "@sta"})
    emit.text.assert_awaited_once_with("@sta")
    await turn.update({**message, "text": "@staticmethod"})
    await turn.update({**message, "text": "@staticmethod"})
    assert [args.args[0] for args in emit.text.await_args_list] == ["@sta", "ticmethod"]
    assert turn.answer == "@staticmethod"
    await turn.request({"id": "request", "status": "pending"})
    await turn.request({"id": "request", "status": "pending"})
    client.decline.assert_awaited_once_with("thread", "request")
    assert "declined" in emit.text.await_args.args[0]


@pytest.mark.asyncio
async def test_subscription_answer_preserves_owner_text_in_stream_and_journal(tmp_path):
    """A-095: source identity stays private while code and user-supplied addresses round-trip."""
    from unittest.mock import AsyncMock

    from test_run_loop import Ids, RecordingResolver, Sink, _wait_for_done_count, factory, ulid

    from harness.model_policy import ThreadModelResolution
    from harness.run_loop import RunLoop
    from harness.t3_turn import SubscriptionTurns
    from harness.transcript import TranscriptJournal

    answer = "@staticmethod\n@scope/name\nreader@example.test"
    provider = {
        "instanceId": "codex",
        "status": "ready",
        "auth": {
            "status": "authenticated",
            "type": "chatgpt",
            "workspaceId": "account-one",
            "label": "Private Account",
            "email": "account@example.test",
        },
        "models": [{"slug": "test-model"}],
    }
    server = T3Server(tmp_path)
    (server.root / "workspace").mkdir(parents=True)
    client = AsyncMock(environment_id="test-environment")
    client.launch.return_value = {"sequence": 1}

    async def call(method, params):
        if method == "server.getConfig":
            return {"providers": [provider]}
        if method == "projects.mutate":
            return {}
        assert method == "orchestration.getThreadProjection"
        return {
            "runs": [
                {
                    "id": "run",
                    "status": "completed",
                    "userMessageId": client.launch.await_args.args[2],
                }
            ],
            "runtimeRequests": [],
            "messages": [{"id": "msg", "role": "assistant", "runId": "run", "text": answer}],
        }

    client.call.side_effect = call
    server.client = AsyncMock(return_value=client)
    resolution = ThreadModelResolution(
        model="subscription:codex/test-model",
        policy="pinned",
        price_sorted=False,
        context_tokens=8192,
    )
    journal = TranscriptJournal(tmp_path / "transcripts")
    loop = RunLoop(
        SubscriptionTurns(None, server, journal),
        factory(Ids()),
        model_resolver=RecordingResolver({"thread-1": resolution}),
        transcript_journal=journal,
    )
    sink = Sink()
    try:
        await loop.submit(thread_id="thread-1", prompt_id=ulid(1), prompt=answer, sink=sink)
        await _wait_for_done_count(sink, 1)
    finally:
        await loop.close()
    text = "".join(
        m.payload.text for m in sink.messages if getattr(m.payload, "kind", None) == "text"
    )
    assert text == "Codex controls its own actions outside Nocturne’s fence.\n\n" + answer
    assert journal.read_messages("thread-1")[-1]["content"] == text
    binding = journal.subscription_binding("thread-1")
    assert binding and binding["source"].endswith("/test-model")
    project = next(
        args.args[1] for args in client.call.await_args_list if args.args[0] == "projects.mutate"
    )
    title = journal.catalog()[0].title
    assert project["title"] == client.launch.await_args.args[-1] == title
    workspace = Path(project["workspaceRoot"])
    assert workspace.parent == server.root / "workspace"
    assert workspace.name.endswith("-" + binding["native_project"][:8])
    assert workspace.stat().st_mode & 0o777 == 0o700
    assert all(
        value not in json.dumps(binding) for value in ("@", "account-one", "Private Account")
    )


@pytest.mark.parametrize(
    ("title", "expected_title", "slug"),
    [
        ("", "Nocturne conversation", "conversation"),
        ("../Tea & Cake/🍰?", "../Tea & Cake/🍰?", "tea-cake"),
        ("🍰!", "🍰!", "conversation"),
        ("A" * 60, "A" * 60, "a" * 40),
    ],
)
def test_native_names_keep_title_and_use_safe_short_folder(title, expected_title, slug):
    """A-095: native history needs a readable title without letting it choose a filesystem path."""
    from harness.t3_turn import _native_names

    assert _native_names(title, "8e4d2a1c-6a4a-41d1-ae92-b1de8cb863af") == (
        expected_title,
        f"nocturne-{slug}-8e4d2a1c",
    )


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
