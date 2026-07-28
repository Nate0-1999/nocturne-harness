from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    MemoryPanelConflictPayload,
    MemoryPanelEditPayload,
    MemoryPanelErrorPayload,
    MemoryPanelPinPayload,
    MemoryPanelRefreshPayload,
    MemoryPanelRemovePayload,
    MemoryPanelStatePayload,
)
from harness.memory_panel import (
    EMPTY_MEMORY_BLOCK,
    MemoryPanelController,
    ThreadMemoryContextRegistry,
)
from harness.spine_client import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSignal,
    InjectPrepareResponse,
    ListMemoriesParams,
    MemoryFeatures,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    ProblemDetail,
    RevisionConflict,
    ScoredMemoryCard,
    SpineProblemError,
    SpineTransportError,
)

REQUEST_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
THREAD_ID = "22345678-1234-5678-1234-567812345678"
INJECTION_ID = UUID("32345678-1234-5678-1234-567812345678")
MEMORY_A = UUID("42345678-1234-5678-1234-567812345678")
MEMORY_B = UUID("52345678-1234-5678-1234-567812345678")
MEMORY_C = UUID("62345678-1234-5678-1234-567812345678")
SNAPSHOT_TS = datetime(2026, 7, 28, 12, tzinfo=UTC)


def memory_card(
    memory_id: UUID,
    *,
    label: str,
    body: str,
    rank: int,
    kind: MemoryKind = MemoryKind.FACT,
) -> ScoredMemoryCard:
    return ScoredMemoryCard(
        memory_id=memory_id,
        label=label,
        body=body,
        kind=kind,
        pin=False,
        score=0.9,
        features=MemoryFeatures(sem=0.9, kw=0.8, time=0.7, proj=0.6, freq=0.5, hist=0.4),
        rank=rank,
    )


def memory_unit(
    memory_id: UUID,
    *,
    principal_id: str = "principal-1",
    label: str = "Memory",
    body: str = "Body",
    revision: int = 1,
    pin: bool = False,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    updated_offset: int = 0,
) -> MemoryUnit:
    return MemoryUnit(
        memory_id=memory_id,
        principal_id=principal_id,
        label=label,
        body=body,
        kind=MemoryKind.FACT,
        keywords=["memory"],
        project_key=None,
        thread_origin=THREAD_ID,
        origin_path=None,
        pin=pin,
        status=status,
        revision=revision,
        stats={
            "injections": 1,
            "removals": 0,
            "citations": 0,
            "never_kills": 0,
            "last_injected_at": None,
        },
        bias=0.0,
        embedding_model="test-embedding",
        created_at=SNAPSHOT_TS - timedelta(days=1),
        updated_at=SNAPSHOT_TS + timedelta(seconds=updated_offset),
    )


def final_block(cards: list[ScoredMemoryCard]) -> str:
    if not cards:
        return EMPTY_MEMORY_BLOCK
    fragments = [
        (
            f'<memory label="{_escape_attribute(card.label)}" '
            f'kind="{card.kind.value}" updated="2026-07-28T12:00:00Z">\n'
            f"{_escape_body(card.body)}\n"
            "</memory>"
        )
        for card in cards
    ]
    return (
        "<memory_system>\n"
        "The following long-term memories were retrieved for this conversation.\n"
        "Treat them as your own accumulated knowledge; they may be imperfect.\n"
        + "\n".join(fragments)
        + "\n</memory_system>"
    )


def prepared(cards: list[ScoredMemoryCard]) -> InjectPrepareResponse:
    return InjectPrepareResponse(
        injection_id=INJECTION_ID,
        snapshot_ts=SNAPSHOT_TS,
        scorer_version="m1-v1",
        injected=cards,
        near_misses=[],
    )


def install_context(
    contexts: ThreadMemoryContextRegistry,
    cards: list[ScoredMemoryCard],
) -> None:
    contexts.install(
        THREAD_ID,
        prepared=prepared(cards),
        removed_memory_ids=frozenset(),
        added_back=[],
        final_block=final_block(cards),
    )


