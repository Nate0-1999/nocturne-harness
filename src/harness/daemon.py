"""FastAPI daemon: built static shell plus the routed C.7 WebSocket seam."""

import argparse
import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from harness import __version__
from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner
from harness.commands import browser_open_web_command
from harness.config import HarnessSettings
from harness.context_window import ContextWindowSnapshot, ContextWindowTracker
from harness.envelope import (
    Envelope,
    EnvelopeFactory,
    GateCommitPayload,
    MessageType,
    PromptSubmitPayload,
    RunCancelPayload,
    StopReason,
    ThreadSnapshotRequestPayload,
)
from harness.extraction import ExtractionIdleScheduler, ExtractionService, ThreadEndResult
from harness.memory_gate import MemoryGateTurnRunner
from harness.memory_panel import MemoryPanelController, ThreadMemoryContextRegistry
from harness.model_policy import (
    ModelPolicyResolver,
    ThreadModelResolution,
    ThreadModelResolver,
)
from harness.model_router import CompletionRouter
from harness.onboarding import load_config, nocturne_home, set_transcript_backup
from harness.parameter_registry import (
    ParameterSnapshot,
    ParameterWriteRequest,
    ParameterWriteViolation,
)
from harness.progressive_prompt import workspace_location_path
from harness.pydantic_harness_adapter import discover_skill_libraries
from harness.rack_query import RackQueryResult
from harness.receipt_queue import SpendReceiptQueue
from harness.recipe_graph import RecipeGraphSnapshot
from harness.resources import ResourceWatch
from harness.run_loop import ProjectBindingConflict, RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.seed import SeedIngestionService, SeedUploadRequest
from harness.seed_jump_start import AgentFileOffers, discover_agent_files
from harness.spine_client import (
    ActivateScorerConfigRequest,
    BatchDecisionResponse,
    CreateScorerConfigRequest,
    MemoryGraphQuery,
    MemoryGraphSnapshot,
    QueueDecisionIntent,
    QueueDecisionRequest,
    QueueDecisionResponse,
    RackScorerActivateRequest,
    RackScorerAuditionRequest,
    RackScorerForceRequest,
    RackScorerSimulationRequest,
    RetrainResponse,
    ScorerAuditionRequest,
    ScorerAuditionResponse,
    ScorerConfigurationView,
    ScorerConsoleQuery,
    ScorerConsoleSnapshot,
    ScorerSimulationRequest,
    ScorerSimulationResponse,
    SpineClient,
    SpineClientError,
    VitalsAccounting,
    VitalsSnapshot,
)
from harness.symphony_experience import SymphonyExperience
from harness.tools_memory import MemoryToolContext
from harness.toolset_runtime import LazyStandardToolset
from harness.transcript import TranscriptJournal, TranscriptJournalUnavailable
from harness.transcript_sync import TranscriptSyncEngine

DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
DEFAULT_WEB_ROOT = DEFAULT_WEB_DIST.parent
MISSING_WEB_BUILD_MESSAGE = (
    "Nocturne's web app is missing. Build it with `npm ci && npm run build` in the "
    "`web` directory, then run `nocturne up` again."
)

type EnvelopeSender = Callable[[Envelope], Awaitable[None]]
type EnvelopeHandler = Callable[[Envelope, EnvelopeSender], Awaitable[None]]
type EnvelopeForwarder = Callable[[Envelope], Awaitable[None]]
type VitalsSnapshotReader = Callable[[], Awaitable[VitalsSnapshot]]
type ThreadVitalsSnapshotReader = Callable[[UUID], Awaitable[VitalsSnapshot]]
type MemoryGraphReader = Callable[[str | None], Awaitable[MemoryGraphSnapshot]]
type ScorerConsoleReader = Callable[[str | None], Awaitable[ScorerConsoleSnapshot]]
type ScorerConfigWriter = Callable[[RackScorerForceRequest], Awaitable[ScorerConfigurationView]]
type ScorerSimulator = Callable[[RackScorerSimulationRequest], Awaitable[ScorerSimulationResponse]]
type ScorerAuditioner = Callable[[RackScorerAuditionRequest], Awaitable[ScorerAuditionResponse]]
type ScorerRetrainer = Callable[[], Awaitable[RetrainResponse]]
type ScorerProposalActivator = Callable[
    [str, RackScorerActivateRequest], Awaitable[ScorerConfigurationView]
]
type ContextWindowReader = Callable[[str | None], ContextWindowSnapshot]
type RecipeGraphReader = Callable[[], RecipeGraphSnapshot]


