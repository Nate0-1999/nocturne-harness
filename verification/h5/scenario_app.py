"""Live-Spine, deterministic-model fixture for H5 browser verification.

Run from the Harness repository root::

    PYTHONPATH=src:. uv run --locked python -m verification.run_fixture \
      verification.h5.scenario_app:create_scenario_app --port 8773

The browser exercises the production SPA, WebSocket daemon, run loop, memory
gate, and configured deployed Spine. Only the downstream model is local and
deterministic. Scenario endpoints create and tombstone only IDs owned by this
fixture process under a fresh dedicated principal.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from harness.agent import HarnessAgent
from harness.config import HarnessSettings
from harness.daemon import create_dev_app
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryRequest,
    CreateMemoryResponse,
    FeedbackRequest,
    FeedbackResponse,
    InjectCommitRequest,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    PatchMemoryResponse,
    RevisionConflict,
    SearchRequest,
    SearchResponse,
    SpineClient,
    SpineTransportError,
)
from verification.fixture_isolation import install_fixture_isolation

TRACE_PATH = Path(__file__).with_name("trace.jsonl")
FIRST_PROMPT = "Use the H5 verification memories to explain the handoff."
SECOND_PROMPT = "Confirm that the second prompt skips the memory gate."
CORRECTED_WRONG_BODY = (
    "The first-prompt memory gate waits for a human decision before the model starts."
)
MACHINE_ID = "h5-verification-machine"
AGENT_ID = "h5-verification-agent"
EDITOR = "verification:h5"


@dataclass(frozen=True, slots=True)
class SeedDefinition:
    role: str
    label: str
    body: str
    kind: MemoryKind
    keywords: tuple[str, ...]
    pin: bool


SEED_DEFINITIONS = (
    SeedDefinition(
        role="keep",
        label="H5 proof — keep",
        body=(
            "Verification reports should lead with the observed result, then give the "
            "supporting evidence."
        ),
        kind=MemoryKind.PREFERENCE,
        keywords=("verification", "evidence", "handoff"),
        pin=True,
    ),
    SeedDefinition(
        role="not_relevant",
        label="H5 proof — not relevant",
        body="The kitchen sourdough starter is fed every Thursday before sunrise.",
        kind=MemoryKind.FACT,
        keywords=("sourdough", "kitchen", "Thursday"),
        pin=True,
    ),
    SeedDefinition(
        role="wrong",
        label="H5 proof — wrong",
        body="The first-prompt memory gate automatically continues after five seconds.",
        kind=MemoryKind.PROCEDURE,
        keywords=("gate", "timeout", "automatic"),
        pin=True,
    ),
    SeedDefinition(
        role="never",
        label="H5 proof — never",
        body="Always inject loud motivational slogans into every technical answer.",
        kind=MemoryKind.PERSONA,
        keywords=("slogans", "loud", "always"),
        pin=True,
    ),
    SeedDefinition(
        role="add_back",
        label="H5 proof — add back",
        body="A brass telescope is stored beside the attic window for winter constellations.",
        kind=MemoryKind.FACT,
        keywords=("telescope", "attic", "constellations"),
        pin=False,
    ),
)


class TraceLog:
    """Append a credential-free trace shared by every fixture seam."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def clear(self) -> None:
        self._path.write_text("", encoding="utf-8")

    def record(self, kind: str, **values: object) -> None:
        record = {
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            **values,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


@dataclass(slots=True)
class SeededMemory:
    role: str
    memory: MemoryUnit

    def public_record(self) -> dict[str, object]:
        return {
            "memory_id": str(self.memory.memory_id),
            "label": self.memory.label,
            "body": self.memory.body,
            "kind": self.memory.kind.value,
            "pin": self.memory.pin,
            "revision": self.memory.revision,
        }


class ScenarioControl:
    """Own exact seeded IDs, trace resets, and one-shot failure selection."""

    def __init__(self, trace: TraceLog) -> None:
        self.trace = trace
        self.principal_id = f"h5-verification-{uuid4().hex}"
        self.seeded: dict[str, SeededMemory] = {}
        self.fail_next: str | None = None
        self.model_calls = 0
        self.prepare_calls = 0
        self.prepare_results = 0
        self.commit_calls = 0
        self.commit_results = 0

    def reset_trace(self) -> None:
        self.fail_next = None
        self.model_calls = 0
        self.prepare_calls = 0
        self.prepare_results = 0
        self.commit_calls = 0
        self.commit_results = 0
        self.trace.clear()
        if self.seeded:
            self.trace_seeded()

    def trace_seeded(self) -> None:
        self.trace.record(
            "scenario.seeded",
            principal_id=self.principal_id,
            roles={role: item.public_record() for role, item in self.seeded.items()},
        )

    def arm_failure(self, phase: str) -> None:
        if phase not in {"prepare", "commit"}:
            raise ValueError("phase must be prepare or commit")
        self.fail_next = phase
        self.trace.record("scenario.failure_armed", phase=phase)

    def consume_failure(self, phase: str) -> bool:
        if self.fail_next != phase:
            return False
        self.fail_next = None
        self.trace.record("scenario.failure_triggered", phase=phase)
        return True


class TracingSpine:
    """Trace H5 ordering and delegate all C.4 calls to the configured Spine."""

    def __init__(self, delegate: SpineClient, control: ScenarioControl) -> None:
        self._delegate = delegate
        self._control = control

    async def aclose(self) -> None:
        await self._delegate.aclose()

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self._control.prepare_calls += 1
        self._control.trace.record(
            "spine.prepare.call",
            thread_id=str(request.thread_id),
            principal_id=request.principal_id,
            prompt_sha256=_digest(request.prompt),
            prompt_length=len(request.prompt),
            model_context_tokens=request.model_context_tokens,
        )
        if self._control.consume_failure("prepare"):
            raise SpineTransportError()
        response = await self._delegate.prepare_injection(request)
        self._control.prepare_results += 1
        self._control.trace.record(
            "spine.prepare.result",
            injection_id=str(response.injection_id),
            injected=[_scored_card_record(card) for card in response.injected],
            near_misses=[_scored_card_record(card) for card in response.near_misses],
        )
        return response

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self._control.commit_calls += 1
        self._control.trace.record(
            "spine.commit.call",
            injection_id=str(request.injection_id),
            removed=[
                {"memory_id": str(item.memory_id), "reason": item.reason.value}
                for item in request.removed
            ],
            added_back=[str(memory_id) for memory_id in request.added_back],
        )
        if self._control.consume_failure("commit"):
            raise SpineTransportError()
        response = await self._delegate.commit_injection(request)
        self._control.commit_results += 1
        self._control.trace.record(
            "spine.commit.result",
            final_block=response.final_block,
            wrong_removed=[str(item.memory_id) for item in response.wrong_removed],
            wrong_removed_current=[_wrong_memory_record(item) for item in response.wrong_removed],
        )
        return response

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        return await self._delegate.submit_feedback(request)

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        return await self._delegate.create_memory(request)

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse:
        traces_wrong_resolution = request.editor == "user" and request.reason.startswith(
            "gate/wrong:"
        )
        if traces_wrong_resolution:
            self._control.trace.record(
                "spine.patch.call",
                memory_id=str(memory_id),
                expected_revision=request.expected_revision,
                body=request.body,
                status=request.status.value if request.status is not None else None,
                editor=request.editor,
                reason=request.reason,
                machine_id=request.machine_id,
            )
        response = await self._delegate.patch_memory(memory_id, request)
        if traces_wrong_resolution:
            self._control.trace.record(
                "spine.patch.result",
                **_wrong_memory_record(response),
            )
        return response

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        return await self._delegate.list_memories(params)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return await self._delegate.search(request)


def create_scenario_app() -> FastAPI:
    """Compose the production H5 path with safe scenario controls."""

    trace = TraceLog(TRACE_PATH)
    trace.clear()
    control = ScenarioControl(trace)
    configured = HarnessSettings(
        principal_id=control.principal_id,
        machine_id=MACHINE_ID,
        agent_id=AGENT_ID,
        # Pins bypass the token budget. A one-token context makes regular
        # budget zero, guaranteeing our sole regular candidate is a near miss.
        model_context_tokens=1,
    )
    token = configured.spine_token
    if token is None or not token.get_secret_value().strip():
        raise ValueError("SPINE_TOKEN is required in Harness/.env for H5 verification")
    traced_spine = TracingSpine(
        SpineClient(configured.spine_url, token.get_secret_value()),
        control,
    )
    model = _scenario_model(control)
    harness_app = create_dev_app(
        settings=configured,
        agent=HarnessAgent(configured, model=model),
        spine=traced_spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="Harness H5 verification")
    install_fixture_isolation(app, "H5 REGRESSION")

    @app.get("/__scenario__/health")
    async def scenario_health() -> Mapping[str, object]:
        return {
            "ok": True,
            "principal_id": control.principal_id,
            "seeded": bool(control.seeded),
        }

    @app.get("/__scenario__/expectation")
    async def scenario_expectation() -> Mapping[str, object]:
        return {
            "first_prompt": FIRST_PROMPT,
            "second_prompt": SECOND_PROMPT,
            "decisions": {
                "not_relevant": "not_relevant",
                "wrong": "wrong",
                "never": "never",
                "add_back": "added_back",
                "wrong_resolution": {
                    "action": "edit",
                    "body": CORRECTED_WRONG_BODY,
                },
            },
            "roles": {role: item.public_record() for role, item in control.seeded.items()},
        }

    @app.post("/__scenario__/seed")
    async def scenario_seed() -> Mapping[str, object]:
        if control.seeded:
            raise HTTPException(
                status_code=409,
                detail="seed IDs already exist; call cleanup before seeding again",
            )
        control.reset_trace()
        for definition in SEED_DEFINITIONS:
            created = await traced_spine.create_memory(
                CreateMemoryRequest(
                    principal_id=control.principal_id,
                    label=definition.label,
                    body=definition.body,
                    kind=definition.kind,
                    keywords=list(definition.keywords),
                    project_key=None,
                    thread_origin=None,
                    origin_path="verification/h5",
                    editor=EDITOR,
                    machine_id=MACHINE_ID,
                    force=True,
                )
            )
            if not isinstance(created, CreatedMemoryResponse):
                raise RuntimeError("forced verification seed did not create a memory")
            memory = created.created
            control.seeded[definition.role] = SeededMemory(definition.role, memory)
            if definition.pin:
                memory = await traced_spine.patch_memory(
                    memory.memory_id,
                    PatchMemoryRequest(
                        expected_revision=memory.revision,
                        pin=True,
                        editor=EDITOR,
                        reason="H5 verification: guarantee injected gate card",
                        machine_id=MACHINE_ID,
                    ),
                )
                control.seeded[definition.role] = SeededMemory(definition.role, memory)
        control.trace_seeded()
        return {
            "ok": True,
            "principal_id": control.principal_id,
            "roles": {role: item.public_record() for role, item in control.seeded.items()},
        }

    @app.post("/__scenario__/reset")
    async def scenario_reset() -> Mapping[str, bool]:
        control.reset_trace()
        return {"ok": True}

    @app.post("/__scenario__/assert-paused")
    async def scenario_assert_paused() -> Mapping[str, object]:
        state = {
            "prepare_calls": control.prepare_calls,
            "prepare_results": control.prepare_results,
            "commit_calls": control.commit_calls,
            "commit_results": control.commit_results,
            "model_calls": control.model_calls,
        }
        expected = {
            "prepare_calls": 1,
            "prepare_results": 1,
            "commit_calls": 0,
            "commit_results": 0,
            "model_calls": 0,
        }
        if state != expected:
            raise HTTPException(
                status_code=409,
                detail={"message": "run is not paused at the prepared gate", **state},
            )
        control.trace.record("scenario.pause_checked", **state)
        return {"ok": True, **state}

    @app.post("/__scenario__/assert-wrong-paused")
    async def scenario_assert_wrong_paused() -> Mapping[str, object]:
        state = {
            "prepare_calls": control.prepare_calls,
            "prepare_results": control.prepare_results,
            "commit_calls": control.commit_calls,
            "commit_results": control.commit_results,
            "model_calls": control.model_calls,
        }
        expected = {
            "prepare_calls": 1,
            "prepare_results": 1,
            "commit_calls": 1,
            "commit_results": 1,
            "model_calls": 0,
        }
        if state != expected:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "run is not paused at wrong-memory resolution",
                    **state,
                },
            )
        control.trace.record("scenario.wrong_pause_checked", **state)
        return {"ok": True, **state}

    @app.post("/__scenario__/fail-next/{phase}")
    async def scenario_fail_next(phase: str) -> Mapping[str, object]:
        try:
            control.arm_failure(phase)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True, "phase": phase}

    @app.post("/__scenario__/cleanup")
    async def scenario_cleanup() -> Mapping[str, object]:
        cleaned: list[str] = []
        for item in tuple(control.seeded.values()):
            await _tombstone_exact(traced_spine, item.memory)
            cleaned.append(str(item.memory.memory_id))
        control.trace.record("scenario.cleaned", memory_ids=cleaned)
        control.seeded.clear()
        return {"ok": True, "tombstoned": cleaned}

    app.mount("/", harness_app)
    return app


