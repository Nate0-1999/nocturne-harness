from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic_ai.messages import BinaryContent

from harness.envelope import GateCommitPayload, StopReason, WrongResolution
from harness.memory_gate import MemoryGateTurnRunner
from harness.memory_panel import EMPTY_MEMORY_BLOCK, ThreadMemoryContextRegistry
from harness.model_policy import ThreadModelResolution
from harness.run_protocol import (
    DynamicSystemInstructions,
    RunEmitter,
    TurnOutcome,
    UsageSnapshot,
)
from harness.spine_client import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSignal,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    MemoryAllocation,
    MemoryFeatures,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
    ScoredMemoryCard,
    SpineTransportError,
)
from harness.tools_memory import MemoryToolContext
from harness.toolset import AgentLocation

THREAD_ID = "22345678-1234-5678-1234-567812345678"
INJECTION_ID = UUID("32345678-1234-5678-1234-567812345678")
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"


def memory_allocation() -> MemoryAllocation:
    return MemoryAllocation(
        memory_context_share=0.10,
        share_tokens=100,
        regular_tokens=0,
        pinned_tokens=0,
        total_tokens=0,
        pinned_overflow_tokens=0,
    )


@dataclass
class RecordingDelegate:
    calls: list[tuple[str, str, tuple[object, ...], str | None, frozenset[UUID]]] = field(
        default_factory=list
    )
    resolutions: list[ThreadModelResolution | None] = field(default_factory=list)
    assistant_text: str | None = None

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
        system_instructions: str | None = None,
        dynamic_instructions: DynamicSystemInstructions | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome:
        del emit
        if dynamic_instructions is not None:
            await dynamic_instructions.render()
            system_instructions = dynamic_instructions.memory_block
        history = tuple(message_history)
        self.resolutions.append(model_resolution)
        self.calls.append((thread_id, prompt, history, system_instructions, excluded_memory_ids))
        return TurnOutcome(
            StopReason.END_TURN,
            (*history, f"{prompt}:done"),
            assistant_text=self.assistant_text,
        )


@dataclass
class ImageRecordingDelegate:
    calls: list[tuple[str, BinaryContent, str | None]] = field(default_factory=list)

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        image: BinaryContent,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
        system_instructions: str | None = None,
        dynamic_instructions: DynamicSystemInstructions | None = None,
        excluded_memory_ids: frozenset[UUID] = frozenset(),
    ) -> TurnOutcome:
        del thread_id, emit, model_resolution, excluded_memory_ids
        if dynamic_instructions is not None:
            await dynamic_instructions.render()
            system_instructions = dynamic_instructions.memory_block
        self.calls.append((prompt, image, system_instructions))
        return TurnOutcome(
            StopReason.END_TURN,
            (*message_history, "image:done"),
            assistant_text="image answer",
        )


@dataclass
class MovingToolset:
    root: Path
    cwd: Path

    def location(self) -> AgentLocation:
        return AgentLocation(
            agent_id="agent-1",
            machine_id="machine-1",
            session_id="test",
            workspace_root=self.root,
            cwd=self.cwd,
            fence_reads=False,
        )


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
        self.feedback_requests: list[FeedbackRequest] = []
        self.feedback_outcomes: list[FeedbackResponse | Exception] = []
        self.commit_response = InjectCommitResponse(
            final_block=EMPTY_MEMORY_BLOCK,
            wrong_removed=[],
        )
        self.prepare_response = InjectPrepareResponse(
            injection_id=INJECTION_ID,
            snapshot_ts=datetime(2026, 7, 21, 12, tzinfo=UTC),
            scorer_version="m1-v1",
            injected=[],
            near_misses=[],
            final_block=None,
            memory_allocation=memory_allocation(),
        )
        self.prepare_outcomes: list[InjectPrepareResponse | Exception] = []
        self.patch_outcomes: list[MemoryUnit | Exception] = []

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self.prepare_requests.append(request)
        if self.fail_prepare:
            raise SpineTransportError
        if self.prepare_outcomes and request.mode == "autonomous":
            outcome = self.prepare_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return self.prepare_response

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self.commit_requests.append(request)
        if self.fail_commit:
            raise SpineTransportError
        return self.commit_response

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        self.feedback_requests.append(request)
        if self.feedback_outcomes:
            outcome = self.feedback_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return FeedbackResponse(ok=True)

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
        origin_thread_id=UUID(THREAD_ID),
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