class TranscriptBackupUpdate(BaseModel):
    enabled: bool


class AttunementTargetRequest(BaseModel):
    kind: Literal["thread", "stack"]
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    thread_ids: list[str]
    source_instance_id: str = Field(min_length=1)


class AttunementPickRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    consumer_instance_id: str = Field(min_length=1)
    source_instance_id: str = Field(min_length=1)
    target: AttunementTargetRequest
    tied_source_instance_ids: list[str] = Field(min_length=2)
    layout_signature: str = Field(min_length=1)


_OUTBOX_BUFFER_SIZE = 256
_RESYNC_CLOSE_REASON = "snapshot resync required"
_RACK_FRAME_HOST = "rack.localhost"
_RACK_MODULE_IDS = frozenset(
    {
        "header",
        "threads",
        "chat",
        "memory",
        "gate",
        "vitals",
        "context_bars",
        "thread_end",
        "palace_queue",
        "model_device",
        "memory_graph",
        "palace_nebula",
        "injection_console",
        "recipe",
        "deck",
    }
)
_RACK_FRAME_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'none'",
        "media-src 'none'",
        "object-src 'none'",
        "frame-src 'none'",
        "worker-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors http://localhost:* http://127.0.0.1:*",
    )
)
_RESERVED_TYPES = frozenset(
    {
        MessageType.RUN_STEER,
        MessageType.PLAN_UPDATE,
        MessageType.CHECKPOINT_CREATED,
        MessageType.CHECKPOINT_RESTORE,
        MessageType.PRESENCE_UPDATE,
    }
)


class _InvalidEnvelope(ValueError):
    """An inbound frame that cannot represent one C.7 envelope."""


class _UnavailableTurnRunner:
    """Honest default until composition supplies trusted run dependencies."""

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del thread_id, prompt, emit, model_resolution
        return TurnOutcome(
            stop_reason=StopReason.ERROR,
            message_history=tuple(message_history),
            usage=UsageSnapshot(),
        )


def _reject_json_constant(value: str) -> None:
    raise json.JSONDecodeError("non-standard JSON constant", value, 0)


def _parse_envelope(raw: str) -> Envelope:
    try:
        decoded = json.loads(raw, parse_constant=_reject_json_constant)
        return Envelope.model_validate(decoded)
    except (ValueError, RecursionError) as exc:
        raise _InvalidEnvelope from exc


def _serialize_envelope(message: Envelope) -> dict[str, object]:
    """Omit optional outer IDs without dropping required null payload members."""

    wire = message.model_dump(mode="json")
    if message.agent_id is None:
        wire.pop("agent_id")
    if message.thread_id is None:
        wire.pop("thread_id")
    return wire


async def _receive_envelope(websocket: WebSocket) -> Envelope | None:
    event = await websocket.receive()
    if event["type"] == "websocket.disconnect":
        return None
    raw = event.get("text")
    if not isinstance(raw, str):
        raise _InvalidEnvelope
    return _parse_envelope(raw)