def _scenario_model(control: ScenarioControl) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo):
        control.model_calls += 1
        prompt = _latest_prompt(messages)
        control.trace.record(
            "model.call",
            call=control.model_calls,
            prompt_sha256=_digest(prompt),
            prompt_length=len(prompt),
            instructions=info.instructions,
        )
        yield f"H5 deterministic model response {control.model_calls}."

    return FunctionModel(stream_function=respond, model_name="local:h5-verification")


def _latest_prompt(messages: Sequence[ModelMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    raise ValueError("deterministic H5 model received no string user prompt")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scored_card_record(card: Any) -> dict[str, object]:
    return {
        "memory_id": str(card.memory_id),
        "label": card.label,
        "body": card.body,
        "kind": card.kind.value,
        "pin": card.pin,
        "score": card.score,
        "features": card.features.model_dump(mode="json"),
        "rank": card.rank,
    }


def _wrong_memory_record(memory: MemoryUnit) -> dict[str, object]:
    return {
        "memory_id": str(memory.memory_id),
        "revision": memory.revision,
        "body": memory.body,
        "status": memory.status.value,
    }


async def _tombstone_exact(spine: TracingSpine, memory: MemoryUnit) -> None:
    expected_revision = memory.revision
    for _ in range(3):
        try:
            await spine.patch_memory(
                memory.memory_id,
                PatchMemoryRequest(
                    expected_revision=expected_revision,
                    status=MemoryStatus.TOMBSTONED,
                    editor=EDITOR,
                    reason="H5 verification cleanup: tombstone exact fixture ID",
                    machine_id=MACHINE_ID,
                ),
            )
            return
        except PatchMemoryConflictError as exc:
            if not isinstance(exc.conflict, RevisionConflict):
                raise
            current = exc.conflict.conflict
            if current.memory_id != memory.memory_id:
                raise RuntimeError("Spine returned a conflict for the wrong memory ID") from exc
            if current.status is MemoryStatus.TOMBSTONED:
                return
            expected_revision = current.revision
    raise RuntimeError(f"could not tombstone exact H5 seed {memory.memory_id} after CAS retries")


__all__ = [
    "CORRECTED_WRONG_BODY",
    "FIRST_PROMPT",
    "SECOND_PROMPT",
    "TRACE_PATH",
    "create_scenario_app",
]
