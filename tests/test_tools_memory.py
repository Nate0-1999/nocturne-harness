import json
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

import httpx
import pytest

from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    CreateMemoryRequest,
    CreateMemoryResponse,
    CreateMemorySplitResponse,
    DuplicateMemoryConflict,
    LabelConflict,
    ListMemoriesParams,
    MemoryKind,
    MemorySplitChild,
    MemorySplitRequest,
    MemorySplitResponse,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    PatchMemoryResponse,
    RevisionConflict,
    SearchRequest,
    SearchResponse,
    SimilarityMemoryCard,
    SimilarMemoriesResponse,
    SpineClientError,
)
from harness.tools_memory import (
    MemoryToolContext,
    create_remembered_memory_split,
    edit_memory,
    save_memory,
    search_memory,
)

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)
THREAD_ID = UUID("10000000-0000-0000-0000-000000000001")
MEMORY_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_MEMORY_ID = UUID("20000000-0000-0000-0000-000000000002")

OutcomeT = TypeVar("OutcomeT")


class FakeSpineGateway:
    """Typed in-memory C.4 boundary that records every tool-side request."""

    def __init__(self) -> None:
        self.create_outcomes: list[CreateMemoryResponse | SpineClientError] = []
        self.split_outcomes: list[CreateMemorySplitResponse | SpineClientError] = []
        self.search_outcomes: list[SearchResponse | SpineClientError] = []
        self.list_pages: dict[int, PagedMemoryListResponse | SpineClientError] = {}
        self.patch_outcomes: list[PatchMemoryResponse | SpineClientError] = []
        self.create_requests: list[CreateMemoryRequest] = []
        self.split_requests: list[MemorySplitRequest] = []
        self.search_requests: list[SearchRequest] = []
        self.list_requests: list[ListMemoriesParams] = []
        self.patch_requests: list[tuple[UUID, PatchMemoryRequest]] = []

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        self.create_requests.append(request)
        return self._take(self.create_outcomes, "create")

    async def create_memory_split(self, request: MemorySplitRequest) -> CreateMemorySplitResponse:
        self.split_requests.append(request)
        return self._take(self.split_outcomes, "split")

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_requests.append(request)
        return self._take(self.search_outcomes, "search")

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        self.list_requests.append(params)
        if params.offset not in self.list_pages:
            raise AssertionError(f"unexpected list offset {params.offset}")
        page = self.list_pages[params.offset]
        if isinstance(page, SpineClientError):
            raise page
        return page

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse:
        self.patch_requests.append((memory_id, request))
        return self._take(self.patch_outcomes, "patch")

    @staticmethod
    def _take(outcomes: list[OutcomeT | SpineClientError], operation: str) -> OutcomeT:
        if not outcomes:
            raise AssertionError(f"unexpected {operation} call")
        outcome = outcomes.pop(0)
        if isinstance(outcome, SpineClientError):
            raise outcome
        return outcome


def memory_unit(
    *,
    memory_id: UUID = MEMORY_ID,
    principal_id: str = "principal-1",
    label: str = "Editor preference",
    body: str = "The user prefers tabs.",
    kind: MemoryKind = MemoryKind.PREFERENCE,
    project_key: str | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    revision: int = 3,
) -> MemoryUnit:
    return MemoryUnit(
        memory_id=memory_id,
        principal_id=principal_id,
        label=label,
        body=body,
        kind=kind,
        keywords=["editor", "tabs"],
        project_key=project_key,
        thread_origin=str(THREAD_ID),
        origin_thread_id=THREAD_ID,
        origin_path="/workspace/notes.md",
        pin=False,
        status=status,
        revision=revision,
        stats={},
        bias=0.0,
        embedding_model="text-embedding-3-small",
        created_at=NOW,
        updated_at=NOW,
    )