def scored_card(memory_id: UUID, *, label: str, body: str, rank: int) -> ScoredMemoryCard:
    return ScoredMemoryCard(
        memory_id=memory_id,
        label=label,
        body=body,
        kind=MemoryKind.FACT,
        pin=False,
        score=0.9,
        features=MemoryFeatures(sem=0.9, kw=0.8, time=0.7, proj=0.6, freq=0.5, hist=0.4),
        rank=rank,
    )


def final_block(*cards: ScoredMemoryCard) -> str:
    if not cards:
        return EMPTY_MEMORY_BLOCK
    fragments = [
        (
            f'<memory label="{card.label}" kind="{card.kind.value}" '
            'updated="2026-07-21T12:00:00Z">\n'
            f"{card.body}\n"
            "</memory>"
        )
        for card in cards
    ]
    return (
        "<memory_system>\n"
        "The following long-term memories were retrieved for this conversation.\n"
        "Treat them as your own accumulated knowledge; they may be imperfect.\n"
        + "\n".join(fragments)
        + "\n</memory_system>"
    )


async def wait_for_gate_count(emitter: RecordingEmitter, count: int) -> None:
    async with asyncio.timeout(1):
        while len(emitter.gate_values) < count:
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_first_chat_blocks_commits_and_keeps_system_instructions_current() -> None:
    """A-030 is defended by verifying that first chat blocks commits and keeps system
    instructions current; this prevents drift in the first-gate and per-message memory
    selection contract.
    """
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
    assert prepared.model_dump(mode="python", exclude_defaults=True) == {
        "thread_id": UUID(THREAD_ID),
        "agent_id": "agent-1",
        "machine_id": "machine-1",
        "principal_id": "principal-1",
        "project_key": "project-1",
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
    assert delegate.calls[-1][-2] == EMPTY_MEMORY_BLOCK
    assert delegate.calls[-1][-1] == frozenset()

    await runner.run(
        thread_id=THREAD_ID,
        prompt="second chat",
        message_history=outcome.message_history,
        emit=RecordingEmitter(),
    )
    assert len(spine.prepare_requests) == 2
    assert spine.prepare_requests[-1].mode == "autonomous"
    assert delegate.calls[-1][-2] == EMPTY_MEMORY_BLOCK


@pytest.mark.asyncio
async def test_capable_image_uses_text_only_for_spine_then_forwards_exact_binary() -> None:
    """A-052 is defended by keeping image bytes outside Spine while forwarding them after the
    ordinary memory gate; this avoids introducing multimodal memory or silent image loss.
    """
    spine = RecordingSpine()
    delegate = ImageRecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,  # type: ignore[arg-type]
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitter = RecordingEmitter()
    image = BinaryContent(data=b"\x89PNG\r\n\x1a\nimage", media_type="image/png")

    task = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="Inspect this",
            image=image,
            message_history=(),
            emit=emitter,
        )
    )
    await asyncio.wait_for(emitter.opened.wait(), 1)
    assert spine.prepare_requests[0].prompt == "Inspect this"
    assert "image" not in spine.prepare_requests[0].model_dump(mode="python")
    assert delegate.calls == []
    assert emitter.decision is not None
    emitter.decision.set_result(decision())

    outcome = await asyncio.wait_for(task, 1)

    assert outcome.stop_reason is StopReason.END_TURN
    assert delegate.calls == [("Inspect this", image, EMPTY_MEMORY_BLOCK)]


