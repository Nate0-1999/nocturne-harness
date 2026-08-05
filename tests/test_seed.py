from uuid import uuid4

import pytest

from harness.agent import ExtractionCandidateDraft, ExtractionVerdictDraft, SeedSplitDraft
from harness.seed import SeedIngestionService, SeedUploadRequest
from harness.spine_client import SearchResponse, SeedResponse


class FakeAgent:
    async def split_seed(self, source_name: str, markdown: str) -> SeedSplitDraft:
        assert source_name == "garden.md"
        assert markdown.startswith("# Garden")
        return SeedSplitDraft(
            candidates=[
                ExtractionCandidateDraft(
                    label="Atomic seed",
                    body="Seed batches require explicit owner consent.",
                    kind="procedure",
                    keywords=["seed", "consent"],
                )
            ]
        )

    async def propose_extraction_verdict(self, candidate, neighbors):
        assert candidate.label == "Atomic seed"
        assert neighbors == []
        return ExtractionVerdictDraft(verdict="new", target_ids=[])


class FakeSpine:
    def __init__(self) -> None:
        self.request = None

    async def search(self, request):
        return SearchResponse(results=[])

    async def create_seed(self, request):
        self.request = request
        return SeedResponse(batch_uid=request.batch_uid, cards=[], duplicate_count=1)


@pytest.mark.asyncio
async def test_markdown_seed_is_split_before_one_standard_queue_write() -> None:
    """A-033 is defended by verifying that markdown seed is split before one standard queue
    write; this prevents drift in the seed splitting and unified-queue contract.
    """
    spine = FakeSpine()
    service = SeedIngestionService(
        agent=FakeAgent(),  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )
    batch_uid = uuid4()

    result = await service.ingest(
        SeedUploadRequest(
            batch_uid=batch_uid,
            source_name="garden.md",
            markdown="# Garden\n\nSeed batches require explicit owner consent.",
        )
    )

    assert result.batch_uid == batch_uid
    assert spine.request is not None
    assert spine.request.source_name == "garden.md"
    assert spine.request.editor == "seed-splitter"
    assert spine.request.candidates[0].label == "Atomic seed"
    assert spine.request.candidates[0].verdict == "new"


@pytest.mark.asyncio
async def test_seed_rejects_non_markdown_before_model_work() -> None:
    """A-033 is defended by verifying that seed rejects non markdown before model work; this
    prevents drift in the seed splitting and unified-queue contract.
    """
    service = SeedIngestionService(
        agent=FakeAgent(),  # type: ignore[arg-type]
        spine=FakeSpine(),  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    with pytest.raises(ValueError, match="markdown"):
        await service.ingest(
            SeedUploadRequest(
                batch_uid=uuid4(),
                source_name="garden.txt",
                markdown="not accepted",
            )
        )
