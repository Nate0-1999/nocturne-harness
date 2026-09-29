import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from harness.agent import ExtractionCandidateDraft, ExtractionDraft, ExtractionVerdictDraft
from harness.envelope import ImageInput
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

    async def extract_thread(self, transcript: str, **_: object) -> ExtractionDraft:
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
            origin_thread_id=thread_id,
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
    # Symphony progress appends snapshots of the same assistant message.
    latest = journal.read_messages(str(thread_id))[-1]
    latest["events"] = [{"event_kind": "symphony_result", "result": "accepted work"}]
    journal.append_message(str(thread_id), latest, parent_id=latest.get("parentId"))
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
    extracted = json.loads(agent.calls[0])
    assert len(extracted) == 2
    assert extracted[-1]["events"] == latest["events"]
    assert len(journal.read_messages(str(thread_id))) == 3
    assert len(spine.requests) == 1
    assert spine.requests[0].candidates[0].verdict == "new"
    assert journal.extracted_tail(str(thread_id)) == journal.transcript_tail(str(thread_id))


@pytest.mark.asyncio
async def test_archive_exposes_only_compact_image_metadata_to_extraction(tmp_path: Path) -> None:
    """A-052 is defended by proving extraction sees the compact image view but never the
    attachment bytes; this prevents durable image data from being copied into model prompts.
    """
    thread_id = uuid4()
    journal = TranscriptJournal(tmp_path / "transcripts")
    prompt_id = "01K1M2A0000000000000000001"
    image = ImageInput(
        kind="image",
        media_type="image/png",
        data_base64=base64.b64encode(b"\x89PNG\r\n\x1a\nimage").decode("ascii"),
    )
    view = journal.append_image_attachment(str(thread_id), prompt_id, image)
    journal.append_message(
        str(thread_id),
        {
            "message_id": prompt_id,
            "role": "user",
            "content": "Inspect this.",
            "image": view.model_dump(mode="json"),
        },
        parent_id=None,
    )
    journal.append_message(
        str(thread_id),
        {
            "message_id": "01K1M2A0000000000000000002",
            "role": "assistant",
            "content": "I inspected it.",
        },
        parent_id=prompt_id,
    )
    agent = FakeAgent()
    service = ExtractionService(
        journal=journal,
        agent=agent,
        spine=FakeSpine(),
        principal_id="owner",
        machine_id="mac",
    )

    await service.archive(thread_id)

    extracted_messages = json.loads(agent.calls[0])
    assert extracted_messages[0]["image"] == view.model_dump(mode="json")
    assert image.data_base64 not in agent.calls[0]
    assert "data_base64" not in agent.calls[0]


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


@pytest.mark.asyncio
async def test_a_refused_merge_target_still_archives_every_fact_as_new(tmp_path: Path) -> None:
    """ADR-022 (M3EX-22): when the Palace refuses a machine-proposed target, the archive
    retries with every fact as a new card instead of answering 503."""
    import httpx

    from harness.spine_client import ProblemDetail, SpineProblemError

    class MergingAgent(FakeAgent):
        async def propose_extraction_verdict(self, candidate, neighbors):
            return ExtractionVerdictDraft(verdict="merge", target_ids=[MEMORY_ID])

    class RefusingSpine(FakeSpine):
        async def create_extraction(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                response = httpx.Response(422, request=httpx.Request("POST", "http://p/x"))
                detail = "verdict targets must be active machine-fetched neighbors"
                raise SpineProblemError(response, ProblemDetail(status=422, detail=detail))
            return ExtractionResponse(cards=[], duplicate_count=0)

    thread_id = uuid4()
    spine = RefusingSpine()
    service = ExtractionService(
        journal=_journal(tmp_path / "transcripts", str(thread_id), datetime.now(UTC)),
        agent=MergingAgent(),
        spine=spine,
        principal_id="owner",
        machine_id="mac",
    )

    await service.archive(thread_id)

    assert [c.verdict for c in spine.requests[0].candidates] == ["merge"]
    assert [(c.verdict, c.target_ids) for c in spine.requests[1].candidates] == [("new", [])]


@pytest.mark.asyncio
async def test_archive_gives_each_memory_the_folder_its_facts_came_from(tmp_path: Path) -> None:
    """ADR-010 (SD-072): a memory is born where its fact was worked — the location of its
    source messages, their common ancestor when they span folders, and the thread's location
    only when the model names no source; each birth folder is its own Palace request."""
    root = tmp_path / "repo"
    web, docs = root / "web", root / "docs"
    web.mkdir(parents=True)
    docs.mkdir()
    thread_id = uuid4()
    journal = TranscriptJournal(tmp_path / "transcripts")
    journal.append_thread_context(
        str(thread_id), str(root), workspace_root=str(root), current_location=str(root)
    )
    said = [
        ("01K1M2A0000000000000000001", "user", "The web build uses Vite.", web),
        ("01K1M2A0000000000000000002", "assistant", "Noted for web.", web),
        ("01K1M2A0000000000000000003", "user", "The docs build uses mkdocs.", docs),
        ("01K1M2A0000000000000000004", "assistant", "Noted for docs.", docs),
    ]
    for message_id, role, content, where in said:
        journal.append_message(
            str(thread_id),
            {"message_id": message_id, "role": role, "content": content, "location": str(where)},
            parent_id=None,
        )
    journal.append_thread_location(str(thread_id), str(docs))

    def fact(label: str, *sources: int) -> ExtractionCandidateDraft:
        return ExtractionCandidateDraft(
            label=label,
            body=f"{label} fact.",
            kind="fact",
            keywords=["build", label.lower()],
            source_message_ids=[said[index][0] for index in sources],
        )

    class LocatingAgent(FakeAgent):
        async def extract_thread(self, transcript: str, **_: object) -> ExtractionDraft:
            return ExtractionDraft(
                working_summary="",
                open_loops=[],
                candidates=[fact("Web", 0, 1), fact("Docs", 2), fact("Both", 0, 2), fact("None")],
            )

    spine = FakeSpine()
    service = ExtractionService(
        journal=journal, agent=LocatingAgent(), spine=spine, principal_id="owner", machine_id="mac"
    )

    await service.archive(thread_id)

    assert [
        (request.origin_location, [candidate.label for candidate in request.candidates])
        for request in spine.requests
    ] == [(str(web), ["Web"]), (str(docs), ["Docs", "None"]), (str(root), ["Both"])]