def request(payload: dict[str, object]) -> Envelope:
    return Envelope.model_validate(
        {
            "v": 1,
            "id": REQUEST_ID,
            "ts": "2026-07-28T12:00:00Z",
            "machine_id": "browser-machine",
            "thread_id": THREAD_ID,
            "type": "memory.panel.update",
            "payload": payload,
        }
    )


@dataclass
class FakeSpine:
    memories: list[MemoryUnit]
    page_size: int = 2
    feedback_outcome: FeedbackResponse | Exception = field(
        default_factory=lambda: FeedbackResponse(ok=True)
    )
    patch_outcomes: list[MemoryUnit | Exception] = field(default_factory=list)
    list_requests: list[ListMemoriesParams] = field(default_factory=list)
    feedback_requests: list[FeedbackRequest] = field(default_factory=list)
    patch_requests: list[tuple[UUID, PatchMemoryRequest]] = field(default_factory=list)

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        self.list_requests.append(params)
        page_items = self.memories[params.offset : params.offset + self.page_size]
        return PagedMemoryListResponse(
            items=page_items,
            total=len(self.memories),
            limit=params.limit,
            offset=params.offset,
        )

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        self.feedback_requests.append(request)
        if isinstance(self.feedback_outcome, Exception):
            raise self.feedback_outcome
        return self.feedback_outcome

    async def patch_memory(self, memory_id: UUID, request: PatchMemoryRequest) -> MemoryUnit:
        self.patch_requests.append((memory_id, request))
        if self.patch_outcomes:
            outcome = self.patch_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            updated = outcome
        else:
            current = next(item for item in self.memories if item.memory_id == memory_id)
            updated = current.model_copy(
                update={
                    "body": request.body if request.body is not None else current.body,
                    "pin": request.pin if request.pin is not None else current.pin,
                    "revision": current.revision + 1,
                    "updated_at": current.updated_at + timedelta(seconds=1),
                }
            )
        self.memories = [
            updated if item.memory_id == updated.memory_id else item for item in self.memories
        ]
        self.memories.sort(key=lambda item: (-item.updated_at.timestamp(), item.memory_id.int))
        return updated


def controller(
    spine: FakeSpine,
    contexts: ThreadMemoryContextRegistry | None = None,
) -> MemoryPanelController:
    return MemoryPanelController(
        spine,
        contexts or ThreadMemoryContextRegistry(),
        EnvelopeFactory(machine_id="trusted-machine", agent_id="agent-1"),
        principal_id="principal-1",
        machine_id="trusted-machine",
    )


async def handle(
    panel: MemoryPanelController,
    payload: MemoryPanelRefreshPayload
    | MemoryPanelRemovePayload
    | MemoryPanelEditPayload
    | MemoryPanelPinPayload,
) -> Envelope:
    sent: list[Envelope] = []

    async def record(message: Envelope) -> None:
        sent.append(message)

    await panel.handle(request(payload.model_dump(mode="json")), record)
    assert len(sent) == 1
    return sent[0]


@pytest.mark.asyncio
async def test_refresh_pages_global_active_list_before_principal_filtering() -> None:
    cards = [memory_card(MEMORY_A, label="A", body="A body", rank=1)]
    contexts = ThreadMemoryContextRegistry()
    install_context(contexts, cards)
    spine = FakeSpine(
        [
            memory_unit(MEMORY_C, principal_id="other-principal", label="Foreign"),
            memory_unit(MEMORY_A, label="A", body="A body"),
            memory_unit(MEMORY_B, label="B"),
            memory_unit(
                UUID("72345678-1234-5678-1234-567812345678"),
                label="Quarantined",
                status=MemoryStatus.QUARANTINED,
            ),
        ]
    )

    response = await handle(
        controller(spine, contexts),
        MemoryPanelRefreshPayload(action="refresh"),
    )

    assert isinstance(response.payload, MemoryPanelStatePayload)
    assert response.payload.request_id == REQUEST_ID
    assert response.payload.result == "refreshed"
    assert response.payload.total == 2
    assert [item.memory.memory_id for item in response.payload.items] == [MEMORY_A, MEMORY_B]
    assert [item.in_context for item in response.payload.items] == [True, False]
    assert [item.offset for item in spine.list_requests] == [0, 2]
    assert all(
        item.status is MemoryStatus.ACTIVE and item.limit == 200 for item in spine.list_requests
    )