def similarity_card(
    *,
    memory_id: UUID = MEMORY_ID,
    label: str = "Editor preference",
    body: str = "The user prefers tabs.",
    kind: MemoryKind = MemoryKind.PREFERENCE,
    pin: bool = False,
    score: float = 0.87,
) -> SimilarityMemoryCard:
    return SimilarityMemoryCard(
        memory_id=memory_id,
        label=label,
        body=body,
        kind=kind,
        pin=pin,
        score=score,
        features=None,
        rank=None,
    )


def memory_page(
    items: list[MemoryUnit], *, total: int | None = None, offset: int = 0
) -> PagedMemoryListResponse:
    return PagedMemoryListResponse(
        items=items,
        total=len(items) if total is None else total,
        limit=200,
        offset=offset,
    )


def context(
    spine: FakeSpineGateway,
    *,
    project_key: str | None = "garden",
    excluded_memory_ids: frozenset[UUID] = frozenset(),
) -> MemoryToolContext:
    return MemoryToolContext(
        spine=spine,
        principal_id="principal-1",
        machine_id="machine-1",
        agent_id="agent-7",
        thread_id=THREAD_ID,
        project_key=project_key,
        origin_path="/workspace/PLAN.md",
        excluded_memory_ids=excluded_memory_ids,
    )


def conflict_response(method: str = "POST") -> httpx.Response:
    return httpx.Response(
        409,
        request=httpx.Request(method, "http://spine.test/v1/memories"),
    )


def create_conflict(
    conflict: DuplicateMemoryConflict | LabelConflict,
) -> CreateMemoryConflictError:
    return CreateMemoryConflictError(conflict_response(), conflict)


def patch_conflict(conflict: RevisionConflict | LabelConflict) -> PatchMemoryConflictError:
    return PatchMemoryConflictError(conflict_response("PATCH"), conflict)


@pytest.mark.asyncio
async def test_a049_remember_split_maps_exact_source_and_trusted_global_provenance() -> None:
    """A-049, ADR-022, and SPEC B.6 rule 12 are defended here.
    The split mapper sends exact source and trusted user/global lineage through one operation.
    """
    spine = FakeSpineGateway()
    source = memory_unit(
        label="Split source", body="Fact one. Fact two.", status=MemoryStatus.TOMBSTONED
    )
    child_one = memory_unit(label="First", body="Fact one.", kind=MemoryKind.FACT)
    child_two = memory_unit(
        memory_id=OTHER_MEMORY_ID, label="Second", body="Fact two.", kind=MemoryKind.FACT
    )
    spine.split_outcomes.append(MemorySplitResponse(source=source, created=[child_one, child_two]))
    children = [
        MemorySplitChild(label="First", body="Fact one.", keywords=["fact", "one"]),
        MemorySplitChild(label="Second", body="Fact two.", keywords=["fact", "two"]),
    ]

    response = await create_remembered_memory_split(
        context(spine),
        source_body="Fact one. Fact two.",
        children=children,
    )

    assert isinstance(response, MemorySplitResponse)
    assert len(spine.split_requests) == 1
    assert spine.split_requests[0].model_dump(mode="json", exclude_none=True) == {
        "principal_id": "principal-1",
        "source_body": "Fact one. Fact two.",
        "children": [child.model_dump() for child in children],
        "thread_origin": str(THREAD_ID),
        "origin_thread_id": str(THREAD_ID),
        "origin_path": "/workspace/PLAN.md",
        "editor": "user",
        "machine_id": "machine-1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("project_scoped", "force", "expected_project"),
    [
        (False, False, None),
        (False, True, None),
        (True, False, "garden"),
        (True, True, "garden"),
    ],
)
async def test_save_maps_only_trusted_context_scope_and_force(
    project_scoped: bool,
    force: bool,
    expected_project: str | None,
) -> None:
    """ADR-005 is defended by verifying that save maps only trusted context scope and force;
    this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    created = memory_unit()
    spine.create_outcomes.append(CreatedMemoryResponse(created=created))

    rendered = await save_memory(
        context(spine),
        "Editor preference",
        "The user prefers tabs.",
        MemoryKind.PREFERENCE,
        ["editor", "tabs"],
        project_scoped=project_scoped,
        force=force,
    )

    assert len(spine.create_requests) == 1
    assert spine.create_requests[0].model_dump(mode="json", exclude_none=True) == {
        "principal_id": "principal-1",
        "label": "Editor preference",
        "body": "The user prefers tabs.",
        "kind": "preference",
        "keywords": ["editor", "tabs"],
        **({"project_key": expected_project} if expected_project is not None else {}),
        "thread_origin": str(THREAD_ID),
        "origin_thread_id": str(THREAD_ID),
        "origin_path": "/workspace/PLAN.md",
        "editor": "agent:agent-7",
        "machine_id": "machine-1",
        "force": force,
    }
    assert rendered == (
        'memory saved: {"memory_id":"20000000-0000-0000-0000-000000000001",'
        '"label":"Editor preference","body":"The user prefers tabs.",'
        '"kind":"preference","revision":3}'
    )


@pytest.mark.asyncio
async def test_save_rejects_project_scope_without_current_project_before_spine_call() -> None:
    """ADR-005 is defended by verifying that save rejects project scope without current project
    before spine call; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()

    rendered = await save_memory(
        context(spine, project_key=None),
        "A label",
        "A body",
        MemoryKind.FACT,
        project_scoped=True,
    )

    assert rendered == (
        "memory not saved: project_scoped=true requires a current project; "
        "global fallback requires explicit user confirmation in a later user turn"
    )
    assert spine.create_requests == []


