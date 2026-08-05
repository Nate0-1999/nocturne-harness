from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest
from pydantic_ai.models.function import FunctionModel
from starlette.websockets import WebSocketDisconnect
from vitals_fixture import vitals_payload

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import EnvelopeSender, _build_web, create_app, create_dev_app
from harness.envelope import Envelope, EnvelopeFactory, MessageType, StopReason
from harness.memory_panel import EMPTY_MEMORY_BLOCK
from harness.model_policy import ThreadModelResolution
from harness.run_loop import RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.spine_client import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSignal,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    ListMemoriesParams,
    MemoryFeatures,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    ScoredMemoryCard,
    SpendEventsRequest,
    SpendEventsResponse,
    SpineTransportError,
    VitalsSnapshot,
)
from harness.transcript import TranscriptJournal

PROMPT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SECOND_PROMPT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
CANCEL_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAX"
SNAPSHOT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAY"
INJECTION_ID = "32345678-1234-5678-1234-567812345678"


def vitals_snapshot() -> VitalsSnapshot:
    return VitalsSnapshot.model_validate(vitals_payload())


def valid_envelope() -> dict[str, object]:
    return {
        "v": 1,
        "id": PROMPT_ID,
        "ts": "2026-07-17T12:00:00Z",
        "machine_id": "machine-1",
        "agent_id": "agent-1",
        "thread_id": "thread-1",
        "type": "prompt.submit",
        "payload": {"prompt": "hello"},
    }


def frame(
    message_type: str,
    payload: object,
    *,
    message_id: str = PROMPT_ID,
    thread_id: str | None = "thread-1",
) -> dict[str, object]:
    message = {
        **valid_envelope(),
        "id": message_id,
        "type": message_type,
        "payload": payload,
    }
    if thread_id is None:
        message.pop("thread_id")
    else:
        message["thread_id"] = thread_id
    return message


def envelope_with_raw_payload(payload: str) -> str:
    raw = json.dumps({**valid_envelope(), "payload": None})
    return raw.replace('"payload": null', f'"payload": {payload}', 1)


def receive_until(websocket, message_type: str) -> tuple[dict[str, object], list[str]]:
    seen: list[str] = []
    for _ in range(12):
        message = websocket.receive_json()
        seen.append(message["type"])
        if message["type"] == message_type:
            return message, seen
    raise AssertionError(f"did not receive {message_type}; saw {seen}")


class CancellableRunner:
    def __init__(self, *, cleanup_delay: float = 0) -> None:
        self.cleanup_delay = cleanup_delay
        self.calls: list[str] = []

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, model_resolution
        self.calls.append(prompt)
        if prompt != "first":
            await emit.text(f"answer:{prompt}")
            return TurnOutcome(
                StopReason.END_TURN,
                (*message_history, f"{prompt}:done"),
                UsageSnapshot(1, 2, 3),
            )

        await emit.text("kept partial")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            if self.cleanup_delay:
                await asyncio.sleep(self.cleanup_delay)
            return TurnOutcome(
                StopReason.CANCELLED,
                (*message_history, "first:cancelled-tool"),
                UsageSnapshot(1, 2, 1),
            )


class FailingPrepareSpine:
    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        del request
        raise SpineTransportError

    async def aclose(self) -> None:
        pass

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        return SpendEventsResponse(accepted=len(request.events))


