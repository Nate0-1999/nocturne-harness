from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from harness.agent import ExtractionCandidateDraft, ExtractionDraft, ExtractionVerdictDraft
from harness.extraction import ExtractionIdleScheduler, ExtractionService
from harness.spine_client import ExtractionResponse, QueueResponse
from harness.transcript import TranscriptJournal


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
    def __init__(self) -> None:
        self.requests = []

    async def create_extraction(self, request):
        self.requests.append(request)
        return ExtractionResponse(cards=[], duplicate_count=1)

    async def approval_queue(self, principal_id: str, *, thread_id=None):
        return QueueResponse(cards=[])

    async def search(self, request):
        from harness.spine_client import SearchResponse

        return SearchResponse(results=[])


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
