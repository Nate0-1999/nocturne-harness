"""PLAN M3VI / F069: verification owns both its Palace scope and local files."""

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel
from test_daemon import GateSpine, frame, receive_until
from test_memory_panel import memory_unit
from test_queue_provenance import BATCH_UID, ITEM_UID, DecisionSpine

from harness import onboarding
from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import QueueDecisionRequest, SpineClient, SpineClientError


def initialize(home, monkeypatch, *, verification=True):
    monkeypatch.setattr(onboarding, "ensure_browser_runtime", lambda home: home / "tools")
    monkeypatch.setattr(onboarding, "browser_runtime_is_ready", lambda home: True)
    onboarding.init_nocturne(
        home=home, verification=verification, environ={"OPENROUTER_API_KEY": "test-key"},
        remote="https://palace.example.test", prompt=lambda _: "test-token",
        stdout=io.StringIO(),
    )
    return onboarding.load_config(home=home)


def test_verification_daemon_cannot_list_owner_memories(tmp_path, monkeypatch):
    """PLAN M3VI / SPEC C.4: the daemon, never the browser, supplies principal scope."""
    config = initialize(tmp_path / "verification", monkeypatch)
    assert config.principal_id.startswith("nocturne-verification-")
    environment = config.process_environment({"PRINCIPAL_ID": "local"})
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    settings = HarnessSettings(_env_file=None)
    owner_memory = memory_unit(uuid4(), principal_id="local", body="Owner-only sentinel")
    corpus = [owner_memory]
    requested = []

    def palace(request):
        assert request.url.path == "/v1/memory-graph/query", "unscoped Palace read"
        query = json.loads(request.content)
        requested.append(query["principal_id"])
        return httpx.Response(200, json={
            "as_of": datetime.now(UTC).isoformat(), "graph_edge_sim": 0.8,
            "nodes": [{"memory": memory.model_dump(mode="json")} for memory in corpus
                      if memory.principal_id == query["principal_id"]],
            "edges": [], "omitted_memory_ids": [],
        })

    monkeypatch.setattr(
        "harness.daemon.SpineClient",
        lambda url, token, **kwargs: SpineClient(
            url, token, transport=httpx.MockTransport(palace), **kwargs,
        ),
    )

    async def unused(_messages, _info):
        yield "unused"

    app = create_dev_app(
        tmp_path, settings=settings,
        agent=HarnessAgent(settings, model=FunctionModel(stream_function=unused)),
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json(frame("memory.panel.update", {"action": "refresh"}))
        panel, _ = receive_until(socket, "memory.panel.update")
        assert panel["payload"]["items"] == []
        graph = client.get("/v1/rack/query?resource=memory_graph&principal_id=local")
        assert graph.status_code == 200
        assert graph.json()["data"]["nodes"] == []
        assert client.get("/v1/identity").json()["principal_id"] == config.principal_id
        own_memory = memory_unit(uuid4(), principal_id=config.principal_id, body="Disposable fact")
        corpus.append(own_memory)
        socket.send_json(frame("memory.panel.update", {"action": "refresh"}))
        panel, _ = receive_until(socket, "memory.panel.update")
        assert [item["memory"]["memory_id"] for item in panel["payload"]["items"]] == [
            str(own_memory.memory_id),
        ]
        socket.send_json(frame("memory.panel.update", {
            "action": "pin", "memory_id": str(owner_memory.memory_id),
            "expected_revision": 1, "pin": True,
        }))
        refusal, _ = receive_until(socket, "memory.panel.update")
        assert refusal["payload"]["action"] == "error"
    assert requested and set(requested) == {config.principal_id}


def test_nondefault_home_env_keeps_all_daemon_files_out_of_owner_home(tmp_path, monkeypatch):
    """PLAN M3VI / ADR-016: a sourced or dotenv-loaded home must not fall back to ~/.nocturne."""
    fake_user = tmp_path / "user"
    fake_user.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_user))
    monkeypatch.delenv("NOCTURNE_HOME", raising=False)
    monkeypatch.delenv("PRINCIPAL_ID", raising=False)
    config = initialize(tmp_path / "verification", monkeypatch)
    settings = HarnessSettings(_env_file=config.path)
    assert settings.nocturne_home == config.home
    assert onboarding._parse_config(config.path)["NOCTURNE_HOME"] == str(config.home)

    async def unused(_messages, _info):
        yield "unused"

    app = create_dev_app(
        tmp_path, settings=settings, spine=GateSpine(),
        agent=HarnessAgent(settings, model=FunctionModel(stream_function=unused)),
    )
    with TestClient(app) as client:
        identity = client.get("/v1/identity").json()
        assert identity["home"] == str(config.home)
        with client.websocket_connect("/ws") as socket:
            socket.send_json(frame("prompt.submit", {"prompt": "/model openrouter:test/model"}))
            receive_until(socket, "run.done")
    assert list((config.home / "transcripts").glob("*.jsonl"))
    assert not (fake_user / ".nocturne").exists()


