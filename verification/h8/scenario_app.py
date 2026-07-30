"""Live-Spine, deterministic-model fixture for H8 browser verification.

Run from the Harness repository root::

    PYTHONPATH=src uv run --locked uvicorn \
      scenario_app:create_scenario_app --factory \
      --app-dir verification/h8 --host 127.0.0.1 --port 8768

The browser exercises the production SPA, WebSocket daemon, run loop,
``/remember`` path, and configured deployed Spine. Only the downstream model
is local and deterministic. Cleanup CAS-tombstones only the exact memory ID
created by this fixture process.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
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

TRACE_PATH = Path(__file__).with_name("trace.jsonl")
MODEL_SLUG = "local:h8-verification"
MACHINE_ID = "h8-sop-verification"
AGENT_ID = "h8-verification-agent"
EDITOR = "verification:h8"

REMEMBER_BODY = "H8 remembers that Markdown evidence needs readable tables and code."
REMEMBER_COMMAND = f"/remember {REMEMBER_BODY}"
REMEMBER_MODEL_PROMPT = f"Memory:\n{REMEMBER_BODY}"
REMEMBER_LABEL = "Readable Markdown evidence"
REMEMBER_KEYWORDS = ("markdown", "tables", "code")
REMEMBER_MODEL_OUTPUT = json.dumps(
    {
        "label": REMEMBER_LABEL,
        "keywords": list(REMEMBER_KEYWORDS),
    }
)

MARKDOWN_PROMPT = (
    "Show the H8 Markdown proof. Keep **plain-user-text** literal in my message "
    'and treat <button data-h8-user-raw="true">unsafe</button> as text.'
)
MARKDOWN_RESPONSE = """## H8 Markdown proof

**Bold text** and *italic text* remain readable.

- First list item
- Second list item

| Surface | Result |
| --- | --- |
| Table | Pass |
| Code | Pass |

```python
print("h8")
```

