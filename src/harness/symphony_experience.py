"""In-conversation Symphony deliberation and a truthful toy-stack proof path."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from harness.conductor import JudgeCharter, SearchBudget
from harness.envelope import (
    StopReason,
    SymphonyCancelAttemptPayload,
    SymphonyCharterForkPayload,
    SymphonyClarificationPayload,
    SymphonyCompletePayload,
    SymphonyInterventionPayload,
    SymphonyLaunchPayload,
)
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot

_TRIGGER = re.compile(r"^take this to a symphony[.!]?\s*$", re.IGNORECASE)


class SymphonyAttemptRecord(BaseModel):
    """One toy attempt, including cooperative cancellation evidence. [G20]"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    attempt_id: str
    state: Literal["running", "cancelled", "completed"]
    cancellation: Literal["none", "requested", "draining", "cancelled"] = "none"
    follow_ups: tuple[str, ...] = ()
    partial_evidence: tuple[str, ...] = ("bounded toy attempt admitted",)
    memories_admitted: Literal[False] = False


class SymphonyInterventionRecord(BaseModel):
    """Auditable owner-to-conductor steering inside one lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: Literal["clarification", "cancel_attempt", "charter_change"]
    attempt_id: str | None = None
    instruction: str | None = None
    requested_at: datetime
    charter_digests: tuple[str, ...]
    transitions: tuple[str, ...] = ()


class SymphonyStackRecord(BaseModel):
    """A durable proof stack; a charter change creates a new record, never a rewrite."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    symphony_id: str
    thread_id: str
    state: Literal["running", "blocked", "completed"]
    execution_kind: Literal["toy"]
    launch: SymphonyLaunchPayload
    search_step_ids: tuple[str, ...]
    charter_digests: tuple[str, ...]
    timeline: tuple[str, ...]
    attempts: tuple[SymphonyAttemptRecord, ...]
    interventions: tuple[SymphonyInterventionRecord, ...] = ()
    forked_from: str | None = None
    forked_to: str | None = None
    blocked_reason: str | None = None
    result: str | None = None
    completed_at: datetime | None = None