@pytest.mark.asyncio
async def test_save_blocks_same_run_global_fallback_after_missing_project_context() -> None:
    """ADR-005 is defended by verifying that save blocks same run global fallback after missing
    project context; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    run_context = context(spine, project_key=None)

    missing_project = await save_memory(
        run_context,
        "Project build",
        "Use uv to build this project.",
        MemoryKind.PROJECT_NOTE,
        project_scoped=True,
    )
    global_retry = await save_memory(
        run_context,
        "Project build",
        "Use uv to build this project.",
        MemoryKind.PROJECT_NOTE,
        project_scoped=False,
    )

    assert "requires a current project" in missing_project
    assert global_retry == (
        "memory not saved: global fallback requires explicit user confirmation in a later user turn"
    )
    assert spine.create_requests == []

    spine.create_outcomes.append(CreatedMemoryResponse(created=memory_unit()))
    confirmed_later_turn = await save_memory(
        context(spine, project_key=None),
        "Project build",
        "Use uv to build this project.",
        MemoryKind.PROJECT_NOTE,
        project_scoped=False,
    )

    assert confirmed_later_turn.startswith("memory saved: ")
    assert len(spine.create_requests) == 1
    assert spine.create_requests[0].project_key is None


@pytest.mark.asyncio
async def test_save_renders_similar_result_without_automatically_forcing_or_retrying() -> None:
    """ADR-005 is defended by verifying that save renders similar result without automatically
    forcing or retrying; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.create_outcomes.append(SimilarMemoriesResponse(created=None, similar=[similarity_card()]))

    rendered = await save_memory(
        context(spine),
        "New editor preference",
        "Tabs are preferred.",
        MemoryKind.PREFERENCE,
        project_scoped=False,
    )

    assert rendered == (
        'similar memory exists: {"memory_id":"20000000-0000-0000-0000-000000000001",'
        '"label":"Editor preference","body":"The user prefers tabs.",'
        '"kind":"preference","pin":false,"score":0.87}; '
        "update it, or call again with force=true"
    )
    assert len(spine.create_requests) == 1
    assert spine.create_requests[0].force is False


