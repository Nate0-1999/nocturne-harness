import json
from pathlib import Path

import pytest

from harness.t3_client import RunTransitions, T3Error
from harness.t3_front import FrontServer
from harness.t3_server import T3Server


@pytest.mark.asyncio
@pytest.mark.parametrize("front", [False, True])
async def test_supervisor_passes_only_native_session_and_private_runtime_settings(
    front, tmp_path, monkeypatch
):
    """A-095: Claude needs USER for Max, but inheriting API keys risks billing the wrong account.

    Report 348: one switch was all that kept T3's usage data here; both servers get every lock.
    """

    class SpawnObserved(Exception):
        pass

    async def inspect_spawn(*args, env, **kwargs):
        assert {
            "T3CODE_TELEMETRY_ENABLED": "false",
            "T3CODE_OTEL_SDK_DISABLED": "true",
            "T3CODE_POSTHOG_HOST": "http://127.0.0.1:9",
            "DO_NOT_TRACK": "1",
        }.items() <= env.items()
        assert set(env) - ({"NOCTURNE_HOME"} if front else set()) == {
            "HOME",
            "USER",
            "SHELL",
            "PATH",
            "TMPDIR",
            "T3CODE_HOME",
            "T3CODE_LAN",
            "T3CODE_TAILSCALE_SERVE",
            "T3CODE_TELEMETRY_ENABLED",
            "T3CODE_OTEL_SDK_DISABLED",
            "T3CODE_POSTHOG_HOST",
            "DO_NOT_TRACK",
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
    server = FrontServer(tmp_path, None, None, tmp_path) if front else T3Server(tmp_path)
    with pytest.raises(SpawnObserved):
        await server._start()
    await server.close()


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
    tool, later_status, reason, monkeypatch, caplog, tmp_path
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
        "location": str(tmp_path),
    }
    runner = t3_turn.SubscriptionTurns(
        None, SimpleNamespace(client=AsyncMock(return_value=client)), journal, lambda _: tmp_path
    )
    option, level, wire_value = (
        ("reasoningEffort", "ultra", "ultra") if tool == "codex" else ("thinking", "off", False)
    )
    offer = {"id": "model", "thinking": {"id": option, "levels": [level]}}
    monkeypatch.setattr(
        t3_turn,
        "resolve_offer",
        AsyncMock(return_value=(model, {"tool": tool, "name": tool}, offer)),
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
async def test_native_stream_emits_partial_words_and_decides_once():
    """A-099: a replayed native request must never run twice or expose account metadata."""
    from unittest.mock import AsyncMock

    from harness.t3_turn import NativeTurn

    client, emit = AsyncMock(), AsyncMock()
    binding = {"location": "/scratch"}
    turn = NativeTurn(client, "thread", "prompt", emit, "Codex", binding, lambda: None)
    turn.run = "run"
    message = {"id": "msg", "role": "assistant", "runId": "run", "streaming": True}
    await turn.update({**message, "text": "@sta"})
    emit.text.assert_awaited_once_with("@sta")
    await turn.update({**message, "text": "@staticmethod"})
    await turn.update({**message, "text": "@staticmethod"})
    assert [args.args[0] for args in emit.text.await_args_list] == ["@sta", "ticmethod"]
    assert turn.answer == "@staticmethod"
    request = {"id": "request", "status": "pending", "kind": "command"}
    details = [
        {
            "type": "approval_request",
            "runId": "run",
            "requestId": "request",
            "prompt": "Read file for private@example.test",
        }
    ]
    emit.boundary_decision.return_value = "allowed_once"
    await turn.request(request, details)
    await turn.request(request, details)
    emit.boundary_decision.assert_awaited_once()
    assert "@" not in emit.boundary_decision.await_args.args[0]["reason"]
    client.respond.assert_awaited_once_with("thread", "request", allow=True)
    assert "permission" not in binding


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
    client.workspace_project.return_value = "shared-project"
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
        SubscriptionTurns(None, server, journal, lambda _: tmp_path),
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
    assert str(tmp_path) in text and text.endswith(answer)
    assert journal.read_messages("thread-1")[-1]["content"] == text
    binding = journal.subscription_binding("thread-1")
    assert binding and binding["source"].endswith("/test-model")
    title = journal.catalog()[0].title
    client.workspace_project.assert_awaited_once_with(str(tmp_path), title)
    assert client.launch.await_args.args[-1] == title and binding["location"] == str(tmp_path)
    assert binding["native_project"] == "shared-project"
    assert all(
        value not in json.dumps(binding) for value in ("@", "account-one", "Private Account")
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


@pytest.mark.asyncio
@pytest.mark.parametrize("found", [False, True])
async def test_conversations_share_only_the_exact_existing_project(found):
    """A-099: two conversations in one folder need separate native threads on one T3 project."""
    from unittest.mock import AsyncMock

    from harness.t3_client import T3Client

    client = T3Client(23001)
    client.call = AsyncMock(side_effect=T3Error("project creation failed"))

    async def frames(method, args):
        assert method == "orchestration.subscribeShell" and args == {}
        projects = [{"id": "neighbor", "workspaceRoot": "/work/neighbor"}]
        if found:
            projects.append({"id": "same", "workspaceRoot": "/work"})
        yield {"values": [{"kind": "snapshot", "snapshot": {"projects": projects}}]}

    client._frames = frames
    if found:
        assert await client.workspace_project("/work", "Second conversation") == "same"
    else:
        with pytest.raises(T3Error, match="project creation failed"):
            await client.workspace_project("/work", "Second conversation")


@pytest.mark.asyncio
async def test_conversation_grant_journals_future_requests_and_still_obeys_provider_override():
    """A-099: a follow-up uses the grant but a provider override still needs the owner."""
    from unittest.mock import AsyncMock

    from harness.t3_turn import NativeTurn

    client, emit = AsyncMock(), AsyncMock()
    binding = {"location": "/work", "permission": "allowed_thread"}
    turn = NativeTurn(client, "thread", "message", emit, "Claude Code", binding, lambda: None)
    turn.run = "run"
    emit.boundary_decision.return_value = "denied"
    for request_id, override in (("read", False), ("override", True)):
        await turn.request(
            {"id": request_id, "status": "pending", "kind": "file-read"},
            [
                {
                    "type": "approval_request",
                    "runId": "run",
                    "requestId": request_id,
                    "prompt": "sibling/file",
                    "fullAccessOverride": override,
                }
            ],
        )
    emit.boundary_decision.assert_awaited_once()
    events = [call.args[0] for call in emit.event.await_args_list]
    assert [e["decision"] for e in events] == ["requested", "allowed_thread", "denied"]
    assert events[0]["reason"] == "File read: sibling/file"
    assert [call.kwargs["allow"] for call in client.respond.await_args_list] == [True, False]