def create_app(
    web_dist: str | Path | None = None,
    *,
    missing_web_message: str = MISSING_WEB_BUILD_MESSAGE,
    routes: Mapping[MessageType, EnvelopeHandler] | None = None,
    run_loop: RunLoop | None = None,
    forward_unknown: EnvelopeForwarder | None = None,
    envelope_factory: EnvelopeFactory | None = None,
    vitals_snapshot_reader: VitalsSnapshotReader | None = None,
    thread_vitals_snapshot_reader: ThreadVitalsSnapshotReader | None = None,
    memory_graph_reader: MemoryGraphReader | None = None,
    scorer_console_reader: ScorerConsoleReader | None = None,
    scorer_config_writer: ScorerConfigWriter | None = None,
    scorer_simulator: ScorerSimulator | None = None,
    scorer_auditioner: ScorerAuditioner | None = None,
    scorer_retrainer: ScorerRetrainer | None = None,
    scorer_proposal_activator: ScorerProposalActivator | None = None,
    context_window_reader: ContextWindowReader | None = None,
    recipe_graph_reader: RecipeGraphReader | None = None,
    before_static_mount: Callable[[FastAPI], None] | None = None,
) -> FastAPI:
    """Create the daemon with process-scoped H7 state and extensible routing."""
    app = FastAPI(title="NOCTURNE", version=__version__)
    factory = envelope_factory or EnvelopeFactory(machine_id="harness-daemon")
    loop = run_loop or RunLoop(_UnavailableTurnRunner(), factory)
    app.router.add_event_handler("shutdown", loop.close)
    route_table: dict[MessageType, EnvelopeHandler] = {}
    if routes is not None:
        for message_type, handler in routes.items():
            if not isinstance(message_type, MessageType):
                raise TypeError("route keys must be MessageType values")
            route_table[message_type] = handler

    @app.middleware("http")
    async def rack_frame_policy(request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        if not response.headers.get("content-type", "").startswith("text/html"):
            return response
        is_rack_frame = (
            request.url.hostname == _RACK_FRAME_HOST
            and request.query_params.get("rack_module") in _RACK_MODULE_IDS
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        if is_rack_frame:
            response.headers["Content-Security-Policy"] = _RACK_FRAME_CSP
        else:
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/v1/rack/query", response_model=RackQueryResult)
    async def rack_query(
        resource: Literal[
            "vitals",
            "parameters",
            "memory_graph",
            "scorer_console",
            "context_window",
            "recipe_graph",
        ],
        as_of: str | None = None,
        thread_id: str | None = None,
    ) -> RackQueryResult:
        """Keep Spine credentials behind the public rack query surface."""

        if resource == "recipe_graph":
            if as_of not in {None, "now"}:
                return RackQueryResult(status="historical_unavailable", as_of=as_of, data=None)
            if recipe_graph_reader is None:
                raise HTTPException(status_code=503, detail="The live recipe is unavailable.")
            try:
                snapshot = recipe_graph_reader()
            except ValueError:
                raise HTTPException(
                    status_code=503,
                    detail="The live recipe is unavailable.",
                ) from None
            return RackQueryResult(status="live", as_of=None, data=snapshot)
        if resource == "context_window":
            if as_of not in {None, "now"}:
                return RackQueryResult(status="historical_unavailable", as_of=as_of, data=None)
            if context_window_reader is None:
                raise HTTPException(status_code=503, detail="Context usage is unavailable.")
            return RackQueryResult(status="live", as_of=None, data=context_window_reader(thread_id))
        if resource == "parameters":
            if thread_id is None or not thread_id.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="CURRENT parameter queries require a thread_id.",
                )
            instant: datetime | None = None
            if as_of not in {None, "now"}:
                try:
                    instant = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="Parameter as_of must be an aware ISO-8601 timestamp.",
                    ) from None
                if instant.tzinfo is None or instant.utcoffset() is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="Parameter as_of must be an aware ISO-8601 timestamp.",
                    )
            try:
                snapshot = await loop.parameter_snapshot(thread_id, as_of=instant)
            except ParameterWriteViolation:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The parameter registry is unavailable.",
                ) from None
            return RackQueryResult(
                status="live",
                as_of=None,
                data=snapshot,
            )
        if resource in {"memory_graph", "scorer_console"}:
            if as_of not in {None, "now"}:
                return RackQueryResult(status="historical_unavailable", as_of=as_of, data=None)
            reader = memory_graph_reader if resource == "memory_graph" else scorer_console_reader
            if reader is None:
                raise HTTPException(
                    status_code=503, detail="Memory instrumentation is unavailable."
                )
            try:
                snapshot = await reader(thread_id)
            except (SpineClientError, ValueError):
                raise HTTPException(
                    status_code=503, detail="Memory instrumentation is unavailable."
                ) from None
            return RackQueryResult(status="live", as_of=None, data=snapshot)
        if as_of not in {None, "now"}:
            return RackQueryResult(status="historical_unavailable", as_of=as_of, data=None)
        if vitals_snapshot_reader is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Palace Vitals are unavailable.",
            )
        try:
            if thread_id is not None:
                if thread_vitals_snapshot_reader is None:
                    raise HTTPException(status_code=503, detail="Thread Vitals are unavailable.")
                snapshot = await thread_vitals_snapshot_reader(UUID(thread_id))
            else:
                snapshot = await vitals_snapshot_reader()
        except SpineClientError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Palace Vitals are unavailable.",
            ) from None
        return RackQueryResult(status="live", as_of=None, data=snapshot)

    @app.post("/v1/rack/scorers", response_model=ScorerConfigurationView)
    async def write_scorer(body: RackScorerForceRequest) -> ScorerConfigurationView:
        if scorer_config_writer is None:
            raise HTTPException(status_code=503, detail="Injection controls are unavailable.")
        try:
            return await scorer_config_writer(body)
        except SpineClientError:
            raise HTTPException(
                status_code=503, detail="Injection controls are unavailable."
            ) from None

    @app.post("/v1/rack/scorers/simulate", response_model=ScorerSimulationResponse)
    async def simulate_scorer(body: RackScorerSimulationRequest) -> ScorerSimulationResponse:
        if scorer_simulator is None:
            raise HTTPException(status_code=503, detail="Injection simulation is unavailable.")
        try:
            return await scorer_simulator(body)
        except SpineClientError:
            raise HTTPException(
                status_code=503, detail="Injection simulation is unavailable."
            ) from None

    @app.post("/v1/rack/scorers/audition", response_model=ScorerAuditionResponse)
    async def audition_scorer(body: RackScorerAuditionRequest) -> ScorerAuditionResponse:
        if scorer_auditioner is None:
            raise HTTPException(status_code=503, detail="Scorer audition is unavailable.")
        try:
            return await scorer_auditioner(body)
        except SpineClientError:
            raise HTTPException(status_code=503, detail="Scorer audition is unavailable.") from None

    @app.post("/v1/rack/scorers/retrain", response_model=RetrainResponse)
    async def retrain_scorer() -> RetrainResponse:
        if scorer_retrainer is None:
            raise HTTPException(status_code=503, detail="Scorer retraining is unavailable.")
        try:
            return await scorer_retrainer()
        except SpineClientError:
            raise HTTPException(
                status_code=503, detail="Scorer retraining is unavailable."
            ) from None

    @app.post("/v1/rack/scorers/{version}/activate", response_model=ScorerConfigurationView)
    async def activate_scorer(
        version: str, body: RackScorerActivateRequest
    ) -> ScorerConfigurationView:
        if scorer_proposal_activator is None:
            raise HTTPException(status_code=503, detail="Injection controls are unavailable.")
        try:
            return await scorer_proposal_activator(version, body)
        except SpineClientError:
            raise HTTPException(
                status_code=503, detail="Injection controls are unavailable."
            ) from None

    @app.post("/v1/rack/parameters", response_model=ParameterSnapshot)
    async def write_parameter(body: ParameterWriteRequest) -> ParameterSnapshot:
        try:
            return await loop.write_parameter(
                module_id=body.module_id,
                thread_id=body.thread_id,
                parameter_id=body.parameter_id,
                value=body.value,
            )
        except ParameterWriteViolation as exc:
            if exc.reason == "busy":
                code = status.HTTP_409_CONFLICT
            elif exc.reason == "invalid":
                code = status.HTTP_422_UNPROCESSABLE_CONTENT
            else:
                code = status.HTTP_403_FORBIDDEN
            raise HTTPException(
                status_code=code,
                detail=f"Parameter write refused: {exc.reason}.",
            ) from None

    @app.post("/v1/rack/attunement-picks", response_model=Envelope)
    async def journal_attunement_pick(body: AttunementPickRequest) -> Envelope:
        """Journal a random proximity-tie choice before the browser treats it as sticky."""

        if body.source_instance_id not in body.tied_source_instance_ids:
            raise HTTPException(
                status_code=422,
                detail="Tie winner is not one of the tied sources.",
            )
        if body.target.source_instance_id != body.source_instance_id:
            raise HTTPException(
                status_code=422,
                detail="Tie target does not match its source.",
            )
        event = factory.create(
            "rack.attunement.pick",
            body.model_dump(mode="json", exclude={"thread_id"}),
            thread_id=body.thread_id,
        )
        await loop.publish(body.thread_id, event)
        return event

    async def not_implemented(message: Envelope, send: EnvelopeSender) -> None:
        await loop.send_direct(
            send,
            factory.create(
                MessageType.ERROR,
                "not implemented",
                thread_id=message.thread_id,
            ),
        )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        outbox: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=_OUTBOX_BUFFER_SIZE)
        resync_required = asyncio.Event()
        connected = True

        async def send(message: Envelope) -> None:
            if not connected or resync_required.is_set():
                return
            validated = Envelope.model_validate(message.model_dump(mode="json"))
            try:
                outbox.put_nowait(validated)
            except asyncio.QueueFull:
                resync_required.set()

        async def write_outbox() -> None:
            while True:
                message = await outbox.get()
                try:
                    await websocket.send_json(_serialize_envelope(message))
                finally:
                    outbox.task_done()

        writer = asyncio.create_task(write_outbox())

        async def close_for_resync() -> None:
            await resync_required.wait()
            writer.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await writer
            if connected:
                with suppress(WebSocketDisconnect, RuntimeError):
                    await websocket.close(
                        code=status.WS_1013_TRY_AGAIN_LATER,
                        reason=_RESYNC_CLOSE_REASON,
                    )

        resync_closer = asyncio.create_task(close_for_resync())

        try:
            await loop.attach(send, on_overflow=resync_required.set)
            while True:
                try:
                    message = await _receive_envelope(websocket)
                except _InvalidEnvelope:
                    await websocket.close(
                        code=status.WS_1008_POLICY_VIOLATION,
                        reason="invalid C.7 envelope",
                    )
                    return
                if message is None:
                    return
                if not isinstance(message.type, MessageType) or message.type in _RESERVED_TYPES:
                    if forward_unknown is not None:
                        await forward_unknown(message)
                    continue

                custom_route = route_table.get(message.type)
                if custom_route is not None:
                    await custom_route(message, send)
                    continue

                if message.type is MessageType.PROMPT_SUBMIT:
                    assert isinstance(message.payload, PromptSubmitPayload)
                    assert message.thread_id is not None
                    await loop.submit(
                        thread_id=message.thread_id,
                        prompt_id=message.id,
                        prompt=message.payload.prompt,
                        image=message.payload.image,
                        symphony=message.payload.symphony,
                        symphony_intervention=message.payload.symphony_intervention,
                        proposed_response=message.payload.proposed_response,
                        sink=send,
                    )
                elif message.type is MessageType.RUN_CANCEL:
                    assert isinstance(message.payload, RunCancelPayload)
                    await loop.cancel(
                        thread_id=(
                            message.thread_id
                            if message.thread_id is not None and message.thread_id.strip()
                            else None
                        ),
                        run_id=message.payload.run_id,
                        sink=send,
                    )
                elif message.type is MessageType.GATE_COMMIT:
                    assert isinstance(message.payload, GateCommitPayload)
                    assert message.thread_id is not None
                    await loop.commit_gate(
                        thread_id=message.thread_id,
                        decision=message.payload,
                        sink=send,
                    )
                elif message.type is MessageType.THREAD_SNAPSHOT and isinstance(
                    message.payload, ThreadSnapshotRequestPayload
                ):
                    assert message.thread_id is not None
                    try:
                        await loop.request_snapshot(
                            message.thread_id,
                            send,
                            project_key=message.payload.project_key,
                            request_id=message.id,
                        )
                    except ProjectBindingConflict as exc:
                        existing = (
                            f"project {exc.existing}"
                            if exc.existing is not None
                            else "unscoped history"
                        )
                        await loop.send_direct(
                            send,
                            factory.create(
                                MessageType.ERROR,
                                {
                                    "code": "project_context_conflict",
                                    "message": (
                                        f"This thread already belongs to {existing}. "
                                        f"Start a new thread in project {exc.requested}."
                                    ),
                                },
                                thread_id=message.thread_id,
                            ),
                        )
                        await loop.request_snapshot(
                            message.thread_id,
                            send,
                            request_id=message.id,
                        )
                else:
                    await not_implemented(message, send)
        except WebSocketDisconnect:
            return
        finally:
            connected = False
            await loop.detach(send)
            writer.cancel()
            resync_closer.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await writer
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await resync_closer

    @app.websocket("/{path:path}")
    async def reject_unknown_websocket(websocket: WebSocket, path: str) -> None:
        await websocket.accept()
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="unknown WebSocket route",
        )

    if before_static_mount is not None:
        before_static_mount(app)

    static_root = Path(web_dist) if web_dist is not None else DEFAULT_WEB_DIST
    if (static_root / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_root, html=True), name="web")
    else:

        @app.get("/", response_class=PlainTextResponse)
        async def missing_web_build() -> PlainTextResponse:
            return PlainTextResponse(
                missing_web_message,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return app


def create_dev_app(
    web_dist: str | Path | None = None,
    *,
    missing_web_message: str = MISSING_WEB_BUILD_MESSAGE,
    settings: HarnessSettings | None = None,
    agent: HarnessAgent | None = None,
    spine: SpineClient | None = None,
    transcript_journal: TranscriptJournal | None = None,
    model_resolver_override: ThreadModelResolver | None = None,
    seed_discovery_root: str | Path | None = None,
    symphony_experience: SymphonyExperience | None = None,
) -> FastAPI:
    """Compose the real H3 agent loop with trusted local M1 run context."""

    configured = settings or HarnessSettings()
    discovery_root = Path.cwd() if seed_discovery_root is None else Path(seed_discovery_root)
    principal_id = _required_identity(configured.principal_id, "PRINCIPAL_ID")
    machine_id = _required_identity(configured.machine_id, "MACHINE_ID")
    agent_id = _required_identity(configured.agent_id, "AGENT_ID")
    owned_spine = spine
    if owned_spine is None:
        token = configured.spine_token
        if token is None or not token.get_secret_value().strip():
            raise ValueError("SPINE_TOKEN is required for `harness dev`")
        owned_spine = SpineClient(configured.spine_url, token.get_secret_value())
    completion_router = CompletionRouter(configured)
    owned_agent = agent or HarnessAgent(
        configured,
        router=completion_router,
        skill_directories=discover_skill_libraries(discovery_root),
    )
    factory = EnvelopeFactory(machine_id=machine_id, agent_id=agent_id)
    owned_symphony_experience = symphony_experience or SymphonyExperience(id_factory=factory.new_id)
    model_resolver = model_resolver_override or ModelPolicyResolver(
        policy=configured.effective_model_policy_chat,
        static_model=configured.chat_model,
        static_context_tokens=configured.model_context_tokens,
        catalog=completion_router.catalog,
    )
    workspace_toolset = LazyStandardToolset(
        cwd=discovery_root,
        workspace_root=discovery_root,
        agent_id=agent_id,
        machine_id=machine_id,
        fence_reads=configured.toolset_fence_reads,
    )

    def context_factory(thread_id: str) -> MemoryToolContext:
        try:
            parsed_thread_id = UUID(thread_id)
        except ValueError as exc:
            raise ValueError("agent thread_id must be a UUID") from exc
        project_key = loop.project_key(thread_id)
        return MemoryToolContext(
            spine=owned_spine,
            principal_id=principal_id,
            machine_id=machine_id,
            agent_id=agent_id,
            thread_id=parsed_thread_id,
            project_key=project_key,
            origin_path=workspace_location_path(workspace_toolset.location()),
            toolset=workspace_toolset,
        )

    memory_contexts = ThreadMemoryContextRegistry()
    context_windows = ContextWindowTracker()
    receipt_queue = SpendReceiptQueue(nocturne_home() / "receipt-queue")
    resource_watch = ResourceWatch(nocturne_home())
    panel = MemoryPanelController(
        owned_spine,
        memory_contexts,
        factory,
        principal_id=principal_id,
        machine_id=machine_id,
    )

    async def publish_ambient_memory_panel(thread_id: str) -> None:
        await panel.publish_ambient(
            thread_id,
            lambda envelope: loop.publish(thread_id, envelope),
        )

    runner = MemoryGateTurnRunner(
        PydanticAITurnRunner(
            owned_agent,
            context_factory,
            owned_spine,
            receipt_queue=receipt_queue,
            context_windows=context_windows,
        ),
        owned_spine,
        context_factory,
        model_context_tokens=configured.model_context_tokens,
        contexts=memory_contexts,
        on_context_changed=publish_ambient_memory_panel,
    )
    journal = transcript_journal or TranscriptJournal(nocturne_home() / "transcripts")

    def browser_consent_was_journaled(thread_id: str) -> bool:
        try:
            return any(
                message.get("role") == "user"
                and message.get("state") == StopReason.END_TURN.value
                and isinstance(message.get("content"), str)
                and browser_open_web_command(message["content"])
                for message in journal.read_messages(thread_id)
            )
        except TranscriptJournalUnavailable:
            return False

    workspace_toolset.set_browser_consent_check(browser_consent_was_journaled)
    transcript_sync = TranscriptSyncEngine(
        journal,
        owned_spine,
        principal_id,
        enabled=configured.nocturne_transcript_backup,
    )

    async def read_vitals_snapshot() -> VitalsSnapshot:
        snapshot = await owned_spine.vitals_snapshot()
        return snapshot.model_copy(
            update={
                "accounting": _vitals_accounting(receipt_queue),
                "resources": resource_watch.snapshot(snapshot.resources.database_bytes),
            }
        )

    async def read_thread_vitals_snapshot(thread_id: UUID) -> VitalsSnapshot:
        snapshot = await owned_spine.thread_vitals_snapshot(thread_id)
        return snapshot.model_copy(
            update={
                "accounting": _vitals_accounting(receipt_queue),
                "resources": resource_watch.snapshot(snapshot.resources.database_bytes),
            }
        )

    async def read_memory_graph(thread_id: str | None) -> MemoryGraphSnapshot:
        memory_ids = None
        if thread_id is not None:
            snapshot = memory_contexts.snapshot(thread_id)
            memory_ids = [] if snapshot is None else sorted(snapshot.member_ids, key=str)
        return await owned_spine.memory_graph(
            MemoryGraphQuery(principal_id=principal_id, memory_ids=memory_ids)
        )

    async def read_scorer_console(thread_id: str | None) -> ScorerConsoleSnapshot:
        return await owned_spine.scorer_console(
            ScorerConsoleQuery(
                principal_id=principal_id,
                thread_id=None if thread_id is None else UUID(thread_id),
            )
        )

    async def simulate_scorer(body: RackScorerSimulationRequest) -> ScorerSimulationResponse:
        return await owned_spine.simulate_scorer(
            ScorerSimulationRequest(
                principal_id=principal_id,
                **body.model_dump(),
            )
        )

    async def force_scorer(body: RackScorerForceRequest) -> ScorerConfigurationView:
        return await owned_spine.create_scorer_config(
            CreateScorerConfigRequest(
                **body.model_dump(),
                actor_class="human",
                machine_id=machine_id,
            )
        )

    async def audition_scorer(body: RackScorerAuditionRequest) -> ScorerAuditionResponse:
        return await owned_spine.audition_scorer(
            ScorerAuditionRequest(
                principal_id=principal_id,
                **body.model_dump(),
            )
        )

    async def retrain_scorer() -> RetrainResponse:
        return await owned_spine.retrain()

    async def activate_scorer(
        version: str, body: RackScorerActivateRequest
    ) -> ScorerConfigurationView:
        return await owned_spine.activate_scorer_config(
            version,
            ActivateScorerConfigRequest(
                event_uid=body.event_uid,
                actor_class="human",
                machine_id=machine_id,
            ),
        )

    loop = RunLoop(
        runner,
        factory,
        model_resolver=model_resolver,
        transcript_journal=journal,
        symphony_experience=owned_symphony_experience,
    )
    extraction = ExtractionService(
        journal=journal,
        agent=owned_agent,
        spine=owned_spine,
        principal_id=principal_id,
        machine_id=machine_id,
    )
    seed_ingestion = SeedIngestionService(
        agent=owned_agent,
        spine=owned_spine,
        principal_id=principal_id,
        machine_id=machine_id,
    )
    idle_extraction = (
        None
        if configured.extraction_idle_hours is None
        else ExtractionIdleScheduler(
            extraction, journal, idle_hours=configured.extraction_idle_hours
        )
    )

    def configure_extraction_routes(app: FastAPI) -> None:
        @app.get("/v1/symphonies/{symphony_id}")
        async def read_symphony(symphony_id: str):
            stack = await owned_symphony_experience.read(symphony_id)
            if stack is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Symphony stack was not found.",
                )
            return stack

        @app.get("/v1/transcripts/settings")
        async def transcript_settings():
            return transcript_sync.snapshot()

        @app.put("/v1/transcripts/settings")
        async def update_transcript_settings(body: TranscriptBackupUpdate):
            try:
                config = load_config(home=nocturne_home())
                set_transcript_backup(config, body.enabled)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Transcript backup setting could not be saved: {exc}",
                ) from exc
            transcript_sync.set_enabled(body.enabled)
            return transcript_sync.snapshot()

        @app.get("/v1/transcripts/catalog")
        async def transcript_catalog():
            return {"threads": journal.catalog()}

        async def flush_receipt_queue() -> None:
            await receipt_queue.flush(owned_spine)

        app.router.add_event_handler("startup", flush_receipt_queue)
        if idle_extraction is not None:
            app.router.add_event_handler("startup", idle_extraction.start)
            app.router.add_event_handler("shutdown", idle_extraction.stop)

        @app.post("/v1/threads/{thread_id}/archive")
        async def archive_thread(thread_id: UUID) -> ThreadEndResult:
            try:
                return await extraction.archive(thread_id)
            except (ValueError, SpineClientError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Thread extraction failed: {exc}",
                ) from exc

        @app.get("/v1/threads/{thread_id}/thread-end")
        async def thread_end(thread_id: UUID) -> ThreadEndResult:
            messages = journal.read_messages(str(thread_id))
            final_post = ""
            for message in reversed(messages):
                if message.get("role") == "assistant" and isinstance(message.get("content"), str):
                    final_post = message["content"]
                    break
            pending = await owned_spine.approval_queue(
                principal_id, thread_id=thread_id, birthplace="thread"
            )
            return ThreadEndResult(thread_id, final_post, "", [], pending.cards, 0, True)

        @app.get("/v1/threads/{thread_id}/messages/{prompt_id}/image")
        async def thread_image(thread_id: UUID, prompt_id: str) -> Response:
            try:
                attachment = journal.read_image_attachment(str(thread_id), prompt_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Thread image was not found.",
                ) from exc
            except TranscriptJournalUnavailable as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Thread image journal is unavailable.",
                ) from exc
            if attachment is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Thread image was not found.",
                )
            return Response(
                content=attachment.data,
                media_type=attachment.view.media_type,
                headers={
                    "Cache-Control": "private, immutable",
                    "ETag": f'"{attachment.view.sha256}"',
                },
            )

        @app.post("/v1/approval-queue/{item_uid}/decisions")
        async def decide_queue_item(
            item_uid: str, body: QueueDecisionIntent
        ) -> QueueDecisionResponse:
            request = QueueDecisionRequest(machine_id=machine_id, **body.model_dump())
            return await owned_spine.decide_queue_item(item_uid, request)

        @app.post("/v1/approval-queue/batches/{batch_uid}/decisions")
        async def decide_queue_batch(
            batch_uid: UUID, body: QueueDecisionIntent
        ) -> BatchDecisionResponse:
            request = QueueDecisionRequest(machine_id=machine_id, **body.model_dump())
            return await owned_spine.decide_queue_batch(batch_uid, request)

        @app.get("/v1/approval-queue")
        async def read_queue(
            thread_id: UUID | None = None,
            birthplace: Literal["thread", "seed", "symphony"] | None = None,
        ):
            return await owned_spine.approval_queue(
                principal_id,
                thread_id=thread_id,
                birthplace=birthplace,
            )

        @app.get("/v1/seeds/jump-start")
        async def seed_jump_start() -> AgentFileOffers:
            return discover_agent_files(discovery_root)

        @app.post("/v1/seeds")
        async def ingest_seed(upload: SeedUploadRequest):
            try:
                return await seed_ingestion.ingest(upload)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            except SpineClientError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Seed ingestion failed: {exc}",
                ) from exc

    app = create_app(
        web_dist,
        missing_web_message=missing_web_message,
        routes={MessageType.MEMORY_PANEL_UPDATE: panel.handle},
        run_loop=loop,
        envelope_factory=factory,
        vitals_snapshot_reader=read_vitals_snapshot,
        thread_vitals_snapshot_reader=read_thread_vitals_snapshot,
        memory_graph_reader=read_memory_graph,
        scorer_console_reader=read_scorer_console,
        scorer_config_writer=force_scorer,
        scorer_simulator=simulate_scorer,
        scorer_auditioner=audition_scorer,
        scorer_retrainer=retrain_scorer,
        scorer_proposal_activator=activate_scorer,
        context_window_reader=context_windows.snapshot,
        recipe_graph_reader=owned_symphony_experience.recipe_snapshot,
        before_static_mount=configure_extraction_routes,
    )

    app.router.add_event_handler("startup", transcript_sync.start)
    app.router.add_event_handler("shutdown", transcript_sync.stop)
    app.router.add_event_handler("shutdown", workspace_toolset.close)
    app.router.add_event_handler("shutdown", owned_spine.aclose)
    app.router.add_event_handler("shutdown", completion_router.aclose)
    return app