@pytest.mark.asyncio
async def test_remove_uses_server_injection_then_rebinds_exact_block_and_exclusions() -> None:
    first = memory_card(
        MEMORY_A,
        label='A & "quoted"',
        body="First <body>\nline two",
        rank=1,
    )
    second = memory_card(MEMORY_B, label="B", body="Second body", rank=2)
    contexts = ThreadMemoryContextRegistry()
    install_context(contexts, [first, second])
    spine = FakeSpine(
        [
            memory_unit(MEMORY_A, label=first.label, body=first.body),
            memory_unit(MEMORY_B, label=second.label, body=second.body),
        ]
    )

    response = await handle(
        controller(spine, contexts),
        MemoryPanelRemovePayload(action="remove", memory_id=MEMORY_A),
    )

    assert spine.feedback_requests == [
        FeedbackRequest(
            injection_id=INJECTION_ID,
            memory_id=MEMORY_A,
            signal=FeedbackSignal.MID_THREAD_REMOVED,
        )
    ]
    snapshot = contexts.snapshot(THREAD_ID)
    assert snapshot is not None
    assert snapshot.member_ids == frozenset({MEMORY_B})
    assert snapshot.excluded_memory_ids == frozenset({MEMORY_A})
    assert snapshot.final_block == final_block([second])
    assert first.body not in snapshot.final_block
    assert isinstance(response.payload, MemoryPanelStatePayload)
    assert response.payload.result == "removed"
    assert [item.in_context for item in response.payload.items] == [False, True]


@pytest.mark.asyncio
async def test_failed_feedback_returns_safe_error_without_mutating_thread_state() -> None:
    card = memory_card(MEMORY_A, label="A", body="Secret response text", rank=1)
    contexts = ThreadMemoryContextRegistry()
    install_context(contexts, [card])
    before = contexts.snapshot(THREAD_ID)
    spine = FakeSpine(
        [memory_unit(MEMORY_A, label=card.label, body=card.body)],
        feedback_outcome=SpineTransportError(),
    )

    response = await handle(
        controller(spine, contexts),
        MemoryPanelRemovePayload(action="remove", memory_id=MEMORY_A),
    )

    assert contexts.snapshot(THREAD_ID) == before
    assert isinstance(response.payload, MemoryPanelErrorPayload)
    assert response.payload.operation == "remove"
    assert response.payload.code == "memory_unavailable"
    assert "Secret response text" not in response.payload.message


@pytest.mark.asyncio
async def test_panel_error_never_exposes_problem_response_body() -> None:
    card = memory_card(MEMORY_A, label="A", body="Body", rank=1)
    contexts = ThreadMemoryContextRegistry()
    install_context(contexts, [card])
    secret = "credential-like raw service detail"
    problem = SpineProblemError(
        httpx.Response(
            409,
            request=httpx.Request("POST", "http://spine.test/v1/feedback"),
        ),
        ProblemDetail(title="Conflict", status=409, detail=secret),
    )
    spine = FakeSpine(
        [memory_unit(MEMORY_A, label=card.label, body=card.body)],
        feedback_outcome=problem,
    )

    response = await handle(
        controller(spine, contexts),
        MemoryPanelRemovePayload(action="remove", memory_id=MEMORY_A),
    )

    assert isinstance(response.payload, MemoryPanelErrorPayload)
    assert response.payload.code == "memory_rejected"
    assert secret not in response.payload.message


@pytest.mark.asyncio
async def test_remove_waits_for_an_active_model_run_before_feedback_and_mutation() -> None:
    card = memory_card(MEMORY_A, label="A", body="Body", rank=1)
    contexts = ThreadMemoryContextRegistry()
    install_context(contexts, [card])
    spine = FakeSpine([memory_unit(MEMORY_A, label=card.label, body=card.body)])
    panel = controller(spine, contexts)

    async with contexts.model_feedback_boundary(THREAD_ID):
        task = asyncio.create_task(
            handle(
                panel,
                MemoryPanelRemovePayload(action="remove", memory_id=MEMORY_A),
            )
        )
        await asyncio.sleep(0)
        assert spine.feedback_requests == []
        snapshot = contexts.snapshot(THREAD_ID)
        assert snapshot is not None
        assert snapshot.member_ids == frozenset({MEMORY_A})

    response = await asyncio.wait_for(task, 1)
    assert spine.feedback_requests[0].memory_id == MEMORY_A
    assert isinstance(response.payload, MemoryPanelStatePayload)
    snapshot = contexts.snapshot(THREAD_ID)
    assert snapshot is not None
    assert snapshot.member_ids == frozenset()