def test_verification_init_refuses_default_or_existing_owner_home(tmp_path, monkeypatch):
    """SPEC D.2 113b / M3VI: verification must never adopt or modify an owner's home."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(onboarding.OnboardingError, match="disposable folder"):
        onboarding.init_nocturne(verification=True, environ={})
    assert not (tmp_path / ".nocturne").exists()
    owner = initialize(tmp_path / "owner", monkeypatch, verification=False)
    before = owner.path.read_bytes()
    with pytest.raises(onboarding.OnboardingError, match="fresh folder"):
        initialize(owner.home, monkeypatch)
    assert owner.path.read_bytes() == before
    settings = HarnessSettings(
        _env_file=None, principal_id="nocturne-verification-test",
        nocturne_home=tmp_path / ".nocturne",
    )
    with pytest.raises(ValueError, match="disposable folder"):
        create_dev_app(tmp_path, settings=settings)
    assert not (tmp_path / ".nocturne").exists()


def test_up_and_doctor_refuse_to_adopt_a_different_running_identity(tmp_path, monkeypatch):
    """PLAN M3VI / SPEC D.2 099: port reuse must not silently open the owner's rack."""
    config = initialize(tmp_path / "verification", monkeypatch)
    monkeypatch.setattr(onboarding, "_existing_nocturne", lambda: True)
    monkeypatch.setattr(
        onboarding.urllib.request, "urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps({
            "principal_id": "local", "home": str(tmp_path / "owner"),
        }).encode()),
    )
    assert onboarding._daemon_preflight(config).failures
    with pytest.raises(onboarding.OnboardingError, match="Another Nocturne identity"):
        onboarding.up_nocturne(home=config.home, open_browser=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_bound_client_refuses_foreign_queue_decisions_and_retries_own(batch):
    """PLAN M3VI / F069: a supplied queue ID cannot bypass the daemon's principal boundary."""
    principal = "nocturne-verification-queue"
    request = QueueDecisionRequest(
        decision="approve", approval_mode="explicit", actor_class="human",
        machine_id="m3vi-verification",
    )
    decisions = DecisionSpine()
    result = (await decisions.decide_queue_batch(BATCH_UID, request) if batch
              else await decisions.decide_queue_item(ITEM_UID, request))
    card = result.cards[0] if batch else result.card
    card.candidate.principal_id = principal
    pending = [card.model_copy(update={"state": "pending"}).model_dump(mode="json")]
    writes = []

    def palace(http_request):
        if http_request.method == "GET":
            assert http_request.url.params["principal_id"] == principal
            return httpx.Response(200, json={"cards": pending})
        writes.append(http_request.url.path)
        pending.clear()
        return httpx.Response(200, json=result.model_dump(mode="json"))

    async with SpineClient(
        "https://palace.example.test", "test-token", principal_id=principal,
        transport=httpx.MockTransport(palace),
    ) as client:
        with pytest.raises(SpineClientError, match="does not belong"):
            if batch:
                await client.decide_queue_batch(uuid4(), request)
            else:
                await client.decide_queue_item("01ARZ3NDEKTSV4RRFFQ69G5FA0", request)
        assert writes == []
        for _ in range(2):
            received = (await client.decide_queue_batch(BATCH_UID, request) if batch
                        else await client.decide_queue_item(ITEM_UID, request))
            assert received == result
        assert len(writes) == 2
    async with SpineClient(
        "https://palace.example.test", "test-token", principal_id=principal,
        transport=httpx.MockTransport(palace),
    ) as restarted:
        with pytest.raises(SpineClientError, match="does not belong"):
            if batch:
                await restarted.decide_queue_batch(BATCH_UID, request)
            else:
                await restarted.decide_queue_item(ITEM_UID, request)
    assert len(writes) == 2


@pytest.mark.parametrize("batch", [False, True])
def test_foreign_queue_http_decision_is_plain_ownership_refusal(tmp_path, monkeypatch, batch):
    """F076: the principal wall refuses item and batch writes with useful copy, never a 500."""
    def palace(request):
        assert request.method == "GET", "foreign queue decision reached the Palace write"
        return httpx.Response(200, json={"cards": []})

    monkeypatch.setattr(
        "harness.daemon.SpineClient",
        lambda url, token, **kwargs: SpineClient(
            url, token, transport=httpx.MockTransport(palace), **kwargs,
        ),
    )
    settings = HarnessSettings(
        _env_file=None, principal_id="nocturne-verification-m3st",
        nocturne_home=tmp_path, spine_url="https://palace.example.test", spine_token="test-token",
    )
    app = create_dev_app(tmp_path, settings=settings)
    path = f"batches/{BATCH_UID}" if batch else ITEM_UID
    with TestClient(app) as client:
        response = client.post(f"/v1/approval-queue/{path}/decisions", json={
            "decision": "approve", "approval_mode": "explicit", "actor_class": "human",
        })
    assert response.status_code == 403
    assert response.json() == {
        "detail": "This queue decision does not belong to this identity. Refresh the queue.",
    }