@pytest.mark.asyncio
async def test_r16_move_reprompts_local_context_and_rescores_before_next_request(
    tmp_path: Path,
) -> None:
    """ADR-010 is defended at the live turn seam, not as an isolated prompt demo."""

    notes = tmp_path / "notes"
    notes.mkdir()
    (tmp_path / "AGENTS.md").write_text("root instruction", encoding="utf-8")
    (notes / "AGENTS.md").write_text("notes instruction", encoding="utf-8")
    (notes / "local.txt").write_text("feet", encoding="utf-8")
    toolset = MovingToolset(tmp_path, tmp_path)
    first_id = UUID("52345678-1234-5678-1234-567812345678")
    moved_id = UUID("62345678-1234-5678-1234-567812345678")
    first_card = scored_card(first_id, label="Root", body="root memory", rank=1)
    moved_card = scored_card(moved_id, label="Notes", body="notes memory", rank=1)
    spine = RecordingSpine()
    spine.prepare_response = spine.prepare_response.model_copy(update={"injected": [first_card]})
    spine.commit_response = InjectCommitResponse(
        final_block=final_block(first_card), wrong_removed=[]
    )
    spine.prepare_outcomes.append(
        InjectPrepareResponse(
            injection_id=UUID("72345678-1234-5678-1234-567812345678"),
            snapshot_ts=datetime(2026, 8, 17, 12, 1, tzinfo=UTC),
            scorer_version="m3f-location",
            injected=[first_card, moved_card],
            near_misses=[],
            final_block=final_block(first_card, moved_card),
            memory_allocation=memory_allocation(),
        )
    )
    rendered: list[str] = []

    class MoveBetweenRequests(RecordingDelegate):
        async def run(self, **kwargs) -> TurnOutcome:  # type: ignore[no-untyped-def]
            dynamic = kwargs["dynamic_instructions"]
            rendered.append(await dynamic.render())
            toolset.cwd = notes
            rendered.append(await dynamic.render())
            return TurnOutcome(StopReason.END_TURN, (), assistant_text="moved")

    def create_context(thread_id: str) -> MemoryToolContext:
        return MemoryToolContext(
            spine=spine,
            principal_id="principal-1",
            machine_id="machine-1",
            agent_id="agent-1",
            thread_id=UUID(thread_id),
            project_key="project-1",
            origin_path=".",
            toolset=toolset,  # type: ignore[arg-type]
        )

    runner = MemoryGateTurnRunner(
        MoveBetweenRequests(),
        spine,
        create_context,
        model_context_tokens=1_000_000,
    )
    emitter = RecordingEmitter()
    task = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID, prompt="Where should this go?", message_history=(), emit=emitter
        )
    )
    await asyncio.wait_for(emitter.opened.wait(), 1)
    assert emitter.decision is not None
    emitter.decision.set_result(decision())
    await asyncio.wait_for(task, 1)

    assert spine.prepare_requests[0].location_path == "."
    assert spine.prepare_requests[1].location_path == "notes"
    assert spine.prepare_requests[1].mode == "autonomous"
    assert spine.prepare_requests[1].prompt == "Where should this go?"
    assert "Current location: ." in rendered[0]
    assert "root memory" in rendered[0]
    assert "notes/AGENTS.md" not in rendered[0]
    assert "Current location: notes" in rendered[1]
    assert "local.txt" in rendered[1]
    assert "notes instruction" in rendered[1]
    assert "notes memory" in rendered[1]
    assert "root memory" in rendered[1]  # Human-confirmed gate members remain locked.


async def _record_ambient(values: list[str], thread_id: str) -> None:
    values.append(thread_id)


