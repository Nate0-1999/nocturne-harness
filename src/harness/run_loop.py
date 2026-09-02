"""Process-scoped scheduling and lifecycle control for C.7 model runs."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic_ai.messages import (
    BinaryContent,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserContent,
    UserPromptPart,
)

from harness.commands import model_command_text, remember_command_text
from harness.envelope import (
    ActiveRunSnapshot,
    Envelope,
    EnvelopeFactory,
    GateCommitPayload,
    GateDismissPayload,
    GateOpenPayload,
    ImageInput,
    ImageView,
    MessageType,
    PromptQueuedPayload,
    ProposedResponseFirePayload,
    QueuedPromptSnapshot,
    RunDeltaEventPayload,
    RunDeltaTextPayload,
    RunDeltaThinkingPayload,
    RunDonePayload,
    RunStartedPayload,
    RunUsagePayload,
    StopReason,
    SymphonyCancelAttemptPayload,
    SymphonyCharterForkPayload,
    SymphonyClarificationPayload,
    SymphonyCompletePayload,
    SymphonyInterventionPayload,
    SymphonyLaunchPayload,
    ThreadSnapshotResponsePayload,
    UsagePayload,
)
from harness.model_policy import (
    ModelCatalogUnavailable,
    ModelRequestParameters,
    NamedModelResolutionError,
    ThreadModelResolution,
    ThreadModelResolver,
)
from harness.parameter_registry import (
    ParameterChange,
    ParameterRegistry,
    ParameterSnapshot,
    ParameterValue,
    ParameterWriteViolation,
)
from harness.project_path import validate_artificial_project_path
from harness.proposed_response import (
    find_proposed_response,
    proposal_was_fired,
    proposed_response_fire_record,
)
from harness.run_protocol import ImageTurnRunner, RunEmitter, TurnOutcome, TurnRunner, UsageSnapshot
from harness.symphony_experience import SymphonyExperience
from harness.transcript import HydratedTranscript, TranscriptJournal

type EnvelopeSink = Callable[[Envelope], Awaitable[None]]

_SUBSCRIPTION_BUFFER_SIZE = 256
type _Delivery = tuple[Envelope, asyncio.Future[None] | None]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Turn:
    run_id: str
    prompt_id: str
    prompt: str
    user_message: dict[str, Any]
    image: BinaryContent | None = None
    image_view: ImageView | None = None
    model_target: str | None = None
    symphony: SymphonyLaunchPayload | None = None
    symphony_intervention: SymphonyInterventionPayload | None = None
    open_symphony_draft_ids: tuple[str, ...] = ()
    accepted_symphony_stack_events: tuple[Mapping[str, object], ...] = ()
    parent_id: str | None = None


@dataclass(slots=True)
class _ActiveRun:
    turn: _Turn
    assistant_message: dict[str, Any]
    state: str = "running"
    usage: UsageSnapshot = UsageSnapshot()
    usage_emitted: bool = False
    task: asyncio.Task[None] | None = None
    gate_decision: asyncio.Future[GateCommitPayload] | None = None
    gate_committing: bool = False
    model_candidate: ThreadModelResolution | None = None
    model_error: str | None = None


@dataclass(slots=True)
class _ThreadState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    message_history: tuple[object, ...] = ()
    active: _ActiveRun | None = None
    queued: deque[_Turn] = field(default_factory=deque)
    open_gate: GateOpenPayload | None = None
    resolved_model: str | None = None
    model_resolution: ThreadModelResolution | None = None
    cached_prefix_tokens: int = 0
    project_key: str | None = None
    project_label: str | None = None
    workspace_root: str | None = None
    current_location: str | None = None


class ProjectBindingConflict(RuntimeError):
    """A project path cannot replace an authoritative thread identity."""

    def __init__(self, requested: str, existing: str | None) -> None:
        self.requested = requested
        self.existing = existing
        super().__init__("thread project context is already fixed")


@dataclass(slots=True)
class _Subscription:
    sink: EnvelopeSink
    thread_id: str | None
    on_overflow: Callable[[], None] | None = None
    queue: asyncio.Queue[_Delivery] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_SUBSCRIPTION_BUFFER_SIZE)
    )
    worker: asyncio.Task[None] | None = None
    failed: bool = False


class _Emitter(RunEmitter):
    def __init__(self, loop: RunLoop, thread_id: str, active: _ActiveRun) -> None:
        self._loop = loop
        self._thread_id = thread_id
        self._active = active

    @property
    def run_id(self) -> str:
        return self._active.turn.run_id

    @property
    def prompt_id(self) -> str:
        return self._active.turn.prompt_id

    async def text(self, value: str) -> None:
        await self._loop._emit_text(self._thread_id, self._active, value)

    async def thinking(self, value: str) -> None:
        await self._loop._emit_thinking(self._thread_id, self._active, value)

    async def event(self, value: Mapping[str, object]) -> None:
        await self._loop._emit_event(self._thread_id, self._active, value)

    async def usage(self, value: UsageSnapshot) -> None:
        await self._loop._emit_usage(self._thread_id, self._active, value)

    async def open_gate(self, value: Mapping[str, object]) -> GateCommitPayload:
        return await self._loop._emit_gate(self._thread_id, self._active, value)

    async def dismiss_gate(self) -> None:
        await self._loop._dismiss_gate(self._thread_id, self._active)

    async def error(self, value: Mapping[str, object]) -> None:
        await self._loop._emit_error(self._thread_id, self._active, value)


class RunLoop:
    """Own daemon-lifetime thread state and schedule one run per thread.

    The injected runner is the only model-facing dependency. A single state
    lock makes subscription snapshots and subsequent live events atomic, and
    also gives terminalization a strict dismiss → done → next-start order.
    """

    def __init__(
        self,
        runner: TurnRunner,
        factory: EnvelopeFactory,
        *,
        run_id_factory: Callable[[], str] | None = None,
        resolved_model: str | None = None,
        model_resolver: ThreadModelResolver | None = None,
        clock: Callable[[], datetime] | None = None,
        transcript_journal: TranscriptJournal | None = None,
        parameter_registry: ParameterRegistry | None = None,
        symphony_experience: SymphonyExperience | None = None,
    ) -> None:
        if resolved_model is not None and model_resolver is not None:
            raise ValueError("use either resolved_model or model_resolver, not both")
        if resolved_model is not None and (
            not isinstance(resolved_model, str)
            or not resolved_model
            or resolved_model != resolved_model.strip()
        ):
            raise ValueError("resolved_model must be nonblank without surrounding whitespace")
        self._runner = runner
        self._factory = factory
        self._run_id_factory = run_id_factory or factory.new_id
        self._initial_resolved_model = resolved_model
        self._model_resolver = model_resolver
        self._clock = clock or (lambda: datetime.now(UTC))
        self._transcript_journal = transcript_journal
        self._parameter_registry = parameter_registry or ParameterRegistry()
        self._symphony_experience = symphony_experience
        self._lock = asyncio.Lock()
        self._submission_locks: dict[str, asyncio.Lock] = {}
        self._pending_captured: dict[str, deque[_Turn]] = {}
        self._threads = self._hydrate_threads(transcript_journal)
        self._subscriptions: list[_Subscription] = []
        self._selected_thread_id: str | None = None
        self._terminal_tasks: set[asyncio.Task[None]] = set()
        self._closing = False
        self._capture_failure: Exception | None = None

    async def parameter_snapshot(
        self,
        thread_id: str,
        *,
        as_of: datetime | None = None,
    ) -> ParameterSnapshot:
        """Read one CURRENT thread through the typed public registry seam."""

        self._require_thread_id(thread_id)
        resolution = await self._resolution_for_thread(thread_id)
        if resolution is None:
            raise ParameterWriteViolation("invalid")
        instant = as_of or self._clock()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("parameter as_of must be timezone-aware")
        async with self._lock:
            state = self._state_for_locked(thread_id)
            if state.model_resolution is None:
                state.model_resolution = resolution
                state.resolved_model = resolution.model
            self._ensure_parameter_thread_locked(thread_id, state.model_resolution)
            return self._parameter_registry.snapshot(thread_id=thread_id, as_of=instant)

    async def write_parameter(
        self,
        *,
        module_id: str,
        thread_id: str,
        parameter_id: str,
        value: object,
    ) -> ParameterSnapshot:
        """Validate, apply, journal, and publish one bound control write."""

        self._require_thread_id(thread_id)
        try:
            normalized = self._parameter_registry.validate_bound_write(
                module_id=module_id,
                parameter_id=parameter_id,
                value=value,
            )
        except ParameterWriteViolation as exc:
            await self._publish_parameter_refusal(
                thread_id=thread_id,
                module_id=module_id,
                parameter_id=parameter_id,
                reason=exc.reason,
            )
            raise

        submission_lock = self._submission_locks.setdefault(thread_id, asyncio.Lock())
        async with submission_lock:
            async with self._lock:
                state = self._state_for_locked(thread_id)
                if state.active is not None:
                    await self._publish_parameter_refusal_locked(
                        thread_id=thread_id,
                        module_id=module_id,
                        parameter_id=parameter_id,
                        reason="busy",
                    )
                    raise ParameterWriteViolation("busy")

            resolution = await self._resolution_for_thread(thread_id)
            if resolution is None:
                await self._publish_parameter_refusal(
                    thread_id=thread_id,
                    module_id=module_id,
                    parameter_id=parameter_id,
                    reason="invalid",
                )
                raise ParameterWriteViolation("invalid")

            candidate: ThreadModelResolution | None = None
            if parameter_id == "model.slug":
                assert isinstance(normalized, str)
                if self._model_resolver is None:
                    await self._publish_parameter_refusal(
                        thread_id=thread_id,
                        module_id=module_id,
                        parameter_id=parameter_id,
                        reason="invalid",
                    )
                    raise ParameterWriteViolation("invalid")
                try:
                    candidate = await self._model_resolver.resolve_named(thread_id, normalized)
                except (NamedModelResolutionError, ModelCatalogUnavailable) as exc:
                    await self._publish_parameter_refusal(
                        thread_id=thread_id,
                        module_id=module_id,
                        parameter_id=parameter_id,
                        reason="invalid",
                    )
                    raise ParameterWriteViolation("invalid") from exc

            async with self._lock:
                state = self._state_for_locked(thread_id)
                if state.active is not None:
                    await self._publish_parameter_refusal_locked(
                        thread_id=thread_id,
                        module_id=module_id,
                        parameter_id=parameter_id,
                        reason="busy",
                    )
                    raise ParameterWriteViolation("busy")
                if state.model_resolution is None:
                    state.model_resolution = resolution
                    state.resolved_model = resolution.model
                previous = state.model_resolution
                self._ensure_parameter_thread_locked(thread_id, previous)
                old_value = self._parameter_value(previous, parameter_id)
                if old_value == normalized:
                    return self._parameter_registry.snapshot(
                        thread_id=thread_id,
                        as_of=self._aware_clock(),
                    )

                if candidate is not None:
                    sacrificed_prefix = state.cached_prefix_tokens
                    updated = replace(
                        candidate,
                        stickiness_epoch=previous.stickiness_epoch + 1,
                        request_parameters=previous.request_parameters,
                    )
                    state.cached_prefix_tokens = 0
                else:
                    updated = self._with_parameter(previous, parameter_id, normalized)
                state.model_resolution = updated
                state.resolved_model = updated.model
                changed_at = self._aware_clock()
                await self._record_parameter_change_locked(
                    thread_id=thread_id,
                    parameter_id=parameter_id,
                    old_value=old_value,
                    new_value=normalized,
                    changed_at=changed_at,
                )
                if candidate is not None:
                    await self._publish_model_change_locked(
                        thread_id=thread_id,
                        state=state,
                        previous=previous,
                        resolution=updated,
                        changed_at=changed_at,
                        reason="human_control",
                        sacrificed_cached_prefix_tokens=sacrificed_prefix,
                    )
                return self._parameter_registry.snapshot(
                    thread_id=thread_id,
                    as_of=changed_at,
                )

    async def attach(
        self,
        sink: EnvelopeSink,
        *,
        on_overflow: Callable[[], None] | None = None,
    ) -> None:
        """Attach a connection and snapshot the selected thread before events."""

        receipt: asyncio.Future[None] | None = None
        async with self._lock:
            self._require_open()
            self._remove_sink_locked(sink)
            thread_id = self._selected_thread_id
            subscription = _Subscription(
                sink=sink,
                thread_id=thread_id,
                on_overflow=on_overflow,
            )
            self._subscriptions.append(subscription)
            if thread_id is not None:
                state = self._state_for_locked(thread_id)
                receipt = self._enqueue_locked(
                    subscription,
                    self._snapshot_envelope(thread_id, state),
                    confirm=True,
                )
        if receipt is not None:
            await receipt

    async def select(self, thread_id: str, sink: EnvelopeSink) -> None:
        """Select and subscribe to a prompt's thread without sending a snapshot."""

        self._require_thread_id(thread_id)
        async with self._lock:
            self._require_open()
            self._state_for_locked(thread_id)
            self._selected_thread_id = thread_id
            self._bind_sink_locked(sink, thread_id)

    async def request_snapshot(
        self,
        thread_id: str,
        sink: EnvelopeSink,
        project_key: str | None = None,
        workspace_root: str | None = None,
        project_label: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Select a thread and acknowledge its durable binding in one snapshot."""

        self._require_thread_id(thread_id)
        canonical_project = (
            None if project_key is None else validate_artificial_project_path(project_key)
        )
        receipt: asyncio.Future[None]
        async with self._lock:
            self._require_open()
            state = self._state_for_locked(thread_id)
            if workspace_root is not None:
                self._bind_workspace_locked(
                    thread_id,
                    state,
                    workspace_root=workspace_root,
                    project_label=project_label,
                )
            elif canonical_project is not None:
                self._bind_project_locked(thread_id, state, canonical_project)
            self._selected_thread_id = thread_id
            existing = self._find_sink_locked(sink)
            on_overflow = existing.on_overflow if existing is not None else None
            self._remove_sink_locked(sink)
            subscription = _Subscription(
                sink=sink,
                thread_id=thread_id,
                on_overflow=on_overflow,
            )
            self._subscriptions.append(subscription)
            pending = self._enqueue_locked(
                subscription,
                self._snapshot_envelope(thread_id, state, request_id=request_id),
                confirm=True,
            )
            assert pending is not None
            receipt = pending
        await receipt

    def project_key(self, thread_id: str) -> str | None:
        """Read the daemon-owned project identity for trusted run composition."""

        self._require_thread_id(thread_id)
        state = self._threads.get(thread_id)
        return None if state is None else state.project_key

    def thread_workspace(self, thread_id: str) -> tuple[str, str] | None:
        """Return this thread's durable workspace root and current location."""

        self._require_thread_id(thread_id)
        state = self._threads.get(thread_id)
        if state is None or state.workspace_root is None or state.current_location is None:
            return None
        return state.workspace_root, state.current_location

    def record_thread_location(self, thread_id: str, current_location: str) -> None:
        """Persist movement for one thread without touching any sibling."""

        self._require_thread_id(thread_id)
        state = self._threads.get(thread_id)
        if state is None or state.workspace_root is None:
            raise ValueError("thread has no bound workspace")
        location = Path(current_location).resolve(strict=True)
        root = Path(state.workspace_root)
        if not location.is_dir() or not location.is_relative_to(root):
            raise ValueError("thread location must remain inside its workspace")
        canonical = str(location)
        if state.current_location == canonical:
            return
        if self._transcript_journal is not None:
            self._transcript_journal.append_thread_location(thread_id, canonical)
        state.current_location = canonical

    async def detach(self, sink: EnvelopeSink) -> None:
        """Detach a connection without changing daemon-lifetime thread state."""

        async with self._lock:
            self._remove_sink_locked(sink)

    async def send_direct(self, sink: EnvelopeSink, envelope: Envelope) -> None:
        """Journal and deliver one daemon-authored event outside the run routes."""

        receipt: asyncio.Future[None]
        async with self._lock:
            self._require_open()
            pending = await self._send_direct_locked(sink, envelope, confirm=True)
            assert pending is not None
            receipt = pending
        await receipt

    async def publish(self, thread_id: str, envelope: Envelope) -> None:
        """Publish one daemon-authored ambient event to a thread's subscribers."""

        self._require_thread_id(thread_id)
        if envelope.thread_id != thread_id:
            raise ValueError("ambient envelope thread does not match its publish target")
        async with self._lock:
            self._require_open()
            await self._publish_locked(thread_id, envelope)

    async def submit(
        self,
        *,
        thread_id: str,
        prompt_id: str,
        prompt: str,
        image: ImageInput | None = None,
        symphony: SymphonyLaunchPayload | None = None,
        symphony_intervention: SymphonyInterventionPayload | None = None,
        proposed_response: ProposedResponseFirePayload | None = None,
        sink: EnvelopeSink | None = None,
    ) -> str:
        """Accept a prompt, starting it now or reserving one FIFO run ID."""

        self._require_thread_id(thread_id)
        if not prompt.strip():
            raise ValueError("prompt must not be blank")
        if image is not None and not isinstance(image, ImageInput):
            raise TypeError("image must be an ImageInput or None")
        if symphony is not None and not isinstance(symphony, SymphonyLaunchPayload):
            raise TypeError("symphony must be a SymphonyLaunchPayload or None")
        if symphony_intervention is not None and not isinstance(
            symphony_intervention,
            (
                SymphonyClarificationPayload,
                SymphonyCancelAttemptPayload,
                SymphonyCharterForkPayload,
                SymphonyCompletePayload,
            ),
        ):
            raise TypeError("symphony_intervention must be a typed intervention or None")
        if proposed_response is not None and not isinstance(
            proposed_response, ProposedResponseFirePayload
        ):
            raise TypeError("proposed_response must be a typed proposal reference or None")
        if sum(value is not None for value in (image, symphony, symphony_intervention)) > 1:
            raise ValueError("image, Symphony launch, and Symphony steering are mutually exclusive")
        if proposed_response is not None and any(
            value is not None for value in (image, symphony, symphony_intervention)
        ):
            raise ValueError("a proposed response must be an ordinary text prompt")
        if (symphony is not None or symphony_intervention is not None) and (
            self._symphony_experience is None
        ):
            raise RuntimeError("Symphony is unavailable in this runtime")
        if image is not None and self._transcript_journal is None:
            raise RuntimeError("image input requires the mandatory transcript journal")
        if proposed_response is not None and self._transcript_journal is None:
            raise RuntimeError("a proposed response requires the mandatory transcript journal")

        run_id = self._run_id_factory()
        # Validate both correlation IDs before mutating process state.
        RunStartedPayload(run_id=run_id, prompt_id=prompt_id)
        model_target = model_command_text(prompt)
        image_view = image.view() if image is not None else None
        binary_image = (
            None
            if image is None
            else BinaryContent(data=image.decoded_bytes(), media_type=image.media_type)
        )
        user_message: dict[str, Any] = {
            "message_id": prompt_id,
            "run_id": run_id,
            "role": "user",
            "content": prompt,
            "state": "queued",
        }
        if image_view is not None:
            user_message["image"] = image_view.model_dump(mode="json")
        turn = _Turn(
            run_id=run_id,
            prompt_id=prompt_id,
            prompt=prompt,
            user_message=user_message,
            image=binary_image,
            image_view=image_view,
            model_target=model_target,
            symphony=symphony,
            symphony_intervention=symphony_intervention,
        )
        async with self._lock:
            self._require_open()
            submission_lock = self._submission_locks.setdefault(thread_id, asyncio.Lock())
            if proposed_response is not None:
                messages = self._state_for_locked(thread_id).messages
                source = find_proposed_response(
                    messages,
                    proposed_response.proposal_run_id,
                )
                if source is None or source[0].get("partial") is not False:
                    raise ValueError("proposed response is not available in this thread")
                if proposal_was_fired(
                    messages,
                    proposed_response.proposal_run_id,
                ):
                    raise ValueError("proposed response was already fired")
                user_message["proposed_response"] = proposed_response_fire_record(
                    source_message=source[0],
                    proposal=source[1],
                    proposal_run_id=proposed_response.proposal_run_id,
                    fired_text=prompt,
                    fired_at=self._aware_clock(),
                )
            if self._transcript_journal is not None:
                if image is not None:
                    stored_view = self._capture_image_attachment(thread_id, prompt_id, image)
                    if stored_view != image_view:  # pragma: no cover - both derive exact bytes
                        raise RuntimeError("journal image view differs from validated input")
                turn.parent_id = self._captured_parent_id(thread_id)
                self._capture_message(thread_id, user_message, parent_id=turn.parent_id)
                self._pending_captured.setdefault(thread_id, deque()).append(turn)

        try:
            async with submission_lock:
                async with self._lock:
                    self._require_open()
                local_symphony = self._symphony_experience is not None and (
                    symphony is not None
                    or symphony_intervention is not None
                    or self._symphony_experience.is_trigger(prompt)
                )
                model_resolution = (
                    None if local_symphony else await self._resolution_for_thread(thread_id)
                )

                async with self._lock:
                    self._require_open()
                    self._discard_pending_capture_locked(thread_id, turn)
                    state = self._state_for_locked(thread_id)
                    turn.open_symphony_draft_ids = self._open_symphony_draft_ids(state.messages)
                    turn.accepted_symphony_stack_events = self._symphony_stack_events(
                        state.messages
                    )
                    if state.model_resolution is None:
                        state.model_resolution = model_resolution
                        if model_resolution is not None:
                            state.resolved_model = model_resolution.model
                    self._selected_thread_id = thread_id
                    if sink is not None:
                        self._bind_sink_locked(sink, thread_id)
                    if self._transcript_journal is None:
                        turn.parent_id = self._parent_for_new_turn_locked(state)
                    state.messages.append(user_message)
                    if state.active is None:
                        await self._start_locked(thread_id, state, turn)
                    else:
                        state.queued.append(turn)
                        await self._publish_locked(
                            thread_id,
                            self._factory.create(
                                MessageType.PROMPT_QUEUED,
                                PromptQueuedPayload(
                                    run_id=run_id,
                                    prompt_id=prompt_id,
                                    image=turn.image_view,
                                ),
                                thread_id=thread_id,
                            ),
                        )
        except BaseException:
            async with self._lock:
                self._discard_pending_capture_locked(thread_id, turn)
            raise
        return run_id

    async def cancel(
        self,
        *,
        thread_id: str | None,
        run_id: str,
        sink: EnvelopeSink | None = None,
    ) -> None:
        """Cancel a matching run, resolving an omitted thread to the selection."""

        async with self._lock:
            self._require_open()
            if thread_id is None:
                matches = [
                    (candidate_id, state)
                    for candidate_id, state in self._threads.items()
                    if state.active is not None and state.active.turn.run_id == run_id
                ]
                if len(matches) == 1:
                    thread_id, state = matches[0]
                else:
                    thread_id = self._selected_thread_id
                    state = self._threads.get(thread_id) if thread_id is not None else None
            else:
                self._require_thread_id(thread_id)
                state = self._threads.get(thread_id)
            if thread_id is None:
                error = self._factory.create(
                    MessageType.ERROR,
                    {"code": "run_not_active", "run_id": run_id},
                )
                if sink is not None:
                    await self._send_direct_locked(sink, error)
                return
            active = state.active if state is not None else None
            if active is None or active.turn.run_id != run_id:
                error = self._factory.create(
                    MessageType.ERROR,
                    {"code": "run_not_active", "run_id": run_id},
                    thread_id=thread_id,
                )
                if sink is not None:
                    await self._send_direct_locked(sink, error)
                else:
                    await self._publish_locked(thread_id, error)
                return

            if sink is not None:
                self._bind_sink_locked(sink, thread_id)
            if active.state != "cancelling":
                active.state = "cancelling"
                if active.task is not None:
                    active.task.cancel()

    async def commit_gate(
        self,
        *,
        thread_id: str,
        decision: GateCommitPayload,
        sink: EnvelopeSink | None = None,
    ) -> None:
        """Resolve one matching open gate, or return a scoped non-mutating error."""

        self._require_thread_id(thread_id)
        async with self._lock:
            self._require_open()
            state = self._threads.get(thread_id)
            active = state.active if state is not None else None
            gate = state.open_gate if state is not None else None
            invalid = (
                active is None
                or gate is None
                or active.state != "waiting_gate"
                or active.turn.run_id != decision.run_id
                or gate.run_id != decision.run_id
                or gate.injection_id != decision.injection_id
                or active.gate_committing
                or active.gate_decision is None
                or active.gate_decision.done()
                or not self._valid_gate_membership(gate, decision)
            )
            if invalid:
                error = self._factory.create(
                    MessageType.ERROR,
                    {"code": "gate_not_committable", "run_id": decision.run_id},
                    thread_id=thread_id,
                )
                if sink is not None:
                    await self._send_direct_locked(sink, error)
                else:
                    await self._publish_locked(thread_id, error)
                return

            if sink is not None:
                self._bind_sink_locked(sink, thread_id)
            active.gate_committing = True
            active.gate_decision.set_result(decision)

    async def close(self) -> None:
        """Cancel daemon-owned tasks during app shutdown and reject new work."""

        async with self._lock:
            if self._closing:
                return
            self._closing = True
            tasks: list[asyncio.Task[None]] = []
            for state in self._threads.values():
                if state.active is None or state.active.task is None:
                    continue
                if state.active.state != "cancelling":
                    state.active.state = "cancelling"
                    state.active.task.cancel()
                tasks.append(state.active.task)
            for subscription in self._subscriptions:
                if subscription.worker is not None:
                    subscription.worker.cancel()
                    tasks.append(subscription.worker)
            self._subscriptions.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # A task cancelled before its coroutine's first step terminalizes from
        # its done callback; let that callback run and await its state cleanup.
        await asyncio.sleep(0)
        while self._terminal_tasks:
            await asyncio.gather(*tuple(self._terminal_tasks), return_exceptions=True)

    async def _start_locked(
        self,
        thread_id: str,
        state: _ThreadState,
        turn: _Turn,
    ) -> None:
        turn.user_message["state"] = "running"
        self._capture_message(
            thread_id,
            turn.user_message,
            parent_id=turn.parent_id,
            advance_tail=False,
        )
        assistant_message: dict[str, Any] = {
            "message_id": turn.run_id,
            "run_id": turn.run_id,
            "role": "assistant",
            "content": "",
            "thinking": "",
            "events": [],
            "partial": True,
        }
        user_index = next(
            index for index, message in enumerate(state.messages) if message is turn.user_message
        )
        state.messages.insert(user_index + 1, assistant_message)
        pending = self._pending_captured.get(thread_id)
        has_follower = bool(state.queued or pending)
        self._capture_message(
            thread_id,
            assistant_message,
            parent_id=turn.prompt_id,
            advance_tail=not has_follower,
        )
        follower = state.queued[0] if state.queued else pending[0] if pending else None
        if follower is not None:
            follower.parent_id = turn.run_id
            self._capture_message(
                thread_id,
                follower.user_message,
                parent_id=follower.parent_id,
                advance_tail=False,
            )
        active = _ActiveRun(turn=turn, assistant_message=assistant_message)
        state.active = active
        history = state.message_history
        await self._publish_locked(
            thread_id,
            self._factory.create(
                MessageType.RUN_STARTED,
                RunStartedPayload(
                    run_id=turn.run_id,
                    prompt_id=turn.prompt_id,
                    resolved_model=state.resolved_model,
                    image=turn.image_view,
                ),
                thread_id=thread_id,
            ),
        )
        active.task = asyncio.create_task(
            self._drive(thread_id, active, history, state.model_resolution),
            name=f"harness-run-{turn.run_id}",
        )
        active.task.add_done_callback(
            lambda task: self._terminalize_prestart_cancel(thread_id, active, task)
        )

    def _terminalize_prestart_cancel(
        self,
        thread_id: str,
        active: _ActiveRun,
        task: asyncio.Task[None],
    ) -> None:
        """Confirm cancellation even when the run task never took its first step."""

        if not task.cancelled():
            return
        terminal = asyncio.create_task(self._finish(thread_id, active, None, StopReason.CANCELLED))
        self._terminal_tasks.add(terminal)
        terminal.add_done_callback(self._terminal_tasks.discard)

    async def _drive(
        self,
        thread_id: str,
        active: _ActiveRun,
        history: tuple[object, ...],
        model_resolution: ThreadModelResolution | None,
    ) -> None:
        outcome: TurnOutcome | None = None
        stop_reason = StopReason.ERROR
        try:
            if self._symphony_experience is not None and (
                active.turn.symphony is not None
                or active.turn.symphony_intervention is not None
                or self._symphony_experience.is_trigger(active.turn.prompt)
            ):
                outcome = await self._symphony_experience.run(
                    thread_id=thread_id,
                    prompt=active.turn.prompt,
                    launch=active.turn.symphony,
                    intervention=active.turn.symphony_intervention,
                    accepted_draft_ids=active.turn.open_symphony_draft_ids,
                    accepted_stack_events=active.turn.accepted_symphony_stack_events,
                    message_history=history,
                    emit=_Emitter(self, thread_id, active),
                )
            elif active.turn.image is not None:
                if active.turn.model_target is not None:
                    outcome = await self._refuse_image(
                        thread_id,
                        active,
                        history,
                        model_resolution,
                        reason="model_command",
                    )
                elif remember_command_text(active.turn.prompt) is not None:
                    outcome = await self._refuse_image(
                        thread_id,
                        active,
                        history,
                        model_resolution,
                        reason="remember_command",
                    )
                else:
                    checked, capability = await self._image_capability_for_run(
                        thread_id,
                        active,
                        model_resolution,
                    )
                    if capability != "supported":
                        outcome = await self._refuse_image(
                            thread_id,
                            active,
                            history,
                            checked,
                            reason=capability,
                        )
                    else:
                        outcome = await cast(ImageTurnRunner, self._runner).run(
                            thread_id=thread_id,
                            prompt=active.turn.prompt,
                            image=active.turn.image,
                            message_history=history,
                            emit=_Emitter(self, thread_id, active),
                            model_resolution=checked,
                        )
            elif active.turn.model_target is not None:
                outcome = await self._resolve_model_command(
                    thread_id=thread_id,
                    active=active,
                    history=history,
                )
            else:
                outcome = await self._runner.run(
                    thread_id=thread_id,
                    prompt=active.turn.prompt,
                    message_history=history,
                    emit=_Emitter(self, thread_id, active),
                    model_resolution=model_resolution,
                )
            if not isinstance(outcome, TurnOutcome):
                raise TypeError("turn runner must return TurnOutcome")
            stop_reason = outcome.stop_reason
        except asyncio.CancelledError:
            stop_reason = StopReason.CANCELLED
        except Exception:
            stop_reason = StopReason.ERROR

        terminal = asyncio.create_task(
            self._finish(thread_id, active, outcome, stop_reason),
            name=f"harness-finish-{active.turn.run_id}",
        )
        while True:
            try:
                await asyncio.shield(terminal)
                break
            except asyncio.CancelledError:
                if terminal.cancelled():
                    raise
                # Cancellation can race with a completed model turn. The
                # controller has already marked the run as cancelling; keep
                # its outcome alive until terminalization preserves history.
                continue

    async def _image_capability_for_run(
        self,
        thread_id: str,
        active: _ActiveRun,
        resolution: ThreadModelResolution | None,
    ) -> tuple[ThreadModelResolution | None, Literal["supported", "unsupported", "unknown"]]:
        """Resolve positive, model-exact OpenRouter image capability. [A-052]"""

        if resolution is None or not resolution.uses_openrouter:
            return resolution, "unknown"
        checked = resolution
        if checked.input_modalities is None:
            resolver = self._model_resolver
            resolve_image = (
                None if resolver is None else getattr(resolver, "resolve_image_capability", None)
            )
            if resolve_image is None:
                return checked, "unknown"
            try:
                candidate = await resolve_image(thread_id, checked)
                if (
                    not isinstance(candidate, ThreadModelResolution)
                    or candidate.model != checked.model
                    or candidate.stickiness_epoch != checked.stickiness_epoch
                ):
                    raise ValueError("image capability lookup changed model identity")
                checked = candidate
            except Exception as exc:
                logger.warning(
                    "image capability unknown thread=%s model=%s reason=%s",
                    thread_id,
                    checked.model,
                    str(exc),
                )
                return resolution, "unknown"

            async with self._lock:
                state = self._live_state_locked(thread_id, active)
                if (
                    state is not None
                    and state.model_resolution is not None
                    and state.model_resolution.model == checked.model
                    and state.model_resolution.stickiness_epoch == checked.stickiness_epoch
                ):
                    state.model_resolution = checked

        if checked.input_modalities is None:
            return checked, "unknown"
        if "image" in checked.input_modalities:
            return checked, "supported"
        return checked, "unsupported"

    async def _refuse_image(
        self,
        thread_id: str,
        active: _ActiveRun,
        history: tuple[object, ...],
        resolution: ThreadModelResolution | None,
        *,
        reason: Literal["model_command", "remember_command", "unsupported", "unknown"],
    ) -> TurnOutcome:
        """Complete a durable, zero-usage refusal without entering any runner. [A-052]"""

        model = resolution.model if resolution is not None else "the unresolved model"
        if reason == "model_command":
            message = (
                "I did not change models or send the image. Send the `/model "
                "openrouter:provider/model` command alone, then resend the image."
            )
        elif reason == "remember_command":
            message = (
                "I did not store or send the image because `/remember` does not accept image "
                "memories yet. Send `/remember` with text alone, or resend the image as a normal "
                "prompt."
            )
        elif reason == "unsupported":
            message = (
                f"{model} does not accept image input, so I did not send this image. Switch to an "
                "image-capable OpenRouter model in Model or with `/model "
                "openrouter:provider/model`, then resend it."
            )
        else:
            message = (
                f"I could not verify image input for {model}, so I did not send this image. Switch "
                "to an image-capable OpenRouter model in Model or with `/model "
                "openrouter:provider/model`, then resend it."
            )

        emitter = _Emitter(self, thread_id, active)
        await emitter.event(
            {
                "event_kind": "image_refusal",
                "reason": reason,
                "model": model,
            }
        )
        await emitter.text(message)
        return TurnOutcome(
            StopReason.END_TURN,
            history,
            UsageSnapshot(),
            assistant_text=message,
            model_visible=False,
        )

    async def _finish(
        self,
        thread_id: str,
        active: _ActiveRun,
        outcome: TurnOutcome | None,
        stop_reason: StopReason,
    ) -> None:
        async with self._lock:
            state = self._threads[thread_id]
            if state.active is not active:
                return

            if active.state == "cancelling":
                stop_reason = StopReason.CANCELLED
            if outcome is not None:
                state.message_history = outcome.message_history
                if not outcome.model_visible:
                    active.turn.user_message["model_visible"] = outcome.model_visible
                if not self._usage_monotonic(active.usage, outcome.usage):
                    if stop_reason is not StopReason.CANCELLED:
                        stop_reason = StopReason.ERROR
                elif not active.usage_emitted or outcome.usage != active.usage:
                    active.usage = outcome.usage
                    await self._publish_usage_locked(thread_id, active)
                if (
                    stop_reason is StopReason.END_TURN
                    and active.turn.model_target is None
                    and remember_command_text(active.turn.prompt) is None
                    and outcome.model_visible
                ):
                    state.cached_prefix_tokens = outcome.cacheable_prefix_tokens

            if (
                stop_reason is StopReason.END_TURN
                and active.turn.model_target is not None
                and active.turn.image is None
            ):
                await self._commit_model_command_locked(thread_id, state, active)

            partial = stop_reason is not StopReason.END_TURN
            active.assistant_message["partial"] = partial
            active.turn.user_message["state"] = stop_reason.value
            self._capture_message(
                thread_id,
                active.turn.user_message,
                parent_id=active.turn.parent_id,
                advance_tail=False,
            )
            self._capture_message(
                thread_id,
                active.assistant_message,
                parent_id=active.turn.prompt_id,
                advance_tail=False,
            )

            if state.open_gate is not None:
                if active.gate_decision is not None and not active.gate_decision.done():
                    active.gate_decision.cancel()
                await self._publish_locked(
                    thread_id,
                    self._factory.create(
                        MessageType.GATE_DISMISS,
                        GateDismissPayload(run_id=active.turn.run_id),
                        thread_id=thread_id,
                    ),
                )
                state.open_gate = None
                active.gate_decision = None
                active.gate_committing = False

            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.RUN_DONE,
                    RunDonePayload(
                        run_id=active.turn.run_id,
                        stop_reason=stop_reason,
                        partial=partial,
                        provider_error=(None if outcome is None else outcome.provider_error),
                    ),
                    thread_id=thread_id,
                ),
            )
            state.active = None

            if not self._closing and self._capture_failure is None and state.queued:
                await self._start_locked(thread_id, state, state.queued.popleft())

    async def _resolve_model_command(
        self,
        *,
        thread_id: str,
        active: _ActiveRun,
        history: tuple[object, ...],
    ) -> TurnOutcome:
        """Resolve one direct command after its FIFO position is acknowledged."""

        target = active.turn.model_target
        assert target is not None
        if not target:
            active.model_error = "Model unchanged: add an OpenRouter model string after /model."
        elif self._model_resolver is None:
            active.model_error = "Model unchanged: broker model switching is unavailable."
        else:
            try:
                active.model_candidate = await self._model_resolver.resolve_named(
                    thread_id,
                    target,
                )
            except NamedModelResolutionError as exc:
                active.model_error = f"Model unchanged: {exc}."
            except ModelCatalogUnavailable:
                active.model_error = "Model unchanged: the OpenRouter model catalog is unavailable."
        return TurnOutcome(StopReason.END_TURN, history, UsageSnapshot())

    async def _commit_model_command_locked(
        self,
        thread_id: str,
        state: _ThreadState,
        active: _ActiveRun,
    ) -> None:
        """Atomically journal and publish a resolved command before run.done."""

        event: dict[str, object] | None = None
        message = active.model_error
        candidate = active.model_candidate
        previous = state.model_resolution
        if message is None and (candidate is None or previous is None):
            message = "Model unchanged: broker model switching is unavailable."
        elif message is None and candidate is not None and previous is not None:
            changed_at = self._clock()
            if changed_at.tzinfo is None:
                raise ValueError("model-change clock must return an aware datetime")
            resolution = replace(
                candidate,
                stickiness_epoch=previous.stickiness_epoch + 1,
                request_parameters=previous.request_parameters,
            )
            event = {
                "event_kind": "model_change",
                "old_model": previous.model,
                "new_model": resolution.model,
                "reason": "human_command",
                "timestamp": changed_at.isoformat(),
                "stickiness_epoch": resolution.stickiness_epoch,
                "sacrificed_cached_prefix_tokens": state.cached_prefix_tokens,
                "context_tokens": resolution.context_tokens,
            }
            state.model_resolution = resolution
            state.resolved_model = resolution.model
            state.cached_prefix_tokens = 0
            self._ensure_parameter_thread_locked(thread_id, previous)
            await self._record_parameter_change_locked(
                thread_id=thread_id,
                parameter_id="model.slug",
                old_value=previous.model,
                new_value=resolution.model,
                changed_at=changed_at,
            )
            logger.info(
                "model_change thread=%s old_model=%s new_model=%s reason=%s "
                "timestamp=%s stickiness_epoch=%s sacrificed_cached_prefix_tokens=%s "
                "context_tokens=%s",
                thread_id,
                event["old_model"],
                event["new_model"],
                event["reason"],
                event["timestamp"],
                event["stickiness_epoch"],
                event["sacrificed_cached_prefix_tokens"],
                event["context_tokens"],
            )
            if previous.model == resolution.model:
                message = (
                    f"Model re-resolved to {resolution.model} in a new stickiness epoch. "
                    f"Context window: {resolution.context_tokens} tokens."
                )
            else:
                message = (
                    f"Model changed from {previous.model} to {resolution.model}. "
                    f"Context window: {resolution.context_tokens} tokens."
                )

        assert message is not None
        if event is not None:
            active.assistant_message["events"].append(deepcopy(event))
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.RUN_DELTA,
                    RunDeltaEventPayload(
                        run_id=active.turn.run_id,
                        kind="event",
                        event=event,
                        resolved_model=state.resolved_model,
                    ),
                    thread_id=thread_id,
                ),
            )
        active.assistant_message["content"] += message
        await self._publish_locked(
            thread_id,
            self._factory.create(
                MessageType.RUN_DELTA,
                RunDeltaTextPayload(
                    run_id=active.turn.run_id,
                    kind="text",
                    text=message,
                ),
                thread_id=thread_id,
            ),
        )

    def _aware_clock(self) -> datetime:
        instant = self._clock()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("parameter clock must return an aware datetime")
        return instant

    def _ensure_parameter_thread_locked(
        self,
        thread_id: str,
        resolution: ThreadModelResolution,
    ) -> None:
        self._parameter_registry.ensure_thread(
            thread_id,
            self._parameter_values(resolution),
        )

    @staticmethod
    def _parameter_values(resolution: ThreadModelResolution) -> dict[str, ParameterValue]:
        parameters = resolution.request_parameters
        return {
            "model.slug": resolution.model,
            "model.temperature": parameters.temperature,
            "model.top_p": parameters.top_p,
            "model.top_k": parameters.top_k,
            "model.max_tokens": parameters.max_tokens,
            "model.effort": parameters.effort,
        }

    @classmethod
    def _parameter_value(
        cls,
        resolution: ThreadModelResolution,
        parameter_id: str,
    ) -> ParameterValue:
        return cls._parameter_values(resolution)[parameter_id]

    @staticmethod
    def _with_parameter(
        resolution: ThreadModelResolution,
        parameter_id: str,
        value: ParameterValue,
    ) -> ThreadModelResolution:
        attribute = parameter_id.removeprefix("model.")
        if attribute == "slug":
            raise ValueError("model.slug must use resolve_named")
        parameters = replace(
            resolution.request_parameters,
            **{attribute: value},
        )
        assert isinstance(parameters, ModelRequestParameters)
        return replace(resolution, request_parameters=parameters)

    async def _record_parameter_change_locked(
        self,
        *,
        thread_id: str,
        parameter_id: str,
        old_value: ParameterValue,
        new_value: ParameterValue,
        changed_at: datetime,
    ) -> None:
        change = ParameterChange(
            event_id=self._factory.new_id(),
            parameter_id=parameter_id,
            thread_id=thread_id,
            timestamp=changed_at,
            old_value=old_value,
            new_value=new_value,
        )
        self._parameter_registry.record(change)
        payload = {
            "event_kind": "parameter_change",
            **change.model_dump(mode="json"),
        }
        await self._publish_locked(
            thread_id,
            self._factory.create("parameter.change", payload, thread_id=thread_id),
        )

    async def _publish_parameter_refusal(
        self,
        *,
        thread_id: str,
        module_id: str,
        parameter_id: str,
        reason: str,
    ) -> None:
        async with self._lock:
            self._state_for_locked(thread_id)
            await self._publish_parameter_refusal_locked(
                thread_id=thread_id,
                module_id=module_id,
                parameter_id=parameter_id,
                reason=reason,
            )

    async def _publish_parameter_refusal_locked(
        self,
        *,
        thread_id: str,
        module_id: str,
        parameter_id: str,
        reason: str,
    ) -> None:
        payload = {
            "event_kind": "parameter_refused",
            "event_id": self._factory.new_id(),
            "module_id": module_id,
            "parameter_id": parameter_id,
            "thread_id": thread_id,
            "timestamp": self._aware_clock().isoformat(),
            "reason": reason,
        }
        await self._publish_locked(
            thread_id,
            self._factory.create("parameter.refused", payload, thread_id=thread_id),
        )

    async def _publish_model_change_locked(
        self,
        *,
        thread_id: str,
        state: _ThreadState,
        previous: ThreadModelResolution,
        resolution: ThreadModelResolution,
        changed_at: datetime,
        reason: str,
        sacrificed_cached_prefix_tokens: int,
    ) -> None:
        event = {
            "event_kind": "model_change",
            "old_model": previous.model,
            "new_model": resolution.model,
            "reason": reason,
            "timestamp": changed_at.isoformat(),
            "stickiness_epoch": resolution.stickiness_epoch,
            "sacrificed_cached_prefix_tokens": sacrificed_cached_prefix_tokens,
            "context_tokens": resolution.context_tokens,
        }
        await self._publish_locked(
            thread_id,
            self._factory.create("model.change", event, thread_id=thread_id),
        )
        logger.info(
            "model_change thread=%s old_model=%s new_model=%s reason=%s "
            "timestamp=%s stickiness_epoch=%s sacrificed_cached_prefix_tokens=%s "
            "context_tokens=%s",
            thread_id,
            previous.model,
            resolution.model,
            reason,
            changed_at.isoformat(),
            resolution.stickiness_epoch,
            sacrificed_cached_prefix_tokens,
            resolution.context_tokens,
        )

    async def _emit_text(
        self,
        thread_id: str,
        active: _ActiveRun,
        value: str,
    ) -> None:
        if not isinstance(value, str):
            raise TypeError("text delta must be a string")
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                return
            active.assistant_message["content"] += value
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.RUN_DELTA,
                    RunDeltaTextPayload(run_id=active.turn.run_id, kind="text", text=value),
                    thread_id=thread_id,
                ),
            )

    async def _emit_thinking(
        self,
        thread_id: str,
        active: _ActiveRun,
        value: str,
    ) -> None:
        if not isinstance(value, str):
            raise TypeError("thinking delta must be a string")
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                return
            active.assistant_message["thinking"] += value
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.RUN_DELTA,
                    RunDeltaThinkingPayload(
                        run_id=active.turn.run_id,
                        kind="thinking",
                        text=value,
                    ),
                    thread_id=thread_id,
                ),
            )

    async def _emit_event(
        self,
        thread_id: str,
        active: _ActiveRun,
        value: Mapping[str, object],
    ) -> None:
        event = dict(value)
        delta = RunDeltaEventPayload(
            run_id=active.turn.run_id,
            kind="event",
            event=event,
        )
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                return
            active.assistant_message["events"].append(deepcopy(event))
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.RUN_DELTA,
                    delta,
                    thread_id=thread_id,
                ),
            )

    async def _emit_usage(
        self,
        thread_id: str,
        active: _ActiveRun,
        value: UsageSnapshot,
    ) -> None:
        if not isinstance(value, UsageSnapshot):
            raise TypeError("usage update must be a UsageSnapshot")
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                return
            if not self._usage_monotonic(active.usage, value):
                raise ValueError("cumulative usage must not decrease")
            active.usage = value
            await self._publish_usage_locked(thread_id, active)

    async def _publish_usage_locked(self, thread_id: str, active: _ActiveRun) -> None:
        active.usage_emitted = True
        await self._publish_locked(
            thread_id,
            self._factory.create(
                MessageType.RUN_USAGE,
                RunUsagePayload(run_id=active.turn.run_id, **self._usage_dict(active.usage)),
                thread_id=thread_id,
            ),
        )

    async def _emit_gate(
        self,
        thread_id: str,
        active: _ActiveRun,
        value: Mapping[str, object],
    ) -> GateCommitPayload:
        raw = {**dict(value), "run_id": active.turn.run_id, "kind": "memory_gate"}
        payload = GateOpenPayload.model_validate(raw)
        decision = asyncio.get_running_loop().create_future()
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                raise RuntimeError("cannot open a gate for an inactive run")
            replacing_resolved_stage = (
                state.open_gate is not None
                and active.gate_decision is not None
                and active.gate_decision.done()
                and active.gate_committing
                and payload.stage == "wrong_resolution"
                and state.open_gate.injection_id == payload.injection_id
            )
            if state.open_gate is not None or active.gate_decision is not None:
                if not replacing_resolved_stage:
                    raise RuntimeError("run already has an unresolved gate")
            active.state = "waiting_gate"
            active.gate_decision = decision
            active.gate_committing = False
            state.open_gate = payload
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.GATE_OPEN,
                    payload,
                    thread_id=thread_id,
                ),
            )
        return await decision

    async def _dismiss_gate(self, thread_id: str, active: _ActiveRun) -> None:
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                raise RuntimeError("cannot dismiss a gate for an inactive run")
            if state.open_gate is None or active.gate_decision is None:
                raise RuntimeError("run has no open gate")
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.GATE_DISMISS,
                    GateDismissPayload(run_id=active.turn.run_id),
                    thread_id=thread_id,
                ),
            )
            state.open_gate = None
            active.gate_decision = None
            active.gate_committing = False
            active.state = "running"

    async def _emit_error(
        self,
        thread_id: str,
        active: _ActiveRun,
        value: Mapping[str, object],
    ) -> None:
        raw = {**dict(value), "run_id": active.turn.run_id}
        async with self._lock:
            state = self._live_state_locked(thread_id, active)
            if state is None:
                return
            await self._publish_locked(
                thread_id,
                self._factory.create(
                    MessageType.ERROR,
                    raw,
                    thread_id=thread_id,
                ),
            )

    @staticmethod
    def _valid_gate_membership(
        gate: GateOpenPayload,
        decision: GateCommitPayload,
    ) -> bool:
        if gate.stage == "wrong_resolution":
            if decision.removed or decision.added_back or decision.wrong_resolution is None:
                return False
            current = gate.wrong_removed[0]
            resolution = decision.wrong_resolution
            return (
                resolution.memory_id == current.memory_id
                and resolution.expected_revision == current.revision
            )

        if decision.wrong_resolution is not None:
            return False
        removed = [item.memory_id for item in decision.removed]
        added_back = list(decision.added_back)
        if len(set(removed)) != len(removed) or len(set(added_back)) != len(added_back):
            return False
        if set(removed).intersection(added_back):
            return False
        injected = {card.memory_id for card in gate.injected}
        near_misses = {card.memory_id for card in gate.near_misses}
        if not set(added_back).issubset(near_misses):
            return False
        return all(
            item.memory_id in injected
            or (item.memory_id in near_misses and item.reason.value == "never")
            for item in decision.removed
        )

    def _live_state_locked(
        self,
        thread_id: str,
        active: _ActiveRun,
    ) -> _ThreadState | None:
        state = self._threads.get(thread_id)
        if state is None or state.active is not active or active.state == "cancelling":
            return None
        return state

    def _snapshot_envelope(
        self,
        thread_id: str,
        state: _ThreadState,
        *,
        request_id: str | None = None,
    ) -> Envelope:
        active_snapshot: ActiveRunSnapshot | None = None
        if state.active is not None:
            active = state.active
            active_snapshot = ActiveRunSnapshot(
                run_id=active.turn.run_id,
                prompt_id=active.turn.prompt_id,
                state=active.state,
                usage=UsagePayload(**self._usage_dict(active.usage)),
                queued=[
                    QueuedPromptSnapshot(
                        run_id=turn.run_id,
                        prompt_id=turn.prompt_id,
                        prompt=turn.prompt,
                        image=turn.image_view,
                    )
                    for turn in state.queued
                ],
            )
        return self._factory.create(
            MessageType.THREAD_SNAPSHOT,
            ThreadSnapshotResponsePayload(
                messages=deepcopy(state.messages),
                open_gate=state.open_gate,
                active_run=active_snapshot,
                project_key=state.project_key,
                project_label=state.project_label,
                workspace_root=state.workspace_root,
                current_location=state.current_location,
                request_id=request_id,
                resolved_model=state.resolved_model,
            ),
            thread_id=thread_id,
        )

    async def _publish_locked(self, thread_id: str, envelope: Envelope) -> None:
        self._capture_event(thread_id, envelope)
        for subscription in tuple(self._subscriptions):
            if subscription.thread_id != thread_id:
                continue
            self._enqueue_locked(subscription, envelope)
        # Let fast delivery workers drain without creating a false overflow
        # during a synchronous burst from one model callback.
        await asyncio.sleep(0)

    async def _send_direct_locked(
        self,
        sink: EnvelopeSink,
        envelope: Envelope,
        *,
        confirm: bool = False,
    ) -> asyncio.Future[None] | None:
        if envelope.thread_id is not None:
            self._capture_event(envelope.thread_id, envelope)
        subscription = self._find_sink_locked(sink)
        if subscription is None:
            # Own even a one-off delivery so detach/close can always stop its
            # worker. Keep it unbound: a direct error must not silently
            # resubscribe a sink that was detached after backpressure.
            subscription = _Subscription(sink=sink, thread_id=None)
            self._subscriptions.append(subscription)
        return self._enqueue_locked(subscription, envelope, confirm=confirm)

    def _enqueue_locked(
        self,
        subscription: _Subscription,
        envelope: Envelope,
        *,
        confirm: bool = False,
    ) -> asyncio.Future[None] | None:
        if subscription.failed:
            if confirm:
                raise ConnectionError("envelope subscription is unavailable")
            return None
        receipt = asyncio.get_running_loop().create_future() if confirm else None
        try:
            subscription.queue.put_nowait((envelope, receipt))
        except asyncio.QueueFull:
            subscription.failed = True
            if subscription.worker is not None:
                subscription.worker.cancel()
            self._subscriptions = [
                candidate for candidate in self._subscriptions if candidate is not subscription
            ]
            if subscription.on_overflow is not None:
                try:
                    subscription.on_overflow()
                except Exception:
                    # Overflow notification is a connection-lifecycle signal;
                    # a faulty observer must not interrupt the authoritative run.
                    pass
            if confirm:
                raise ConnectionError("envelope subscription exceeded its buffer") from None
            return None
        if subscription.worker is None:
            subscription.worker = asyncio.create_task(
                self._deliver_subscription(subscription),
                name="harness-envelope-delivery",
            )
        return receipt

    async def _deliver_subscription(self, subscription: _Subscription) -> None:
        try:
            while True:
                envelope, receipt = await subscription.queue.get()
                try:
                    await subscription.sink(envelope)
                except asyncio.CancelledError:
                    if receipt is not None and not receipt.done():
                        receipt.set_exception(ConnectionError("envelope delivery stopped"))
                    raise
                except Exception as exc:
                    subscription.failed = True
                    if receipt is not None and not receipt.done():
                        receipt.set_exception(exc)
                    return
                else:
                    if receipt is not None and not receipt.done():
                        receipt.set_result(None)
                finally:
                    subscription.queue.task_done()
        finally:
            while not subscription.queue.empty():
                _, receipt = subscription.queue.get_nowait()
                if receipt is not None and not receipt.done():
                    receipt.set_exception(ConnectionError("envelope delivery stopped"))
                subscription.queue.task_done()

    def _bind_sink_locked(self, sink: EnvelopeSink, thread_id: str) -> None:
        subscription = self._find_sink_locked(sink)
        if subscription is not None and not subscription.failed:
            subscription.thread_id = thread_id
            return
        if subscription is not None:
            self._remove_sink_locked(sink)
        self._subscriptions.append(_Subscription(sink=sink, thread_id=thread_id))

    def _remove_sink_locked(self, sink: EnvelopeSink) -> None:
        for subscription in self._subscriptions:
            if subscription.sink is sink and subscription.worker is not None:
                subscription.worker.cancel()
        self._subscriptions = [
            subscription for subscription in self._subscriptions if subscription.sink is not sink
        ]

    def _find_sink_locked(self, sink: EnvelopeSink) -> _Subscription | None:
        return next(
            (subscription for subscription in self._subscriptions if subscription.sink is sink),
            None,
        )

    def _require_open(self) -> None:
        if self._capture_failure is not None:
            raise RuntimeError("run loop is unavailable after transcript capture failure") from (
                self._capture_failure
            )
        if self._closing:
            raise RuntimeError("run loop is closed")

    def _state_for_locked(self, thread_id: str) -> _ThreadState:
        state = self._threads.get(thread_id)
        if state is None:
            state = _ThreadState(resolved_model=self._initial_resolved_model)
            self._threads[thread_id] = state
        return state

    @staticmethod
    def _open_symphony_draft_ids(messages: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
        """Recover open deliberations from durable events without making them model history."""

        opened: list[str] = []
        completed: set[str] = set()
        for message in messages:
            events = message.get("events")
            if not isinstance(events, list):
                continue
            for event in events:
                if not isinstance(event, dict):
                    continue
                if event.get("event_kind") == "symphony_deliberation":
                    draft_id = event.get("draft_id")
                    if isinstance(draft_id, str):
                        opened.append(draft_id)
                elif event.get("event_kind") == "symphony_result":
                    launch = event.get("launch")
                    if isinstance(launch, dict) and isinstance(launch.get("draft_id"), str):
                        completed.add(launch["draft_id"])
        return tuple(draft_id for draft_id in opened if draft_id not in completed)

    @staticmethod
    def _symphony_stack_events(
        messages: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, object], ...]:
        """Recover the latest durable snapshot for each stack after a daemon restart."""

        latest: dict[str, Mapping[str, object]] = {}
        for message in messages:
            events = message.get("events")
            if not isinstance(events, list):
                continue
            for event in events:
                if not isinstance(event, dict) or event.get("event_kind") not in {
                    "symphony_state",
                    "symphony_result",
                }:
                    continue
                symphony_id = event.get("symphony_id")
                if isinstance(symphony_id, str):
                    latest[symphony_id] = event
        return tuple(latest.values())

    def _bind_project_locked(
        self,
        thread_id: str,
        state: _ThreadState,
        project_key: str,
    ) -> None:
        if state.project_key == project_key:
            return
        if (
            state.project_key is not None
            or state.messages
            or state.active is not None
            or state.queued
            or self._pending_captured.get(thread_id)
        ):
            raise ProjectBindingConflict(project_key, state.project_key)
        if self._transcript_journal is not None:
            self._transcript_journal.append_thread_context(thread_id, project_key)
        state.project_key = project_key

    def _bind_workspace_locked(
        self,
        thread_id: str,
        state: _ThreadState,
        *,
        workspace_root: str,
        project_label: str | None,
    ) -> None:
        root = Path(workspace_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("thread workspace must be an existing directory")
        canonical = str(root)
        label = (project_label or root.name).strip()
        if not label:
            raise ValueError("project label must not be blank")
        if state.workspace_root is not None:
            if state.workspace_root != canonical:
                raise ProjectBindingConflict(canonical, state.project_key)
            if project_label is not None and label != state.project_label:
                if self._transcript_journal is not None:
                    self._transcript_journal.append_thread_context(
                        thread_id,
                        canonical,
                        project_label=label,
                        workspace_root=canonical,
                        current_location=state.current_location,
                    )
                state.project_label = label
            return
        if state.project_key is not None and state.project_key.startswith("/"):
            raise ProjectBindingConflict(canonical, state.project_key)
        if self._transcript_journal is not None:
            self._transcript_journal.append_thread_context(
                thread_id,
                canonical,
                project_label=label,
                workspace_root=canonical,
                current_location=canonical,
            )
        state.project_key = canonical
        state.project_label = label
        state.workspace_root = canonical
        state.current_location = canonical

    def _hydrate_threads(
        self,
        journal: TranscriptJournal | None,
    ) -> dict[str, _ThreadState]:
        if journal is None:
            return {}
        return {
            transcript.thread_id: _ThreadState(
                messages=[deepcopy(message) for message in transcript.messages],
                message_history=self._rehydrate_model_history(transcript),
                resolved_model=transcript.resolved_model or self._initial_resolved_model,
                project_key=transcript.project_key,
                project_label=transcript.project_label,
                workspace_root=transcript.workspace_root,
                current_location=transcript.current_location,
            )
            for transcript in journal.hydrate_threads()
        }

    @staticmethod
    def _rehydrate_model_history(transcript: HydratedTranscript) -> tuple[object, ...]:
        history: list[object] = []
        messages = transcript.messages
        for index in range(0, len(messages) - 1, 2):
            user = messages[index]
            assistant = messages[index + 1]
            prompt = user.get("content")
            answer = assistant.get("content")
            if (
                user.get("role") != "user"
                or assistant.get("role") != "assistant"
                or user.get("state") != StopReason.END_TURN.value
                or assistant.get("partial") is not False
                or user.get("model_visible") is False
                or not isinstance(prompt, str)
                or not isinstance(answer, str)
                or model_command_text(prompt) is not None
                or remember_command_text(prompt) is not None
            ):
                continue
            user_content: str | list[UserContent] = prompt
            if "image" in user:
                prompt_id = user.get("message_id")
                if not isinstance(prompt_id, str):  # pragma: no cover - journal validation
                    continue
                attachment = transcript.attachments.get(prompt_id)
                if attachment is None:  # pragma: no cover - journal validation
                    continue
                user_content = [
                    prompt,
                    BinaryContent(
                        data=attachment.data,
                        media_type=attachment.view.media_type,
                    ),
                ]
            history.extend(
                (
                    ModelRequest([UserPromptPart(user_content)]),
                    ModelResponse([TextPart(answer)]),
                )
            )
        return tuple(history)

    def _discard_pending_capture_locked(self, thread_id: str, turn: _Turn) -> None:
        pending = self._pending_captured.get(thread_id)
        if pending is None:
            return
        try:
            pending.remove(turn)
        except ValueError:
            return
        if not pending:
            del self._pending_captured[thread_id]

    @staticmethod
    def _parent_for_new_turn_locked(state: _ThreadState) -> str | None:
        if state.queued:
            return state.queued[-1].prompt_id
        if state.active is not None:
            return state.active.turn.run_id
        if not state.messages:
            return None
        parent_id = state.messages[-1].get("message_id")
        if not isinstance(parent_id, str) or not parent_id:
            raise RuntimeError("thread transcript message is missing its message_id")
        return parent_id

    def _captured_parent_id(self, thread_id: str) -> str | None:
        assert self._transcript_journal is not None
        try:
            return self._transcript_journal.next_parent_id(thread_id)
        except Exception as exc:
            self._fail_capture(exc)

    def _capture_message(
        self,
        thread_id: str,
        message: Mapping[str, Any],
        *,
        parent_id: str | None,
        advance_tail: bool = True,
    ) -> None:
        if self._transcript_journal is not None:
            if self._capture_failure is not None:
                self._fail_capture(self._capture_failure)
            try:
                self._transcript_journal.append_message(
                    thread_id,
                    message,
                    parent_id=parent_id,
                    advance_tail=advance_tail,
                )
            except Exception as exc:
                self._fail_capture(exc)

    def _capture_image_attachment(
        self,
        thread_id: str,
        prompt_id: str,
        image: ImageInput,
    ) -> ImageView:
        assert self._transcript_journal is not None
        if self._capture_failure is not None:
            self._fail_capture(self._capture_failure)
        try:
            return self._transcript_journal.append_image_attachment(thread_id, prompt_id, image)
        except Exception as exc:
            self._fail_capture(exc)

    def _capture_event(self, thread_id: str, envelope: Envelope) -> None:
        if self._transcript_journal is not None:
            if self._capture_failure is not None:
                self._fail_capture(self._capture_failure)
            try:
                self._transcript_journal.append_event(thread_id, envelope)
            except Exception as exc:
                self._fail_capture(exc)

    def _fail_capture(self, exc: Exception) -> None:
        if self._capture_failure is None:
            self._capture_failure = exc
            logger.critical("transcript capture failed; run loop is now unavailable", exc_info=exc)
        raise RuntimeError("transcript capture failed; run loop is now unavailable") from exc

    async def _resolution_for_thread(
        self,
        thread_id: str,
    ) -> ThreadModelResolution | None:
        hydrated_model: str | None = None
        async with self._lock:
            state = self._threads.get(thread_id)
            if state is not None and state.model_resolution is not None:
                return state.model_resolution
            if state is not None:
                hydrated_model = state.resolved_model
        if self._model_resolver is None:
            return None
        if hydrated_model is not None:
            resolve_hydrated = getattr(self._model_resolver, "resolve_hydrated", None)
            try:
                if resolve_hydrated is not None:
                    return await resolve_hydrated(thread_id, hydrated_model)
                return await self._model_resolver.resolve_named(thread_id, hydrated_model)
            except (ModelCatalogUnavailable, NamedModelResolutionError):
                fallback = await self._model_resolver.resolve(thread_id)
                return ThreadModelResolution(
                    model=hydrated_model,
                    context_tokens=fallback.context_tokens,
                    policy="hydrated_unverified",
                    request_parameters=fallback.request_parameters,
                )
        return await self._model_resolver.resolve(thread_id)

    @staticmethod
    def _require_thread_id(thread_id: str) -> None:
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id must not be blank")

    @staticmethod
    def _usage_monotonic(previous: UsageSnapshot, current: UsageSnapshot) -> bool:
        return (
            current.requests >= previous.requests
            and current.input_tokens >= previous.input_tokens
            and current.output_tokens >= previous.output_tokens
            and current.cache_read_tokens >= previous.cache_read_tokens
            and current.cache_write_tokens >= previous.cache_write_tokens
        )

    @staticmethod
    def _usage_dict(value: UsageSnapshot) -> dict[str, int]:
        return {
            "requests": value.requests,
            "input_tokens": value.input_tokens,
            "output_tokens": value.output_tokens,
            "cache_read_tokens": value.cache_read_tokens,
            "cache_write_tokens": value.cache_write_tokens,
        }
