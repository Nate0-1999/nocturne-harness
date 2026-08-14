"""Optional, retrying projection of the mandatory local journal into Spine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from harness.spine_client import AppendTranscriptsRequest, SpineClient, TranscriptRecordInput
from harness.transcript import TranscriptJournal


@dataclass(frozen=True, slots=True)
class TranscriptSyncSnapshot:
    enabled: bool
    state: str
    record_count: int | None
    latest_received_at: datetime | None
    error: str | None


class TranscriptSyncEngine:
    """Retry cloud appends without weakening locally durable turn capture."""

    def __init__(
        self,
        journal: TranscriptJournal,
        spine: SpineClient,
        principal_id: str,
        *,
        enabled: bool,
        interval_seconds: float = 1.0,
    ) -> None:
        self._journal = journal
        self._spine = spine
        self._principal_id = principal_id
        self._enabled = enabled
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._record_count: int | None = None
        self._latest_received_at: datetime | None = None
        self._error: str | None = None
        self._syncing = False

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._error = None
        self._wake.set()

    def snapshot(self) -> TranscriptSyncSnapshot:
        if not self._enabled:
            state = "off"
        elif self._error is not None:
            state = "waiting"
        elif self._syncing:
            state = "syncing"
        else:
            state = "synced" if self._record_count is not None else "starting"
        return TranscriptSyncSnapshot(
            enabled=self._enabled,
            state=state,
            record_count=self._record_count,
            latest_received_at=self._latest_received_at,
            error=self._error,
        )

    async def sync_once(self) -> None:
        if not self._enabled:
            return
        self._syncing = True
        try:
            records = self._journal.cloud_records()
            status = None
            for offset in range(0, len(records), 100):
                batch = records[offset : offset + 100]
                result = await self._spine.append_transcripts(
                    AppendTranscriptsRequest(
                        principal_id=self._principal_id,
                        records=[
                            TranscriptRecordInput(
                                thread_id=record.thread_id,
                                sequence=record.sequence,
                                journal_line=record.journal_line,
                                sha256=record.sha256,
                            )
                            for record in batch
                        ],
                    )
                )
                status = result.status
            if status is None:
                status = await self._spine.transcript_status(self._principal_id)
            self._record_count = status.record_count
            self._latest_received_at = status.latest_received_at
            self._error = None
        except Exception:
            self._error = "Transcript backup is waiting for the Palace; it will retry."
        finally:
            self._syncing = False

    async def _run(self) -> None:
        while True:
            await self.sync_once()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass
            self._wake.clear()