@pytest.mark.asyncio
async def test_post_first_turn_rescores_without_gate_and_publishes_ambient_membership() -> None:
    """A-030 is defended by verifying that post first turn rescores without gate and publishes
    ambient membership; this prevents drift in the first-gate and per-message memory
    selection contract.
    """
    first_id = UUID("52345678-1234-5678-1234-567812345678")
    entered_id = UUID("62345678-1234-5678-1234-567812345678")
    first_card = scored_card(first_id, label="Confirmed", body="First body.", rank=1)
    entered_card = scored_card(entered_id, label="Ambient", body="Second body.", rank=2)
    spine = RecordingSpine()
    spine.prepare_response = spine.prepare_response.model_copy(update={"injected": [first_card]})
    spine.commit_response = InjectCommitResponse(
        final_block=final_block(first_card), wrong_removed=[]
    )
    spine.prepare_outcomes.append(
        InjectPrepareResponse(
            injection_id=UUID("72345678-1234-5678-1234-567812345678"),
            snapshot_ts=datetime(2026, 7, 21, 12, 1, tzinfo=UTC),
            scorer_version="m1-v1",
            injected=[first_card, entered_card],
            near_misses=[],
            final_block=final_block(first_card, entered_card),
            memory_allocation=memory_allocation(),
        )
    )
    ambient: list[str] = []
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
        on_context_changed=lambda thread_id: _record_ambient(ambient, thread_id),
    )

    first_emitter = RecordingEmitter()
    first = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="first",
            message_history=(),
            emit=first_emitter,
        )
    )
    await asyncio.wait_for(first_emitter.opened.wait(), 1)
    assert first_emitter.decision is not None
    first_emitter.decision.set_result(decision())
    first_outcome = await asyncio.wait_for(first, 1)

    second_emitter = RecordingEmitter()
    await runner.run(
        thread_id=THREAD_ID,
        prompt="second",
        message_history=first_outcome.message_history,
        emit=second_emitter,
    )

    assert second_emitter.events == []
    assert ambient == [THREAD_ID]
    request = spine.prepare_requests[-1]
    assert request.mode == "autonomous"
    assert request.current_memory_ids == [first_id]
    assert request.confirmed_memory_ids == [first_id]
    assert request.excluded_memory_ids == []
    assert delegate.calls[-1][-2] == final_block(first_card, entered_card)


@pytest.mark.asyncio
async def test_citations_follow_each_model_calls_exact_event_source() -> None:
    """Each ordinary response labels its gated or autonomous M2G batch. [A-036]"""

    memory_id = UUID("52345678-1234-5678-1234-567812345678")
    autonomous_id = UUID("72345678-1234-5678-1234-567812345678")
    body = "Always write tests before changing shared production behavior."
    card = scored_card(memory_id, label="Testing discipline", body=body, rank=1)
    spine = RecordingSpine()
    spine.prepare_response = spine.prepare_response.model_copy(update={"injected": [card]})
    spine.commit_response = InjectCommitResponse(final_block=final_block(card), wrong_removed=[])
    spine.prepare_outcomes.append(
        InjectPrepareResponse(
            injection_id=autonomous_id,
            snapshot_ts=datetime(2026, 7, 21, 12, 1, tzinfo=UTC),
            scorer_version="m1-v1",
            injected=[card],
            near_misses=[],
            final_block=final_block(card),
            memory_allocation=memory_allocation(),
        )
    )
    delegate = RecordingDelegate(assistant_text=f"Agreed: {body}")
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )

    emitter = RecordingEmitter()
    first = asyncio.create_task(
        runner.run(thread_id=THREAD_ID, prompt="first", message_history=(), emit=emitter)
    )
    await asyncio.wait_for(emitter.opened.wait(), 1)
    assert emitter.decision is not None
    emitter.decision.set_result(decision())
    first_outcome = await asyncio.wait_for(first, 1)
    await runner.run(
        thread_id=THREAD_ID,
        prompt="second",
        message_history=first_outcome.message_history,
        emit=RecordingEmitter(),
    )

    assert spine.feedback_requests == [
        FeedbackRequest(
            injection_id=INJECTION_ID,
            memory_id=memory_id,
            signal=FeedbackSignal.CITED,
        ),
        FeedbackRequest(
            injection_id=autonomous_id,
            memory_id=memory_id,
            signal=FeedbackSignal.CITED,
        ),
    ]


@pytest.mark.asyncio
async def test_citation_failure_is_visible_without_retracting_the_turn() -> None:
    """A-036 reports passive persistence failure after preserving model output."""

    memory_id = UUID("52345678-1234-5678-1234-567812345678")
    body = "Always write tests before changing shared production behavior."
    card = scored_card(memory_id, label="Testing discipline", body=body, rank=1)
    spine = RecordingSpine()
    spine.prepare_response = spine.prepare_response.model_copy(update={"injected": [card]})
    spine.commit_response = InjectCommitResponse(final_block=final_block(card), wrong_removed=[])
    spine.feedback_outcomes.append(SpineTransportError())
    delegate = RecordingDelegate(assistant_text=body)
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitter = RecordingEmitter()
    task = asyncio.create_task(
        runner.run(thread_id=THREAD_ID, prompt="first", message_history=(), emit=emitter)
    )
    await asyncio.wait_for(emitter.opened.wait(), 1)
    assert emitter.decision is not None
    emitter.decision.set_result(decision())

    outcome = await asyncio.wait_for(task, 1)

    assert outcome.stop_reason is StopReason.END_TURN
    assert emitter.errors[-1]["phase"] == "citation"


