"""Process-scoped scheduling and lifecycle control for C.7 model runs."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from harness.envelope import (
    ActiveRunSnapshot,
    Envelope,
    EnvelopeFactory,
    GateCommitPayload,
    GateDismissPayload,
    GateOpenPayload,
    MessageType,
    PromptQueuedPayload,
    QueuedPromptSnapshot,
    RunDeltaEventPayload,
    RunDeltaTextPayload,
    RunDeltaThinkingPayload,
    RunDonePayload,
    RunStartedPayload,
    RunUsagePayload,
    StopReason,
    ThreadSnapshotResponsePayload,
    UsagePayload,
)
from harness.model_policy import (
    ThreadModelResolution,
    ThreadModelResolver,
)
from harness.run_protocol import RunEmitter, TurnOutcome, TurnRunner, UsageSnapshot

type EnvelopeSink = Callable[[Envelope], Awaitable[None]]

_SUBSCRIPTION_BUFFER_SIZE = 256
type _Delivery = tuple[Envelope, asyncio.Future[None] | None]


@dataclass(slots=True)
class _Turn:
    run_id: str
    prompt_id: str
    prompt: str
    user_message: dict[str, Any]


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


@dataclass(slots=True)
class _ThreadState:
    messages: list[dict[str, Any]] = field(default_factory=list)
    message_history: tuple[object, ...] = ()
    active: _ActiveRun | None = None
    queued: deque[_Turn] = field(default_factory=deque)
    open_gate: GateOpenPayload | None = None
    resolved_model: str | None = None
    model_resolution: ThreadModelResolution | None = None


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
        self._lock = asyncio.Lock()
        self._threads: dict[str, _ThreadState] = {}
        self._subscriptions: list[_Subscription] = []
        self._selected_thread_id: str | None = None
        self._terminal_tasks: set[asyncio.Task[None]] = set()
        self._closing = False

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

    async def request_snapshot(self, thread_id: str, sink: EnvelopeSink) -> None:
        """Select a thread and atomically send its one authoritative snapshot."""

        self._require_thread_id(thread_id)
        receipt: asyncio.Future[None]
        async with self._lock:
            self._require_open()
            state = self._state_for_locked(thread_id)
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
                self._snapshot_envelope(thread_id, state),
                confirm=True,
            )
            assert pending is not None
            receipt = pending
        await receipt

    async def detach(self, sink: EnvelopeSink) -> None:
        """Detach a connection without changing daemon-lifetime thread state."""

        async with self._lock:
            self._remove_sink_locked(sink)

    async def submit(
        self,
        *,
        thread_id: str,
        prompt_id: str,
        prompt: str,
        sink: EnvelopeSink | None = None,
    ) -> str:
        """Accept a prompt, starting it now or reserving one FIFO run ID."""

        self._require_thread_id(thread_id)
        if not prompt.strip():
            raise ValueError("prompt must not be blank")

        async with self._lock:
            self._require_open()
        run_id = self._run_id_factory()
        # Validate both correlation IDs before mutating process state.
        RunStartedPayload(run_id=run_id, prompt_id=prompt_id)
        model_resolution = await self._resolution_for_thread(thread_id)
        user_message: dict[str, Any] = {
            "message_id": prompt_id,
            "run_id": run_id,
            "role": "user",
            "content": prompt,
            "state": "queued",
        }
        turn = _Turn(
            run_id=run_id,
            prompt_id=prompt_id,
            prompt=prompt,
            user_message=user_message,
        )

        async with self._lock:
            self._require_open()
            state = self._state_for_locked(thread_id)
            if state.model_resolution is None:
                state.model_resolution = model_resolution
                if model_resolution is not None:
                    state.resolved_model = model_resolution.model
            elif model_resolution is not None and state.model_resolution != model_resolution:
                raise RuntimeError("thread model resolution changed after its first run")
            self._selected_thread_id = thread_id
            if sink is not None:
                self._bind_sink_locked(sink, thread_id)
            state.messages.append(user_message)
            if state.active is None:
                await self._start_locked(thread_id, state, turn)
            else:
                state.queued.append(turn)
                await self._publish_locked(
                    thread_id,
                    self._factory.create(
                        MessageType.PROMPT_QUEUED,
                        PromptQueuedPayload(run_id=run_id, prompt_id=prompt_id),
                        thread_id=thread_id,
                    ),
                )
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
                if not self._usage_monotonic(active.usage, outcome.usage):
                    if stop_reason is not StopReason.CANCELLED:
                        stop_reason = StopReason.ERROR
                elif not active.usage_emitted or outcome.usage != active.usage:
                    active.usage = outcome.usage
                    await self._publish_usage_locked(thread_id, active)

            partial = stop_reason is not StopReason.END_TURN
            active.assistant_message["partial"] = partial
            active.turn.user_message["state"] = stop_reason.value

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
                    ),
                    thread_id=thread_id,
                ),
            )
            state.active = None

            if not self._closing and state.queued:
                await self._start_locked(thread_id, state, state.queued.popleft())

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

    def _snapshot_envelope(self, thread_id: str, state: _ThreadState) -> Envelope:
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
                resolved_model=state.resolved_model,
            ),
            thread_id=thread_id,
        )

    async def _publish_locked(self, thread_id: str, envelope: Envelope) -> None:
        for subscription in tuple(self._subscriptions):
            if subscription.thread_id != thread_id:
                continue
            self._enqueue_locked(subscription, envelope)
        # Let fast delivery workers drain without creating a false overflow
        # during a synchronous burst from one model callback.
        await asyncio.sleep(0)

    async def _send_direct_locked(self, sink: EnvelopeSink, envelope: Envelope) -> None:
        subscription = self._find_sink_locked(sink)
        if subscription is None:
            # Own even a one-off delivery so detach/close can always stop its
            # worker. Keep it unbound: a direct error must not silently
            # resubscribe a sink that was detached after backpressure.
            subscription = _Subscription(sink=sink, thread_id=None)
            self._subscriptions.append(subscription)
        self._enqueue_locked(subscription, envelope)

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
        if self._closing:
            raise RuntimeError("run loop is closed")

    def _state_for_locked(self, thread_id: str) -> _ThreadState:
        state = self._threads.get(thread_id)
        if state is None:
            state = _ThreadState(resolved_model=self._initial_resolved_model)
            self._threads[thread_id] = state
        return state

    async def _resolution_for_thread(
        self,
        thread_id: str,
    ) -> ThreadModelResolution | None:
        async with self._lock:
            state = self._threads.get(thread_id)
            if state is not None and state.model_resolution is not None:
                return state.model_resolution
        if self._model_resolver is None:
            return None
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