@pytest.mark.asyncio
async def test_save_never_renders_an_excluded_similar_memory() -> None:
    """ADR-005 is defended by verifying that save never renders an excluded similar memory;
    this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.create_outcomes.append(
        SimilarMemoriesResponse(
            created=None,
            similar=[
                similarity_card(
                    body="The unique chartreuse body must stay hidden.",
                )
            ],
        )
    )

    rendered = await save_memory(
        context(spine, excluded_memory_ids=frozenset({MEMORY_ID})),
        "New editor preference",
        "Tabs are preferred.",
        MemoryKind.PREFERENCE,
        project_scoped=False,
    )

    assert rendered == ("memory not saved: similar memory exists but is excluded from this turn")
    assert str(MEMORY_ID) not in rendered
    assert "chartreuse" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            create_conflict(DuplicateMemoryConflict(duplicate_of=similarity_card())),
            'memory not saved: duplicate memory exists: {"memory_id":'
            '"20000000-0000-0000-0000-000000000001","label":"Editor preference",'
            '"body":"The user prefers tabs.","kind":"preference","pin":false,'
            '"score":0.87}',
        ),
        (
            create_conflict(
                LabelConflict(label_conflict={"memory_id": OTHER_MEMORY_ID, "label": "Taken label"})
            ),
            'memory not saved: label already exists: {"memory_id":'
            '"20000000-0000-0000-0000-000000000002","label":"Taken label"}',
        ),
    ],
)
async def test_save_surfaces_hard_duplicate_and_label_conflicts_without_retry(
    failure: CreateMemoryConflictError,
    expected: str,
) -> None:
    """ADR-005 is defended by verifying that save surfaces hard duplicate and label conflicts
    without retry; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.create_outcomes.append(failure)

    rendered = await save_memory(
        context(spine),
        "Taken label",
        "A body",
        MemoryKind.FACT,
        project_scoped=False,
        force=True,
    )

    assert rendered == expected
    assert len(spine.create_requests) == 1


@pytest.mark.asyncio
async def test_save_never_renders_an_excluded_create_conflict() -> None:
    """ADR-005 is defended by verifying that save never renders an excluded create conflict;
    this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.create_outcomes.append(
        create_conflict(
            DuplicateMemoryConflict(
                duplicate_of=similarity_card(
                    body="The unique chartreuse body must stay hidden.",
                )
            )
        )
    )

    rendered = await save_memory(
        context(spine, excluded_memory_ids=frozenset({MEMORY_ID})),
        "Taken label",
        "A body",
        MemoryKind.FACT,
        project_scoped=False,
    )

    assert rendered == "memory not saved: conflicting memory is excluded from this turn"
    assert str(MEMORY_ID) not in rendered
    assert "chartreuse" not in rendered


@pytest.mark.asyncio
async def test_search_defaults_to_five_current_project_and_preserves_compact_order() -> None:
    """ADR-005 is defended by verifying that search defaults to five current project and
    preserves compact order; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.search_outcomes.append(
        SearchResponse(
            results=[
                similarity_card(label="First", body="One", score=0.9),
                similarity_card(
                    memory_id=OTHER_MEMORY_ID,
                    label="Second ☃",
                    body="Two",
                    kind=MemoryKind.FACT,
                    pin=True,
                    score=0.8,
                ),
            ]
        )
    )

    rendered = await search_memory(context(spine), "editor setup")

    assert spine.search_requests == [
        SearchRequest(
            principal_id="principal-1",
            query="editor setup",
            k=5,
            project_key="garden",
        )
    ]
    lines = rendered.splitlines()
    assert lines == [
        '{"memory_id":"20000000-0000-0000-0000-000000000001","label":"First",'
        '"body":"One","kind":"preference","pin":false,"score":0.9}',
        '{"memory_id":"20000000-0000-0000-0000-000000000002","label":"Second ☃",'
        '"body":"Two","kind":"fact","pin":true,"score":0.8}',
    ]
    assert [json.loads(line)["label"] for line in lines] == ["First", "Second ☃"]
    expected_keys = {"memory_id", "label", "body", "kind", "pin", "score"}
    assert all(set(json.loads(line)) == expected_keys for line in lines)


