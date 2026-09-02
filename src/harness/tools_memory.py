"""Framework-free business logic for the three C.6 memory tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import ValidationError

if TYPE_CHECKING:
    from harness.toolset import StandardToolset

from harness.progressive_prompt import workspace_location_path
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
    SpineProblemError,
    SpineResponseError,
    SpineTransportError,
)


class SpineGateway(Protocol):
    """The C.4 operations needed by H3, independent of HTTP transport."""

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse: ...

    async def create_memory_split(
        self, request: MemorySplitRequest
    ) -> CreateMemorySplitResponse: ...

    async def search(self, request: SearchRequest) -> SearchResponse: ...

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse: ...

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse: ...


@dataclass(slots=True)
class _MemoryToolRunState:
    """Mutable policy state shared only by tools in one trusted model run."""

    missing_project_context: bool = False


@dataclass(frozen=True, slots=True)
class MemoryToolContext:
    """Trusted per-run identity and provenance; none are model arguments."""

    spine: SpineGateway
    principal_id: str
    machine_id: str
    agent_id: str
    thread_id: UUID | None = None
    project_key: str | None = None
    origin_path: str | None = None
    toolset: StandardToolset | None = None
    excluded_memory_ids: frozenset[UUID] = frozenset()
    _run_state: _MemoryToolRunState = field(
        default_factory=_MemoryToolRunState,
        repr=False,
        compare=False,
    )

    def current_origin_path(self) -> str | None:
        """Read provenance from the same live location used by workspace tools. [R16]"""

        if self.toolset is None:
            return self.origin_path
        return workspace_location_path(self.toolset.location())

    def current_origin_location(self) -> str | None:
        """Return the canonical folder where this thread is standing."""

        if self.toolset is None:
            return None
        return str(self.toolset.location().cwd.resolve(strict=True))


async def save_memory(
    context: MemoryToolContext,
    label: str,
    body: str,
    kind: MemoryKind,
    keywords: list[str] | None = None,
    *,
    project_scoped: bool,
    force: bool = False,
) -> str:
    """Save one atomic durable memory; use force only after reviewing a similar result."""

    if project_scoped and context.project_key is None:
        context._run_state.missing_project_context = True
        return (
            "memory not saved: project_scoped=true requires a current project; "
            "global fallback requires explicit user confirmation in a later user turn"
        )
    if not project_scoped and context._run_state.missing_project_context:
        return (
            "memory not saved: global fallback requires explicit user confirmation "
            "in a later user turn"
        )

    request = CreateMemoryRequest(
        principal_id=context.principal_id,
        label=label,
        body=body,
        kind=kind,
        keywords=keywords,
        project_key=context.project_key if project_scoped else None,
        thread_origin=str(context.thread_id) if context.thread_id is not None else None,
        origin_thread_id=context.thread_id,
        origin_path=context.current_origin_path(),
        origin_location=context.current_origin_location(),
        editor=f"agent:{context.agent_id}",
        machine_id=context.machine_id,
        force=force,
    )
    try:
        response = await context.spine.create_memory(request)
    except CreateMemoryConflictError as exc:
        if _create_conflict_is_excluded(context, exc):
            return "memory not saved: conflicting memory is excluded from this turn"
        return render_create_conflict(exc)
    except SpineClientError as exc:
        return render_spine_error("save", exc)
    if isinstance(response, SimilarMemoriesResponse):
        visible = [
            card for card in response.similar if card.memory_id not in context.excluded_memory_ids
        ]
        if not visible and response.similar:
            return "memory not saved: similar memory exists but is excluded from this turn"
        response = response.model_copy(update={"similar": visible})
    return render_create_response(response)


async def search_memory(context: MemoryToolContext, query: str, k: int = 5) -> str:
    """Search active memories for this user and current project; return up to k compact cards."""

    try:
        request = SearchRequest(
            principal_id=context.principal_id,
            query=query,
            k=k,
            project_key=context.project_key,
        )
    except ValidationError:
        return "memory search failed: k must be an integer from 1 through 50"

    if context.excluded_memory_ids:
        request = request.model_copy(
            update={"k": min(50, request.k + len(context.excluded_memory_ids))}
        )

    try:
        response = await context.spine.search(request)
    except SpineClientError as exc:
        return render_spine_error("search", exc)
    visible_results = [
        card for card in response.results if card.memory_id not in context.excluded_memory_ids
    ][:k]
    if not visible_results:
        return "no matching memories"
    return "\n".join(_render_card(card) for card in visible_results)


async def edit_memory(
    context: MemoryToolContext,
    label_or_id: str,
    new_body: str,
    reason: str,
) -> str:
    """Replace one memory body by exact label or ID; explain why the correction is needed."""

    try:
        target, resolution_error = await _resolve_active_memory(context, label_or_id)
    except SpineClientError as exc:
        return render_spine_error("edit", exc)
    if target is None:
        return resolution_error

    request = _edit_request(context, target.revision, new_body, reason)
    try:
        updated = await context.spine.patch_memory(target.memory_id, request)
    except PatchMemoryConflictError as exc:
        if not isinstance(exc.conflict, RevisionConflict):
            return render_patch_conflict(exc)
        retry = request.model_copy(update={"expected_revision": exc.conflict.conflict.revision})
        try:
            updated = await context.spine.patch_memory(target.memory_id, retry)
        except PatchMemoryConflictError as retry_exc:
            return render_patch_conflict(retry_exc)
        except SpineClientError as retry_exc:
            return render_spine_error("edit", retry_exc)
    except SpineClientError as exc:
        return render_spine_error("edit", exc)

    return f"memory updated: {_render_unit(updated)}"


async def create_remembered_memory(
    context: MemoryToolContext,
    *,
    label: str,
    body: str,
    keywords: list[str],
) -> CreateMemoryResponse:
    """Create the user-authored fact in the thread's authoritative project."""

    return await context.spine.create_memory(
        CreateMemoryRequest(
            principal_id=context.principal_id,
            label=label,
            body=body,
            kind=MemoryKind.FACT,
            keywords=keywords,
            project_key=context.project_key,
            thread_origin=str(context.thread_id) if context.thread_id is not None else None,
            origin_thread_id=context.thread_id,
            origin_path=context.current_origin_path(),
            origin_location=context.current_origin_location(),
            editor="user",
            machine_id=context.machine_id,
            force=False,
        )
    )


