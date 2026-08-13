from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from harness.agent import ExtractionCandidateDraft, ExtractionVerdictDraft, SeedSplitDraft
from harness.seed import SeedIngestionService, SeedUploadRequest
from harness.seed_identity import seed_batch_uid
from harness.spine_client import (
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    QueueCard,
    QueueResponse,
    SearchResponse,
    SeedResponse,
    SimilarityMemoryCard,
    SpineTransportError,
)

ITEM_UID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
MEMORY_ID = UUID("60000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 8, 8, 22, tzinfo=UTC)


class FakeAgent:
    def __init__(self) -> None:
        self.split_calls = 0

    async def split_seed(self, source_name: str, markdown: str) -> SeedSplitDraft:
        self.split_calls += 1
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
    def __init__(
        self,
        *,
        fail_create: bool = False,
        pending: list[QueueCard] | None = None,
        search_results: list[SimilarityMemoryCard] | None = None,
    ) -> None:
        self.request = None
        self.fail_create = fail_create
        self.pending = pending or []
        self.search_results = search_results or []

    async def search(self, request):
        return SearchResponse(results=self.search_results)

    async def create_seed(self, request):
        self.request = request
        if self.fail_create:
            raise SpineTransportError
        return SeedResponse(batch_uid=request.batch_uid, cards=[], duplicate_count=1)

    async def approval_queue(self, principal_id: str, *, thread_id=None, birthplace=None):
        assert principal_id == "owner"
        assert thread_id is None
        assert birthplace == "seed"
        return QueueResponse(cards=self.pending if self.request is not None else [])


def _seed_card(*, batch_uid: UUID, source_name: str = "garden.md", source_sha256: str) -> QueueCard:
    return QueueCard(
        item_uid=ITEM_UID,
        candidate=MemoryUnit(
            memory_id=MEMORY_ID,
            principal_id="owner",
            label="Atomic seed",
            body="Seed batches require explicit owner consent.",
            kind=MemoryKind.PROCEDURE,
            keywords=["seed", "consent"],
            project_key=None,
            thread_origin=None,
            origin_path=source_name,
            pin=False,
            status=MemoryStatus.CANDIDATE,
            revision=1,
            stats={},
            bias=0,
            embedding_model="fixture",
            created_at=NOW,
            updated_at=NOW,
        ),
        birthplace="seed",
        birthplace_thread_id=None,
        batch_uid=batch_uid,
        source_name=source_name,
        source_sha256=source_sha256,
        verdict="new",
        neighbors=[],
        target_ids=[],
        state="pending",
        created_at=NOW,
    )


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


@pytest.mark.asyncio
async def test_seed_transport_failure_reconciles_the_exact_durable_batch() -> None:
    """F021 and A-033 require a false seed failure to return the exact durable batch so an
    owner retry cannot create duplicate corpus work.
    """
    batch_uid = uuid4()
    markdown = "# Garden\n\nSeed batches require explicit owner consent."
    spine = FakeSpine(
        fail_create=True,
        pending=[
            _seed_card(
                batch_uid=batch_uid,
                source_sha256=sha256(markdown.encode("utf-8")).hexdigest(),
            )
        ],
    )
    service = SeedIngestionService(
        agent=FakeAgent(),  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    result = await service.ingest(
        SeedUploadRequest(batch_uid=batch_uid, source_name="garden.md", markdown=markdown)
    )

    assert result.batch_uid == batch_uid
    assert [card.item_uid for card in result.cards] == [ITEM_UID]
    assert result.duplicate_count == 0


@pytest.mark.asyncio
async def test_seed_transport_failure_stays_loud_without_exact_batch_proof() -> None:
    """F021 requires an unproven seed failure to stay visible instead of treating another
    source digest under the same batch UID as success.
    """
    batch_uid = uuid4()
    spine = FakeSpine(
        fail_create=True,
        pending=[_seed_card(batch_uid=batch_uid, source_sha256="0" * 64)],
    )
    service = SeedIngestionService(
        agent=FakeAgent(),  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    with pytest.raises(SpineTransportError):
        await service.ingest(
            SeedUploadRequest(
                batch_uid=batch_uid,
                source_name="garden.md",
                markdown="# Garden\n\nSeed batches require explicit owner consent.",
            )
        )


@pytest.mark.asyncio
async def test_seed_replay_returns_pending_batch_before_model_work() -> None:
    """F021 and A-033 require an exact batch replay to return the durable result before a
    non-deterministic model split can spend again or change response metadata.
    """
    batch_uid = uuid4()
    markdown = "# Garden\n\nSeed batches require explicit owner consent."
    agent = FakeAgent()
    spine = FakeSpine()
    spine.request = object()
    spine.pending = [
        _seed_card(
            batch_uid=batch_uid,
            source_sha256=sha256(markdown.encode("utf-8")).hexdigest(),
        )
    ]
    service = SeedIngestionService(
        agent=agent,  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    result = await service.ingest(
        SeedUploadRequest(batch_uid=batch_uid, source_name="garden.md", markdown=markdown)
    )

    assert [card.item_uid for card in result.cards] == [ITEM_UID]
    assert result.duplicate_count == 0
    assert agent.split_calls == 0


@pytest.mark.asyncio
async def test_repeat_seed_entrance_reuses_exact_pending_document() -> None:
    """F042 and the M2Y3 charge require a second paste attempt UUID to converge on the
    exact pending source metadata and digest without repeating model work.
    """

    existing_batch_uid = uuid4()
    attempt_batch_uid = uuid4()
    markdown = "# Garden\n\nSeed batches require explicit owner consent."
    agent = FakeAgent()
    spine = FakeSpine(
        pending=[
            _seed_card(
                batch_uid=existing_batch_uid,
                source_sha256=sha256(markdown.encode("utf-8")).hexdigest(),
            )
        ]
    )
    spine.request = object()
    service = SeedIngestionService(
        agent=agent,  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    result = await service.ingest(
        SeedUploadRequest(
            batch_uid=attempt_batch_uid,
            source_name="garden.md",
            markdown=markdown,
        )
    )

    assert result.batch_uid == existing_batch_uid
    assert [card.item_uid for card in result.cards] == [ITEM_UID]
    assert agent.split_calls == 0


@pytest.mark.asyncio
async def test_generated_paste_names_share_one_stable_source_identity() -> None:
    """F042 requires repeated focused paste to retain one document identity even though
    the browser's generated filename includes the attempt time.
    """

    class PasteAgent(FakeAgent):
        async def split_seed(self, source_name: str, markdown: str) -> SeedSplitDraft:
            assert source_name == "pasted.md"
            self.split_calls += 1
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

    spine = FakeSpine()
    service = SeedIngestionService(
        agent=PasteAgent(),  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    await service.ingest(
        SeedUploadRequest(
            batch_uid=uuid4(),
            source_name="pasted-2026-08-13T15-45-01.123Z.md",
            markdown="# Garden\n\nSeed batches require explicit owner consent.",
        )
    )

    assert spine.request is not None
    assert spine.request.source_name == "pasted.md"


@pytest.mark.asyncio
async def test_double_paste_reports_one_reviewable_batch_without_second_split() -> None:
    """F042 and the M2Y3 charge require double paste to converge on one pending batch and
    report its durable success without running the splitter a second time.
    """

    markdown = "# Garden\n\nSeed batches require explicit owner consent."
    source_sha256 = sha256(markdown.encode("utf-8")).hexdigest()
    first_batch_uid = uuid4()

    class DurableFakeSpine(FakeSpine):
        def __init__(self) -> None:
            super().__init__()
            self.create_calls = 0

        async def create_seed(self, request):
            self.request = request
            self.create_calls += 1
            self.pending = [
                _seed_card(
                    batch_uid=request.batch_uid,
                    source_name=request.source_name,
                    source_sha256=request.source_sha256,
                )
            ]
            return SeedResponse(
                batch_uid=request.batch_uid,
                cards=self.pending,
                duplicate_count=0,
            )

    class PasteAgent(FakeAgent):
        async def split_seed(self, source_name: str, source: str) -> SeedSplitDraft:
            assert source_name == "pasted.md"
            assert source == markdown
            self.split_calls += 1
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

    agent = PasteAgent()
    spine = DurableFakeSpine()
    service = SeedIngestionService(
        agent=agent,  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    first = await service.ingest(
        SeedUploadRequest(
            batch_uid=first_batch_uid,
            source_name="pasted-2026-08-13T15-45-01.123Z.md",
            markdown=markdown,
        )
    )
    second = await service.ingest(
        SeedUploadRequest(
            batch_uid=uuid4(),
            source_name="pasted-2026-08-13T15-46-02.456Z.md",
            markdown=markdown,
        )
    )

    assert first == second
    assert first.batch_uid == first_batch_uid
    assert [card.item_uid for card in first.cards] == [ITEM_UID]
    assert spine.create_calls == 1
    assert agent.split_calls == 1
    assert spine.pending[0].source_sha256 == source_sha256


@pytest.mark.asyncio
async def test_seed_verdict_sees_only_standard_create_dedup_neighbors() -> None:
    """F042 and the M2Y3 charge require paste verdict targets to stay inside the standard
    create/dedup neighborhood so rollback cannot strand the document without a queue row.
    """

    class NeighborCapturingAgent(FakeAgent):
        def __init__(self) -> None:
            super().__init__()
            self.neighbors: list[dict[str, str]] = []

        async def propose_extraction_verdict(self, candidate, neighbors):
            self.neighbors = neighbors
            return ExtractionVerdictDraft(verdict="new", target_ids=[])

    accepted_id = UUID("60000000-0000-4000-8000-000000000002")
    rejected_id = UUID("60000000-0000-4000-8000-000000000003")
    agent = NeighborCapturingAgent()
    spine = FakeSpine(
        search_results=[
            SimilarityMemoryCard(
                memory_id=accepted_id,
                label="Dedup neighbor",
                body="Close enough for the standard create pipeline.",
                kind=MemoryKind.FACT,
                pin=False,
                score=0.80,
                features=None,
                rank=None,
            ),
            SimilarityMemoryCard(
                memory_id=rejected_id,
                label="Search-only neighbor",
                body="Visible in search but outside the create dedup band.",
                kind=MemoryKind.FACT,
                pin=False,
                score=0.799999,
                features=None,
                rank=None,
            ),
        ]
    )
    service = SeedIngestionService(
        agent=agent,  # type: ignore[arg-type]
        spine=spine,  # type: ignore[arg-type]
        principal_id="owner",
        machine_id="mac",
    )

    await service.ingest(
        SeedUploadRequest(
            batch_uid=uuid4(),
            source_name="garden.md",
            markdown="# Garden\n\nSeed batches require explicit owner consent.",
        )
    )

    assert [item["memory_id"] for item in agent.neighbors] == [str(accepted_id)]


def test_seed_batch_uid_is_stable_and_document_specific() -> None:
    """F042 and the M2Y3 charge require every seed entrance to replay one exact document
    identity instead of minting duplicate corpus work after an ambiguous response.
    """

    markdown = "# Garden\n\nSeed batches require explicit owner consent."

    assert seed_batch_uid("garden.md", markdown) == seed_batch_uid("garden.md", markdown)
    assert seed_batch_uid("garden.md", markdown).version == 8
    assert seed_batch_uid("garden.md", markdown) != seed_batch_uid("other.md", markdown)
