"""M2I Markdown seed splitting into the standard approval queue."""

import re
from hashlib import sha256
from pathlib import PurePath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from harness.agent import HarnessAgent
from harness.spine_client import (
    ExtractionCandidate,
    QueueCard,
    SearchRequest,
    SeedRequest,
    SeedResponse,
    SpineClient,
    SpineClientError,
)

_SEED_VERDICT_NEIGHBOR_MIN_SCORE = 0.80
_GENERATED_PASTE_NAME = re.compile(r"^pasted-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:\.\d+)?Z\.md$")


class SeedUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_uid: UUID
    source_name: str = Field(min_length=1, max_length=255)
    markdown: str = Field(min_length=1)


class SeedIngestionService:
    def __init__(
        self,
        *,
        agent: HarnessAgent,
        spine: SpineClient,
        principal_id: str,
        machine_id: str,
    ) -> None:
        self._agent = agent
        self._spine = spine
        self._principal_id = principal_id
        self._machine_id = machine_id

    async def ingest(self, upload: SeedUploadRequest) -> SeedResponse:
        _validate_upload(upload)
        source_name = _canonical_seed_source_name(upload.source_name)
        source_sha256 = sha256(upload.markdown.encode("utf-8")).hexdigest()
        try:
            existing = await self._pending_batch(
                upload.batch_uid,
                source_name,
                source_sha256,
            )
        except SpineClientError:
            existing = None
        if existing is not None:
            return existing
        split = await self._agent.split_seed(source_name, upload.markdown)
        candidates: list[ExtractionCandidate] = []
        for item in split.candidates:
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
                if neighbor.score is not None and neighbor.score >= _SEED_VERDICT_NEIGHBOR_MIN_SCORE
            ]
            verdict = await self._agent.propose_extraction_verdict(item, neighbor_payload)
            candidates.append(
                ExtractionCandidate(
                    label=item.label.strip(),
                    body=item.body.strip(),
                    kind=item.kind,
                    keywords=[word.strip().lower() for word in item.keywords],
                    verdict=verdict.verdict,
                    target_ids=verdict.target_ids,
                )
            )
        request = SeedRequest(
            principal_id=self._principal_id,
            batch_uid=upload.batch_uid,
            source_name=source_name,
            source_sha256=source_sha256,
            markdown=upload.markdown,
            machine_id=self._machine_id,
            editor="seed-splitter",
            candidates=candidates,
        )
        try:
            return await self._spine.create_seed(request)
        except SpineClientError:
            existing = await self._pending_batch(
                request.batch_uid,
                request.source_name,
                request.source_sha256,
            )
            if existing is None:
                raise
            return existing

    async def _pending_batch(
        self,
        batch_uid: UUID,
        source_name: str,
        source_sha256: str,
    ) -> SeedResponse | None:
        pending = await self._spine.approval_queue(
            self._principal_id,
            birthplace="seed",
        )
        cards = _matching_seed_cards(
            pending.cards,
            batch_uid=batch_uid,
            source_name=source_name,
            source_sha256=source_sha256,
        )
        if not cards:
            return None
        resolved_batch_uid = cards[0].batch_uid
        if resolved_batch_uid is None:  # pragma: no cover - birthplace filter owns this shape
            return None
        return SeedResponse(
            batch_uid=resolved_batch_uid,
            cards=cards,
            duplicate_count=0,
        )


def _validate_upload(upload: SeedUploadRequest) -> None:
    valid_basename = PurePath(upload.source_name).name == upload.source_name
    valid_extension = upload.source_name.lower().endswith((".md", ".markdown"))
    if not valid_basename or not valid_extension:
        raise ValueError("Choose a .md or .markdown file.")
    if not upload.markdown.strip():
        raise ValueError("The Markdown document is blank.")
    if len(upload.markdown.encode("utf-8")) > 24 * 1024:
        raise ValueError("The Markdown document exceeds 24 KiB.")


def _canonical_seed_source_name(source_name: str) -> str:
    return "pasted.md" if _GENERATED_PASTE_NAME.fullmatch(source_name) else source_name


def _matching_seed_cards(
    cards: list[QueueCard],
    *,
    batch_uid: UUID,
    source_name: str,
    source_sha256: str,
) -> list[QueueCard]:
    matching_document = [
        card
        for card in cards
        if card.source_name == source_name and card.source_sha256 == source_sha256
    ]
    requested = [card for card in matching_document if card.batch_uid == batch_uid]
    if requested:
        return requested
    if not matching_document:
        return []
    existing_batch_uid = matching_document[0].batch_uid
    return [card for card in matching_document if card.batch_uid == existing_batch_uid]
