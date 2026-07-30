"""FastAPI daemon: built static shell plus the routed C.7 WebSocket seam."""

import argparse
import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from harness.agent import HarnessAgent
from harness.agent_runtime import PydanticAITurnRunner
from harness.config import HarnessSettings
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
from harness.memory_gate import MemoryGateTurnRunner
from harness.memory_panel import MemoryPanelController, ThreadMemoryContextRegistry
from harness.model_policy import (
    ModelPolicyResolver,
    OpenRouterCatalogClient,
    ThreadModelResolution,
)
from harness.run_loop import RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot
from harness.spine_client import SpineClient
from harness.tools_memory import MemoryToolContext

DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
DEFAULT_WEB_ROOT = DEFAULT_WEB_DIST.parent

type EnvelopeSender = Callable[[Envelope], Awaitable[None]]
type EnvelopeHandler = Callable[[Envelope, EnvelopeSender], Awaitable[None]]
type EnvelopeForwarder = Callable[[Envelope], Awaitable[None]]

_OUTBOX_BUFFER_SIZE = 256
_RESYNC_CLOSE_REASON = "snapshot resync required"
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
    routes: Mapping[MessageType, EnvelopeHandler] | None = None,
    run_loop: RunLoop | None = None,
    forward_unknown: EnvelopeForwarder | None = None,
    envelope_factory: EnvelopeFactory | None = None,
) -> FastAPI:
    """Create the daemon with process-scoped H7 state and extensible routing."""
    app = FastAPI(title="Harness", version="0.0.0")
    factory = envelope_factory or EnvelopeFactory(machine_id="harness-daemon")
    loop = run_loop or RunLoop(_UnavailableTurnRunner(), factory)
    app.router.add_event_handler("shutdown", loop.close)
    route_table: dict[MessageType, EnvelopeHandler] = {}
    if routes is not None:
        for message_type, handler in routes.items():
            if not isinstance(message_type, MessageType):
                raise TypeError("route keys must be MessageType values")
            route_table[message_type] = handler

    async def not_implemented(message: Envelope, send: EnvelopeSender) -> None:
        await send(
            factory.create(
                MessageType.ERROR,
                "not implemented",
                thread_id=message.thread_id,
            )
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
                    await loop.request_snapshot(message.thread_id, send)
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

    static_root = Path(web_dist) if web_dist is not None else DEFAULT_WEB_DIST
    if (static_root / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_root, html=True), name="web")
    else:

        @app.get("/", response_class=PlainTextResponse)
        async def missing_web_build() -> PlainTextResponse:
            return PlainTextResponse(
                "web build missing; build web/ before starting harness",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return app


def create_dev_app(
    web_dist: str | Path | None = None,
    *,
    settings: HarnessSettings | None = None,
    agent: HarnessAgent | None = None,
    spine: SpineClient | None = None,
) -> FastAPI:
    """Compose the real H3 agent loop with trusted local M1 run context."""

    configured = settings or HarnessSettings()
    principal_id = _required_identity(configured.principal_id, "PRINCIPAL_ID")
    machine_id = _required_identity(configured.machine_id, "MACHINE_ID")
    agent_id = _required_identity(configured.agent_id, "AGENT_ID")
    owned_spine = spine
    if owned_spine is None:
        token = configured.spine_token
        if token is None or not token.get_secret_value().strip():
            raise ValueError("SPINE_TOKEN is required for `harness dev`")
        owned_spine = SpineClient(configured.spine_url, token.get_secret_value())
    owned_agent = agent or HarnessAgent(configured)
    factory = EnvelopeFactory(machine_id=machine_id, agent_id=agent_id)
    openrouter_key = (
        configured.openrouter_api_key.get_secret_value()
        if configured.openrouter_api_key is not None
        else None
    )
    model_catalog = OpenRouterCatalogClient(openrouter_key)
    model_resolver = ModelPolicyResolver(
        policy=configured.effective_model_policy_chat,
        static_model=configured.chat_model,
        static_context_tokens=configured.model_context_tokens,
        catalog=model_catalog,
    )

    def context_factory(thread_id: str) -> MemoryToolContext:
        try:
            parsed_thread_id = UUID(thread_id)
        except ValueError as exc:
            raise ValueError("agent thread_id must be a UUID") from exc
        return MemoryToolContext(
            spine=owned_spine,
            principal_id=principal_id,
            machine_id=machine_id,
            agent_id=agent_id,
            thread_id=parsed_thread_id,
            project_key=None,
            origin_path=None,
        )

    memory_contexts = ThreadMemoryContextRegistry()
    runner = MemoryGateTurnRunner(
        PydanticAITurnRunner(owned_agent, context_factory),
        owned_spine,
        context_factory,
        model_context_tokens=configured.model_context_tokens,
        contexts=memory_contexts,
    )
    panel = MemoryPanelController(
        owned_spine,
        memory_contexts,
        factory,
        principal_id=principal_id,
        machine_id=machine_id,
    )
    loop = RunLoop(runner, factory, model_resolver=model_resolver)
    app = create_app(
        web_dist,
        routes={MessageType.MEMORY_PANEL_UPDATE: panel.handle},
        run_loop=loop,
        envelope_factory=factory,
    )
    app.router.add_event_handler("shutdown", owned_spine.aclose)
    app.router.add_event_handler("shutdown", model_catalog.aclose)
    return app


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