async def create_remembered_memory_split(
    context: MemoryToolContext,
    *,
    source_body: str,
    children: list[MemorySplitChild],
) -> CreateMemorySplitResponse:
    """Atomically create one global, user-authored A-049 split family."""

    return await context.spine.create_memory_split(
        MemorySplitRequest(
            principal_id=context.principal_id,
            source_body=source_body,
            children=children,
            thread_origin=str(context.thread_id) if context.thread_id is not None else None,
            origin_thread_id=context.thread_id,
            origin_path=context.current_origin_path(),
            origin_location=context.current_origin_location(),
            editor="user",
            machine_id=context.machine_id,
        )
    )


async def _resolve_active_memory(
    context: MemoryToolContext, label_or_id: str
) -> tuple[MemoryUnit | None, str]:
    memories: list[MemoryUnit] = []
    offset = 0
    while True:
        page = await context.spine.list_memories(
            ListMemoriesParams(
                status=MemoryStatus.ACTIVE,
                limit=200,
                offset=offset,
            )
        )
        memories.extend(
            item
            for item in page.items
            if item.principal_id == context.principal_id
            and item.status == MemoryStatus.ACTIVE
            and item.memory_id not in context.excluded_memory_ids
        )
        if not page.items or offset + len(page.items) >= page.total:
            break
        offset += len(page.items)

    parsed_id: UUID | None
    try:
        parsed_id = UUID(label_or_id)
    except ValueError:
        parsed_id = None

    if parsed_id is not None:
        id_matches = [item for item in memories if item.memory_id == parsed_id]
        if len(id_matches) == 1:
            return id_matches[0], ""
        if len(id_matches) > 1:
            return None, f"memory not edited: ID {label_or_id!r} is ambiguous"

    label_matches = [item for item in memories if item.label == label_or_id]
    if len(label_matches) == 1:
        return label_matches[0], ""
    if not label_matches:
        return None, f"memory not edited: no active exact match for {label_or_id!r}"
    return None, f"memory not edited: exact label {label_or_id!r} is ambiguous"