@pytest.mark.asyncio
async def test_remove_rejects_nonmember_without_contacting_spine() -> None:
    spine = FakeSpine([memory_unit(MEMORY_A)])

    response = await handle(
        controller(spine),
        MemoryPanelRemovePayload(action="remove", memory_id=MEMORY_A),
    )

    assert spine.feedback_requests == []
    assert spine.list_requests == []
    assert isinstance(response.payload, MemoryPanelErrorPayload)
    assert response.payload.code == "not_in_context"


@pytest.mark.asyncio
async def test_edit_uses_browser_revision_and_daemon_owned_provenance() -> None:
    original = memory_unit(MEMORY_A, body="Old body", revision=4)
    spine = FakeSpine([original])
    contexts = ThreadMemoryContextRegistry()
    install_context(
        contexts,
        [memory_card(MEMORY_A, label=original.label, body=original.body, rank=1)],
    )
    frozen = contexts.snapshot(THREAD_ID)

    response = await handle(
        controller(spine, contexts),
        MemoryPanelEditPayload(
            action="edit",
            memory_id=MEMORY_A,
            expected_revision=4,
            body="New body",
        ),
    )

    assert spine.patch_requests == [
        (
            MEMORY_A,
            PatchMemoryRequest(
                expected_revision=4,
                body="New body",
                editor="user",
                reason="panel/edit",
                machine_id="trusted-machine",
            ),
        )
    ]
    assert isinstance(response.payload, MemoryPanelStatePayload)
    assert response.payload.result == "edited"
    assert response.payload.items[0].memory.body == "New body"
    assert response.payload.items[0].memory.revision == 5
    assert contexts.snapshot(THREAD_ID) == frozen


@pytest.mark.asyncio
async def test_pin_uses_browser_revision_and_daemon_owned_provenance() -> None:
    original = memory_unit(MEMORY_A, revision=7, pin=False)
    spine = FakeSpine([original])
    contexts = ThreadMemoryContextRegistry()
    install_context(
        contexts,
        [memory_card(MEMORY_A, label=original.label, body=original.body, rank=1)],
    )
    frozen = contexts.snapshot(THREAD_ID)

    response = await handle(
        controller(spine, contexts),
        MemoryPanelPinPayload(
            action="pin",
            memory_id=MEMORY_A,
            expected_revision=7,
            pin=True,
        ),
    )

    assert spine.patch_requests == [
        (
            MEMORY_A,
            PatchMemoryRequest(
                expected_revision=7,
                pin=True,
                editor="user",
                reason="panel/pin",
                machine_id="trusted-machine",
            ),
        )
    ]
    assert isinstance(response.payload, MemoryPanelStatePayload)
    assert response.payload.result == "pin_changed"
    assert response.payload.items[0].memory.pin is True
    assert response.payload.items[0].memory.revision == 8
    assert contexts.snapshot(THREAD_ID) == frozen


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["edit", "pin"])
async def test_patch_cas_conflict_surfaces_current_unit_without_retry(operation: str) -> None:
    original = memory_unit(MEMORY_A, revision=2)
    current = memory_unit(
        MEMORY_A,
        revision=3,
        body="Concurrent body",
        pin=True,
        status=MemoryStatus.TOMBSTONED,
    )
    conflict = PatchMemoryConflictError(
        httpx.Response(
            409,
            request=httpx.Request("PATCH", f"http://spine.test/v1/memories/{MEMORY_A}"),
        ),
        RevisionConflict(conflict=current),
    )
    spine = FakeSpine([original], patch_outcomes=[conflict])
    payload: MemoryPanelEditPayload | MemoryPanelPinPayload
    if operation == "edit":
        payload = MemoryPanelEditPayload(
            action="edit",
            memory_id=MEMORY_A,
            expected_revision=2,
            body="Stale edit",
        )
    else:
        payload = MemoryPanelPinPayload(
            action="pin",
            memory_id=MEMORY_A,
            expected_revision=2,
            pin=True,
        )

    response = await handle(controller(spine), payload)

    assert len(spine.patch_requests) == 1
    assert isinstance(response.payload, MemoryPanelConflictPayload)
    assert response.payload.operation == operation
    assert response.payload.memory == current
    assert "try again" in response.payload.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current",
    [
        memory_unit(MEMORY_B, revision=3),
        memory_unit(MEMORY_A, principal_id="other-principal", revision=3),
    ],
)
async def test_patch_rejects_conflict_unit_outside_requested_principal_boundary(
    current: MemoryUnit,
) -> None:
    original = memory_unit(MEMORY_A, revision=2)
    conflict = PatchMemoryConflictError(
        httpx.Response(
            409,
            request=httpx.Request("PATCH", f"http://spine.test/v1/memories/{MEMORY_A}"),
        ),
        RevisionConflict(conflict=current),
    )
    spine = FakeSpine([original], patch_outcomes=[conflict])

    response = await handle(
        controller(spine),
        MemoryPanelEditPayload(
            action="edit",
            memory_id=MEMORY_A,
            expected_revision=2,
            body="Stale edit",
        ),
    )

    assert len(spine.patch_requests) == 1
    assert isinstance(response.payload, MemoryPanelErrorPayload)
    assert response.payload.code == "invalid_response"
    assert "other-principal" not in response.payload.message
    assert str(MEMORY_B) not in response.payload.message