def _vitals_accounting(receipt_queue: SpendReceiptQueue) -> VitalsAccounting:
    snapshot = receipt_queue.snapshot()
    return VitalsAccounting(
        status=snapshot.status,
        pending_lines=snapshot.pending_lines,
        oldest_queued_at=snapshot.oldest_queued_at,
        source="harness.receipt_queue",
    )


def _required_identity(value: str, name: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def _build_web(web_root: Path = DEFAULT_WEB_ROOT) -> None:
    """Produce the built static shell that the daemon serves."""
    try:
        subprocess.run(["npm", "ci"], cwd=web_root, check=True)
        subprocess.run(["npm", "run", "build"], cwd=web_root, check=True)
    except FileNotFoundError as exc:
        raise SystemExit("npm is required for `harness dev`") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit("web install/build failed; daemon not started") from exc


def main() -> None:
    """Run the required `harness dev` developer command."""
    parser = argparse.ArgumentParser(prog="harness")
    parser.add_argument("command", choices=("dev",))
    args = parser.parse_args()

    if args.command == "dev":
        _build_web()
        uvicorn.run(
            "harness.daemon:create_dev_app",
            factory=True,
            host="127.0.0.1",
            port=8765,
            reload=True,
            reload_dirs=[str(DEFAULT_WEB_ROOT.parent / "src")],
        )


if __name__ == "__main__":
    main()