def _edit_request(
    context: MemoryToolContext,
    expected_revision: int,
    new_body: str,
    reason: str,
) -> PatchMemoryRequest:
    return PatchMemoryRequest(
        expected_revision=expected_revision,
        body=new_body,
        editor=f"agent:{context.agent_id}",
        reason=reason,
        machine_id=context.machine_id,
    )


def render_create_response(response: CreateMemoryResponse) -> str:
    if isinstance(response, CreatedMemoryResponse):
        return f"memory saved: {_render_unit(response.created)}"
    return (
        f"similar memory exists: {_render_cards(response)}; "
        "update it, or call again with force=true"
    )


def render_create_conflict(exc: CreateMemoryConflictError) -> str:
    if isinstance(exc.conflict, DuplicateMemoryConflict):
        duplicate = _render_card(exc.conflict.duplicate_of)
        return f"memory not saved: duplicate memory exists: {duplicate}"
    target = exc.conflict.label_conflict
    return "memory not saved: label already exists: " + _compact_json(
        {"memory_id": str(target.memory_id), "label": target.label}
    )


def _create_conflict_is_excluded(
    context: MemoryToolContext, exc: CreateMemoryConflictError
) -> bool:
    if isinstance(exc.conflict, DuplicateMemoryConflict):
        memory_id = exc.conflict.duplicate_of.memory_id
    else:
        memory_id = exc.conflict.label_conflict.memory_id
    return memory_id in context.excluded_memory_ids


def render_patch_conflict(exc: PatchMemoryConflictError) -> str:
    if isinstance(exc.conflict, RevisionConflict):
        return (
            "memory not edited: revision conflict remains after one retry: "
            f"{_render_unit(exc.conflict.conflict)}"
        )
    if isinstance(exc.conflict, LabelConflict):
        target = exc.conflict.label_conflict
        return "memory not edited: label conflict: " + _compact_json(
            {"memory_id": str(target.memory_id), "label": target.label}
        )
    return "memory not edited: unrecognized conflict"


def _render_cards(response: SimilarMemoriesResponse) -> str:
    if not response.similar:
        return "[]"
    return "\n".join(_render_card(card) for card in response.similar)


def _render_card(card: SimilarityMemoryCard) -> str:
    return _compact_json(
        {
            "memory_id": str(card.memory_id),
            "label": card.label,
            "body": card.body,
            "kind": card.kind.value,
            "pin": card.pin,
            "score": card.score,
        }
    )


def _render_unit(unit: MemoryUnit) -> str:
    return _compact_json(
        {
            "memory_id": str(unit.memory_id),
            "label": unit.label,
            "body": unit.body,
            "kind": unit.kind.value,
            "revision": unit.revision,
        }
    )


def render_spine_error(action: str, exc: SpineClientError) -> str:
    if isinstance(exc, SpineTransportError):
        detail = "memory service unavailable"
    elif isinstance(exc, SpineProblemError):
        fields = [value for value in (exc.problem.title, exc.problem.detail) if value]
        detail = ": ".join(fields) if fields else f"memory service returned HTTP {exc.status_code}"
    elif isinstance(exc, SpineResponseError):
        detail = f"memory service returned an invalid HTTP {exc.status_code} response"
    else:
        detail = "memory service failed"
    return f"memory {action} failed: {detail}"


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
