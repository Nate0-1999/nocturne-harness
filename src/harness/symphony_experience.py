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
from harness.envelope import StopReason, SymphonyLaunchPayload
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot

_TRIGGER = re.compile(r"^take this to a symphony[.!]?\s*$", re.IGNORECASE)


class SymphonyStackRecord(BaseModel):
    """A separately addressable, immutable proof stack returned to its source thread."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    symphony_id: str
    thread_id: str
    state: Literal["completed"]
    execution_kind: Literal["toy"]
    launch: SymphonyLaunchPayload
    search_step_ids: tuple[str, ...]
    charter_digests: tuple[str, ...]
    timeline: tuple[str, ...]
    result: str
    completed_at: datetime


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
        message_history: Sequence[object],
        emit: RunEmitter,
        accepted_draft_ids: Sequence[str] = (),
    ) -> TurnOutcome:
        """Open deliberation or execute the signed proof stack without a mode switch."""

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
            stack = self._complete_toy_stack(thread_id, launch)
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
        await emit.event(
            {
                "event_kind": "symphony_result",
                **stack.model_dump(mode="json"),
            }
        )
        text = (
            f"Toy Symphony {stack.symphony_id} completed in its own stack. "
            "Its result is attached here; this conversation never moved."
        )
        await emit.text(text)
        return self._local_outcome(message_history, text)

    async def read(self, symphony_id: str) -> SymphonyStackRecord | None:
        """Read one stack by its identity for headless and owner-path verification."""

        async with self._lock:
            return self._stacks.get(symphony_id)

    def _complete_toy_stack(
        self,
        thread_id: str,
        launch: SymphonyLaunchPayload,
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
            state="completed",
            execution_kind="toy",
            launch=launch,
            search_step_ids=search_steps,
            charter_digests=tuple(charter.digest for charter in charters),
            timeline=(
                "deliberation_ratified",
                "authority_signed",
                "toy_recipe_executed",
                "judge_panel_unanimous",
                "completed",
            ),
            result=(
                f"Proved {len(launch.recipe)} recipe step(s), {len(search_steps)} marked "
                "search node(s), and all three fixed judge charters under the signed authority."
            ),
            completed_at=self._clock(),
        )

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