class SymphonyExperience:
    """Join an ordinary chat turn to one ratified, independently identified stack."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._id_factory = id_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._draft_threads: dict[str, str] = {}
        self._stacks: dict[str, SymphonyStackRecord] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def is_trigger(prompt: str) -> bool:
        """Recognize the explicit owner phrase without stealing ordinary conversation."""

        return _TRIGGER.fullmatch(prompt.strip()) is not None

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        launch: SymphonyLaunchPayload | None,
        intervention: SymphonyInterventionPayload | None = None,
        message_history: Sequence[object],
        emit: RunEmitter,
        accepted_draft_ids: Sequence[str] = (),
        accepted_stack_events: Sequence[Mapping[str, object]] = (),
    ) -> TurnOutcome:
        """Open, launch, or steer a stack through the ordinary thread journal."""

        async with self._lock:
            self._hydrate(accepted_stack_events)

        if intervention is not None:
            return await self._intervene(
                thread_id=thread_id,
                intervention=intervention,
                message_history=message_history,
                emit=emit,
            )

        if launch is None:
            if not self.is_trigger(prompt):
                raise ValueError("a Symphony turn requires the explicit trigger or launch artifact")
            draft_id = self._id_factory()
            async with self._lock:
                self._draft_threads[draft_id] = thread_id
            await emit.event(self._draft_event(draft_id))
            text = (
                "Let’s fix the recipe, search marks, judge charters, metrics, and real authority "
                "walls here before anything launches. I have left every acceptance field for "
                "you to ratify."
            )
            await emit.text(text)
            return self._local_outcome(message_history, text)

        async with self._lock:
            live_thread = self._draft_threads.get(launch.draft_id)
            if live_thread != thread_id and launch.draft_id not in accepted_draft_ids:
                raise ValueError("Symphony launch does not belong to this thread's open draft")
            stack = self._new_stack(thread_id, launch)
            if not launch.hold_for_steering:
                stack = self._complete(stack)
            self._stacks[stack.symphony_id] = stack
            self._draft_threads.pop(launch.draft_id, None)

        await emit.event(
            {
                "event_kind": "symphony_started",
                "symphony_id": stack.symphony_id,
                "execution_kind": stack.execution_kind,
                "authority": launch.authority.model_dump(mode="json"),
            }
        )
        if stack.state == "completed":
            await emit.event(self._result_event(stack))
            text = (
                f"Toy Symphony {stack.symphony_id} completed in its own stack. "
                "Its result is attached here; this conversation never moved."
            )
        else:
            await emit.event(self._state_event(stack))
            text = (
                f"Toy Symphony {stack.symphony_id} is live on the Deck. "
                "Steering stays in this conversation and goes only to the conductor."
            )
        await emit.text(text)
        return self._local_outcome(message_history, text)

    async def read(self, symphony_id: str) -> SymphonyStackRecord | None:
        """Read one stack by its identity for headless and owner-path verification."""

        async with self._lock:
            return self._stacks.get(symphony_id)

    def _new_stack(
        self,
        thread_id: str,
        launch: SymphonyLaunchPayload,
        *,
        forked_from: str | None = None,
    ) -> SymphonyStackRecord:
        charters = tuple(
            JudgeCharter(
                seat=charter.seat,
                rubric=charter.rubric,
                evidence_requirements=charter.evidence_requirements,
                metrics=charter.metrics,
            )
            for charter in launch.judge_charters
        )
        authority = launch.authority
        # Construct the real R22 type at the boundary so the chat card cannot
        # drift from the conductor's spend, round, depth, child, or clock laws.
        SearchBudget(
            attempts=authority.attempts,
            spend_wall_usd=Decimal(authority.spend_wall_usd),
            max_rounds=authority.max_rounds,
            depth_cap=authority.depth_cap,
            children_per_attempt=authority.children_per_attempt,
            duration_seconds=float(authority.duration_minutes * 60),
        )
        search_steps = tuple(step.step_id for step in launch.recipe if step.search)
        return SymphonyStackRecord(
            symphony_id=self._id_factory(),
            thread_id=thread_id,
            state="running",
            execution_kind="toy",
            launch=launch,
            search_step_ids=search_steps,
            charter_digests=tuple(charter.digest for charter in charters),
            timeline=(
                "deliberation_ratified",
                "authority_signed",
                *((f"forked_from:{forked_from}",) if forked_from is not None else ()),
                "toy_attempts_running",
            ),
            attempts=tuple(
                SymphonyAttemptRecord(attempt_id=f"attempt-{number}", state="running")
                for number in range(1, launch.authority.attempts + 1)
            ),
            forked_from=forked_from,
        )

    async def _intervene(
        self,
        *,
        thread_id: str,
        intervention: SymphonyInterventionPayload,
        message_history: Sequence[object],
        emit: RunEmitter,
    ) -> TurnOutcome:
        async with self._lock:
            stack = self._stacks.get(str(intervention.symphony_id))
            if stack is None or stack.thread_id != thread_id:
                raise ValueError("Symphony steering target does not belong to this thread")
            if stack.state != "running":
                raise ValueError("only a running Symphony can be steered")

            if isinstance(intervention, SymphonyClarificationPayload):
                stack = self._clarify(stack, intervention)
                events = [self._state_event(stack)]
                text = (
                    f"Clarification logged for {intervention.attempt_id} inside the signed charge."
                )
            elif isinstance(intervention, SymphonyCancelAttemptPayload):
                stack = self._cancel_attempt(stack, intervention)
                events = [
                    {
                        "event_kind": "symphony_cancellation",
                        "symphony_id": stack.symphony_id,
                        "attempt_id": intervention.attempt_id,
                        "state": state,
                        "partial_evidence_retained": state == "cancelled",
                        "memories_admitted": False,
                    }
                    for state in ("requested", "draining", "cancelled")
                ]
                events.append(self._state_event(stack))
                text = f"{intervention.attempt_id} drained and cancelled; partial evidence remains."
            elif isinstance(intervention, SymphonyCharterForkPayload):
                stack, child = self._fork(stack, intervention)
                self._stacks[child.symphony_id] = child
                events = [self._state_event(stack), self._state_event(child)]
                text = (
                    f"Charter change forked {stack.symphony_id} to {child.symphony_id}; "
                    "the signed parent was not rewritten."
                )
            elif isinstance(intervention, SymphonyCompletePayload):
                stack = self._complete(stack)
                events = [self._state_event(stack), self._result_event(stack)]
                text = f"Toy Symphony {stack.symphony_id} completed and returned to this chat."
            else:  # pragma: no cover - discriminated union is closed
                raise TypeError("unsupported Symphony intervention")

            self._stacks[stack.symphony_id] = stack

        for event in events:
            await emit.event(event)
        await emit.text(text)
        return self._local_outcome(message_history, text)

    def _clarify(
        self,
        stack: SymphonyStackRecord,
        intervention: SymphonyClarificationPayload,
    ) -> SymphonyStackRecord:
        attempts = self._replace_attempt(
            stack,
            intervention.attempt_id,
            lambda attempt: attempt.model_copy(
                update={"follow_ups": (*attempt.follow_ups, intervention.instruction)}
            ),
        )
        record = SymphonyInterventionRecord(
            kind="clarification",
            attempt_id=intervention.attempt_id,
            instruction=intervention.instruction,
            requested_at=self._clock(),
            charter_digests=stack.charter_digests,
        )
        return stack.model_copy(
            update={
                "attempts": attempts,
                "interventions": (*stack.interventions, record),
                "timeline": (*stack.timeline, f"clarified:{intervention.attempt_id}"),
            }
        )

    def _cancel_attempt(
        self,
        stack: SymphonyStackRecord,
        intervention: SymphonyCancelAttemptPayload,
    ) -> SymphonyStackRecord:
        attempts = self._replace_attempt(
            stack,
            intervention.attempt_id,
            lambda attempt: attempt.model_copy(
                update={
                    "state": "cancelled",
                    "cancellation": "cancelled",
                    "partial_evidence": (*attempt.partial_evidence, "retained after drain"),
                }
            ),
        )
        record = SymphonyInterventionRecord(
            kind="cancel_attempt",
            attempt_id=intervention.attempt_id,
            requested_at=self._clock(),
            charter_digests=stack.charter_digests,
            transitions=("requested", "draining", "cancelled"),
        )
        return stack.model_copy(
            update={
                "attempts": attempts,
                "interventions": (*stack.interventions, record),
                "timeline": (
                    *stack.timeline,
                    f"cancel_requested:{intervention.attempt_id}",
                    f"draining:{intervention.attempt_id}",
                    f"cancelled:{intervention.attempt_id}",
                ),
            }
        )

    def _fork(
        self,
        stack: SymphonyStackRecord,
        intervention: SymphonyCharterForkPayload,
    ) -> tuple[SymphonyStackRecord, SymphonyStackRecord]:
        charters = tuple(
            intervention.charter if charter.seat == intervention.charter.seat else charter
            for charter in stack.launch.judge_charters
        )
        launch = stack.launch.model_copy(update={"judge_charters": charters})
        child = self._new_stack(stack.thread_id, launch, forked_from=stack.symphony_id)
        record = SymphonyInterventionRecord(
            kind="charter_change",
            requested_at=self._clock(),
            charter_digests=stack.charter_digests,
        )
        parent = stack.model_copy(
            update={
                "state": "blocked",
                "forked_to": child.symphony_id,
                "blocked_reason": "Owner changed a signed judge charter; continue in the fork.",
                "interventions": (*stack.interventions, record),
                "timeline": (*stack.timeline, f"forked_to:{child.symphony_id}", "blocked"),
            }
        )
        return parent, child

    def _complete(self, stack: SymphonyStackRecord) -> SymphonyStackRecord:
        attempts = tuple(
            attempt
            if attempt.state == "cancelled"
            else attempt.model_copy(
                update={
                    "state": "completed",
                    "partial_evidence": (*attempt.partial_evidence, "toy proof completed"),
                }
            )
            for attempt in stack.attempts
        )
        result = (
            f"Proved {len(stack.launch.recipe)} recipe step(s), "
            f"{len(stack.search_step_ids)} marked search node(s), and all three fixed "
            "judge charters under the signed authority."
        )
        return stack.model_copy(
            update={
                "state": "completed",
                "attempts": attempts,
                "timeline": (
                    *stack.timeline,
                    "toy_recipe_executed",
                    "judge_panel_unanimous",
                    "completed",
                ),
                "result": result,
                "completed_at": self._clock(),
            }
        )

    @staticmethod
    def _replace_attempt(
        stack: SymphonyStackRecord,
        attempt_id: str,
        update: Callable[[SymphonyAttemptRecord], SymphonyAttemptRecord],
    ) -> tuple[SymphonyAttemptRecord, ...]:
        found = False
        attempts: list[SymphonyAttemptRecord] = []
        for attempt in stack.attempts:
            if attempt.attempt_id == attempt_id:
                if attempt.state != "running":
                    raise ValueError("only a running attempt can be steered")
                attempt = update(attempt)
                found = True
            attempts.append(attempt)
        if not found:
            raise ValueError("attempt does not belong to the Symphony")
        return tuple(attempts)

    def _hydrate(self, events: Sequence[Mapping[str, object]]) -> None:
        for event in events:
            if event.get("event_kind") != "symphony_state":
                continue
            try:
                stack = SymphonyStackRecord.model_validate(
                    {key: value for key, value in event.items() if key != "event_kind"}
                )
            except ValueError:
                continue
            self._stacks[stack.symphony_id] = stack

    @staticmethod
    def _state_event(stack: SymphonyStackRecord) -> dict[str, object]:
        return {"event_kind": "symphony_state", **stack.model_dump(mode="json")}

    @staticmethod
    def _result_event(stack: SymphonyStackRecord) -> dict[str, object]:
        return {"event_kind": "symphony_result", **stack.model_dump(mode="json")}

    @staticmethod
    def _local_outcome(history: Sequence[object], text: str) -> TurnOutcome:
        return TurnOutcome(
            StopReason.END_TURN,
            tuple(history),
            UsageSnapshot(),
            assistant_text=text,
            model_visible=False,
        )

    @staticmethod
    def _draft_event(draft_id: str) -> Mapping[str, object]:
        return {
            "event_kind": "symphony_deliberation",
            "draft_id": draft_id,
            "objective": "",
            "motivation": "",
            "recipe": [
                {
                    "step_id": "step-1",
                    "title": "",
                    "done_when": "",
                    "search": True,
                }
            ],
            "judge_charters": [
                {
                    "seat": "motivation",
                    "rubric": [""],
                    "evidence_requirements": [""],
                    "metrics": [],
                },
                {
                    "seat": "implementation",
                    "rubric": [""],
                    "evidence_requirements": [""],
                    "metrics": [],
                },
                {
                    "seat": "performance",
                    "rubric": [""],
                    "evidence_requirements": [""],
                    "metrics": [""],
                },
            ],
            "authority": {
                "attempts": 3,
                "spend_wall_usd": "10",
                "max_rounds": 3,
                "depth_cap": 2,
                "children_per_attempt": 4,
                "duration_minutes": 30,
                "signed": False,
            },
        }
