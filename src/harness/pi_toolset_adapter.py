"""The sole adapter between Nocturne's toolset seam and PI's JSONL RPC process."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError

from harness.envelope import generate_ulid
from harness.toolset import (
    AgentLocation,
    PresenceEvent,
    PresenceSink,
    ToolExecutionResult,
    ToolName,
    ToolsetError,
    ToolsetProtocolError,
    ToolsetState,
    ToolsetUnavailableError,
)

_RUNTIME_ROOT = Path(__file__).with_name("_pi")
_LOCATION_EXTENSION = _RUNTIME_ROOT / "nocturne_location.mjs"
_MAX_RECORD_BYTES = 1_048_576
_PRESENCE_STATUS_KEY = "nocturne-presence"
_TOOL_RESULT_STATUS_KEY = "nocturne-tool-result"


class _RpcState(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    isStreaming: StrictBool
    isCompacting: StrictBool
    autoCompactionEnabled: StrictBool
    messageCount: StrictInt
    pendingMessageCount: StrictInt


class _PresenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: StrictStr
    machine_id: StrictStr
    session_id: StrictStr
    event: Literal["spawn", "cwd_change", "read", "write", "idle", "exit"]
    path: StrictStr
    ts: datetime


class _ToolResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: StrictStr
    tool_name: Literal["read", "edit", "write", "grep", "find", "ls", "bash", "move"]
    success: StrictBool
    content: StrictStr


def _default_command() -> tuple[str, ...]:
    configured = os.environ.get("NOCTURNE_PI_COMMAND", "").strip()
    if configured:
        executable = Path(configured).expanduser()
        if executable.is_file():
            return (str(executable),)
        raise ToolsetUnavailableError(
            "The configured PI runtime is missing; run `nocturne init` to repair it."
        )
    executable = _RUNTIME_ROOT / "node_modules" / ".bin" / ("pi.cmd" if os.name == "nt" else "pi")
    if not executable.is_file():
        raise ToolsetUnavailableError(
            "PI is not installed; run `uv run --locked python "
            "scripts/update_pi_toolset.py 0.84.2` from the Harness checkout."
        )
    return (str(executable),)


class PiRpcToolset:
    """Private subprocess implementation of the Harness-owned StandardToolset seam."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        location: AgentLocation,
        presence_sink: PresenceSink | None,
        timeout_seconds: float,
    ) -> None:
        self._process = process
        self._location = location
        self._presence_sink = presence_sink
        self._presence_events: list[PresenceEvent] = []
        self._timeout_seconds = timeout_seconds
        self._request_lock = asyncio.Lock()
        self._request_sequence = 0
        self._pending: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self._tool_results: dict[str, asyncio.Future[_ToolResultRecord]] = {}
        self._reader_error: ToolsetError | None = None
        self._closing = False
        self._stderr_tail = bytearray()
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    @classmethod
    async def open(
        cls,
        *,
        command: Sequence[str] | None = None,
        cwd: Path | None = None,
        workspace_root: Path | None = None,
        agent_id: str = "harness-agent",
        machine_id: str = "local-machine",
        session_id: str,
        fence_reads: bool = False,
        presence_sink: PresenceSink | None = None,
        timeout_seconds: float = 5.0,
    ) -> Self:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        for name, value in (
            ("agent_id", agent_id),
            ("machine_id", machine_id),
            ("session_id", session_id),
        ):
            if not value.strip() or "\n" in value or "\r" in value:
                raise ValueError(f"{name} must be nonblank and single-line")
        initial_location = (cwd or Path.cwd()).resolve(strict=True)
        root = (workspace_root or initial_location).resolve(strict=True)
        if not initial_location.is_dir() or not root.is_dir():
            raise ValueError("cwd and workspace_root must be existing directories")
        if not initial_location.is_relative_to(root):
            raise ValueError("cwd must be inside workspace_root")
        if not _LOCATION_EXTENSION.is_file():
            raise ToolsetUnavailableError("Nocturne's PI location adapter is not installed")
        argv = tuple(command) if command is not None else _default_command()
        if not argv or any(not part for part in argv):
            raise ValueError("command must contain only nonblank arguments")
        environment = os.environ.copy()
        environment.update(
            {
                "NOCTURNE_AGENT_ID": agent_id,
                "NOCTURNE_MACHINE_ID": machine_id,
                "NOCTURNE_SESSION_ID": session_id,
                "NOCTURNE_WORKSPACE_ROOT": str(root),
                "NOCTURNE_INITIAL_LOCATION": str(initial_location),
                "NOCTURNE_FENCE_READS": "1" if fence_reads else "0",
            }
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                "--mode",
                "rpc",
                "--no-session",
                "--no-approve",
                "--offline",
                "--no-extensions",
                "--extension",
                str(_LOCATION_EXTENSION),
                cwd=str(initial_location),
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_MAX_RECORD_BYTES,
            )
        except OSError as exc:
            raise ToolsetUnavailableError(f"PI could not start: {exc}") from exc
        return cls(
            process,
            location=AgentLocation(
                agent_id=agent_id,
                machine_id=machine_id,
                session_id=session_id,
                workspace_root=root,
                cwd=initial_location,
                fence_reads=fence_reads,
            ),
            presence_sink=presence_sink,
            timeout_seconds=timeout_seconds,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def state(self) -> ToolsetState:
        response = await self._request("get_state")
        try:
            payload = _RpcState.model_validate(response["data"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise ToolsetProtocolError("PI returned an invalid get_state payload") from exc
        return ToolsetState(
            is_streaming=payload.isStreaming,
            is_compacting=payload.isCompacting,
            auto_compaction_enabled=payload.autoCompactionEnabled,
            message_count=payload.messageCount,
            pending_message_count=payload.pendingMessageCount,
        )

    def location(self) -> AgentLocation:
        return self._location

    def presence_events(self) -> tuple[PresenceEvent, ...]:
        return tuple(self._presence_events)

    async def move(self, path: Path) -> AgentLocation:
        target = path if path.is_absolute() else self._location.cwd / path
        target = target.resolve(strict=True)
        if not target.is_dir():
            raise ValueError("move target must be an existing directory")
        if not target.is_relative_to(self._location.workspace_root):
            raise ValueError("move target must be inside workspace_root")
        await self._request(
            "prompt",
            message=f"/nocturne-move {json.dumps(str(target), ensure_ascii=False)}",
        )
        if self._location.cwd != target:
            raise ToolsetProtocolError("PI accepted move without emitting its presence event")
        return self._location

    async def execute(
        self,
        tool_name: ToolName,
        arguments: Mapping[str, object],
    ) -> ToolExecutionResult:
        """Execute one PI-owned tool through the single private RPC adapter."""

        invocation_id = generate_ulid()
        future: asyncio.Future[_ToolResultRecord] = asyncio.get_running_loop().create_future()
        self._tool_results[invocation_id] = future
        try:
            await self._request(
                "prompt",
                message=(
                    "/nocturne-tool "
                    + json.dumps(
                        {
                            "invocation_id": invocation_id,
                            "tool_name": tool_name,
                            "arguments": dict(arguments),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
            )
            try:
                record = await asyncio.wait_for(future, timeout=self._timeout_seconds)
            except TimeoutError as exc:
                raise ToolsetProtocolError("PI tool result timed out") from exc
        finally:
            self._tool_results.pop(invocation_id, None)
        if record.tool_name != tool_name:
            raise ToolsetProtocolError("PI correlated the wrong tool result")
        return ToolExecutionResult(
            tool_name=tool_name,
            content=record.content,
            success=record.success,
        )

    async def close(self) -> None:
        self._closing = True
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            self._process.stdin.close()
            try:
                await self._process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if self._process.returncode is not None:
            await self._finish_reader_tasks()
            return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=1.0)
        except TimeoutError:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=1.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        await self._finish_reader_tasks()

    async def _request(self, command: str, **payload: object) -> Mapping[str, Any]:
        async with self._request_lock:
            if self._process.stdin is None or self._process.stdout is None:
                raise ToolsetProtocolError("PI process pipes are unavailable")
            if self._process.returncode is not None:
                raise ToolsetUnavailableError(await self._exit_message())
            if self._reader_error is not None:
                raise self._reader_error

            self._request_sequence += 1
            request_id = f"nocturne-{self._request_sequence}"
            future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            wire = json.dumps(
                {"id": request_id, "type": command, **payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self._process.stdin.write(wire + b"\n")
            try:
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                self._pending.pop(request_id, None)
                raise ToolsetUnavailableError(await self._exit_message()) from exc
            try:
                record = await asyncio.wait_for(future, timeout=self._timeout_seconds)
            except TimeoutError as exc:
                raise ToolsetProtocolError("PI RPC response timed out") from exc
            finally:
                self._pending.pop(request_id, None)
            if record.get("command") != command:
                raise ToolsetProtocolError("PI correlated the wrong RPC command")
            if record.get("success") is not True:
                error = record.get("error")
                detail = error if isinstance(error, str) and error else "request refused"
                raise ToolsetProtocolError(f"PI {command} failed: {detail}")
            return record

    async def _read_loop(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                raw = await self._process.stdout.readuntil(b"\n")
                record = self._decode_record(raw)
                if self._consume_presence(record):
                    continue
                if self._consume_tool_result(record):
                    continue
                if record.get("type") != "response":
                    continue
                request_id = record.get("id")
                future = self._pending.get(request_id) if isinstance(request_id, str) else None
                if future is not None and not future.done():
                    future.set_result(record)
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                self._set_reader_error(ToolsetProtocolError("PI ended with a partial JSONL record"))
            elif not self._closing:
                self._set_reader_error(ToolsetUnavailableError(await self._exit_message()))
        except asyncio.LimitOverrunError:
            self._set_reader_error(
                ToolsetProtocolError("PI RPC record exceeded the one-MiB seam bound")
            )
        except ToolsetError as exc:
            self._set_reader_error(exc)
        except Exception as exc:  # pragma: no cover - last-resort task containment
            self._set_reader_error(ToolsetProtocolError(f"PI RPC reader failed: {exc}"))

    def _decode_record(self, raw: bytes) -> Mapping[str, Any]:
        if len(raw) > _MAX_RECORD_BYTES:
            raise ToolsetProtocolError("PI RPC record exceeded the one-MiB seam bound")
        raw = raw.removesuffix(b"\n").removesuffix(b"\r")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolsetProtocolError("PI emitted malformed UTF-8 JSONL") from exc
        if not isinstance(decoded, Mapping):
            raise ToolsetProtocolError("PI emitted a non-object RPC record")
        return decoded

    def _consume_presence(self, record: Mapping[str, Any]) -> bool:
        if not (
            record.get("type") == "extension_ui_request"
            and record.get("method") == "setStatus"
            and record.get("statusKey") == _PRESENCE_STATUS_KEY
        ):
            return False
        raw = record.get("statusText")
        if not isinstance(raw, str):
            raise ToolsetProtocolError("PI emitted an empty presence status")
        try:
            parsed = _PresenceRecord.model_validate_json(raw)
        except ValidationError as exc:
            raise ToolsetProtocolError("PI emitted an invalid presence event") from exc
        if (
            parsed.agent_id != self._location.agent_id
            or parsed.machine_id != self._location.machine_id
            or parsed.session_id != self._location.session_id
        ):
            raise ToolsetProtocolError("PI presence identity changed inside one toolset")
        event_path = Path(parsed.path).resolve()
        if parsed.event in {"spawn", "cwd_change", "idle", "exit"}:
            if not event_path.is_relative_to(self._location.workspace_root):
                raise ToolsetProtocolError("PI presence location escaped the workspace")
            self._location = AgentLocation(
                agent_id=self._location.agent_id,
                machine_id=self._location.machine_id,
                session_id=self._location.session_id,
                workspace_root=self._location.workspace_root,
                cwd=event_path,
                fence_reads=self._location.fence_reads,
            )
        event = PresenceEvent(
            agent_id=parsed.agent_id,
            machine_id=parsed.machine_id,
            session_id=parsed.session_id,
            event=parsed.event,
            path=event_path,
            ts=parsed.ts,
        )
        self._presence_events.append(event)
        if self._presence_sink is not None:
            self._presence_sink(event)
        return True

    def _consume_tool_result(self, record: Mapping[str, Any]) -> bool:
        if not (
            record.get("type") == "extension_ui_request"
            and record.get("method") == "setStatus"
            and record.get("statusKey") == _TOOL_RESULT_STATUS_KEY
        ):
            return False
        raw = record.get("statusText")
        if not isinstance(raw, str):
            raise ToolsetProtocolError("PI emitted an empty tool result")
        try:
            parsed = _ToolResultRecord.model_validate_json(raw)
        except ValidationError as exc:
            raise ToolsetProtocolError("PI emitted an invalid tool result") from exc
        future = self._tool_results.get(parsed.invocation_id)
        if future is None:
            raise ToolsetProtocolError("PI emitted an uncorrelated tool result")
        if not future.done():
            future.set_result(parsed)
        return True

    def _set_reader_error(self, error: ToolsetError) -> None:
        self._reader_error = error
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        for future in self._tool_results.values():
            if not future.done():
                future.set_exception(error)

    async def _drain_stderr(self) -> None:
        if self._process.stderr is None:
            return
        while chunk := await self._process.stderr.read(4096):
            self._stderr_tail.extend(chunk)
            if len(self._stderr_tail) > 4096:
                del self._stderr_tail[:-4096]

    async def _finish_reader_tasks(self) -> None:
        for task in (self._reader_task, self._stderr_task):
            if task.done():
                with suppress(asyncio.CancelledError, Exception):
                    await task
                continue
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _exit_message(self) -> str:
        detail = " ".join(self._stderr_tail.decode("utf-8", errors="replace").split())
        suffix = f": {detail}" if detail else ""
        return f"PI RPC process ended unexpectedly{suffix}"
