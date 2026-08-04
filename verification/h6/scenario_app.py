"""Live-Spine, deterministic-model fixture for H6 browser verification.

Run from the Harness repository root::

    PYTHONPATH=src:. uv run --locked python -m verification.run_fixture \
      verification.h6.scenario_app:create_scenario_app --port 8766

The browser exercises the production SPA, WebSocket daemon, memory gate,
memory-panel controller, run loop, and configured deployed Spine. Only the
downstream model is local and deterministic. Scenario endpoints create and
tombstone only IDs owned by this fixture process under fresh synthetic
principals.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
)
from verification.fixture_isolation import install_fixture_isolation

TRACE_PATH = Path(__file__).with_name("trace.jsonl")
FIRST_PROMPT = "Open the H6 verification thread context."
SECOND_PROMPT = "Report which H6 context markers are present now."
REMOVE_MARKER = "H6_REMOVE_MARKER_7319"
KEEP_MARKER = "H6_KEEP_MARKER_8642"
EDIT_ORIGINAL_MARKER = "H6_EDIT_ORIGINAL_MARKER_4158"
PIN_MARKER = "H6_PIN_MARKER_2094"
EDITED_BODY = "H6 edit saved through the memory panel with compare-and-swap."
CONFLICT_DRAFT_BODY = "H6 draft that must survive a visible revision conflict."
CONFLICT_CURRENT_BODY = "H6 concurrent editor won this revision before panel save."
MACHINE_ID = "h6-sop-verification"
AGENT_ID = "h6-verification-agent"
EDITOR = "verification:h6"


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
        role="thread_remove",
        label="H6 thread context — remove",
        body=f"{REMOVE_MARKER}: remove this only from the open thread context.",
        kind=MemoryKind.FACT,
        keywords=("H6", "remove", "thread", "context"),
        pin=True,
    ),
    SeedDefinition(
        role="thread_keep",
        label="H6 thread context — retain",
        body=f"{KEEP_MARKER}: retain this in the open thread context.",
        kind=MemoryKind.FACT,
        keywords=("H6", "retain", "thread", "context"),
        pin=True,
    ),
    SeedDefinition(
        role="edit_success",
        label="H6 panel edit",
        body=f"{EDIT_ORIGINAL_MARKER}: this frozen thread fragment must not be rewritten.",
        kind=MemoryKind.PROCEDURE,
        keywords=("H6", "panel", "edit"),
        pin=True,
    ),
    SeedDefinition(
        role="edit_conflict",
        label="H6 panel conflict",
        body="H6 body before the concurrent edit.",
        kind=MemoryKind.PROCEDURE,
        keywords=("H6", "panel", "conflict"),
        pin=False,
    ),
    SeedDefinition(
        role="pin_toggle",
        label="H6 panel pin",
        body=f"{PIN_MARKER}: future pin candidacy must not rewrite this thread.",
        kind=MemoryKind.PREFERENCE,
        keywords=("H6", "panel", "pin"),
        pin=False,
    ),
)

FOREIGN_DEFINITION = SeedDefinition(
    role="foreign_sentinel",
    label="H6 foreign-principal sentinel",
    body="Synthetic isolation sentinel: this must never cross the browser boundary.",
    kind=MemoryKind.FACT,
    keywords=("H6", "foreign", "sentinel"),
    pin=False,
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
    """Own exact seed IDs and all privacy-safe fixture observations."""

    def __init__(self, trace: TraceLog) -> None:
        suffix = uuid4().hex
        self.trace = trace
        self.principal_id = f"h6-verification-{suffix}"
        self.foreign_principal_id = f"h6-verification-foreign-{suffix}"
        self.seeded: dict[str, SeededMemory] = {}
        self.foreign: SeededMemory | None = None
        self.conflict_staged = False
        self.model_calls = 0
        self.last_injection_id: UUID | None = None

    def reset_trace(self) -> None:
        self.conflict_staged = False
        self.model_calls = 0
        self.last_injection_id = None
        self.trace.clear()

    def all_seeded(self) -> tuple[SeededMemory, ...]:
        foreign = () if self.foreign is None else (self.foreign,)
        return (*self.seeded.values(), *foreign)

    def role_for_id(self, memory_id: UUID | str) -> str | None:
        value = str(memory_id)
        for item in self.all_seeded():
            if str(item.memory.memory_id) == value:
                return item.role
        return None

    def replace(self, memory: MemoryUnit) -> None:
        role = self.role_for_id(memory.memory_id)
        if role is None:
            return
        updated = SeededMemory(role, memory)
        if role == FOREIGN_DEFINITION.role:
            self.foreign = updated
        else:
            self.seeded[role] = updated

    def trace_seeded(self) -> None:
        if self.foreign is None:
            raise RuntimeError("foreign sentinel was not seeded")
        self.trace.record(
            "scenario.seeded",
            principal_id=self.principal_id,
            roles={role: item.public_record() for role, item in self.seeded.items()},
            foreign=self.foreign.public_record(),
        )


class TracingSpine:
    """Trace exact H6 C.4 boundaries while delegating to deployed Spine."""

    def __init__(self, delegate: SpineClient, control: ScenarioControl) -> None:
        self._delegate = delegate
        self._control = control

    async def aclose(self) -> None:
        await self._delegate.aclose()

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        self._control.trace.record(
            "spine.prepare.call",
            thread_id=str(request.thread_id),
            principal_matches=request.principal_id == self._control.principal_id,
            prompt_sha256=_digest(request.prompt),
            model_context_tokens=request.model_context_tokens,
        )
        response = await self._delegate.prepare_injection(request)
        self._control.last_injection_id = response.injection_id
        self._control.trace.record(
            "spine.prepare.result",
            injection_id=str(response.injection_id),
            injected=[self._control.role_for_id(card.memory_id) for card in response.injected],
            near_misses=[
                self._control.role_for_id(card.memory_id) for card in response.near_misses
            ],
        )
        return response

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        self._control.trace.record(
            "spine.commit.call",
            injection_id=str(request.injection_id),
            matches_prepared=request.injection_id == self._control.last_injection_id,
            removed=[
                {
                    "role": self._control.role_for_id(item.memory_id),
                    "reason": item.reason.value,
                }
                for item in request.removed
            ],
            added_back=[self._control.role_for_id(memory_id) for memory_id in request.added_back],
        )
        response = await self._delegate.commit_injection(request)
        self._control.trace.record(
            "spine.commit.result",
            final_block_sha256=_digest(response.final_block),
            memory_block_count=response.final_block.count("<memory_system>"),
            keep_present=KEEP_MARKER in response.final_block,
            remove_present=REMOVE_MARKER in response.final_block,
            edit_original_present=EDIT_ORIGINAL_MARKER in response.final_block,
            pin_present=PIN_MARKER in response.final_block,
            wrong_removed=[
                self._control.role_for_id(item.memory_id) for item in response.wrong_removed
            ],
        )
        return response

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        self._control.trace.record(
            "spine.feedback.call",
            injection_id=str(request.injection_id),
            matches_committed=request.injection_id == self._control.last_injection_id,
            role=self._control.role_for_id(request.memory_id),
            signal=request.signal.value,
        )
        response = await self._delegate.submit_feedback(request)
        self._control.trace.record(
            "spine.feedback.result",
            role=self._control.role_for_id(request.memory_id),
            ok=response.ok,
        )
        return response

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        return await self._delegate.create_memory(request)

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse:
        role = self._control.role_for_id(memory_id)
        if role is not None:
            self._control.trace.record(
                "spine.patch.call",
                role=role,
                expected_revision=request.expected_revision,
                body=request.body,
                pin=request.pin,
                status=request.status.value if request.status is not None else None,
                editor=request.editor,
                reason=request.reason,
                machine_id=request.machine_id,
            )
        try:
            response = await self._delegate.patch_memory(memory_id, request)
        except PatchMemoryConflictError as exc:
            if role is not None and isinstance(exc.conflict, RevisionConflict):
                current = exc.conflict.conflict
                self._control.replace(current)
                self._control.trace.record(
                    "spine.patch.conflict",
                    role=role,
                    expected_revision=request.expected_revision,
                    current_revision=current.revision,
                    current_body=current.body,
                    current_pin=current.pin,
                    current_status=current.status.value,
                    reason=request.reason,
                )
            raise
        if role is not None:
            self._control.replace(response)
            self._control.trace.record(
                "spine.patch.result",
                role=role,
                revision=response.revision,
                body=response.body,
                pin=response.pin,
                status=response.status.value,
                reason=request.reason,
            )
        return response

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        response = await self._delegate.list_memories(params)
        fixture_items = [
            {
                "role": role,
                "status": item.status.value,
                "revision": item.revision,
            }
            for item in response.items
            if (role := self._control.role_for_id(item.memory_id)) is not None
        ]
        self._control.trace.record(
            "spine.list.result",
            requested_status=params.status.value if params.status is not None else None,
            limit=params.limit,
            offset=params.offset,
            page_size=len(response.items),
            fixture_items=fixture_items,
        )
        return response

    async def search(self, request: SearchRequest) -> SearchResponse:
        return await self._delegate.search(request)


class PanelFrameTrace:
    """Observe sanitized D→C panel frames without replacing production code."""

    def __init__(self, app: ASGIApp, control: ScenarioControl) -> None:
        self._app = app
        self._control = control

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def traced_send(message: Message) -> None:
            if scope["type"] == "websocket" and message["type"] == "websocket.send":
                self._observe(message)
            await send(message)

        await self._app(scope, receive, traced_send)

    def _observe(self, message: Message) -> None:
        raw = message.get("text")
        if not isinstance(raw, str):
            return
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            return
        if not isinstance(envelope, dict) or envelope.get("type") != "memory.panel.update":
            return
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return
        action = payload.get("action")
        if action == "state":
            summaries: list[dict[str, object]] = []
            unknown_count = 0
            principal_mismatch_count = 0
            foreign_visible = False
            items = payload.get("items")
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("memory"), dict):
                    unknown_count += 1
                    continue
                memory = item["memory"]
                memory_id = memory.get("memory_id")
                role = self._control.role_for_id(memory_id) if isinstance(memory_id, str) else None
                principal_id = memory.get("principal_id")
                if principal_id != self._control.principal_id:
                    principal_mismatch_count += 1
                if role == FOREIGN_DEFINITION.role:
                    foreign_visible = True
                if role not in self._control.seeded:
                    unknown_count += 1
                    continue
                summaries.append(
                    {
                        "role": role,
                        "in_context": item.get("in_context"),
                        "revision": memory.get("revision"),
                        "pin": memory.get("pin"),
                        "body": memory.get("body"),
                    }
                )
            self._control.trace.record(
                "browser.panel.state",
                request_id=payload.get("request_id"),
                result=payload.get("result"),
                total=payload.get("total"),
                items=summaries,
                unknown_count=unknown_count,
                principal_mismatch_count=principal_mismatch_count,
                foreign_visible=foreign_visible,
            )
        elif action == "conflict":
            memory = payload.get("memory")
            memory_id = memory.get("memory_id") if isinstance(memory, dict) else None
            role = self._control.role_for_id(memory_id) if isinstance(memory_id, str) else None
            self._control.trace.record(
                "browser.panel.conflict",
                request_id=payload.get("request_id"),
                operation=payload.get("operation"),
                role=role,
                current_revision=(memory.get("revision") if isinstance(memory, dict) else None),
                current_body=memory.get("body") if isinstance(memory, dict) else None,
            )
        elif action == "error":
            self._control.trace.record(
                "browser.panel.error",
                request_id=payload.get("request_id"),
                operation=payload.get("operation"),
                code=payload.get("code"),
            )


def create_scenario_app() -> FastAPI:
    """Compose the production H6 path with safe scenario controls."""

    trace = TraceLog(TRACE_PATH)
    trace.clear()
    control = ScenarioControl(trace)
    configured = HarnessSettings(
        principal_id=control.principal_id,
        machine_id=MACHINE_ID,
        agent_id=AGENT_ID,
        # Pins bypass the regular token budget. One context token makes all
        # unpinned fixture units deterministic near misses.
        model_context_tokens=1,
    )
    token = configured.spine_token
    if token is None or not token.get_secret_value().strip():
        raise ValueError("SPINE_TOKEN is required in .env for H6 verification")
    traced_spine = TracingSpine(
        SpineClient(configured.spine_url, token.get_secret_value()),
        control,
    )
    harness_app = create_dev_app(
        settings=configured,
        agent=HarnessAgent(configured, model=_scenario_model(control)),
        spine=traced_spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="Harness H6 verification")
    install_fixture_isolation(app, "H6 REGRESSION")

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
            "edited_body": EDITED_BODY,
            "conflict_draft_body": CONFLICT_DRAFT_BODY,
            "conflict_current_body": CONFLICT_CURRENT_BODY,
            "roles": {role: item.public_record() for role, item in control.seeded.items()},
            "foreign": (control.foreign.public_record() if control.foreign is not None else None),
        }

    @app.post("/__scenario__/seed")
    async def scenario_seed() -> Mapping[str, object]:
        if control.seeded or control.foreign is not None:
            raise HTTPException(
                status_code=409,
                detail="seed IDs already exist; call cleanup before seeding again",
            )
        control.reset_trace()
        for definition in SEED_DEFINITIONS:
            memory = await _create_seed(
                traced_spine,
                principal_id=control.principal_id,
                definition=definition,
            )
            control.seeded[definition.role] = SeededMemory(definition.role, memory)
            if definition.pin:
                memory = await traced_spine.patch_memory(
                    memory.memory_id,
                    PatchMemoryRequest(
                        expected_revision=memory.revision,
                        pin=True,
                        editor=EDITOR,
                        reason="H6 verification setup: guarantee injected context",
                        machine_id=MACHINE_ID,
                    ),
                )
                control.seeded[definition.role] = SeededMemory(definition.role, memory)

        foreign = await _create_seed(
            traced_spine,
            principal_id=control.foreign_principal_id,
            definition=FOREIGN_DEFINITION,
        )
        control.foreign = SeededMemory(FOREIGN_DEFINITION.role, foreign)
        control.trace_seeded()
        return {
            "ok": True,
            "principal_id": control.principal_id,
            "visible_roles": {role: item.public_record() for role, item in control.seeded.items()},
            "foreign_sentinel_id": str(foreign.memory_id),
        }

    @app.post("/__scenario__/stage-conflict")
    async def scenario_stage_conflict() -> Mapping[str, object]:
        if control.conflict_staged:
            raise HTTPException(status_code=409, detail="conflict already staged")
        try:
            current = control.seeded["edit_conflict"].memory
        except KeyError as exc:
            raise HTTPException(status_code=409, detail="seed before staging conflict") from exc
        updated = await traced_spine.patch_memory(
            current.memory_id,
            PatchMemoryRequest(
                expected_revision=current.revision,
                body=CONFLICT_CURRENT_BODY,
                editor=EDITOR,
                reason="H6 verification setup: concurrent editor",
                machine_id=MACHINE_ID,
            ),
        )
        control.seeded["edit_conflict"] = SeededMemory("edit_conflict", updated)
        control.conflict_staged = True
        control.trace.record(
            "scenario.conflict_staged",
            role="edit_conflict",
            revision=updated.revision,
            body=updated.body,
        )
        return {
            "ok": True,
            "memory_id": str(updated.memory_id),
            "revision": updated.revision,
            "body": updated.body,
        }

    @app.post("/__scenario__/cleanup")
    async def scenario_cleanup() -> Mapping[str, object]:
        exact = tuple(control.all_seeded())
        if not exact:
            raise HTTPException(status_code=409, detail="there are no exact seed IDs to clean")
        cleaned: list[str] = []
        exact_ids = {item.memory.memory_id for item in exact}
        for item in exact:
            await _tombstone_exact(traced_spine, item.memory)
            cleaned.append(str(item.memory.memory_id))
        remaining_active = await _active_exact_ids(traced_spine, exact_ids)
        if remaining_active:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "exact fixture IDs remain active after cleanup",
                    "memory_ids": sorted(str(item) for item in remaining_active),
                },
            )
        control.trace.record(
            "scenario.cleaned",
            memory_ids=cleaned,
            remaining_active_ids=[],
        )
        control.seeded.clear()
        control.foreign = None
        return {
            "ok": True,
            "tombstoned": cleaned,
            "remaining_active_ids": [],
        }

    app.mount("/", PanelFrameTrace(harness_app, control))
    return app


async def _create_seed(
    spine: TracingSpine,
    *,
    principal_id: str,
    definition: SeedDefinition,
) -> MemoryUnit:
    created = await spine.create_memory(
        CreateMemoryRequest(
            principal_id=principal_id,
            label=definition.label,
            body=definition.body,
            kind=definition.kind,
            keywords=list(definition.keywords),
            project_key=None,
            thread_origin=None,
            origin_path="verification/h6",
            editor=EDITOR,
            machine_id=MACHINE_ID,
            force=True,
        )
    )
    if not isinstance(created, CreatedMemoryResponse):
        raise RuntimeError("forced verification seed did not create a memory")
    return created.created


def _scenario_model(control: ScenarioControl) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo):
        control.model_calls += 1
        prompt = _latest_prompt(messages)
        instructions = info.instructions or ""
        keep_present = KEEP_MARKER in instructions
        remove_present = REMOVE_MARKER in instructions
        edit_original_present = EDIT_ORIGINAL_MARKER in instructions
        edited_body_present = EDITED_BODY in instructions
        pin_present = PIN_MARKER in instructions
        control.trace.record(
            "model.call",
            call=control.model_calls,
            prompt_sha256=_digest(prompt),
            instructions_sha256=_digest(instructions),
            memory_block_count=instructions.count("<memory_system>"),
            keep_present=keep_present,
            remove_present=remove_present,
            edit_original_present=edit_original_present,
            edited_body_present=edited_body_present,
            pin_present=pin_present,
        )
        yield (
            f"H6 context check {control.model_calls}: retained marker "
            f"{'present' if keep_present else 'absent'}; removed marker "
            f"{'present' if remove_present else 'absent'}; frozen edit marker "
            f"{'present' if edit_original_present else 'absent'}; newly pinned marker "
            f"{'present' if pin_present else 'absent'}."
        )

    return FunctionModel(stream_function=respond, model_name="local:h6-verification")


def _latest_prompt(messages: Sequence[ModelMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    raise ValueError("deterministic H6 model received no string user prompt")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _active_exact_ids(spine: TracingSpine, exact_ids: set[UUID]) -> set[UUID]:
    remaining: set[UUID] = set()
    offset = 0
    while True:
        page = await spine.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=200, offset=offset)
        )
        remaining.update(item.memory_id for item in page.items if item.memory_id in exact_ids)
        if not page.items or offset + len(page.items) >= page.total:
            return remaining
        offset += len(page.items)


async def _tombstone_exact(spine: TracingSpine, memory: MemoryUnit) -> MemoryUnit:
    expected_revision = memory.revision
    for _ in range(3):
        try:
            return await spine.patch_memory(
                memory.memory_id,
                PatchMemoryRequest(
                    expected_revision=expected_revision,
                    status=MemoryStatus.TOMBSTONED,
                    editor=EDITOR,
                    reason="H6 verification cleanup: tombstone exact fixture ID",
                    machine_id=MACHINE_ID,
                ),
            )
        except PatchMemoryConflictError as exc:
            if not isinstance(exc.conflict, RevisionConflict):
                raise
            current = exc.conflict.conflict
            if current.memory_id != memory.memory_id:
                raise RuntimeError("Spine returned a conflict for the wrong memory ID") from exc
            if current.status is MemoryStatus.TOMBSTONED:
                return current
            expected_revision = current.revision
    raise RuntimeError(f"could not tombstone exact H6 seed {memory.memory_id} after CAS retries")


__all__ = [
    "CONFLICT_CURRENT_BODY",
    "CONFLICT_DRAFT_BODY",
    "EDITED_BODY",
    "FIRST_PROMPT",
    "SECOND_PROMPT",
    "TRACE_PATH",
    "create_scenario_app",
]