class GateSpine:
    def __init__(self) -> None:
        self.prepare_requests: list[InjectPrepareRequest] = []
        self.commit_requests: list[InjectCommitRequest] = []
        self.vitals_requests = 0
        self.closed = False

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepare_requests.append(request)
        return InjectPrepareResponse(
            injection_id=UUID(INJECTION_ID),
            snapshot_ts=datetime(2026, 7, 21, 12, tzinfo=UTC),
            scorer_version="m1-v1",
            injected=[],
            near_misses=[],
            final_block=None,
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self.commit_requests.append(request)
        return InjectCommitResponse(final_block=EMPTY_MEMORY_BLOCK, wrong_removed=[])

    async def aclose(self) -> None:
        self.closed = True

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        return SpendEventsResponse(accepted=len(request.events))

    async def vitals_snapshot(self) -> VitalsSnapshot:
        self.vitals_requests += 1
        return vitals_snapshot()


class PanelGateSpine:
    def __init__(self) -> None:
        self.first_id = UUID("42345678-1234-5678-1234-567812345678")
        self.second_id = UUID("52345678-1234-5678-1234-567812345678")
        self.cards = [
            self._card(self.first_id, "Remove", "remove this chartreuse body", 1),
            self._card(self.second_id, "Keep", "keep this cobalt body", 2),
        ]
        self.memories = [
            self._unit(self.first_id, "Remove", "remove this chartreuse body"),
            self._unit(self.second_id, "Keep", "keep this cobalt body"),
        ]
        self.feedback_requests: list[FeedbackRequest] = []

    @staticmethod
    def _card(memory_id: UUID, label: str, body: str, rank: int) -> ScoredMemoryCard:
        return ScoredMemoryCard(
            memory_id=memory_id,
            label=label,
            body=body,
            kind=MemoryKind.FACT,
            pin=True,
            score=0.9,
            features=MemoryFeatures(
                sem=0.9,
                kw=0.8,
                time=0.7,
                proj=0.6,
                freq=0.5,
                hist=0.4,
            ),
            rank=rank,
        )

    @staticmethod
    def _unit(memory_id: UUID, label: str, body: str) -> MemoryUnit:
        now = datetime(2026, 7, 28, 12, tzinfo=UTC)
        return MemoryUnit(
            memory_id=memory_id,
            principal_id="principal-test",
            label=label,
            body=body,
            kind=MemoryKind.FACT,
            keywords=["test"],
            project_key=None,
            thread_origin=None,
            origin_path=None,
            pin=True,
            status=MemoryStatus.ACTIVE,
            revision=1,
            stats={},
            bias=0,
            embedding_model="test",
            created_at=now,
            updated_at=now,
        )

    @property
    def block(self) -> str:
        fragments = [
            (
                f'<memory label="{card.label}" kind="{card.kind.value}" '
                'updated="2026-07-28T12:00:00Z">\n'
                f"{card.body}\n"
                "</memory>"
            )
            for card in self.cards
        ]
        return (
            "<memory_system>\n"
            "The following long-term memories were retrieved for this conversation.\n"
            "Treat them as your own accumulated knowledge; they may be imperfect.\n"
            + "\n".join(fragments)
            + "\n</memory_system>"
        )

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        del request
        return InjectPrepareResponse(
            injection_id=UUID(INJECTION_ID),
            snapshot_ts=datetime(2026, 7, 28, 12, tzinfo=UTC),
            scorer_version="m1-v1",
            injected=self.cards,
            near_misses=[],
            final_block=None,
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        del request
        return InjectCommitResponse(final_block=self.block, wrong_removed=[])

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        self.feedback_requests.append(request)
        return FeedbackResponse(ok=True)

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        return PagedMemoryListResponse(
            items=self.memories,
            total=len(self.memories),
            limit=params.limit,
            offset=params.offset,
        )

    async def aclose(self) -> None:
        pass

    async def record_spend_events(self, request: SpendEventsRequest) -> SpendEventsResponse:
        return SpendEventsResponse(accepted=len(request.events))


def app_with_runner(runner: CancellableRunner, tmp_path: Path):
    factory = EnvelopeFactory(machine_id="daemon-test")
    return create_app(
        tmp_path,
        run_loop=RunLoop(runner, factory),
        envelope_factory=factory,
    )


class OverflowOnAttachLoop:
    async def attach(
        self,
        sink: EnvelopeSender,
        *,
        on_overflow: Callable[[], None] | None = None,
    ) -> None:
        del sink
        assert on_overflow is not None
        on_overflow()

    async def detach(self, sink: EnvelopeSender) -> None:
        del sink

    async def close(self) -> None:
        pass


def test_serves_built_web_static(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that serves built web static; this prevents drift in
    the daemon transport and event-loop contract.
    """
    (tmp_path / "index.html").write_text("<h1>Harness shell</h1>", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    response = client.get("/")

    assert response.status_code == 200
    assert "Harness shell" in response.text


def test_composed_http_routes_precede_the_static_mount(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that composed http routes precede the static mount;
    this prevents drift in the daemon transport and event-loop contract.
    """
    (tmp_path / "index.html").write_text("<h1>Harness shell</h1>", encoding="utf-8")

    def configure(app: FastAPI) -> None:
        @app.post("/v1/threads/{thread_id}/archive")
        async def archive(thread_id: UUID) -> dict[str, str]:
            return {"thread_id": str(thread_id)}

    client = TestClient(create_app(tmp_path, before_static_mount=configure))
    thread_id = uuid4()

    response = client.post(f"/v1/threads/{thread_id}/archive")

    assert response.status_code == 200
    assert response.json() == {"thread_id": str(thread_id)}


def test_static_shell_and_rack_frame_have_distinct_frame_policies(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that static shell and rack frame have distinct frame
    policies; this prevents drift in the daemon transport and event-loop contract.
    """
    (tmp_path / "index.html").write_text("<h1>Harness shell</h1>", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    shell = client.get("/", headers={"host": "127.0.0.1:8765"})
    rack = client.get(
        "/?rack_module=chat",
        headers={"host": "rack.localhost:8765"},
    )
    vitals_rack = client.get(
        "/?rack_module=vitals",
        headers={"host": "rack.localhost:8765"},
    )
    forged = client.get(
        "/?rack_module=chat",
        headers={"host": "127.0.0.1:8765"},
    )

    assert shell.headers["x-frame-options"] == "DENY"
    assert shell.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert "x-frame-options" not in rack.headers
    assert "connect-src 'none'" in rack.headers["content-security-policy"]
    assert (
        "frame-ancestors http://localhost:* http://127.0.0.1:*"
        in rack.headers["content-security-policy"]
    )
    assert "connect-src 'none'" in vitals_rack.headers["content-security-policy"]
    assert forged.headers["x-frame-options"] == "DENY"


def test_rack_vitals_query_uses_the_injected_reader_before_static_mount(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that rack vitals query uses the injected reader before
    static mount; this prevents drift in the daemon transport and event-loop contract.
    """
    (tmp_path / "index.html").write_text("<h1>Harness shell</h1>", encoding="utf-8")
    calls = 0

    async def read_vitals() -> VitalsSnapshot:
        nonlocal calls
        calls += 1
        return vitals_snapshot()

    client = TestClient(create_app(tmp_path, vitals_snapshot_reader=read_vitals))

    response = client.get("/v1/rack/query?resource=vitals&as_of=now")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "live",
        "as_of": None,
        "data": vitals_snapshot().model_dump(mode="json"),
    }
    assert calls == 1


def test_rack_vitals_query_truthfully_rejects_historical_as_of_without_reading() -> None:
    """SPEC C.7 is defended by verifying that rack vitals query truthfully rejects historical
    as of without reading; this prevents drift in the daemon transport and event-loop
    contract.
    """

    async def must_not_read() -> VitalsSnapshot:
        raise AssertionError("historical query must not read the live snapshot")

    client = TestClient(create_app(vitals_snapshot_reader=must_not_read))
    historical = "2026-08-02T11:00:00Z"

    response = client.get(
        "/v1/rack/query",
        params={"resource": "vitals", "as_of": historical},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "historical_unavailable",
        "as_of": historical,
        "data": None,
    }


def test_unavailable_rack_vitals_returns_503_without_disturbing_chat() -> None:
    """SPEC C.7 is defended by verifying that unavailable rack vitals returns 503 without
    disturbing chat; this prevents drift in the daemon transport and event-loop contract.
    """

    async def unavailable() -> VitalsSnapshot:
        raise SpineTransportError

    app = create_app(vitals_snapshot_reader=unavailable)

    with TestClient(app) as client:
        failed = client.get("/v1/rack/query?resource=vitals&as_of=now")
        assert failed.status_code == 503
        assert failed.json() == {"detail": "Palace Vitals are unavailable."}

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(valid_envelope())
            started = websocket.receive_json()
            usage = websocket.receive_json()
            done = websocket.receive_json()

    assert [started["type"], usage["type"], done["type"]] == [
        "run.started",
        "run.usage",
        "run.done",
    ]
    assert done["payload"]["stop_reason"] == "error"


def test_missing_rack_vitals_reader_is_an_explicit_503() -> None:
    """SPEC C.7 is defended by verifying that missing rack vitals reader is an explicit 503;
    this prevents drift in the daemon transport and event-loop contract.
    """
    response = TestClient(create_app()).get("/v1/rack/query?resource=vitals")

    assert response.status_code == 503
    assert response.json() == {"detail": "Palace Vitals are unavailable."}


def test_missing_web_build_is_explicit(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that missing web build is explicit; this prevents
    drift in the daemon transport and event-loop contract.
    """
    client = TestClient(create_app(tmp_path))

    response = client.get("/")

    assert response.status_code == 503
    assert response.text == "web build missing; build web/ before starting harness"


def test_dev_app_wires_the_owned_spine_into_the_public_rack_query(tmp_path: Path) -> None:
    """A-044 keeps the public Vitals boundary enriched with owner-local resources."""

    async def stream(_messages, _info):
        yield "unused"

    settings = HarnessSettings(
        _env_file=None,
        spine_token="test-token",
        principal_id="principal-test",
        machine_id="machine-test",
        agent_id="agent-test",
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
    )
    agent = HarnessAgent(settings, model=FunctionModel(stream_function=stream))
    spine = GateSpine()
    app = create_dev_app(
        tmp_path,
        settings=settings,
        agent=agent,
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=TranscriptJournal(tmp_path / "transcripts"),
    )

    with TestClient(app) as client:
        response = client.get("/v1/rack/query?resource=vitals&as_of=now")

    assert response.status_code == 200
    assert response.json()["data"]["window_minutes"] == 60
    resources = response.json()["data"]["resources"]
    assert resources["status"] == "measured"
    assert resources["database_bytes"] == vitals_snapshot().resources.database_bytes
    assert resources["daemon_rss_bytes"] > 0
    assert resources["disk_free_bytes"] > 0
    assert spine.vitals_requests == 1


def test_dev_build_uses_locked_install_before_vite_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC C.7 is defended by verifying that dev build uses locked install before vite build;
    this prevents drift in the daemon transport and event-loop contract.
    """
    calls: list[tuple[list[str], Path, bool]] = []

    def record(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append((command, cwd, check))

    monkeypatch.setattr("harness.daemon.subprocess.run", record)

    _build_web(tmp_path)

    assert calls == [
        (["npm", "ci"], tmp_path, True),
        (["npm", "run", "build"], tmp_path, True),
    ]


def test_default_prompt_gets_fresh_correlated_error_lifecycle(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that default prompt gets fresh correlated error
    lifecycle; this prevents drift in the daemon transport and event-loop contract.
    """
    client = TestClient(create_app(tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(valid_envelope())
        started = websocket.receive_json()
        usage = websocket.receive_json()
        done = websocket.receive_json()

    assert started["type"] == "run.started"
    assert started["id"] != PROMPT_ID
    assert started["machine_id"] == "harness-daemon"
    assert started["payload"]["prompt_id"] == PROMPT_ID
    run_id = started["payload"]["run_id"]
    assert usage == {
        **usage,
        "type": "run.usage",
        "payload": {
            "run_id": run_id,
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        },
    }
    assert done["type"] == "run.done"
    assert done["payload"] == {
        "run_id": run_id,
        "stop_reason": "error",
        "partial": True,
    }
    assert len({started["id"], usage["id"], done["id"]}) == 3


def test_dev_app_wires_the_real_streaming_agent_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC C.7 is defended by verifying that dev app wires the real streaming agent adapter;
    this prevents drift in the daemon transport and event-loop contract.
    """

    async def stream(_messages, _info):
        yield "wired response"

    settings = HarnessSettings(
        _env_file=None,
        spine_token="test-token",
        principal_id="principal-test",
        machine_id="machine-test",
        agent_id="agent-test",
        chat_model="openrouter:static/visible-model",
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
    )
    agent = HarnessAgent(settings, model=FunctionModel(stream_function=stream))
    state_home = tmp_path / "state"
    monkeypatch.setenv("NOCTURNE_HOME", str(state_home))
    app = create_dev_app(
        tmp_path,
        settings=settings,
        agent=agent,
        spine=FailingPrepareSpine(),  # type: ignore[arg-type]
    )
    thread_id = "22345678-1234-5678-1234-567812345678"

    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            frame(
                "prompt.submit",
                {"prompt": "hello"},
                thread_id=thread_id,
            )
        )
        messages: list[dict[str, object]] = []
        while True:
            message = websocket.receive_json()
            messages.append(message)
            if message["type"] == "run.done":
                break

    assert messages[0]["type"] == "run.started"
    assert messages[0]["payload"]["resolved_model"] == "openrouter:static/visible-model"
    assert messages[1]["type"] == "error"
    assert messages[1]["payload"] == {
        "code": "memory_unavailable",
        "run_id": messages[0]["payload"]["run_id"],
        "phase": "prepare",
        "message": "Memory is unavailable; continuing without injected context.",
    }
    assert all(message["type"] != "gate.open" for message in messages)
    assert messages[-1]["payload"]["stop_reason"] == "end_turn"
    assert messages[-1]["payload"]["partial"] is False
    assert any(
        message["type"] == "run.delta"
        and message["payload"].get("kind") == "text"
        and message["payload"].get("text") == "wired response"
        for message in messages
    )
    assert all(message["machine_id"] == "machine-test" for message in messages)
    assert all(message["agent_id"] == "agent-test" for message in messages)
    assert len(list((state_home / "transcripts").glob("*.jsonl"))) == 1


def test_explicit_pinned_policy_does_not_resolve_unused_chat_model(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that explicit pinned policy does not resolve unused
    chat model; this prevents drift in the daemon transport and event-loop contract.
    """
    settings = HarnessSettings(
        _env_file=None,
        spine_token="test-token",
        chat_model="anthropic:claude-sonnet-4-6",
        model_policy_chat="pinned:openrouter:minimax/minimax-m3",
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key="test-openrouter-key",
    )

    app = create_dev_app(
        tmp_path,
        settings=settings,
        spine=FailingPrepareSpine(),  # type: ignore[arg-type]
        transcript_journal=TranscriptJournal(tmp_path / "transcripts"),
    )

    with TestClient(app):
        pass


def test_dev_gate_round_trip_blocks_validates_commits_and_injects_system_block(
    tmp_path: Path,
) -> None:
    """SPEC C.7 is defended by verifying that dev gate round trip blocks validates commits and
    injects system block; this prevents drift in the daemon transport and event-loop
    contract.
    """
    observed_messages = []

    async def answer(messages, _info):
        observed_messages.extend(messages)
        yield "after gate"

    settings = HarnessSettings(
        _env_file=None,
        spine_token="test-token",
        principal_id="principal-test",
        machine_id="machine-test",
        agent_id="agent-test",
        model_context_tokens=777_777,
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
    )
    agent = HarnessAgent(settings, model=FunctionModel(stream_function=answer))
    spine = GateSpine()
    transcript_journal = TranscriptJournal(tmp_path / "transcripts")
    app = create_dev_app(
        tmp_path,
        settings=settings,
        agent=agent,
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=transcript_journal,
    )
    thread_id = "22345678-1234-5678-1234-567812345678"

    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("prompt.submit", {"prompt": "hello"}, thread_id=thread_id))
        started = websocket.receive_json()
        opened = websocket.receive_json()
        run_id = started["payload"]["run_id"]
        assert opened["type"] == "gate.open"
        assert opened["payload"] == {
            "run_id": run_id,
            "kind": "memory_gate",
            "injection_id": INJECTION_ID,
            "snapshot_ts": "2026-07-21T12:00:00Z",
            "scorer_version": "m1-v1",
            "stage": "review",
            "injected": [],
            "near_misses": [],
            "wrong_removed": [],
            "resolution_error": None,
        }
        assert observed_messages == []

        websocket.send_json(
            frame(
                "gate.commit",
                {
                    "run_id": run_id,
                    "injection_id": "42345678-1234-5678-1234-567812345678",
                    "removed": [],
                    "added_back": [],
                },
                message_id=CANCEL_ID,
                thread_id=thread_id,
            )
        )
        rejected = websocket.receive_json()
        assert rejected["type"] == "error"
        assert rejected["payload"] == {
            "code": "gate_not_committable",
            "run_id": run_id,
        }
        assert observed_messages == []

        commit_payload = {
            "run_id": run_id,
            "injection_id": INJECTION_ID,
            "removed": [],
            "added_back": [],
        }
        websocket.send_json(
            frame(
                "gate.commit",
                commit_payload,
                message_id=SNAPSHOT_ID,
                thread_id=thread_id,
            )
        )
        resumed: list[dict[str, object]] = []
        while True:
            message = websocket.receive_json()
            resumed.append(message)
            if message["type"] == "run.done":
                break

        websocket.send_json(
            frame(
                "gate.commit",
                commit_payload,
                message_id="01ARZ3NDEKTSV4RRFFQ69G5FAZ",
                thread_id=thread_id,
            )
        )
        duplicate = websocket.receive_json()

    resumed_types = [message["type"] for message in resumed]
    assert resumed_types[0] == "gate.dismiss"
    assert "run.delta" in resumed_types
    assert resumed_types[-1] == "run.done"
    assert duplicate["type"] == "error"
    assert duplicate["payload"] == {"code": "gate_not_committable", "run_id": run_id}
    assert spine.prepare_requests[0].model_context_tokens == 777_777
    assert spine.commit_requests == [
        InjectCommitRequest(injection_id=UUID(INJECTION_ID), removed=[], added_back=[])
    ]
    requests = [message for message in observed_messages if isinstance(message, ModelRequest)]
    assert len(requests) == 1
    assert requests[0].instructions is not None
    assert requests[0].instructions.endswith("\n" + EMPTY_MEMORY_BLOCK)
    assert spine.closed is True
    transcript_types = [
        json.loads(line)["event"]["type"]
        for line in transcript_journal.path_for_thread(thread_id).read_text().splitlines()
        if json.loads(line)["record_type"] == "event"
    ]
    assert "gate.open" in transcript_types
    assert "gate.dismiss" in transcript_types
    assert "error" in transcript_types


def test_dev_panel_remove_updates_shared_context_for_the_next_model_call(
    tmp_path: Path,
) -> None:
    """SPEC C.7 is defended by verifying that dev panel remove updates shared context for the
    next model call; this prevents drift in the daemon transport and event-loop contract.
    """
    observed_calls: list[tuple[object, ...]] = []

    async def answer(messages, _info):
        observed_calls.append(tuple(messages))
        yield "answer"

    settings = HarnessSettings(
        _env_file=None,
        spine_token="test-token",
        principal_id="principal-test",
        machine_id="machine-test",
        agent_id="agent-test",
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
    )
    agent = HarnessAgent(settings, model=FunctionModel(stream_function=answer))
    spine = PanelGateSpine()
    transcript_journal = TranscriptJournal(tmp_path / "transcripts")
    app = create_dev_app(
        tmp_path,
        settings=settings,
        agent=agent,
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=transcript_journal,
    )
    thread_id = "22345678-1234-5678-1234-567812345678"

    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("prompt.submit", {"prompt": "first"}, thread_id=thread_id))
        started = websocket.receive_json()
        opened = websocket.receive_json()
        assert opened["type"] == "gate.open"
        websocket.send_json(
            frame(
                "gate.commit",
                {
                    "run_id": started["payload"]["run_id"],
                    "injection_id": INJECTION_ID,
                    "removed": [],
                    "added_back": [],
                },
                message_id=CANCEL_ID,
                thread_id=thread_id,
            )
        )
        receive_until(websocket, "run.done")

        websocket.send_json(
            frame(
                "memory.panel.update",
                {"action": "remove", "memory_id": str(spine.first_id)},
                message_id=SECOND_PROMPT_ID,
                thread_id=thread_id,
            )
        )
        panel = websocket.receive_json()
        assert panel["type"] == "memory.panel.update"
        assert panel["payload"]["action"] == "state"
        assert panel["payload"]["request_id"] == SECOND_PROMPT_ID
        assert panel["payload"]["result"] == "removed"
        assert [
            (item["memory"]["memory_id"], item["in_context"]) for item in panel["payload"]["items"]
        ] == [
            (str(spine.first_id), False),
            (str(spine.second_id), True),
        ]

        websocket.send_json(
            frame(
                "prompt.submit",
                {"prompt": "second"},
                message_id="01ARZ3NDEKTSV4RRFFQ69G5FAZ",
                thread_id=thread_id,
            )
        )
        receive_until(websocket, "run.done")

    assert spine.feedback_requests == [
        FeedbackRequest(
            injection_id=UUID(INJECTION_ID),
            memory_id=spine.first_id,
            signal=FeedbackSignal.MID_THREAD_REMOVED,
        )
    ]
    assert len(observed_calls) == 2
    second_requests = [
        message for message in observed_calls[1] if isinstance(message, ModelRequest)
    ]
    assert all(
        "remove this chartreuse body" not in (message.instructions or "")
        for message in second_requests
    )
    assert any(
        "keep this cobalt body" in (message.instructions or "") for message in second_requests
    )
    captured_event_types = [
        row["event"]["type"]
        for row in (
            json.loads(line)
            for line in transcript_journal.path_for_thread(thread_id).read_text().splitlines()
        )
        if row["record_type"] == "event"
    ]
    assert "memory.panel.update" not in captured_event_types


def test_unimplemented_known_type_uses_fresh_daemon_error(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that unimplemented known type uses fresh daemon error;
    this prevents drift in the daemon transport and event-loop contract.
    """
    transcript_journal = TranscriptJournal(tmp_path / "transcripts")
    factory = EnvelopeFactory(machine_id="harness-daemon")
    loop = RunLoop(
        CancellableRunner(),
        factory,
        transcript_journal=transcript_journal,
    )
    app = create_app(tmp_path, run_loop=loop, envelope_factory=factory)

    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("thread.create", {}))
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["payload"] == "not implemented"
    assert response["id"] != PROMPT_ID
    assert response["machine_id"] == "harness-daemon"
    assert response["thread_id"] == "thread-1"
    rows = [
        json.loads(line)
        for line in transcript_journal.path_for_thread("thread-1").read_text().splitlines()
    ]
    assert [row["event"]["type"] for row in rows] == ["error"]


def test_ws_custom_route_overrides_known_loop_handler(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws custom route overrides known loop handler;
    this prevents drift in the daemon transport and event-loop contract.
    """
    routed: list[MessageType] = []

    async def handler(message: Envelope, send: EnvelopeSender) -> None:
        assert isinstance(message.type, MessageType)
        routed.append(message.type)
        await send(message.model_copy(update={"type": MessageType.ERROR, "payload": "routed"}))

    client = TestClient(create_app(tmp_path, routes={MessageType.PROMPT_SUBMIT: handler}))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(valid_envelope())
        response = websocket.receive_json()

    assert response["type"] == "error"
    assert response["payload"] == "routed"
    assert routed == [MessageType.PROMPT_SUBMIT]


def test_ws_handler_may_stream_multiple_valid_envelopes(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws handler may stream multiple valid envelopes;
    this prevents drift in the daemon transport and event-loop contract.
    """
    factory = EnvelopeFactory(machine_id="daemon-test")

    async def stream(message: Envelope, send: EnvelopeSender) -> None:
        for index in range(2):
            await send(
                factory.create(
                    MessageType.ERROR,
                    {"index": index},
                    thread_id=message.thread_id,
                )
            )

    client = TestClient(
        create_app(
            tmp_path,
            routes={MessageType.PROMPT_SUBMIT: stream},
            envelope_factory=factory,
        )
    )

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(valid_envelope())
        assert websocket.receive_json()["payload"] == {"index": 0}
        assert websocket.receive_json()["payload"] == {"index": 1}


def test_ws_live_subscription_overflow_closes_for_snapshot_resync(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws live subscription overflow closes for snapshot
    resync; this prevents drift in the daemon transport and event-loop contract.
    """
    client = TestClient(create_app(tmp_path, run_loop=OverflowOnAttachLoop()))  # type: ignore[arg-type]

    with client.websocket_connect("/ws") as websocket:
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1013
    assert caught.value.reason == "snapshot resync required"


def test_ws_outbox_overflow_closes_for_snapshot_resync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC C.7 is defended by verifying that ws outbox overflow closes for snapshot resync;
    this prevents drift in the daemon transport and event-loop contract.
    """

    async def block_json_send(self, data, mode: str = "text") -> None:
        del self, data, mode
        await asyncio.Future()

    factory = EnvelopeFactory(machine_id="daemon-test")

    async def overflow(message: Envelope, send: EnvelopeSender) -> None:
        for index in range(4):
            await send(
                factory.create(
                    MessageType.ERROR,
                    {"index": index},
                    thread_id=message.thread_id,
                )
            )

    monkeypatch.setattr("harness.daemon._OUTBOX_BUFFER_SIZE", 2)
    monkeypatch.setattr("starlette.websockets.WebSocket.send_json", block_json_send)
    client = TestClient(
        create_app(
            tmp_path,
            routes={MessageType.PROMPT_SUBMIT: overflow},
            envelope_factory=factory,
        )
    )

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(valid_envelope())
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1013
    assert caught.value.reason == "snapshot resync required"


def test_ws_cancel_midstream_confirms_and_preserves_partial_work(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws cancel midstream confirms and preserves
    partial work; this prevents drift in the daemon transport and event-loop contract.
    """
    runner = CancellableRunner()
    client = TestClient(app_with_runner(runner, tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("prompt.submit", {"prompt": "first"}))
        started = websocket.receive_json()
        delta = websocket.receive_json()
        run_id = started["payload"]["run_id"]
        assert delta["payload"] == {
            "run_id": run_id,
            "kind": "text",
            "text": "kept partial",
        }

        websocket.send_json(
            frame(
                "run.cancel",
                {"run_id": run_id},
                message_id=CANCEL_ID,
                thread_id=None,
            )
        )
        done, seen = receive_until(websocket, "run.done")
        assert seen == ["run.usage", "run.done"]
        assert done["payload"] == {
            "run_id": run_id,
            "stop_reason": "cancelled",
            "partial": True,
        }

        websocket.send_json(
            frame(
                "thread.snapshot",
                {"request": True},
                message_id=SNAPSHOT_ID,
            )
        )
        snapshot = websocket.receive_json()

    assert snapshot["type"] == "thread.snapshot"
    assistant = next(
        message for message in snapshot["payload"]["messages"] if message["role"] == "assistant"
    )
    assert assistant["content"] == "kept partial"
    assert assistant["partial"] is True
    assert runner.calls == ["first"]


def test_ws_duplicate_cancel_while_cleanup_pending_shares_one_confirmation(
    tmp_path: Path,
) -> None:
    """SPEC C.7 is defended by verifying that ws duplicate cancel while cleanup pending shares
    one confirmation; this prevents drift in the daemon transport and event-loop contract.
    """
    runner = CancellableRunner(cleanup_delay=0.03)
    client = TestClient(app_with_runner(runner, tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("prompt.submit", {"prompt": "first"}))
        started = websocket.receive_json()
        assert websocket.receive_json()["type"] == "run.delta"
        run_id = started["payload"]["run_id"]

        websocket.send_json(
            frame(
                "run.cancel",
                {"run_id": run_id},
                message_id=CANCEL_ID,
            )
        )
        websocket.send_json(
            frame(
                "run.cancel",
                {"run_id": run_id},
                message_id=SNAPSHOT_ID,
            )
        )
        _, seen = receive_until(websocket, "run.done")
        assert seen.count("run.done") == 1
        assert "error" not in seen

        websocket.send_json(
            frame(
                "thread.snapshot",
                {"request": True},
                message_id="01ARZ3NDEKTSV4RRFFQ69G5FAZ",
            )
        )
        next_message = websocket.receive_json()

    assert next_message["type"] == "thread.snapshot"
    assert runner.calls == ["first"]


def test_ws_queues_prompt_and_runs_it_once_after_terminal_boundary(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws queues prompt and runs it once after terminal
    boundary; this prevents drift in the daemon transport and event-loop contract.
    """
    runner = CancellableRunner()
    client = TestClient(app_with_runner(runner, tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("prompt.submit", {"prompt": "first"}))
        first_started = websocket.receive_json()
        assert websocket.receive_json()["type"] == "run.delta"
        first_run_id = first_started["payload"]["run_id"]

        websocket.send_json(
            frame(
                "prompt.submit",
                {"prompt": "second"},
                message_id=SECOND_PROMPT_ID,
            )
        )
        queued = websocket.receive_json()
        second_run_id = queued["payload"]["run_id"]
        assert queued == {
            **queued,
            "type": "prompt.queued",
            "payload": {
                "run_id": second_run_id,
                "prompt_id": SECOND_PROMPT_ID,
            },
        }

        websocket.send_json(
            frame(
                "run.cancel",
                {"run_id": first_run_id},
                message_id=CANCEL_ID,
            )
        )
        messages: list[dict[str, object]] = []
        while True:
            message = websocket.receive_json()
            messages.append(message)
            if message["type"] == "run.done" and message["payload"]["run_id"] == second_run_id:
                break

    indexed = [(message["type"], message["payload"]["run_id"]) for message in messages]
    assert indexed.index(("run.done", first_run_id)) < indexed.index(("run.started", second_run_id))
    assert indexed.count(("run.started", second_run_id)) == 1
    assert indexed.count(("run.done", second_run_id)) == 1
    assert runner.calls == ["first", "second"]


def test_ws_reconnect_hydrates_once_from_snapshot_without_delta_replay(
    tmp_path: Path,
) -> None:
    """SPEC C.7 is defended by verifying that ws reconnect hydrates once from snapshot without
    delta replay; this prevents drift in the daemon transport and event-loop contract.
    """
    runner = CancellableRunner()
    with TestClient(app_with_runner(runner, tmp_path)) as client:
        with client.websocket_connect("/ws") as first_socket:
            first_socket.send_json(frame("prompt.submit", {"prompt": "first"}))
            started = first_socket.receive_json()
            delta = first_socket.receive_json()
            assert delta["type"] == "run.delta"
            run_id = started["payload"]["run_id"]

        with client.websocket_connect("/ws") as reconnected:
            snapshot = reconnected.receive_json()
            assert snapshot["type"] == "thread.snapshot"
            assert snapshot["payload"]["active_run"]["run_id"] == run_id
            assert snapshot["payload"]["messages"][-1]["content"] == "kept partial"

            reconnected.send_json(
                frame(
                    "run.cancel",
                    {"run_id": run_id},
                    message_id=CANCEL_ID,
                    thread_id=None,
                )
            )
            _, seen = receive_until(reconnected, "run.done")

    assert "thread.snapshot" not in seen
    assert "run.delta" not in seen
    assert runner.calls == ["first"]


@pytest.mark.parametrize("message_type", ["relay.connect", "run.steer"])
def test_unknown_and_reserved_types_forward_unchanged_or_ignore(
    tmp_path: Path, message_type: str
) -> None:
    """SPEC C.7 is defended by verifying that unknown and reserved types forward unchanged or
    ignore; this prevents drift in the daemon transport and event-loop contract.
    """
    forwarded: list[Envelope] = []

    async def forward(message: Envelope) -> None:
        forwarded.append(message)

    client = TestClient(create_app(tmp_path, forward_unknown=forward))
    incoming = frame(message_type, {"future": [1, True, None]})

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(incoming)
        websocket.send_json(
            frame(
                "thread.snapshot",
                {"request": True},
                message_id=SNAPSHOT_ID,
            )
        )
        response = websocket.receive_json()

    assert response["type"] == "thread.snapshot"
    assert len(forwarded) == 1
    assert forwarded[0].model_dump(mode="json", exclude_none=True) == incoming


def test_unknown_type_without_forwarder_is_ignored_without_closing(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that unknown type without forwarder is ignored without
    closing; this prevents drift in the daemon transport and event-loop contract.
    """
    client = TestClient(create_app(tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(frame("relay.connect", {"opaque": "value"}))
        websocket.send_json(
            frame(
                "thread.snapshot",
                {"request": True},
                message_id=SNAPSHOT_ID,
            )
        )
        response = websocket.receive_json()

    assert response["type"] == "thread.snapshot"
    assert response["payload"] == {
        "messages": [],
        "open_gate": None,
        "active_run": None,
    }


def test_snapshot_request_is_enqueued_before_a_later_direct_route_response(
    tmp_path: Path,
) -> None:
    """SPEC C.7 is defended by verifying that snapshot request is enqueued before a later
    direct route response; this prevents drift in the daemon transport and event-loop
    contract.
    """
    client = TestClient(create_app(tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(
            frame(
                "thread.snapshot",
                {"request": True},
                message_id=SNAPSHOT_ID,
            )
        )
        websocket.send_json(
            frame(
                "thread.create",
                {},
                message_id="01ARZ3NDEKTSV4RRFFQ69G5FAZ",
            )
        )
        first = websocket.receive_json()
        second = websocket.receive_json()

    assert first["type"] == "thread.snapshot"
    assert second["type"] == "error"


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "null",
        "[]",
        json.dumps({**valid_envelope(), "payload": float("nan")}),
        json.dumps({key: value for key, value in valid_envelope().items() if key != "payload"}),
        json.dumps({**valid_envelope(), "v": 2}),
        json.dumps({**valid_envelope(), "type": " "}),
        json.dumps(
            {
                **valid_envelope(),
                "type": "run.delta",
                "payload": {"kind": "text", "text": "missing run"},
            }
        ),
        json.dumps({**valid_envelope(), "localhost": True}),
    ],
)
def test_ws_rejects_malformed_text_envelope(tmp_path: Path, raw: str) -> None:
    """SPEC C.7 is defended by verifying that ws rejects malformed text envelope; this prevents
    drift in the daemon transport and event-loop contract.
    """
    client = TestClient(create_app(tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_text(raw)
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1008
    assert caught.value.reason == "invalid C.7 envelope"


@pytest.mark.parametrize(
    "raw_payload",
    [
        pytest.param("9" * 10_000, id="integer-parser-limit"),
        pytest.param("[" * 20_000 + "0" + "]" * 20_000, id="recursive-json"),
    ],
)
def test_ws_rejects_json_parser_limits(tmp_path: Path, raw_payload: str) -> None:
    """SPEC C.7 is defended by verifying that ws rejects json parser limits; this prevents
    drift in the daemon transport and event-loop contract.
    """
    client = TestClient(create_app(tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_text(envelope_with_raw_payload(raw_payload))
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1008
    assert caught.value.reason == "invalid C.7 envelope"


def test_ws_rejects_binary_frame_without_routing(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws rejects binary frame without routing; this
    prevents drift in the daemon transport and event-loop contract.
    """
    routed = False

    async def handler(message: Envelope, send: EnvelopeSender) -> None:
        nonlocal routed
        routed = True

    client = TestClient(create_app(tmp_path, routes={MessageType.PROMPT_SUBMIT: handler}))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_bytes(json.dumps(valid_envelope()).encode())
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1008
    assert caught.value.reason == "invalid C.7 envelope"
    assert routed is False


def test_ws_stops_routing_after_first_malformed_message(tmp_path: Path) -> None:
    """SPEC C.7 is defended by verifying that ws stops routing after first malformed message;
    this prevents drift in the daemon transport and event-loop contract.
    """
    routed: list[str] = []

    async def handler(message: Envelope, send: EnvelopeSender) -> None:
        routed.append(message.id)
        await send(message.model_copy(update={"type": MessageType.ERROR, "payload": "routed"}))

    client = TestClient(create_app(tmp_path, routes={MessageType.PROMPT_SUBMIT: handler}))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(valid_envelope())
        assert websocket.receive_json()["type"] == "error"
        websocket.send_text("{")
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1008
    assert routed == [PROMPT_ID]


@pytest.mark.parametrize("path", ["/ws/", "/unknown"])
def test_built_static_mode_rejects_unknown_websocket_path(tmp_path: Path, path: str) -> None:
    """SPEC C.7 is defended by verifying that built static mode rejects unknown websocket path;
    this prevents drift in the daemon transport and event-loop contract.
    """
    (tmp_path / "index.html").write_text("<h1>Harness shell</h1>", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json(valid_envelope())
        assert websocket.receive_json()["type"] == "run.started"

    with client.websocket_connect(path) as websocket:
        with pytest.raises(WebSocketDisconnect) as caught:
            websocket.receive_json()

    assert caught.value.code == 1008
    assert caught.value.reason == "unknown WebSocket route"