@pytest.mark.asyncio
async def test_thread_resolution_controls_prepare_context_and_reaches_both_model_paths() -> None:
    """A-030 is defended by verifying that thread resolution controls prepare context and
    reaches both model paths; this prevents drift in the first-gate and per-message memory
    selection contract.
    """
    spine = RecordingSpine()
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    resolution = ThreadModelResolution(
        model="openrouter:vendor/selected",
        context_tokens=131_072,
        policy="elbow",
        price_sorted=True,
    )

    await runner.run(
        thread_id=THREAD_ID,
        prompt="/remember keep this",
        message_history=(),
        emit=RecordingEmitter(),
        model_resolution=resolution,
    )
    assert spine.prepare_requests == []
    assert delegate.resolutions == [resolution]

    emitted = RecordingEmitter()
    chat = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="ordinary chat",
            message_history=(),
            emit=emitted,
            model_resolution=resolution,
        )
    )
    await asyncio.wait_for(emitted.opened.wait(), 1)
    assert spine.prepare_requests[0].model_context_tokens == 131_072
    assert emitted.decision is not None
    emitted.decision.set_result(decision())
    await asyncio.wait_for(chat, 1)

    assert delegate.resolutions == [resolution, resolution]


@pytest.mark.asyncio
async def test_later_turn_uses_rerendered_block_and_persistent_exclusions() -> None:
    """A-030 is defended by verifying that later turn uses rerendered block and persistent
    exclusions; this prevents drift in the first-gate and per-message memory selection
    contract.
    """
    first_id = UUID("52345678-1234-5678-1234-567812345678")
    second_id = UUID("62345678-1234-5678-1234-567812345678")
    first_card = scored_card(first_id, label="Remove", body="Remove this body.", rank=1)
    second_card = scored_card(second_id, label="Keep", body="Keep this body.", rank=2)
    spine = RecordingSpine()
    spine.prepare_response = spine.prepare_response.model_copy(
        update={"injected": [first_card, second_card]}
    )
    spine.commit_response = InjectCommitResponse(
        final_block=final_block(first_card, second_card),
        wrong_removed=[],
    )
    contexts = ThreadMemoryContextRegistry()
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
        contexts=contexts,
    )
    emitted = RecordingEmitter()
    first_turn = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="first",
            message_history=(),
            emit=emitted,
        )
    )
    await asyncio.wait_for(emitted.opened.wait(), 1)
    assert emitted.decision is not None
    emitted.decision.set_result(decision())
    first_outcome = await asyncio.wait_for(first_turn, 1)
    assert delegate.calls[-1][-2] == final_block(first_card, second_card)

    assert contexts.remove(THREAD_ID, first_id) is True
    await runner.run(
        thread_id=THREAD_ID,
        prompt="second",
        message_history=first_outcome.message_history,
        emit=RecordingEmitter(),
    )

    assert delegate.calls[-1][-2] == final_block(second_card)
    assert delegate.calls[-1][-1] == frozenset({first_id})
    assert "Remove this body." not in delegate.calls[-1][-2]
    assert "Keep this body." in delegate.calls[-1][-2]