@pytest.mark.asyncio
async def test_search_overfetches_and_never_renders_excluded_gate_removals() -> None:
    """ADR-005 is defended by verifying that search overfetches and never renders excluded gate
    removals; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    allowed_third_id = UUID("20000000-0000-0000-0000-000000000003")
    spine.search_outcomes.append(
        SearchResponse(
            results=[
                similarity_card(
                    memory_id=MEMORY_ID,
                    label="Removed",
                    body="The unique chartreuse body must stay hidden.",
                    score=0.99,
                ),
                similarity_card(
                    memory_id=OTHER_MEMORY_ID,
                    label="Allowed",
                    body="Visible first.",
                    score=0.9,
                ),
                similarity_card(
                    memory_id=allowed_third_id,
                    label="Allowed second",
                    body="Visible second.",
                    score=0.8,
                ),
            ]
        )
    )

    rendered = await search_memory(
        context(spine, excluded_memory_ids=frozenset({MEMORY_ID})),
        "editor setup",
        k=2,
    )

    assert spine.search_requests[0].k == 3
    assert str(MEMORY_ID) not in rendered
    assert "chartreuse" not in rendered
    assert [json.loads(line)["memory_id"] for line in rendered.splitlines()] == [
        str(OTHER_MEMORY_ID),
        str(allowed_third_id),
    ]


@pytest.mark.asyncio
async def test_search_renders_empty_results_truthfully() -> None:
    """ADR-005 is defended by verifying that search renders empty results truthfully; this
    prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.search_outcomes.append(SearchResponse(results=[]))

    assert await search_memory(context(spine), "nothing") == "no matching memories"
    assert len(spine.search_requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_k", [0, 51])
async def test_search_rejects_invalid_k_without_spine_call(invalid_k: int) -> None:
    """ADR-005 is defended by verifying that search rejects invalid k without spine call; this
    prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()

    rendered = await search_memory(context(spine), "query", k=invalid_k)

    assert rendered == "memory search failed: k must be an integer from 1 through 50"
    assert spine.search_requests == []


@pytest.mark.asyncio
async def test_edit_resolves_uuid_before_an_exact_uuid_shaped_label() -> None:
    """ADR-005 is defended by verifying that edit resolves uuid before an exact uuid shaped
    label; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    by_id = memory_unit(memory_id=MEMORY_ID, label="Actual ID target")
    by_label = memory_unit(memory_id=OTHER_MEMORY_ID, label=str(MEMORY_ID))
    spine.list_pages[0] = memory_page([by_label, by_id])
    spine.patch_outcomes.append(by_id.model_copy(update={"body": "Updated", "revision": 4}))

    await edit_memory(context(spine), str(MEMORY_ID), "Updated", "Correction")

    assert [memory_id for memory_id, _ in spine.patch_requests] == [MEMORY_ID]


@pytest.mark.asyncio
async def test_edit_falls_back_to_exact_label_when_label_is_uuid_shaped() -> None:
    """ADR-005 is defended by verifying that edit falls back to exact label when label is uuid
    shaped; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    uuid_label = str(MEMORY_ID)
    target = memory_unit(memory_id=OTHER_MEMORY_ID, label=uuid_label)
    spine.list_pages[0] = memory_page([target])
    spine.patch_outcomes.append(target.model_copy(update={"body": "Updated", "revision": 4}))

    await edit_memory(context(spine), uuid_label, "Updated", "Correction")

    assert [memory_id for memory_id, _ in spine.patch_requests] == [OTHER_MEMORY_ID]


@pytest.mark.asyncio
async def test_edit_exact_label_is_case_sensitive_and_rejects_substrings() -> None:
    """ADR-005 is defended by verifying that edit exact label is case sensitive and rejects
    substrings; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.list_pages[0] = memory_page(
        [
            memory_unit(memory_id=MEMORY_ID, label="Build command"),
            memory_unit(memory_id=OTHER_MEMORY_ID, label="build command"),
        ]
    )
    lower = memory_unit(memory_id=OTHER_MEMORY_ID, label="build command")
    spine.patch_outcomes.append(lower.model_copy(update={"body": "Updated", "revision": 4}))

    rendered = await edit_memory(context(spine), "build command", "Updated", "Correction")

    assert rendered.startswith("memory updated: ")
    assert [memory_id for memory_id, _ in spine.patch_requests] == [OTHER_MEMORY_ID]

    no_match_spine = FakeSpineGateway()
    no_match_spine.list_pages[0] = memory_page([memory_unit(label="Production build command")])
    no_match = await edit_memory(context(no_match_spine), "build", "Updated", "Correction")
    assert no_match == "memory not edited: no active exact match for 'build'"
    assert no_match_spine.patch_requests == []


@pytest.mark.asyncio
async def test_edit_filters_other_principals_and_non_active_rows_locally() -> None:
    """ADR-005 is defended by verifying that edit filters other principals and non active rows
    locally; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    wrong_principal = memory_unit(principal_id="principal-2", label="Target")
    tombstoned = memory_unit(
        memory_id=OTHER_MEMORY_ID,
        label="Target",
        status=MemoryStatus.TOMBSTONED,
    )
    active = memory_unit(
        memory_id=UUID("20000000-0000-0000-0000-000000000003"),
        label="Target",
    )
    spine.list_pages[0] = memory_page([wrong_principal, tombstoned, active])
    spine.patch_outcomes.append(active.model_copy(update={"body": "Updated", "revision": 4}))

    await edit_memory(context(spine), "Target", "Updated", "Correction")

    assert [memory_id for memory_id, _ in spine.patch_requests] == [active.memory_id]
    assert spine.list_requests[0].status is MemoryStatus.ACTIVE


@pytest.mark.asyncio
async def test_edit_cannot_resolve_an_excluded_gate_removal() -> None:
    """ADR-005 is defended by verifying that edit cannot resolve an excluded gate removal; this
    prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.list_pages[0] = memory_page(
        [
            memory_unit(
                body="The unique chartreuse body must stay hidden.",
            )
        ]
    )

    rendered = await edit_memory(
        context(spine, excluded_memory_ids=frozenset({MEMORY_ID})),
        str(MEMORY_ID),
        "Updated",
        "Correction",
    )

    assert rendered == f"memory not edited: no active exact match for '{MEMORY_ID}'"
    assert "chartreuse" not in rendered
    assert spine.patch_requests == []


@pytest.mark.asyncio
async def test_edit_paginates_principal_wide_without_project_filter() -> None:
    """ADR-005 is defended by verifying that edit paginates principal wide without project
    filter; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    first = memory_unit(label="Decoy", project_key="garden")
    target = memory_unit(
        memory_id=OTHER_MEMORY_ID,
        label="Across projects",
        project_key="another-project",
    )
    spine.list_pages[0] = memory_page([first], total=2, offset=0)
    spine.list_pages[1] = memory_page([target], total=2, offset=1)
    spine.patch_outcomes.append(target.model_copy(update={"body": "Updated", "revision": 4}))

    await edit_memory(context(spine), "Across projects", "Updated", "Correction")

    assert [request.offset for request in spine.list_requests] == [0, 1]
    assert all(request.limit == 200 for request in spine.list_requests)
    assert all(request.project_key is None for request in spine.list_requests)
    assert [memory_id for memory_id, _ in spine.patch_requests] == [OTHER_MEMORY_ID]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("items", "label", "expected"),
    [
        ([], "Missing", "memory not edited: no active exact match for 'Missing'"),
        (
            [
                memory_unit(memory_id=MEMORY_ID, label="Repeated"),
                memory_unit(memory_id=OTHER_MEMORY_ID, label="Repeated"),
            ],
            "Repeated",
            "memory not edited: exact label 'Repeated' is ambiguous",
        ),
    ],
)
async def test_edit_does_not_patch_missing_or_ambiguous_exact_match(
    items: list[MemoryUnit],
    label: str,
    expected: str,
) -> None:
    """ADR-005 is defended by verifying that edit does not patch missing or ambiguous exact
    match; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    spine.list_pages[0] = memory_page(items)

    assert await edit_memory(context(spine), label, "Updated", "Correction") == expected
    assert spine.patch_requests == []


@pytest.mark.asyncio
async def test_edit_patch_is_body_only_with_trusted_metadata_and_expected_revision() -> None:
    """ADR-005 is defended by verifying that edit patch is body only with trusted metadata and
    expected revision; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    target = memory_unit(revision=3)
    updated = target.model_copy(update={"body": "Use four spaces.", "revision": 4})
    spine.list_pages[0] = memory_page([target])
    spine.patch_outcomes.append(updated)

    rendered = await edit_memory(
        context(spine),
        "Editor preference",
        "Use four spaces.",
        "User corrected the preference",
    )

    assert len(spine.patch_requests) == 1
    memory_id, request = spine.patch_requests[0]
    assert memory_id == MEMORY_ID
    assert request.model_dump(mode="json", exclude_none=True) == {
        "expected_revision": 3,
        "body": "Use four spaces.",
        "editor": "agent:agent-7",
        "reason": "User corrected the preference",
        "machine_id": "machine-1",
    }
    assert rendered == (
        'memory updated: {"memory_id":"20000000-0000-0000-0000-000000000001",'
        '"label":"Editor preference","body":"Use four spaces.",'
        '"kind":"preference","revision":4}'
    )


@pytest.mark.asyncio
async def test_edit_retries_revision_conflict_once_with_returned_current_revision() -> None:
    """ADR-005 is defended by verifying that edit retries revision conflict once with returned
    current revision; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    original = memory_unit(revision=3)
    current = memory_unit(body="Concurrent update", revision=8)
    updated = memory_unit(body="Corrected", revision=9)
    spine.list_pages[0] = memory_page([original])
    spine.patch_outcomes.extend([patch_conflict(RevisionConflict(conflict=current)), updated])

    rendered = await edit_memory(context(spine), str(MEMORY_ID), "Corrected", "Correction")

    assert rendered.startswith("memory updated: ")
    assert len(spine.patch_requests) == 2
    assert [request.expected_revision for _, request in spine.patch_requests] == [3, 8]
    assert [
        request.model_dump(mode="json", exclude={"expected_revision"}, exclude_none=True)
        for _, request in spine.patch_requests
    ] == [
        {
            "body": "Corrected",
            "editor": "agent:agent-7",
            "reason": "Correction",
            "machine_id": "machine-1",
        }
    ] * 2


@pytest.mark.asyncio
async def test_edit_does_not_retry_label_conflict() -> None:
    """ADR-005 is defended by verifying that edit does not retry label conflict; this prevents
    drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    target = memory_unit()
    spine.list_pages[0] = memory_page([target])
    spine.patch_outcomes.append(
        patch_conflict(
            LabelConflict(label_conflict={"memory_id": OTHER_MEMORY_ID, "label": "Already used"})
        )
    )

    rendered = await edit_memory(context(spine), str(MEMORY_ID), "Updated", "Correction")

    assert rendered == (
        'memory not edited: label conflict: {"memory_id":'
        '"20000000-0000-0000-0000-000000000002","label":"Already used"}'
    )
    assert len(spine.patch_requests) == 1


@pytest.mark.asyncio
async def test_edit_stops_after_second_revision_conflict_without_third_attempt() -> None:
    """ADR-005 is defended by verifying that edit stops after second revision conflict without
    third attempt; this prevents drift in the owner memory-tool safety contract.
    """
    spine = FakeSpineGateway()
    original = memory_unit(revision=3)
    first_current = memory_unit(body="First concurrent update", revision=8)
    second_current = memory_unit(body="Second concurrent update", revision=9)
    spine.list_pages[0] = memory_page([original])
    spine.patch_outcomes.extend(
        [
            patch_conflict(RevisionConflict(conflict=first_current)),
            patch_conflict(RevisionConflict(conflict=second_current)),
        ]
    )

    rendered = await edit_memory(context(spine), str(MEMORY_ID), "Corrected", "Correction")

    assert rendered.startswith("memory not edited: revision conflict remains after one retry: ")
    assert '"revision":9' in rendered
    assert len(spine.patch_requests) == 2
    assert [request.expected_revision for _, request in spine.patch_requests] == [3, 8]
