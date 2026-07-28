from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from harness.envelope import GateCommitPayload, StopReason, WrongResolution
from harness.memory_gate import MemoryGateTurnRunner
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.spine_client import (
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
    SpineTransportError,
)
from harness.tools_memory import MemoryToolContext

THREAD_ID = "22345678-1234-5678-1234-567812345678"
INJECTION_ID = UUID("32345678-1234-5678-1234-567812345678")
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"


@dataclass
class RecordingDelegate:
    calls: list[tuple[str, str, tuple[object, ...], str | None, frozenset[UUID]]] = field(
        default_factory=list
    )

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        system_instructions: str | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome:
        del emit
        history = tuple(message_history)
        self.calls.append((thread_id, prompt, history, system_instructions, excluded_memory_ids))
        return TurnOutcome(StopReason.END_TURN, (*history, f"{prompt}:done"))


@dataclass
class RecordingEmitter:
    opened: asyncio.Event = field(default_factory=asyncio.Event)
    decision: asyncio.Future[GateCommitPayload] | None = None
    gate_values: list[Mapping[str, object]] = field(default_factory=list)
    errors: list[Mapping[str, object]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    async def text(self, value: str) -> None:
        del value

    async def thinking(self, value: str) -> None:
        del value

    async def event(self, value: Mapping[str, object]) -> None:
        del value

    async def usage(self, value: UsageSnapshot) -> None:
        del value

    async def open_gate(self, value: Mapping[str, object]) -> GateCommitPayload:
        self.gate_values.append(value)
        self.events.append("gate.open")
        self.decision = asyncio.get_running_loop().create_future()
        self.opened.set()
        return await self.decision

    async def dismiss_gate(self) -> None:
        self.events.append("gate.dismiss")

    async def error(self, value: Mapping[str, object]) -> None:
        self.errors.append(value)
        self.events.append(f"error:{value['phase']}")


class RecordingSpine:
    def __init__(self, *, fail_prepare: bool = False, fail_commit: bool = False) -> None:
        self.fail_prepare = fail_prepare
        self.fail_commit = fail_commit
        self.prepare_requests: list[InjectPrepareRequest] = []
        self.commit_requests: list[InjectCommitRequest] = []
        self.patch_requests: list[tuple[UUID, PatchMemoryRequest]] = []
        self.commit_response = InjectCommitResponse(
            final_block="trusted memory block",
            wrong_removed=[],
        )
        self.patch_outcomes: list[MemoryUnit | Exception] = []

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepare_requests.append(request)
        if self.fail_prepare:
            raise SpineTransportError
        return InjectPrepareResponse(
            injection_id=INJECTION_ID,
            snapshot_ts=datetime(2026, 7, 21, 12, tzinfo=UTC),
            scorer_version="m1-v1",
            injected=[],
            near_misses=[],
        )

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self.commit_requests.append(request)
        if self.fail_commit:
            raise SpineTransportError
        return self.commit_response

    async def patch_memory(self, memory_id: UUID, request: PatchMemoryRequest) -> MemoryUnit:
        self.patch_requests.append((memory_id, request))
        outcome = self.patch_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def context_factory(spine: object):
    def create(thread_id: str) -> MemoryToolContext:
        assert thread_id == THREAD_ID
        return MemoryToolContext(
            spine=spine,  # type: ignore[arg-type]
            principal_id="principal-1",
            machine_id="machine-1",
            agent_id="agent-1",
            thread_id=UUID(thread_id),
            project_key="project-1",
            origin_path="/workspace/file.py",
        )

    return create


def decision(*, injection_id: UUID = INJECTION_ID) -> GateCommitPayload:
    return GateCommitPayload(
        run_id=RUN_ID,
        injection_id=injection_id,
        removed=[],
        added_back=[],
    )


def memory_unit(*, revision: int = 2, body: str = "Current wrong body") -> MemoryUnit:
    return MemoryUnit(
        memory_id=UUID("42345678-1234-5678-1234-567812345678"),
        principal_id="principal-1",
        label="Wrong memory",
        body=body,
        kind=MemoryKind.FACT,
        keywords=[],
        project_key="project-1",
        thread_origin=THREAD_ID,
        origin_path="/workspace/file.py",
        pin=False,
        status=MemoryStatus.ACTIVE,
        revision=revision,
        stats={
            "injections": 1,
            "removals": 1,
            "citations": 0,
            "never_kills": 0,
            "last_injected_at": None,
        },
        bias=0.0,
        embedding_model="test-embedding",
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        updated_at=datetime(2026, 7, 21, tzinfo=UTC),
    )


async def wait_for_gate_count(emitter: RecordingEmitter, count: int) -> None:
    async with asyncio.timeout(1):
        while len(emitter.gate_values) < count:
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_first_chat_blocks_commits_and_supplies_system_instructions_once() -> None:
    spine = RecordingSpine()
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )

    remember = await runner.run(
        thread_id=THREAD_ID,
        prompt="/remember keep this",
        message_history=(),
        emit=RecordingEmitter(),
    )
    assert remember.stop_reason is StopReason.END_TURN
    assert spine.prepare_requests == []

    emitted = RecordingEmitter()
    first = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="ordinary chat",
            message_history=remember.message_history,
            emit=emitted,
        )
    )
    await asyncio.wait_for(emitted.opened.wait(), 1)
    assert [call[1] for call in delegate.calls] == ["/remember keep this"]
    assert len(spine.prepare_requests) == 1
    prepared = spine.prepare_requests[0]
    assert prepared.model_dump(mode="python") == {
        "thread_id": UUID(THREAD_ID),
        "agent_id": "agent-1",
        "machine_id": "machine-1",
        "principal_id": "principal-1",
        "project_key": "project-1",
        "agent_kind": None,
        "prompt": "ordinary chat",
        "model_context_tokens": 1_000_000,
    }
    assert emitted.decision is not None
    emitted.decision.set_result(decision())
    outcome = await asyncio.wait_for(first, 1)

    assert outcome.stop_reason is StopReason.END_TURN
    assert emitted.events == ["gate.open", "gate.dismiss"]
    assert spine.commit_requests == [
        InjectCommitRequest(injection_id=INJECTION_ID, removed=[], added_back=[])
    ]
    assert delegate.calls[-1][-2] == "trusted memory block"
    assert delegate.calls[-1][-1] == frozenset()

    await runner.run(
        thread_id=THREAD_ID,
        prompt="second chat",
        message_history=outcome.message_history,
        emit=RecordingEmitter(),
    )
    assert len(spine.prepare_requests) == 1
    assert delegate.calls[-1][-2] is None


