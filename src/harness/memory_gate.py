"""Framework-neutral first-chat memory injection gate orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast
from uuid import UUID

from pydantic_ai.messages import BinaryContent

from harness.citation import cited_memory_ids
from harness.commands import browser_open_web_command, remember_command_text
from harness.memory_panel import ThreadMemoryContextRegistry, ThreadMemorySnapshot
from harness.model_policy import ThreadModelResolution
from harness.progressive_prompt import render_workspace_context, workspace_location_path
from harness.run_protocol import (
    DynamicSystemInstructions,
    ImageSystemInstructionTurnRunner,
    RunEmitter,
    SystemInstructionTurnRunner,
    TurnOutcome,
)
from harness.spine_client import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSignal,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    MemoryStatus,
    MemoryUnit,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    PatchMemoryResponse,
    RevisionConflict,
    SpineClientError,
)
from harness.tools_memory import MemoryToolContext, render_spine_error

type ContextFactory = Callable[[str], MemoryToolContext]
type ContextChanged = Callable[[str], Awaitable[None]]

_MEMORY_UNAVAILABLE_MESSAGE = "Memory is unavailable; continuing without injected context."


def _live_location_path(context: MemoryToolContext) -> str | None:
    toolset = context.toolset
    return None if toolset is None else workspace_location_path(toolset.location())


class _ProgressiveInstructions(DynamicSystemInstructions):
    """Refresh location-sensitive context before each provider request. [R16]"""

    def __init__(
        self,
        *,
        thread_id: str,
        prompt: str,
        context: MemoryToolContext,
        spine: InjectionGateway,
        contexts: ThreadMemoryContextRegistry,
        model_context_tokens: int,
        emit: RunEmitter,
        on_context_changed: ContextChanged | None,
    ) -> None:
        self._thread_id = thread_id
        self._prompt = prompt
        self._context = context
        self._spine = spine
        self._contexts = contexts
        self._model_context_tokens = model_context_tokens
        self._emit = emit
        self._on_context_changed = on_context_changed
        self._last_location = self._location_path()
        snapshot = contexts.snapshot(thread_id)
        self._memory_block = snapshot.final_block if snapshot is not None else None
        self._workspace_block: str | None = None

    @property
    def memory_block(self) -> str | None:
        return self._memory_block

    @property
    def workspace_block(self) -> str | None:
        return self._workspace_block

    async def render(self) -> str | None:
        location_path = self._location_path()
        if location_path != self._last_location:
            self._last_location = location_path
            await self._refresh_memory(location_path)
        toolset = self._context.toolset
        self._workspace_block = (
            render_workspace_context(toolset.location()) if toolset is not None else None
        )
        snapshot = self._contexts.snapshot(self._thread_id)
        self._memory_block = snapshot.final_block if snapshot is not None else None
        blocks = [
            block for block in (self._workspace_block, self._memory_block) if block is not None
        ]
        return "\n\n".join(blocks) or None

    def _location_path(self) -> str | None:
        toolset = self._context.toolset
        return None if toolset is None else workspace_location_path(toolset.location())

    async def _refresh_memory(self, location_path: str | None) -> None:
        snapshot = self._contexts.snapshot(self._thread_id)
        if snapshot is None or self._context.thread_id is None:
            return
        try:
            prepared = await self._spine.prepare_injection(
                InjectPrepareRequest(
                    thread_id=self._context.thread_id,
                    agent_id=self._context.agent_id,
                    machine_id=self._context.machine_id,
                    principal_id=self._context.principal_id,
                    project_key=self._context.project_key,
                    location_path=location_path,
                    agent_kind=None,
                    prompt=self._prompt,
                    model_context_tokens=self._model_context_tokens,
                    mode="autonomous",
                    current_memory_ids=sorted(snapshot.member_ids, key=lambda value: value.int),
                    confirmed_memory_ids=sorted(
                        snapshot.confirmed_memory_ids, key=lambda value: value.int
                    ),
                    excluded_memory_ids=sorted(
                        snapshot.excluded_memory_ids, key=lambda value: value.int
                    ),
                )
            )
            _, changed = self._contexts.replace_autonomous(
                self._thread_id,
                prepared=prepared,
            )
        except (SpineClientError, ValueError):
            await self._emit.error(
                {
                    "code": "memory_unavailable",
                    "phase": "movement_rescore",
                    "message": _MEMORY_UNAVAILABLE_MESSAGE,
                }
            )
            return
        if changed and self._on_context_changed is not None:
            await self._on_context_changed(self._thread_id)


class InjectionGateway(Protocol):
    """The C.4 operations used by the first-chat injection flow."""

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse: ...

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse: ...

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse: ...

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse: ...


class MemoryGateTurnRunner:
    """Gate the first ordinary chat in each daemon-lifetime thread exactly once."""

    def __init__(
        self,
        delegate: SystemInstructionTurnRunner,
        spine: InjectionGateway,
        context_factory: ContextFactory,
        *,
        model_context_tokens: int,
        contexts: ThreadMemoryContextRegistry | None = None,
        on_context_changed: ContextChanged | None = None,
    ) -> None:
        if type(model_context_tokens) is not int or model_context_tokens <= 0:
            raise ValueError("model_context_tokens must be a positive integer")
        self._delegate = delegate
        self._spine = spine
        self._context_factory = context_factory
        self._model_context_tokens = model_context_tokens
        self._contexts = contexts or ThreadMemoryContextRegistry()
        self._on_context_changed = on_context_changed
        self._attempted_threads: set[str] = set()

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
        image: BinaryContent | None = None,
    ) -> TurnOutcome:
        """Prepare, block for a valid decision, commit, then invoke the model."""

        if remember_command_text(prompt) is not None or browser_open_web_command(prompt):
            return await self._run_model(
                thread_id=thread_id,
                prompt=prompt,
                message_history=message_history,
                emit=emit,
                model_resolution=model_resolution,
                image=image,
            )
        if thread_id in self._attempted_threads:
            if self._contexts.snapshot(thread_id) is None:
                return await self._run_model(
                    thread_id=thread_id,
                    prompt=prompt,
                    message_history=message_history,
                    emit=emit,
                    model_resolution=model_resolution,
                    image=image,
                )
            return await self._run_autonomous(
                thread_id=thread_id,
                prompt=prompt,
                message_history=message_history,
                emit=emit,
                model_resolution=model_resolution,
                image=image,
            )

        # Claim before any fallible work. A cancelled or failed attempt must not
        # surprise the human with a later first-turn gate in this process.
        self._attempted_threads.add(thread_id)
        context = self._context_factory(thread_id)
        if context.thread_id is None:
            raise ValueError("memory gate context requires a thread_id")

        try:
            prepared = await self._spine.prepare_injection(
                InjectPrepareRequest(
                    thread_id=context.thread_id,
                    agent_id=context.agent_id,
                    machine_id=context.machine_id,
                    principal_id=context.principal_id,
                    project_key=context.project_key,
                    location_path=_live_location_path(context),
                    agent_kind=None,
                    prompt=prompt,
                    model_context_tokens=(
                        model_resolution.context_tokens
                        if model_resolution is not None
                        else self._model_context_tokens
                    ),
                )
            )
        except SpineClientError:
            await self._memory_unavailable(emit, phase="prepare")
            return await self._run_model(
                thread_id=thread_id,
                prompt=prompt,
                message_history=message_history,
                emit=emit,
                model_resolution=model_resolution,
                image=image,
            )

        decision = await emit.open_gate(
            {
                "injection_id": prepared.injection_id,
                "snapshot_ts": prepared.snapshot_ts,
                "scorer_version": prepared.scorer_version,
                "injected": prepared.injected,
                "near_misses": prepared.near_misses,
            }
        )
        excluded_memory_ids = frozenset(item.memory_id for item in decision.removed)

        try:
            committed = await self._spine.commit_injection(
                InjectCommitRequest(
                    # Never trust the echoed browser ID at the C.4 boundary.
                    injection_id=prepared.injection_id,
                    removed=decision.removed,
                    added_back=decision.added_back,
                )
            )
        except SpineClientError:
            await self._memory_unavailable(emit, phase="commit")
            await emit.dismiss_gate()
            return await self._run_model(
                thread_id=thread_id,
                prompt=prompt,
                message_history=message_history,
                emit=emit,
                additional_excluded_memory_ids=excluded_memory_ids,
                model_resolution=model_resolution,
                image=image,
            )

        try:
            self._contexts.install(
                thread_id,
                prepared=prepared,
                removed_memory_ids=excluded_memory_ids,
                added_back=decision.added_back,
                final_block=committed.final_block,
            )
        except ValueError:
            await self._memory_unavailable(emit, phase="commit")
            await emit.dismiss_gate()
            return await self._run_model(
                thread_id=thread_id,
                prompt=prompt,
                message_history=message_history,
                emit=emit,
                additional_excluded_memory_ids=excluded_memory_ids,
                model_resolution=model_resolution,
                image=image,
            )

        for wrong in committed.wrong_removed:
            await self._resolve_wrong_memory(
                current=wrong,
                prepared=prepared,
                context=context,
                emit=emit,
            )

        await emit.dismiss_gate()
        return await self._run_model(
            thread_id=thread_id,
            prompt=prompt,
            message_history=message_history,
            emit=emit,
            additional_excluded_memory_ids=excluded_memory_ids,
            model_resolution=model_resolution,
            image=image,
        )

    async def _resolve_wrong_memory(
        self,
        *,
        current: MemoryUnit,
        prepared: InjectPrepareResponse,
        context: MemoryToolContext,
        emit: RunEmitter,
    ) -> None:
        """Keep the hard pause open until one current wrong unit is resolved."""

        resolution_error: str | None = None
        while True:
            decision = await emit.open_gate(
                {
                    "stage": "wrong_resolution",
                    "injection_id": prepared.injection_id,
                    "snapshot_ts": prepared.snapshot_ts,
                    "scorer_version": prepared.scorer_version,
                    "injected": [],
                    "near_misses": [],
                    "wrong_removed": [current],
                    "resolution_error": resolution_error,
                }
            )
            resolution = decision.wrong_resolution
            if (
                resolution is None
                or decision.removed
                or decision.added_back
                or resolution.memory_id != current.memory_id
                or resolution.expected_revision != current.revision
            ):
                raise ValueError("wrong-resolution decision does not match the current gate")

            request = PatchMemoryRequest(
                expected_revision=current.revision,
                body=resolution.body if resolution.action == "edit" else None,
                status=(MemoryStatus.TOMBSTONED if resolution.action == "expire" else None),
                editor="user",
                reason=f"gate/wrong:{resolution.action}",
                machine_id=context.machine_id,
            )
            try:
                updated = await self._spine.patch_memory(current.memory_id, request)
            except PatchMemoryConflictError as exc:
                if isinstance(exc.conflict, RevisionConflict):
                    current = exc.conflict.conflict
                    resolution_error = (
                        "This memory changed while you were reviewing it. "
                        "Review the latest version and try again."
                    )
                else:
                    resolution_error = (
                        "The memory could not be resolved because its label conflicts."
                    )
                continue
            except SpineClientError as exc:
                resolution_error = render_spine_error("update", exc)
                continue

            if updated.memory_id != current.memory_id:
                raise RuntimeError("Spine patched a different memory than requested")
            return

    async def _run_model(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        additional_excluded_memory_ids: frozenset[UUID] = frozenset(),
        model_resolution: ThreadModelResolution | None = None,
        image: BinaryContent | None = None,
    ) -> TurnOutcome:
        async with self._contexts.model_feedback_boundary(thread_id):
            run_context = self._context_factory(thread_id)
            context = self._contexts.snapshot(thread_id)
            excluded_memory_ids = (
                context.excluded_memory_ids if context is not None else frozenset()
            ) | additional_excluded_memory_ids
            progressive = self._progressive_instructions(
                thread_id=thread_id,
                prompt=prompt,
                context=run_context,
                emit=emit,
                model_resolution=model_resolution,
            )
            if image is None:
                outcome = await self._delegate.run(
                    thread_id=thread_id,
                    prompt=prompt,
                    message_history=message_history,
                    emit=emit,
                    model_resolution=model_resolution,
                    dynamic_instructions=progressive,
                    excluded_memory_ids=excluded_memory_ids,
                )
            else:
                outcome = await cast(ImageSystemInstructionTurnRunner, self._delegate).run(
                    thread_id=thread_id,
                    prompt=prompt,
                    image=image,
                    message_history=message_history,
                    emit=emit,
                    model_resolution=model_resolution,
                    dynamic_instructions=progressive,
                    excluded_memory_ids=excluded_memory_ids,
                )
            await self._record_citations(self._contexts.snapshot(thread_id), outcome, emit)
            return outcome

    async def _run_autonomous(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None,
        image: BinaryContent | None = None,
    ) -> TurnOutcome:
        """Re-score once, update ambient state, then run without another gate."""

        context = self._context_factory(thread_id)
        if context.thread_id is None:
            raise ValueError("memory rescore context requires a thread_id")
        async with self._contexts.model_feedback_boundary(thread_id):
            snapshot = self._contexts.snapshot(thread_id)
            if snapshot is None:  # pragma: no cover - guarded by run()
                raise RuntimeError("thread memory context disappeared")
            try:
                prepared = await self._spine.prepare_injection(
                    InjectPrepareRequest(
                        thread_id=context.thread_id,
                        agent_id=context.agent_id,
                        machine_id=context.machine_id,
                        principal_id=context.principal_id,
                        project_key=context.project_key,
                        location_path=_live_location_path(context),
                        agent_kind=None,
                        prompt=prompt,
                        model_context_tokens=(
                            model_resolution.context_tokens
                            if model_resolution is not None
                            else self._model_context_tokens
                        ),
                        mode="autonomous",
                        current_memory_ids=sorted(snapshot.member_ids, key=lambda value: value.int),
                        confirmed_memory_ids=sorted(
                            snapshot.confirmed_memory_ids, key=lambda value: value.int
                        ),
                        excluded_memory_ids=sorted(
                            snapshot.excluded_memory_ids, key=lambda value: value.int
                        ),
                    )
                )
                current, changed = self._contexts.replace_autonomous(
                    thread_id,
                    prepared=prepared,
                )
            except SpineClientError:
                await self._memory_unavailable(emit, phase="rescore")
                current = snapshot
                changed = False
            except ValueError:
                await self._memory_unavailable(emit, phase="rescore")
                current = snapshot
                changed = False

            if changed and self._on_context_changed is not None:
                await self._on_context_changed(thread_id)
            progressive = self._progressive_instructions(
                thread_id=thread_id,
                prompt=prompt,
                context=context,
                emit=emit,
                model_resolution=model_resolution,
            )
            if image is None:
                outcome = await self._delegate.run(
                    thread_id=thread_id,
                    prompt=prompt,
                    message_history=message_history,
                    emit=emit,
                    model_resolution=model_resolution,
                    dynamic_instructions=progressive,
                    excluded_memory_ids=current.excluded_memory_ids,
                )
            else:
                outcome = await cast(ImageSystemInstructionTurnRunner, self._delegate).run(
                    thread_id=thread_id,
                    prompt=prompt,
                    image=image,
                    message_history=message_history,
                    emit=emit,
                    model_resolution=model_resolution,
                    dynamic_instructions=progressive,
                    excluded_memory_ids=current.excluded_memory_ids,
                )
            await self._record_citations(self._contexts.snapshot(thread_id), outcome, emit)
            return outcome

    def _progressive_instructions(
        self,
        *,
        thread_id: str,
        prompt: str,
        context: MemoryToolContext,
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None,
    ) -> _ProgressiveInstructions:
        return _ProgressiveInstructions(
            thread_id=thread_id,
            prompt=prompt,
            context=context,
            spine=self._spine,
            contexts=self._contexts,
            model_context_tokens=(
                model_resolution.context_tokens
                if model_resolution is not None
                else self._model_context_tokens
            ),
            emit=emit,
            on_context_changed=self._on_context_changed,
        )

    async def _record_citations(
        self,
        context: ThreadMemorySnapshot | None,
        outcome: TurnOutcome,
        emit: RunEmitter,
    ) -> None:
        """Persist each lexical reuse against this model call's event batch. [A-036]"""

        if outcome.stop_reason.value != "end_turn" or outcome.assistant_text is None:
            return
        if context is None:
            return
        failed = False
        for memory_id in cited_memory_ids(outcome.assistant_text, context.memory_bodies):
            injection_id = context.event_sources.get(memory_id)
            if injection_id is None:
                continue
            try:
                await self._spine.submit_feedback(
                    FeedbackRequest(
                        injection_id=injection_id,
                        memory_id=memory_id,
                        signal=FeedbackSignal.CITED,
                    )
                )
            except SpineClientError:
                failed = True
        if failed:
            await self._memory_unavailable(emit, phase="citation")

    @staticmethod
    async def _memory_unavailable(emit: RunEmitter, *, phase: str) -> None:
        await emit.error(
            {
                "code": "memory_unavailable",
                "phase": phase,
                "message": _MEMORY_UNAVAILABLE_MESSAGE,
            }
        )
