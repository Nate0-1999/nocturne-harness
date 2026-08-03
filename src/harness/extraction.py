"""M2H archive extraction over M2D durable transcripts."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from harness.agent import ExtractionCandidateDraft, HarnessAgent
from harness.spine_client import (
    ExtractionCandidate,
    ExtractionRequest,
    QueueCard,
    SearchRequest,
    SpineClient,
)
from harness.transcript import TranscriptJournal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ThreadEndResult:
    thread_id: UUID
    final_post: str
    working_summary: str
    open_loops: list[str]
    cards: list[QueueCard]
    duplicate_count: int
    already_extracted: bool


class ExtractionService:
    def __init__(
        self,
        *,
        journal: TranscriptJournal,
        agent: HarnessAgent,
        spine: SpineClient,
        principal_id: str,
        machine_id: str,
    ) -> None:
        self._journal = journal
        self._agent = agent
        self._spine = spine
        self._principal_id = principal_id
        self._machine_id = machine_id

    async def archive(self, thread_id: UUID) -> ThreadEndResult:
        text_id = str(thread_id)
        messages = self._journal.read_messages(text_id)
        tail = self._journal.transcript_tail(text_id)
        if not messages or tail is None:
            raise ValueError("thread has no durable transcript to archive")
        final_post = _final_assistant_post(messages)
        if self._journal.extracted_tail(text_id) == tail:
            pending = await self._spine.approval_queue(
                self._principal_id,
                thread_id=thread_id,
                birthplace="thread",
            )
            return ThreadEndResult(thread_id, final_post, "", [], pending.cards, 0, True)
        transcript = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        draft = await self._agent.extract_thread(transcript)
        candidates = []
        for item in draft.candidates:
            neighbors = await self._spine.search(
                SearchRequest(
                    principal_id=self._principal_id,
                    query=item.body,
                    k=5,
                    project_key=None,
                )
            )
            neighbor_payload = [
                {
                    "memory_id": str(neighbor.memory_id),
                    "label": neighbor.label,
                    "body": neighbor.body,
                }
                for neighbor in neighbors.results
            ]
            verdict = await self._agent.propose_extraction_verdict(item, neighbor_payload)
            candidates.append(_candidate(item, verdict.verdict, verdict.target_ids))
        response = await self._spine.create_extraction(
            ExtractionRequest(
                principal_id=self._principal_id,
                thread_id=thread_id,
                machine_id=self._machine_id,
                editor="extraction",
                candidates=candidates,
            )
        )
        self._journal.append_extraction(
            text_id,
            tail_message_id=tail,
            working_summary=draft.working_summary,
            open_loops=list(draft.open_loops),
            item_uids=[card.item_uid for card in response.cards],
        )
        return ThreadEndResult(
            thread_id,
            final_post,
            draft.working_summary,
            list(draft.open_loops),
            response.cards,
            response.duplicate_count,
            False,
        )


class ExtractionIdleScheduler:
    """Retryable cheap-model fallback for transcripts abandoned without archive."""

    def __init__(
        self,
        service: ExtractionService,
        journal: TranscriptJournal,
        *,
        idle_hours: float,
        interval_seconds: float = 300,
    ) -> None:
        self._service = service
        self._journal = journal
        self._idle_hours = idle_hours
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=self._idle_hours)
        for thread_id in self._journal.idle_thread_ids(cutoff):
            try:
                await self._service.archive(UUID(thread_id))
            except Exception:
                logger.warning(
                    "idle extraction failed thread=%s; will retry", thread_id, exc_info=True
                )

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_seconds)


def _candidate(
    item: ExtractionCandidateDraft,
    verdict: Literal["new", "merge", "supersede", "contradict"],
    target_ids: list[UUID],
) -> ExtractionCandidate:
    return ExtractionCandidate(
        label=item.label.strip(),
        body=item.body.strip(),
        kind=item.kind,
        keywords=[word.strip().lower() for word in item.keywords],
        verdict=verdict,
        target_ids=target_ids,
    )


def _final_assistant_post(messages: list[dict[str, object]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""