@pytest.mark.asyncio
async def test_wrong_removal_stays_paused_until_current_unit_is_edited() -> None:
    spine = RecordingSpine()
    wrong = memory_unit()
    updated = wrong.model_copy(update={"body": "Corrected body", "revision": 3})
    spine.commit_response = InjectCommitResponse(
        final_block="trusted memory block",
        wrong_removed=[wrong],
    )
    spine.patch_outcomes.append(updated)
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitted = RecordingEmitter()
    task = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="ordinary chat",
            message_history=(),
            emit=emitted,
        )
    )

    await wait_for_gate_count(emitted, 1)
    assert emitted.decision is not None
    emitted.decision.set_result(
        GateCommitPayload(
            run_id=RUN_ID,
            injection_id=INJECTION_ID,
            removed=[{"memory_id": wrong.memory_id, "reason": "wrong"}],
            added_back=[],
        )
    )
    await wait_for_gate_count(emitted, 2)
    assert delegate.calls == []
    wrong_gate = emitted.gate_values[-1]
    assert wrong_gate["stage"] == "wrong_resolution"
    assert wrong_gate["wrong_removed"] == [wrong]
    assert wrong_gate["resolution_error"] is None

    assert emitted.decision is not None
    emitted.decision.set_result(
        GateCommitPayload(
            run_id=RUN_ID,
            injection_id=INJECTION_ID,
            removed=[],
            added_back=[],
            wrong_resolution=WrongResolution(
                memory_id=wrong.memory_id,
                expected_revision=wrong.revision,
                action="edit",
                body="Corrected body",
            ),
        )
    )
    outcome = await asyncio.wait_for(task, 1)

    assert outcome.stop_reason is StopReason.END_TURN
    assert emitted.events == ["gate.open", "gate.open", "gate.dismiss"]
    assert spine.patch_requests == [
        (
            wrong.memory_id,
            PatchMemoryRequest(
                expected_revision=wrong.revision,
                body="Corrected body",
                editor="user",
                reason="gate/wrong:edit",
                machine_id="machine-1",
            ),
        )
    ]
    assert delegate.calls == [
        (
            THREAD_ID,
            "ordinary chat",
            (),
            "trusted memory block",
            frozenset({wrong.memory_id}),
        )
    ]


