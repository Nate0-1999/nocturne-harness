from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from harness.agent import ExtractionCandidateDraft, ExtractionDraft, ExtractionVerdictDraft
from harness.extraction import ExtractionIdleScheduler, ExtractionService
from harness.spine_client import (
    ExtractionResponse,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    QueueCard,
    QueueResponse,
    SpineTransportError,
)
from harness.transcript import TranscriptJournal

ITEM_UID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
MEMORY_ID = UUID("60000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 8, 8, 22, tzinfo=UTC)


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def extract_thread(self, transcript: str) -> ExtractionDraft:
        self.calls.append(transcript)
        return ExtractionDraft(
            working_summary="Queue law was settled.",
            open_loops=["Verify the browser surface."],
            candidates=[
                ExtractionCandidateDraft(
                    label="Queue consent",
                    body="Thread-born memory candidates require owner consent.",
                    kind="procedure",
                    keywords=["queue", "consent"],
                )
            ],
        )

    async def propose_extraction_verdict(self, candidate, neighbors):
        return ExtractionVerdictDraft(verdict="new", target_ids=[])


class FakeSpine:
    def __init__(
        self, *, fail_create: bool = False, pending: list[QueueCard] | None = None
    ) -> None:
        self.requests = []
        self.fail_create = fail_create
        self.pending = pending or []

    async def create_extraction(self, request):
        self.requests.append(request)
        if self.fail_create:
            raise SpineTransportError
        return ExtractionResponse(cards=[], duplicate_count=1)

    async def approval_queue(self, principal_id: str, *, thread_id=None, birthplace=None):
        return QueueResponse(cards=self.pending)

    async def search(self, request):
        from harness.spine_client import SearchResponse

        return SearchResponse(results=[])


def _thread_card(
    thread_id: UUID, *, body: str = "Thread-born memory candidates require owner consent."
) -> QueueCard:
    return QueueCard(
        item_uid=ITEM_UID,
        candidate=MemoryUnit(
            memory_id=MEMORY_ID,
            principal_id="owner",
            label="Queue consent",
            body=body,
            kind=MemoryKind.PROCEDURE,
            keywords=["queue", "consent"],
            project_key=None,
            thread_origin=str(thread_id),
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
        birthplace="thread",
        birthplace_thread_id=thread_id,
        batch_uid=None,
        source_name=None,
        source_sha256=None,
        verdict="new",
        neighbors=[],
        target_ids=[],
        state="pending",
        created_at=NOW,
    )


def _journal(root: Path, thread_id: str, now: datetime) -> TranscriptJournal:
    journal = TranscriptJournal(root, clock=lambda: now)
    journal.append_message(
        thread_id,
        {"message_id": "01K1M2A0000000000000000001", "role": "user", "content": "Keep it."},
        parent_id=None,
    )
    journal.append_message(
        thread_id,
        {
            "message_id": "01K1M2A0000000000000000002",
            "role": "assistant",
            "content": "I will preserve consent.",
        },
        parent_id="01K1M2A0000000000000000001",
    )
    return journal


@pytest.mark.asyncio
async def test_archive_reads_durable_transcript_and_is_idempotent_per_tail(tmp_path: Path) -> None:
    """A-033 is defended by verifying that archive reads durable transcript and is idempotent
    per tail; this prevents drift in the thread extraction trigger and idempotency contract.
    """
    thread_id = uuid4()
    journal = _journal(tmp_path / "transcripts", str(thread_id), datetime.now(UTC))
    agent = FakeAgent()
    spine = FakeSpine()
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=spine,
        principal_id="owner",
        machine_id="mac",
    )

    first = await service.archive(thread_id)
    second = await service.archive(thread_id)

    assert first.final_post == "I will preserve consent."
    assert first.duplicate_count == 1
    assert first.already_extracted is False
    assert second.already_extracted is True
    assert len(agent.calls) == 1
    assert len(spine.requests) == 1
    assert spine.requests[0].candidates[0].verdict == "new"
    assert journal.extracted_tail(str(thread_id)) == journal.transcript_tail(str(thread_id))


@pytest.mark.asyncio
async def test_idle_scheduler_uses_same_archive_path(tmp_path: Path) -> None:
    """A-033 is defended by verifying that idle scheduler uses same archive path; this prevents
    drift in the thread extraction trigger and idempotency contract.
    """
    thread_id = uuid4()
    old = datetime.now(UTC) - timedelta(hours=4)
    journal = _journal(tmp_path / "transcripts", str(thread_id), old)
    agent = FakeAgent()
    spine = FakeSpine()
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=spine,
        principal_id="owner",
        machine_id="mac",
    )
    scheduler = ExtractionIdleScheduler(service, journal, idle_hours=2)

    await scheduler.run_once()

    assert len(agent.calls) == 1
    assert journal.extracted_tail(str(thread_id)) == journal.transcript_tail(str(thread_id))


@pytest.mark.asyncio
async def test_archive_transport_failure_reconciles_then_marks_the_tail(tmp_path: Path) -> None:
    """F022 and A-032 require archive to recover an exact thread candidate after a false
    failure and mark the tail so a second archive does not create duplicate work.
    """
    thread_id = uuid4()
    journal = _journal(tmp_path / "transcripts", str(thread_id), datetime.now(UTC))
    agent = FakeAgent()
    spine = FakeSpine(fail_create=True, pending=[_thread_card(thread_id)])
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    first = await service.archive(thread_id)
    second = await service.archive(thread_id)

    assert [card.item_uid for card in first.cards] == [ITEM_UID]
    assert first.already_extracted is False
    assert second.already_extracted is True
    assert len(agent.calls) == 1
    assert len(spine.requests) == 1
    assert journal.extracted_tail(str(thread_id)) == journal.transcript_tail(str(thread_id))


@pytest.mark.asyncio
async def test_archive_transport_failure_stays_loud_without_exact_candidate(
    tmp_path: Path,
) -> None:
    """F022 requires archive failure to remain visible when the thread queue contains no
    candidate that proves the attempted extraction became durable.
    """
    thread_id = uuid4()
    journal = _journal(tmp_path / "transcripts", str(thread_id), datetime.now(UTC))
    spine = FakeSpine(
        fail_create=True,
        pending=[_thread_card(thread_id, body="A different extraction tail.")],
    )
    service = ExtractionService(
        journal=journal,
        agent=FakeAgent(),  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    with pytest.raises(SpineTransportError):
        await service.archive(thread_id)

    assert journal.extracted_tail(str(thread_id)) is None
