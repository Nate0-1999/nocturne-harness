"""A-057 local journal projection and resurrection proofs."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from harness.spine_client import TranscriptStatus
from harness.transcript import TranscriptJournal
from harness.transcript_sync import TranscriptSyncEngine

THREAD_ID = "00000000-0000-0000-0000-000000005701"


def _message() -> dict[str, object]:
    return {
        "message_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
        "role": "user",
        "content": "Restore my conversation",
        "state": "complete",
    }


def test_a057_exact_rows_restore_and_derive_the_catalog(tmp_path: Path) -> None:
    """A-057 restores exact transcript bytes and derives navigation from that authority."""

    source = TranscriptJournal(
        tmp_path / "source",
        clock=lambda: datetime(2026, 8, 14, 12, tzinfo=UTC),
    )
    source.append_message(THREAD_ID, _message(), parent_id=None)
    records = source.cloud_records()

    restored = TranscriptJournal(tmp_path / "restored")
    assert restored.restore_cloud_records(records) == 1
    assert (
        restored.path_for_thread(THREAD_ID).read_bytes()
        == source.path_for_thread(THREAD_ID).read_bytes()
    )
    catalog = restored.catalog()
    assert len(catalog) == 1
    assert catalog[0].thread_id == THREAD_ID
    assert catalog[0].title == "Restore my conversation"
    assert catalog[0].created_at == "2026-08-14T12:00:00.000Z"


class _Spine:
    def __init__(self) -> None:
        self.requests = []

    async def append_transcripts(self, request):
        self.requests.append(request)
        return type(
            "Result",
            (),
            {
                "status": TranscriptStatus(
                    principal_id="local",
                    thread_count=1,
                    record_count=len(request.records),
                    latest_received_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
                )
            },
        )()

    async def transcript_status(self, principal_id: str) -> TranscriptStatus:
        return TranscriptStatus(
            principal_id=principal_id,
            thread_count=0,
            record_count=0,
            latest_received_at=None,
        )


@pytest.mark.asyncio
async def test_a057_sync_is_optional_exact_and_owner_visible(tmp_path: Path) -> None:
    """A-057 keeps local durability primary while exposing optional Palace progress."""

    journal = TranscriptJournal(tmp_path / "journal")
    journal.append_message(THREAD_ID, _message(), parent_id=None)
    spine = _Spine()
    engine = TranscriptSyncEngine(journal, spine, "local", enabled=False)

    await engine.sync_once()
    assert spine.requests == []
    assert engine.snapshot().state == "off"

    engine.set_enabled(True)
    await engine.sync_once()
    assert len(spine.requests) == 1
    sent = spine.requests[0].records[0]
    assert sent.thread_id == UUID(THREAD_ID)
    assert sent.journal_line == journal.cloud_records()[0].journal_line
    assert engine.snapshot().state == "synced"
    assert engine.snapshot().record_count == 1
