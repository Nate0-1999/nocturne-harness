"""End-to-end decision-provenance regressions for M2Y1 / F023."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    BatchDecisionResponse,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    QueueCard,
    QueueDecisionRequest,
    QueueDecisionResponse,
)
from harness.transcript import TranscriptJournal

ITEM_UID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
DECISION_UID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
BATCH_UID = UUID("50000000-0000-4000-8000-000000000001")
MEMORY_ID = UUID("60000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 8, 8, 22, tzinfo=UTC)


class DecisionSpine:
    def __init__(self) -> None:
        self.requests: list[QueueDecisionRequest] = []

    async def decide_queue_item(
        self, item_uid: str, request: QueueDecisionRequest
    ) -> QueueDecisionResponse:
        self.requests.append(request)
        return QueueDecisionResponse(
            card=_card(item_uid=item_uid, batch_uid=None, request=request),
            decision=request.decision,
            approval_mode=request.approval_mode,
            actor_class=request.actor_class,
            decision_uid=DECISION_UID,
        )

    async def decide_queue_batch(
        self, batch_uid: UUID, request: QueueDecisionRequest
    ) -> BatchDecisionResponse:
        self.requests.append(request)
        return BatchDecisionResponse(
            batch_uid=batch_uid,
            decision=request.decision,
            cards=[_card(item_uid=ITEM_UID, batch_uid=batch_uid, request=request)],
        )

    async def aclose(self) -> None:
        pass


def _card(*, item_uid: str, batch_uid: UUID | None, request: QueueDecisionRequest) -> QueueCard:
    state = "approved" if request.decision == "approve" else "rejected"
    return QueueCard(
        item_uid=item_uid,
        candidate=MemoryUnit(
            memory_id=MEMORY_ID,
            principal_id="principal-test",
            label="Decision provenance",
            body="The daemon owns the machine identity on queue decisions.",
            kind=MemoryKind.FACT,
            keywords=["decision", "provenance"],
            project_key=None,
            thread_origin=None,
            origin_path=None,
            pin=False,
            status=MemoryStatus.CANDIDATE,
            revision=1,
            stats={},
            bias=0,
            embedding_model="fixture",
            created_at=NOW,
            updated_at=NOW,
        ),
        birthplace="seed" if batch_uid is not None else "thread",
        birthplace_thread_id=(
            None if batch_uid is not None else UUID("70000000-0000-4000-8000-000000000001")
        ),
        batch_uid=batch_uid,
        source_name="decision.md" if batch_uid is not None else None,
        source_sha256="0" * 64 if batch_uid is not None else None,
        verdict="new",
        neighbors=[],
        target_ids=[],
        state=state,
        created_at=NOW,
    )


def _app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    machine_id: str,
    spine: DecisionSpine,
):
    state_home = tmp_path / machine_id
    monkeypatch.setenv("NOCTURNE_HOME", str(state_home))
    settings = HarnessSettings(
        _env_file=None,
        spine_token="test-token",
        principal_id="principal-test",
        machine_id=machine_id,
        agent_id="agent-test",
        extraction_idle_hours=None,
        anthropic_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
    )

    async def stream(_messages, _info):
        yield "unused"

    return create_dev_app(
        tmp_path,
        settings=settings,
        agent=HarnessAgent(settings, model=FunctionModel(stream_function=stream)),
        spine=spine,  # type: ignore[arg-type]
        transcript_journal=TranscriptJournal(state_home / "transcripts"),
    )


@pytest.mark.parametrize(
    ("machine_id", "path", "payload"),
    [
        (
            "nocturne-owner-machine",
            f"/v1/approval-queue/{ITEM_UID}/decisions",
            {
                "decision": "approve",
                "approval_mode": "explicit",
                "actor_class": "human",
            },
        ),
        (
            "m2y1-sop-verification",
            f"/v1/approval-queue/batches/{BATCH_UID}/decisions",
            {
                "decision": "deny",
                "approval_mode": "explicit",
                "actor_class": "human",
            },
        ),
    ],
)
def test_queue_taps_land_with_the_daemon_machine_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    machine_id: str,
    path: str,
    payload: dict[str, str],
) -> None:
    """F023 requires owner and verification taps to keep distinct trusted provenance."""
    spine = DecisionSpine()
    app = _app(tmp_path, monkeypatch, machine_id=machine_id, spine=spine)

    with TestClient(app) as client:
        response = client.post(path, json=payload)

    assert response.status_code == 200
    assert [request.machine_id for request in spine.requests] == [machine_id]


def test_queue_tap_cannot_supply_or_override_machine_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F023 forbids browser-authored machine identity at the owner API boundary."""
    spine = DecisionSpine()
    app = _app(tmp_path, monkeypatch, machine_id="trusted-daemon", spine=spine)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/approval-queue/{ITEM_UID}/decisions",
            json={
                "decision": "approve",
                "approval_mode": "explicit",
                "actor_class": "human",
                "machine_id": "forged-browser",
            },
        )

    assert response.status_code == 422
    assert spine.requests == []


def test_owner_api_publishes_choice_fields_without_machine_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F023 keeps machine identity out of the browser-visible decision contract."""
    app = _app(
        tmp_path,
        monkeypatch,
        machine_id="trusted-daemon",
        spine=DecisionSpine(),
    )

    with TestClient(app) as client:
        document = client.get("/openapi.json").json()

    request_ref = document["paths"][f"/v1/approval-queue/{'{item_uid}'}/decisions"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]["$ref"]
    schema_name = request_ref.rsplit("/", 1)[-1]
    properties = document["components"]["schemas"][schema_name]["properties"]

    assert set(properties) == {"decision", "approval_mode", "actor_class"}
