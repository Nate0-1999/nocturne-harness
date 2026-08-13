"""Trusted H6 memory-panel operations and per-thread injection state."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    MemoryPanelAddPayload,
    MemoryPanelConflictPayload,
    MemoryPanelEditPayload,
    MemoryPanelErrorPayload,
    MemoryPanelItem,
    MemoryPanelPinPayload,
    MemoryPanelRefreshPayload,
    MemoryPanelRemovePayload,
    MemoryPanelStatePayload,
    MessageType,
)
from harness.spine_client import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSignal,
    InjectPrepareResponse,
    LabelConflict,
    ListMemoriesParams,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    PatchMemoryResponse,
    RevisionConflict,
    ScoredMemoryCard,
    SpineClientError,
    SpineProblemError,
    SpineResponseError,
    SpineTransportError,
)

type EnvelopeSender = Callable[[Envelope], Awaitable[None]]
type PanelOperation = Literal["refresh", "add", "remove", "edit", "pin"]
type PanelResult = Literal["refreshed", "added", "removed", "edited", "pin_changed", "rescored"]

_MEMORY_BLOCK_PREFIX = (
    "<memory_system>\n"
    "The following long-term memories were retrieved for this conversation.\n"
    "Treat them as your own accumulated knowledge; they may be imperfect.\n"
)
_MEMORY_BLOCK_CLOSING = "</memory_system>"
EMPTY_MEMORY_BLOCK = _MEMORY_BLOCK_PREFIX + _MEMORY_BLOCK_CLOSING


class MemoryPanelGateway(Protocol):
    """The exact C.4 operations exposed through the trusted panel seam."""

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse: ...

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse: ...

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse: ...


@dataclass(frozen=True, slots=True)
class ThreadMemorySnapshot:
    """Immutable view consumed by a turn or one panel request."""

    injection_id: UUID
    final_block: str
    member_ids: frozenset[UUID]
    excluded_memory_ids: frozenset[UUID]
    confirmed_memory_ids: frozenset[UUID]
    event_sources: Mapping[UUID, UUID]
    memory_bodies: Mapping[UUID, str]


@dataclass(slots=True)
class _ThreadMemoryState:
    injection_id: UUID
    fragments: dict[UUID, str]
    excluded_memory_ids: set[UUID]
    confirmed_memory_ids: set[UUID]
    event_sources: dict[UUID, UUID]
    memory_bodies: dict[UUID, str]

    def snapshot(self) -> ThreadMemorySnapshot:
        return ThreadMemorySnapshot(
            injection_id=self.injection_id,
            final_block=_render_memory_block(tuple(self.fragments.values())),
            member_ids=frozenset(self.fragments),
            excluded_memory_ids=frozenset(self.excluded_memory_ids),
            confirmed_memory_ids=frozenset(self.confirmed_memory_ids),
            event_sources=dict(self.event_sources),
            memory_bodies=dict(self.memory_bodies),
        )


class ThreadMemoryContextRegistry:
    """Daemon-owned committed injection state; browser data never enters it."""

    def __init__(self) -> None:
        self._threads: dict[str, _ThreadMemoryState] = {}
        self._model_feedback_locks: dict[str, asyncio.Lock] = {}

    def install(
        self,
        thread_id: str,
        *,
        prepared: InjectPrepareResponse,
        removed_memory_ids: frozenset[UUID],
        added_back: Sequence[UUID],
        final_block: str,
    ) -> ThreadMemorySnapshot:
        """Bind canonical final-block fragments to the committed event membership."""

        if thread_id in self._threads:
            raise ValueError("thread already has a committed memory context")

        all_injected = {card.memory_id: card for card in prepared.injected}
        near_misses = {card.memory_id: card for card in prepared.near_misses}
        if len(all_injected) != len(prepared.injected):
            raise ValueError("prepared injection contains duplicate injected memory IDs")
        if len(near_misses) != len(prepared.near_misses):
            raise ValueError("prepared injection contains duplicate near-miss memory IDs")
        if set(all_injected) & set(near_misses):
            raise ValueError("prepared injection repeats a memory across card classes")
        prepared_ids = set(all_injected) | set(near_misses)
        if not removed_memory_ids <= prepared_ids:
            raise ValueError("removed memory is not a prepared card")
        if len(set(added_back)) != len(added_back):
            raise ValueError("added-back memory IDs must be unique")
        if removed_memory_ids & set(added_back):
            raise ValueError("removed and added-back memory IDs must be disjoint")
        injected = {
            memory_id: card
            for memory_id, card in all_injected.items()
            if memory_id not in removed_memory_ids
        }
        try:
            selected = [*injected.values(), *(near_misses[memory_id] for memory_id in added_back)]
        except KeyError as exc:
            raise ValueError("added-back memory is not a prepared near miss") from exc

        selected.sort(key=lambda card: (card.rank, card.memory_id.int))
        fragments = _bind_final_block(final_block, selected)
        state = _ThreadMemoryState(
            injection_id=prepared.injection_id,
            fragments=dict(zip((card.memory_id for card in selected), fragments, strict=True)),
            excluded_memory_ids=set(removed_memory_ids),
            confirmed_memory_ids={card.memory_id for card in selected},
            event_sources={memory_id: prepared.injection_id for memory_id in prepared_ids},
            memory_bodies={card.memory_id: card.body for card in selected},
        )
        self._threads[thread_id] = state
        return state.snapshot()

    def snapshot(self, thread_id: str) -> ThreadMemorySnapshot | None:
        state = self._threads.get(thread_id)
        return None if state is None else state.snapshot()

    def remove(self, thread_id: str, memory_id: UUID) -> bool:
        """Remove one retained fragment and persist its tool exclusion."""

        state = self._threads.get(thread_id)
        if state is None or memory_id not in state.fragments:
            return False
        del state.fragments[memory_id]
        del state.memory_bodies[memory_id]
        state.confirmed_memory_ids.discard(memory_id)
        state.excluded_memory_ids.add(memory_id)
        return True

    def add(self, thread_id: str, memory: MemoryUnit) -> bool:
        """Re-add one human-excluded active unit as a confirmed thread lock."""

        state = self._threads.get(thread_id)
        if state is None or memory.memory_id not in state.excluded_memory_ids:
            return False
        state.fragments[memory.memory_id] = _memory_unit_fragment(memory)
        state.memory_bodies[memory.memory_id] = memory.body
        state.excluded_memory_ids.remove(memory.memory_id)
        state.confirmed_memory_ids.add(memory.memory_id)
        return True

    def replace_autonomous(
        self,
        thread_id: str,
        *,
        prepared: InjectPrepareResponse,
    ) -> tuple[ThreadMemorySnapshot, bool]:
        """Install one autonomous canonical block while preserving human locks."""

        state = self._threads.get(thread_id)
        if state is None:
            raise ValueError("thread does not have a committed memory context")
        if prepared.final_block is None:
            raise ValueError("autonomous prepare did not return a final block")
        cards = sorted(prepared.injected, key=lambda card: (card.rank, card.memory_id.int))
        ids = [card.memory_id for card in cards]
        if len(ids) != len(set(ids)):
            raise ValueError("autonomous prepare contains duplicate selected memories")
        if not state.confirmed_memory_ids <= set(ids):
            raise ValueError("autonomous prepare demoted a confirmed memory")
        if state.excluded_memory_ids & set(ids):
            raise ValueError("autonomous prepare resurrected an excluded memory")
        fragments = _bind_final_block(prepared.final_block, cards)
        changed = set(state.fragments) != set(ids)
        state.fragments = dict(zip(ids, fragments, strict=True))
        state.memory_bodies = {card.memory_id: card.body for card in cards}
        state.injection_id = prepared.injection_id
        for card in (*prepared.injected, *prepared.near_misses):
            state.event_sources[card.memory_id] = prepared.injection_id
        return state.snapshot(), changed

    @asynccontextmanager
    async def model_feedback_boundary(self, thread_id: str) -> AsyncIterator[None]:
        """Serialize provider runs with feedback that rewrites their context."""

        lock = self._model_feedback_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            yield


class MemoryPanelController:
    """Translate the closed panel union into trusted C.4 calls."""

    def __init__(
        self,
        spine: MemoryPanelGateway,
        contexts: ThreadMemoryContextRegistry,
        factory: EnvelopeFactory,
        *,
        principal_id: str,
        machine_id: str,
    ) -> None:
        if not principal_id.strip() or not machine_id.strip():
            raise ValueError("panel identities must not be blank")
        self._spine = spine
        self._contexts = contexts
        self._factory = factory
        self._principal_id = principal_id
        self._machine_id = machine_id

    async def handle(self, message: Envelope, send: EnvelopeSender) -> None:
        """Handle one validated C→D request and emit exactly one correlated result."""

        if message.thread_id is None:  # Envelope validation owns this invariant.
            raise ValueError("memory panel request requires thread_id")
        payload = message.payload
        if isinstance(payload, MemoryPanelRefreshPayload):
            await self._send_state(
                thread_id=message.thread_id,
                request_id=message.id,
                result="refreshed",
                operation="refresh",
                send=send,
            )
        elif isinstance(payload, MemoryPanelAddPayload):
            await self._add(message.thread_id, message.id, payload, send)
        elif isinstance(payload, MemoryPanelRemovePayload):
            await self._remove(message.thread_id, message.id, payload, send)
        elif isinstance(payload, MemoryPanelEditPayload):
            await self._patch(
                thread_id=message.thread_id,
                request_id=message.id,
                payload=payload,
                operation="edit",
                result="edited",
                send=send,
            )
        elif isinstance(payload, MemoryPanelPinPayload):
            await self._patch(
                thread_id=message.thread_id,
                request_id=message.id,
                payload=payload,
                operation="pin",
                result="pin_changed",
                send=send,
            )
        else:
            await self._send_error(
                thread_id=message.thread_id,
                request_id=message.id,
                operation="refresh",
                code="invalid_action",
                message="The browser sent an invalid memory panel action.",
                send=send,
            )

    async def publish_ambient(self, thread_id: str, send: EnvelopeSender) -> None:
        """Publish an unsolicited authoritative panel refresh after re-scoring."""

        await self._send_state(
            thread_id=thread_id,
            request_id=self._factory.new_id(),
            result="rescored",
            operation="refresh",
            send=send,
        )

    async def _add(
        self,
        thread_id: str,
        request_id: str,
        payload: MemoryPanelAddPayload,
        send: EnvelopeSender,
    ) -> None:
        error: tuple[str, str] | None = None
        async with self._contexts.model_feedback_boundary(thread_id):
            context = self._contexts.snapshot(thread_id)
            source = None if context is None else context.event_sources.get(payload.memory_id)
            if (
                context is None
                or payload.memory_id not in context.excluded_memory_ids
                or source is None
            ):
                error = ("not_thread_excluded", "This memory is not excluded from the thread.")
            else:
                try:
                    active = await self._active_principal_memories()
                    memory = next(
                        (item for item in active if item.memory_id == payload.memory_id), None
                    )
                    if memory is None:
                        error = (
                            "memory_not_found",
                            "This active memory is no longer available. Refresh and try again.",
                        )
                    else:
                        response = await self._spine.submit_feedback(
                            FeedbackRequest(
                                injection_id=source,
                                memory_id=payload.memory_id,
                                signal=FeedbackSignal.MID_THREAD_ADDED,
                            )
                        )
                        if response.ok is not True:  # pragma: no cover
                            error = (
                                "invalid_response",
                                "The memory service returned an invalid re-add response.",
                            )
                        elif not self._contexts.add(thread_id, memory):
                            error = (
                                "context_changed",
                                "The thread context changed before the memory could be re-added.",
                            )
                except SpineClientError as exc:
                    error = _safe_spine_error(exc)
        if error is not None:
            await self._send_error(
                thread_id=thread_id,
                request_id=request_id,
                operation="add",
                code=error[0],
                message=error[1],
                send=send,
            )
            return
        await self._send_state(
            thread_id=thread_id,
            request_id=request_id,
            result="added",
            operation="add",
            send=send,
        )

    async def _remove(
        self,
        thread_id: str,
        request_id: str,
        payload: MemoryPanelRemovePayload,
        send: EnvelopeSender,
    ) -> None:
        error: tuple[str, str] | None = None
        async with self._contexts.model_feedback_boundary(thread_id):
            context = self._contexts.snapshot(thread_id)
            if context is None or payload.memory_id not in context.member_ids:
                error = (
                    "not_in_context",
                    "This memory is not in the current conversation context.",
                )
            else:
                try:
                    source = context.event_sources.get(payload.memory_id)
                    if source is None:
                        raise ValueError("context member has no injection event source")
                    response = await self._spine.submit_feedback(
                        FeedbackRequest(
                            injection_id=source,
                            memory_id=payload.memory_id,
                            signal=FeedbackSignal.MID_THREAD_REMOVED,
                        )
                    )
                except SpineClientError as exc:
                    error = _safe_spine_error(exc)
                else:
                    if response.ok is not True:  # pragma: no cover - typed literal true
                        error = (
                            "invalid_response",
                            "The memory service returned an invalid removal response.",
                        )
                    else:
                        # Local state changes only after the typed `{ok:true}` response.
                        self._contexts.remove(thread_id, payload.memory_id)

        if error is not None:
            await self._send_error(
                thread_id=thread_id,
                request_id=request_id,
                operation="remove",
                code=error[0],
                message=error[1],
                send=send,
            )
            return
        await self._send_state(
            thread_id=thread_id,
            request_id=request_id,
            result="removed",
            operation="remove",
            send=send,
        )

    async def _patch(
        self,
        *,
        thread_id: str,
        request_id: str,
        payload: MemoryPanelEditPayload | MemoryPanelPinPayload,
        operation: Literal["edit", "pin"],
        result: Literal["edited", "pin_changed"],
        send: EnvelopeSender,
    ) -> None:
        try:
            active = await self._active_principal_memories()
        except SpineClientError as exc:
            await self._send_spine_error(thread_id, request_id, operation, exc, send)
            return
        current = next((item for item in active if item.memory_id == payload.memory_id), None)
        if current is None:
            await self._send_error(
                thread_id=thread_id,
                request_id=request_id,
                operation=operation,
                code="memory_not_found",
                message="This active memory is no longer available. Refresh and try again.",
                send=send,
            )
            return

        if isinstance(payload, MemoryPanelEditPayload) and payload.body == current.body:
            await self._send_error(
                thread_id=thread_id,
                request_id=request_id,
                operation=operation,
                code="no_change",
                message="Nothing changed. Edit the memory body before saving.",
                send=send,
            )
            return

        request = PatchMemoryRequest(
            expected_revision=payload.expected_revision,
            body=payload.body if isinstance(payload, MemoryPanelEditPayload) else None,
            pin=payload.pin if isinstance(payload, MemoryPanelPinPayload) else None,
            editor="user",
            reason=f"panel/{operation}",
            machine_id=self._machine_id,
        )
        try:
            updated = await self._spine.patch_memory(payload.memory_id, request)
        except PatchMemoryConflictError as exc:
            if isinstance(exc.conflict, RevisionConflict):
                conflict = exc.conflict.conflict
                if (
                    conflict.memory_id != payload.memory_id
                    or conflict.principal_id != self._principal_id
                ):
                    await self._send_error(
                        thread_id=thread_id,
                        request_id=request_id,
                        operation=operation,
                        code="invalid_response",
                        message="The memory service returned an invalid conflict response.",
                        send=send,
                    )
                else:
                    await send(
                        self._factory.create(
                            MessageType.MEMORY_PANEL_UPDATE,
                            MemoryPanelConflictPayload(
                                action="conflict",
                                request_id=request_id,
                                operation=operation,
                                memory=conflict,
                                message=(
                                    "This memory changed while you were editing it. "
                                    "Review the latest version and try again."
                                ),
                            ),
                            thread_id=thread_id,
                        )
                    )
            else:
                assert isinstance(exc.conflict, LabelConflict)
                await self._send_error(
                    thread_id=thread_id,
                    request_id=request_id,
                    operation=operation,
                    code="memory_conflict",
                    message="The memory service rejected this change because of a conflict.",
                    send=send,
                )
            return
        except SpineClientError as exc:
            await self._send_spine_error(thread_id, request_id, operation, exc, send)
            return

        if (
            updated.memory_id != payload.memory_id
            or updated.principal_id != self._principal_id
            or updated.status is not MemoryStatus.ACTIVE
            or updated.revision != payload.expected_revision + 1
            or (
                isinstance(payload, MemoryPanelEditPayload)
                and updated.body != payload.body
            )
            or (
                isinstance(payload, MemoryPanelPinPayload)
                and updated.pin is not payload.pin
            )
        ):
            await self._send_error(
                thread_id=thread_id,
                request_id=request_id,
                operation=operation,
                code="invalid_response",
                message=(
                    "Memory did not confirm the requested change. "
                    "Refresh and try again."
                ),
                send=send,
            )
            return
        authoritative = [
            updated if memory.memory_id == updated.memory_id else memory
            for memory in active
        ]
        await self._send_state(
            thread_id=thread_id,
            request_id=request_id,
            result=result,
            operation=operation,
            send=send,
            memories=authoritative,
        )

    async def _send_state(
        self,
        *,
        thread_id: str,
        request_id: str,
        result: PanelResult,
        operation: PanelOperation,
        send: EnvelopeSender,
        memories: Sequence[MemoryUnit] | None = None,
    ) -> None:
        if memories is None:
            try:
                memories = await self._active_principal_memories()
            except SpineClientError as exc:
                await self._send_spine_error(thread_id, request_id, operation, exc, send)
                return
        context = self._contexts.snapshot(thread_id)
        members = context.member_ids if context is not None else frozenset()
        items = [
            MemoryPanelItem(
                memory=memory,
                in_context=memory.memory_id in members,
                thread_excluded=(
                    context is not None and memory.memory_id in context.excluded_memory_ids
                ),
            )
            for memory in memories
        ]
        await send(
            self._factory.create(
                MessageType.MEMORY_PANEL_UPDATE,
                MemoryPanelStatePayload(
                    action="state",
                    request_id=request_id,
                    result=result,
                    items=items,
                    total=len(items),
                ),
                thread_id=thread_id,
            )
        )

    async def _active_principal_memories(self) -> list[MemoryUnit]:
        """Page the global C.4 list completely, then cross the browser boundary."""

        memories: list[MemoryUnit] = []
        offset = 0
        while True:
            page = await self._spine.list_memories(
                ListMemoriesParams(
                    status=MemoryStatus.ACTIVE,
                    limit=200,
                    offset=offset,
                )
            )
            memories.extend(
                item
                for item in page.items
                if item.principal_id == self._principal_id and item.status is MemoryStatus.ACTIVE
            )
            if not page.items or offset + len(page.items) >= page.total:
                break
            offset += len(page.items)
        return memories

    async def _send_spine_error(
        self,
        thread_id: str,
        request_id: str,
        operation: PanelOperation,
        exc: SpineClientError,
        send: EnvelopeSender,
    ) -> None:
        code, message = _safe_spine_error(exc)
        await self._send_error(
            thread_id=thread_id,
            request_id=request_id,
            operation=operation,
            code=code,
            message=message,
            send=send,
        )

    async def _send_error(
        self,
        *,
        thread_id: str,
        request_id: str,
        operation: PanelOperation,
        code: str,
        message: str,
        send: EnvelopeSender,
    ) -> None:
        await send(
            self._factory.create(
                MessageType.MEMORY_PANEL_UPDATE,
                MemoryPanelErrorPayload(
                    action="error",
                    request_id=request_id,
                    operation=operation,
                    code=code,
                    message=message,
                ),
                thread_id=thread_id,
            )
        )


def _bind_final_block(final_block: str, cards: Sequence[ScoredMemoryCard]) -> tuple[str, ...]:
    """Split canonical structure without reserializing frozen event values."""

    if not cards:
        if final_block != EMPTY_MEMORY_BLOCK:
            raise ValueError("zero-member final block is not canonical")
        return ()
    closing = "\n" + _MEMORY_BLOCK_CLOSING
    if not final_block.startswith(_MEMORY_BLOCK_PREFIX) or not final_block.endswith(closing):
        raise ValueError("final block does not have canonical outer structure")
    content = final_block[len(_MEMORY_BLOCK_PREFIX) : -len(closing)]
    fragments: list[str] = []
    while content:
        end = content.find("</memory>")
        if end < 0:
            raise ValueError("final block contains an unterminated memory fragment")
        end += len("</memory>")
        fragments.append(content[:end])
        content = content[end:]
        if content:
            if not content.startswith("\n<memory "):
                raise ValueError("final block contains noncanonical fragment separation")
            content = content[1:]
    if len(fragments) != len(cards):
        raise ValueError("final block membership does not match committed cards")

    for card, fragment in zip(cards, fragments, strict=True):
        expected_start = (
            f'<memory label="{_escape_attribute(card.label)}" '
            f'kind="{_escape_attribute(card.kind.value)}" updated="'
        )
        expected_end = f'">\n{_escape_body(card.body)}\n</memory>'
        if not fragment.startswith(expected_start) or not fragment.endswith(expected_end):
            raise ValueError("final block fragment does not match committed card order")
    return tuple(fragments)


def _render_memory_block(fragments: Sequence[str]) -> str:
    if not fragments:
        return EMPTY_MEMORY_BLOCK
    return _MEMORY_BLOCK_PREFIX + "\n".join(fragments) + "\n" + _MEMORY_BLOCK_CLOSING


def _memory_unit_fragment(memory: MemoryUnit) -> str:
    """Render one current active unit with the canonical C.6 escaping rules."""

    updated = memory.updated_at.isoformat()
    return (
        f'<memory label="{_escape_attribute(memory.label)}" '
        f'kind="{_escape_attribute(memory.kind.value)}" '
        f'updated="{_escape_attribute(updated)}">\n'
        f"{_escape_body(memory.body)}\n</memory>"
    )


def _escape_attribute(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\t", "&#9;")
        .replace("\n", "&#10;")
        .replace("\r", "&#13;")
    )


def _escape_body(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_spine_error(exc: SpineClientError) -> tuple[str, str]:
    if isinstance(exc, SpineTransportError):
        return "memory_unavailable", "The memory service is unavailable. Try again."
    if isinstance(exc, SpineProblemError):
        return (
            "memory_rejected",
            "The memory service rejected this request. Refresh and try again.",
        )
    if isinstance(exc, SpineResponseError):
        return "invalid_response", "The memory service returned an invalid response."
    return "memory_failed", "The memory request failed. Try again."