@pytest.mark.asyncio
async def test_edit_cannot_target_another_principals_memory() -> None:
    spine = FakeSpine([memory_unit(MEMORY_A, principal_id="other-principal")])

    response = await handle(
        controller(spine),
        MemoryPanelEditPayload(
            action="edit",
            memory_id=MEMORY_A,
            expected_revision=1,
            body="Unauthorized edit",
        ),
    )

    assert spine.patch_requests == []
    assert isinstance(response.payload, MemoryPanelErrorPayload)
    assert response.payload.code == "memory_not_found"


def test_context_install_fails_closed_on_unbindable_final_block() -> None:
    card = memory_card(MEMORY_A, label="A", body="Body", rank=1)
    contexts = ThreadMemoryContextRegistry()

    with pytest.raises(ValueError, match="fragment"):
        contexts.install(
            THREAD_ID,
            prepared=prepared([card]),
            removed_memory_ids=frozenset(),
            added_back=[],
            final_block=final_block(
                [memory_card(MEMORY_B, label="Different", body="Body", rank=1)]
            ),
        )

    assert contexts.snapshot(THREAD_ID) is None


def test_context_install_binds_commit_membership_in_rank_order() -> None:
    removed = memory_card(MEMORY_A, label="Removed", body="Removed body", rank=1)
    retained = memory_card(MEMORY_B, label="Retained", body="Retained body", rank=3)
    added = memory_card(MEMORY_C, label="Added", body="Added body", rank=2)
    response = InjectPrepareResponse(
        injection_id=INJECTION_ID,
        snapshot_ts=SNAPSHOT_TS,
        scorer_version="m1-v1",
        injected=[removed, retained],
        near_misses=[added],
    )
    contexts = ThreadMemoryContextRegistry()

    snapshot = contexts.install(
        THREAD_ID,
        prepared=response,
        removed_memory_ids=frozenset({MEMORY_A}),
        added_back=[MEMORY_C],
        final_block=final_block([added, retained]),
    )

    assert snapshot.member_ids == frozenset({MEMORY_B, MEMORY_C})
    assert snapshot.excluded_memory_ids == frozenset()
    assert snapshot.final_block == final_block([added, retained])
    assert snapshot.final_block.index("Added body") < snapshot.final_block.index("Retained body")
    assert "Removed body" not in snapshot.final_block


def _escape_attribute(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\t", "&#9;")
        .replace("\n", "&#10;")
        .replace("\r", "&#13;")
    )


def _escape_body(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