@pytest.mark.asyncio
async def test_near_miss_never_preserves_committed_context_and_exclusion() -> None:
    """A-030 is defended by verifying that near miss never preserves committed context and
    exclusion; this prevents drift in the first-gate and per-message memory selection
    contract.
    """
    retained_id = UUID("52345678-1234-5678-1234-567812345678")
    vetoed_id = UUID("62345678-1234-5678-1234-567812345678")
    retained = scored_card(retained_id, label="Keep", body="Keep this body.", rank=1)
    near_miss = scored_card(vetoed_id, label="Never", body="Exclude this body.", rank=2)
    spine = RecordingSpine()
    spine.prepare_response = spine.prepare_response.model_copy(
        update={"injected": [retained], "near_misses": [near_miss]}
    )
    spine.commit_response = InjectCommitResponse(
        final_block=final_block(retained),
        wrong_removed=[],
    )
    delegate = RecordingDelegate()
    runner = MemoryGateTurnRunner(
        delegate,
        spine,
        context_factory(spine),
        model_context_tokens=1_000_000,
    )
    emitted = RecordingEmitter()
    turn = asyncio.create_task(
        runner.run(
            thread_id=THREAD_ID,
            prompt="ordinary chat",
            message_history=(),
            emit=emitted,
        )
    )
    await asyncio.wait_for(emitted.opened.wait(), 1)
    assert emitted.decision is not None
    emitted.decision.set_result(
        GateCommitPayload(
            run_id=RUN_ID,
            injection_id=INJECTION_ID,
            removed=[{"memory_id": vetoed_id, "reason": "never"}],
            added_back=[],
        )
    )
    await asyncio.wait_for(turn, 1)

    assert emitted.errors == []
    assert emitted.events == ["gate.open", "gate.dismiss"]
    assert delegate.calls == [
        (
            THREAD_ID,
            "ordinary chat",
            (),
            final_block(retained),
            frozenset({vetoed_id}),
        )
    ]

    await runner.run(
        thread_id=THREAD_ID,
        prompt="later chat",
        message_history=(),
        emit=RecordingEmitter(),
    )
    assert delegate.calls[-1] == (
        THREAD_ID,
        "later chat",
        (),
        final_block(retained),
        frozenset({vetoed_id}),
    )


@pytest.mark.asyncio
async def test_wrong_removal_stays_paused_until_current_unit_is_edited() -> None:
    """A-030 is defended by verifying that wrong removal stays paused until current unit is
    edited; this prevents drift in the first-gate and per-message memory selection contract.
    """
    spine = RecordingSpine()
    wrong = memory_unit()
    updated = wrong.model_copy(update={"body": "Corrected body", "revision": 3})
    spine.prepare_response = spine.prepare_response.model_copy(
        update={
            "injected": [
                scored_card(
                    wrong.memory_id,
                    label=wrong.label,
                    body=wrong.body,
                    rank=1,
                )
            ]
        }
    )
    spine.commit_response = InjectCommitResponse(
        final_block=EMPTY_MEMORY_BLOCK,
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
            EMPTY_MEMORY_BLOCK,
            frozenset({wrong.memory_id}),
        )
    ]


@pytest.mark.asyncio
async def test_wrong_resolution_refreshes_a_cas_conflict_then_expires() -> None:
    """A-030 is defended by verifying that wrong resolution refreshes a cas conflict then
    expires; this prevents drift in the first-gate and per-message memory selection
    contract.
    """
    spine = RecordingSpine()
    original = memory_unit()
    refreshed = memory_unit(revision=3, body="Concurrent correction")
    expired = refreshed.model_copy(update={"status": MemoryStatus.TOMBSTONED, "revision": 4})
    spine.prepare_response = spine.prepare_response.model_copy(
        update={
            "injected": [
                scored_card(
                    original.memory_id,
                    label=original.label,
                    body=original.body,
                    rank=1,
                )
            ]
        }
    )
    spine.commit_response = InjectCommitResponse(
        final_block=EMPTY_MEMORY_BLOCK,
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
    """A-030 is defended by verifying that spine failure is visible and fails open without
    instructions; this prevents drift in the first-gate and per-message memory selection
    contract.
    """
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
    """A-030 is defended by verifying that cancelled attempt is claimed and never invokes the
    model; this prevents drift in the first-gate and per-message memory selection contract.
    """
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
    """A-030 is defended by verifying that gate config rejects non positive or boolean context
    windows; this prevents drift in the first-gate and per-message memory selection
    contract.
    """
    spine = RecordingSpine()
    for value in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            MemoryGateTurnRunner(
                RecordingDelegate(),
                spine,
                context_factory(spine),
                model_context_tokens=value,
            )