<button data-h8-raw="true">Unsafe button</button>
<script>globalThis.__h8RawHtmlExecuted = true</script>
"""


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


class ScenarioControl:
    """Own the fresh principal, exact created ID, and sanitized observations."""

    def __init__(self, trace: TraceLog) -> None:
        self.trace = trace
        self.principal_id = f"h8-verification-{uuid4().hex}"
        self.created: MemoryUnit | None = None

    def trace_started(self) -> None:
        self.trace.record(
            "scenario.started",
            principal_id=self.principal_id,
            machine_id=MACHINE_ID,
            agent_id=AGENT_ID,
            resolved_model=MODEL_SLUG,
        )


class TracingHarnessAgent(HarnessAgent):
    """Record an unexpected `/remember` exception before the run loop contains it."""

    def __init__(self, control: ScenarioControl, *args: Any, **kwargs: Any) -> None:
        self._scenario_control = control
        super().__init__(*args, **kwargs)

    async def remember(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await super().remember(*args, **kwargs)
        except Exception as exc:
            self._scenario_control.trace.record(
                "agent.remember.exception",
                exception_type=type(exc).__name__,
                message=str(exc),
            )
            raise


class TracingSpine:
    """Trace the exact H8 save while delegating every C.4 call to Spine."""

    def __init__(self, delegate: SpineClient, control: ScenarioControl) -> None:
        self._delegate = delegate
        self._control = control

    async def aclose(self) -> None:
        await self._delegate.aclose()

    async def prepare_injection(self, request: InjectPrepareRequest) -> InjectPrepareResponse:
        return await self._delegate.prepare_injection(request)

    async def commit_injection(self, request: InjectCommitRequest) -> InjectCommitResponse:
        return await self._delegate.commit_injection(request)

    async def submit_feedback(self, request: FeedbackRequest) -> FeedbackResponse:
        return await self._delegate.submit_feedback(request)

    async def create_memory(self, request: CreateMemoryRequest) -> CreateMemoryResponse:
        if self._control.created is not None:
            self._control.trace.record(
                "spine.create.rejected",
                reason="fixture already owns one exact memory ID",
                existing_memory_id=str(self._control.created.memory_id),
            )
            raise RuntimeError(
                "H8 verification fixture refuses a second memory before exact-ID cleanup"
            )
        self._control.trace.record(
            "spine.create.call",
            principal_matches=request.principal_id == self._control.principal_id,
            label=request.label,
            body_sha256=_digest(request.body),
            memory_kind=request.kind.value,
            keywords=request.keywords,
            project_key=request.project_key,
            thread_origin=request.thread_origin,
            origin_path=request.origin_path,
            editor=request.editor,
            machine_id=request.machine_id,
            force=request.force,
        )
        response = await self._delegate.create_memory(request)
        if isinstance(response, CreatedMemoryResponse):
            created = response.created
            self._control.created = created
            self._control.trace.record(
                "spine.create.result",
                outcome="created",
                memory_id=str(created.memory_id),
                label=created.label,
                body_sha256=_digest(created.body),
                keywords=created.keywords,
                status=created.status.value,
                revision=created.revision,
            )
        else:
            self._control.trace.record(
                "spine.create.result",
                outcome="not_created",
                response_type=type(response).__name__,
            )
        return response

    async def patch_memory(
        self, memory_id: UUID, request: PatchMemoryRequest
    ) -> PatchMemoryResponse:
        is_fixture = (
            self._control.created is not None and memory_id == self._control.created.memory_id
        )
        if is_fixture:
            self._control.trace.record(
                "spine.patch.call",
                memory_id=str(memory_id),
                expected_revision=request.expected_revision,
                status=request.status.value if request.status is not None else None,
                editor=request.editor,
                reason=request.reason,
                machine_id=request.machine_id,
            )
        try:
            response = await self._delegate.patch_memory(memory_id, request)
        except PatchMemoryConflictError as exc:
            if is_fixture and isinstance(exc.conflict, RevisionConflict):
                current = exc.conflict.conflict
                self._control.trace.record(
                    "spine.patch.conflict",
                    memory_id=str(memory_id),
                    expected_revision=request.expected_revision,
                    current_revision=current.revision,
                    current_status=current.status.value,
                )
            raise
        if is_fixture:
            self._control.trace.record(
                "spine.patch.result",
                memory_id=str(response.memory_id),
                status=response.status.value,
                revision=response.revision,
            )
        return response

    async def list_memories(self, params: ListMemoriesParams) -> PagedMemoryListResponse:
        return await self._delegate.list_memories(params)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return await self._delegate.search(request)


class WireTrace:
    """Observe sanitized browser↔daemon H8 frames without replacing production code."""

    def __init__(self, app: ASGIApp, control: ScenarioControl) -> None:
        self._app = app
        self._control = control

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def traced_receive() -> Message:
            message = await receive()
            if scope["type"] == "websocket" and message["type"] == "websocket.receive":
                self._observe_client(message)
            return message

        async def traced_send(message: Message) -> None:
            if scope["type"] == "websocket" and message["type"] == "websocket.send":
                self._observe_server(message)
            await send(message)

        await self._app(scope, traced_receive, traced_send)

    def _observe_client(self, message: Message) -> None:
        envelope = _decode_wire_message(message)
        if envelope is None or envelope.get("type") != "prompt.submit":
            return
        payload = envelope.get("payload")
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if not isinstance(prompt, str):
            return
        self._control.trace.record(
            "wire.prompt.submit",
            prompt_id=envelope.get("id"),
            thread_id=envelope.get("thread_id"),
            purpose=_prompt_purpose(prompt),
            prompt_sha256=_digest(prompt),
        )

    def _observe_server(self, message: Message) -> None:
        envelope = _decode_wire_message(message)
        if envelope is None:
            return
        message_type = envelope.get("type")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return
        if message_type == "thread.snapshot":
            self._control.trace.record(
                "wire.thread.snapshot",
                thread_id=envelope.get("thread_id"),
                resolved_model=payload.get("resolved_model"),
                message_count=(
                    len(payload["messages"]) if isinstance(payload.get("messages"), list) else None
                ),
            )
        elif message_type == "run.started":
            self._control.trace.record(
                "wire.run.started",
                thread_id=envelope.get("thread_id"),
                run_id=payload.get("run_id"),
                prompt_id=payload.get("prompt_id"),
                resolved_model=payload.get("resolved_model"),
            )
        elif message_type == "run.delta" and payload.get("kind") == "text":
            self._control.trace.record(
                "wire.run.text",
                thread_id=envelope.get("thread_id"),
                run_id=payload.get("run_id"),
                text=payload.get("text"),
            )
        elif message_type == "run.done":
            self._control.trace.record(
                "wire.run.done",
                thread_id=envelope.get("thread_id"),
                run_id=payload.get("run_id"),
                stop_reason=payload.get("stop_reason"),
                partial=payload.get("partial"),
            )
        elif message_type == "error":
            self._control.trace.record(
                "wire.error",
                thread_id=envelope.get("thread_id"),
                payload=payload,
            )


def create_scenario_app() -> FastAPI:
    """Compose the production H8 path with exact fixture controls."""

    trace = TraceLog(TRACE_PATH)
    trace.clear()
    control = ScenarioControl(trace)
    control.trace_started()
    configured = HarnessSettings(
        principal_id=control.principal_id,
        machine_id=MACHINE_ID,
        agent_id=AGENT_ID,
        chat_model=MODEL_SLUG,
        model_context_tokens=1,
    )
    token = configured.spine_token
    if token is None or not token.get_secret_value().strip():
        raise ValueError("SPINE_TOKEN is required in .env for H8 verification")
    traced_spine = TracingSpine(
        SpineClient(configured.spine_url, token.get_secret_value()),
        control,
    )
    harness_app = create_dev_app(
        settings=configured,
        agent=TracingHarnessAgent(
            control,
            configured,
            model=_scenario_model(control),
        ),
        spine=traced_spine,  # type: ignore[arg-type]
    )
    app = FastAPI(title="Harness H8 verification")

    @app.get("/__scenario__/health")
    async def scenario_health() -> Mapping[str, object]:
        return {
            "ok": True,
            "principal_id": control.principal_id,
            "resolved_model": MODEL_SLUG,
            "created_memory_id": (
                str(control.created.memory_id) if control.created is not None else None
            ),
        }

    @app.get("/__scenario__/expectation")
    async def scenario_expectation() -> Mapping[str, object]:
        return {
            "remember_command": REMEMBER_COMMAND,
            "remember_label": REMEMBER_LABEL,
            "remember_keywords": list(REMEMBER_KEYWORDS),
            "markdown_prompt": MARKDOWN_PROMPT,
            "markdown_response": MARKDOWN_RESPONSE,
            "resolved_model": MODEL_SLUG,
        }

    @app.post("/__scenario__/cleanup")
    async def scenario_cleanup() -> Mapping[str, object]:
        created = control.created
        if created is None:
            raise HTTPException(status_code=409, detail="there is no exact H8 memory to clean")
        cleaned = await _tombstone_exact(traced_spine, created)
        remaining_active = await _active_exact_ids(traced_spine, {created.memory_id})
        if remaining_active:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "the exact H8 fixture ID remains active after cleanup",
                    "memory_ids": sorted(str(item) for item in remaining_active),
                },
            )
        control.trace.record(
            "scenario.cleaned",
            memory_ids=[str(created.memory_id)],
            final_revision=cleaned.revision,
            remaining_active_ids=[],
        )
        control.created = None
        return {
            "ok": True,
            "tombstoned": [str(created.memory_id)],
            "remaining_active_ids": [],
        }

    app.mount("/", WireTrace(harness_app, control))
    return app


def _scenario_model(control: ScenarioControl) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        output = _model_output(control, messages, info)
        return ModelResponse(parts=[TextPart(output)])

    async def stream(messages: list[ModelMessage], info: AgentInfo):
        yield _model_output(control, messages, info)

    return FunctionModel(
        respond,
        stream_function=stream,
        model_name=MODEL_SLUG,
    )


def _model_output(
    control: ScenarioControl,
    messages: Sequence[ModelMessage],
    info: AgentInfo,
) -> str:
    prompt = _latest_prompt(messages)
    purpose = _model_prompt_purpose(prompt)
    output = REMEMBER_MODEL_OUTPUT if purpose == "remember" else MARKDOWN_RESPONSE
    instructions = info.instructions or ""
    control.trace.record(
        "model.call",
        purpose=purpose,
        resolved_model=MODEL_SLUG,
        prompt_sha256=_digest(prompt),
        instructions_sha256=_digest(instructions),
        function_tools=[tool.name for tool in info.function_tools],
        output_tools=[tool.name for tool in info.output_tools],
        allow_text_output=info.allow_text_output,
        output_sha256=_digest(output),
    )
    return output


def _latest_prompt(messages: Sequence[ModelMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    raise ValueError("deterministic H8 model received no string user prompt")


def _model_prompt_purpose(prompt: str) -> str:
    if prompt == REMEMBER_MODEL_PROMPT:
        return "remember"
    if prompt == MARKDOWN_PROMPT:
        return "markdown"
    raise ValueError(f"deterministic H8 model received an unexpected prompt: {prompt!r}")


def _prompt_purpose(prompt: str) -> str:
    if prompt == REMEMBER_COMMAND:
        return "remember"
    if prompt == MARKDOWN_PROMPT:
        return "markdown"
    return "unexpected"


def _decode_wire_message(message: Message) -> dict[str, object] | None:
    raw = message.get("text")
    if not isinstance(raw, str):
        return None
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


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
                    reason="H8 verification cleanup: tombstone exact fixture ID",
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
    raise RuntimeError(f"could not tombstone exact H8 memory {memory.memory_id} after CAS retries")


__all__ = [
    "MARKDOWN_PROMPT",
    "MARKDOWN_RESPONSE",
    "MODEL_SLUG",
    "REMEMBER_COMMAND",
    "REMEMBER_KEYWORDS",
    "REMEMBER_LABEL",
    "TRACE_PATH",
    "create_scenario_app",
]