@pytest.mark.asyncio
async def test_wrong_resolution_refreshes_a_cas_conflict_then_expires() -> None:
    spine = RecordingSpine()
    original = memory_unit()
    refreshed = memory_unit(revision=3, body="Concurrent correction")
    expired = refreshed.model_copy(update={"status": MemoryStatus.TOMBSTONED, "revision": 4})
    spine.commit_response = InjectCommitResponse(
        final_block="trusted memory block",
        wrong_removed=[original],
    )
    response = httpx.Response(
        409,
        request=httpx.Request("PATCH", "http://spine.test/v1/memories"),
    )
    spine.patch_outcomes.extend(
        [
            PatchMemoryConflictError(
                response,
                RevisionConflict(conflict=refreshed),
            ),
            expired,
        ]
    )
    runner = MemoryGateTurnRunner(
        RecordingDelegate(),
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitted = RecordingEmitter()
    task = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="ordinary chat",
            message_history=(),
            emit=emitted,
        )
    )

    await wait_for_gate_count(emitted, 1)
    assert emitted.decision is not None
    emitted.decision.set_result(
        GateCommitPayload(
            run_id=RUN_ID,
            injection_id=INJECTION_ID,
            removed=[{"memory_id": original.memory_id, "reason": "wrong"}],
            added_back=[],
        )
    )
    await wait_for_gate_count(emitted, 2)
    assert emitted.decision is not None
    emitted.decision.set_result(
        GateCommitPayload(
            run_id=RUN_ID,
            injection_id=INJECTION_ID,
            removed=[],
            added_back=[],
            wrong_resolution=WrongResolution(
                memory_id=original.memory_id,
                expected_revision=original.revision,
                action="edit",
                body="First correction",
            ),
        )
    )

    await wait_for_gate_count(emitted, 3)
    retry_gate = emitted.gate_values[-1]
    assert retry_gate["wrong_removed"] == [refreshed]
    assert "changed while you were reviewing" in str(retry_gate["resolution_error"])
    assert emitted.decision is not None
    emitted.decision.set_result(
        GateCommitPayload(
            run_id=RUN_ID,
            injection_id=INJECTION_ID,
            removed=[],
            added_back=[],
            wrong_resolution=WrongResolution(
                memory_id=refreshed.memory_id,
                expected_revision=refreshed.revision,
                action="expire",
            ),
        )
    )
    await asyncio.wait_for(task, 1)

    assert [request.expected_revision for _, request in spine.patch_requests] == [2, 3]
    assert spine.patch_requests[-1][1].status is MemoryStatus.TOMBSTONED
    assert spine.patch_requests[-1][1].reason == "gate/wrong:expire"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["prepare", "commit"])
async def test_spine_failure_is_visible_and_fails_open_without_instructions(phase: str) -> None:
    spine = RecordingSpine(
        fail_prepare=phase == "prepare",
        fail_commit=phase == "commit",
    )
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitted = RecordingEmitter()
    removed_id = memory_unit().memory_id
    task = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="hello",
            message_history=(),
            emit=emitted,
        )
    )
    if phase == "commit":
        await asyncio.wait_for(emitted.opened.wait(), 1)
        assert emitted.decision is not None
        emitted.decision.set_result(
            GateCommitPayload(
                run_id=RUN_ID,
                injection_id=INJECTION_ID,
                removed=[{"memory_id": removed_id, "reason": "never"}],
                added_back=[],
            )
        )
    await asyncio.wait_for(task, 1)

    assert emitted.errors == [
        {
            "code": "memory_unavailable",
            "phase": phase,
            "message": "Memory is unavailable; continuing without injected context.",
        }
    ]
    expected_exclusions = frozenset({removed_id}) if phase == "commit" else frozenset()
    assert delegate.calls == [(THREAD_ID, "hello", (), None, expected_exclusions)]
    if phase == "prepare":
        assert emitted.events == ["error:prepare"]
    else:
        assert emitted.events == ["gate.open", "error:commit", "gate.dismiss"]


@pytest.mark.asyncio
async def test_cancelled_attempt_is_claimed_and_never_invokes_the_model() -> None:
    spine = RecordingSpine()
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitted = RecordingEmitter()
    first = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="first",
            message_history=(),
            emit=emitted,
        )
    )
    await asyncio.wait_for(emitted.opened.wait(), 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert delegate.calls == []

    await runner.run(
        thread_id=THREAD_ID,
        prompt="next",
        message_history=(),
        emit=RecordingEmitter(),
    )
    assert len(spine.prepare_requests) == 1
    assert delegate.calls == [(THREAD_ID, "next", (), None, frozenset())]


def test_gate_config_rejects_non_positive_or_boolean_context_windows() -> None:
    spine = RecordingSpine()
    for value in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            MemoryGateTurnRunner(
                RecordingDelegate(),
                spine,
                context_factory(spine),
                model_context_tokens=value,
            )
