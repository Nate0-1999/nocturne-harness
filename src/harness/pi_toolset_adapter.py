"""The sole adapter between Nocturne's toolset seam and PI's JSONL RPC process."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError

from harness.toolset import (
    ToolsetProtocolError,
    ToolsetState,
    ToolsetUnavailableError,
)

_RUNTIME_ROOT = Path(__file__).with_name("_pi")
_MAX_RECORD_BYTES = 1_048_576


class _RpcState(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    isStreaming: StrictBool
    isCompacting: StrictBool
    autoCompactionEnabled: StrictBool
    messageCount: StrictInt
    pendingMessageCount: StrictInt


def _default_command() -> tuple[str, ...]:
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
        timeout_seconds: float,
    ) -> None:
        self._process = process
        self._timeout_seconds = timeout_seconds
        self._request_lock = asyncio.Lock()
        self._request_sequence = 0

    @classmethod
    async def open(
        cls,
        *,
        command: Sequence[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 5.0,
    ) -> Self:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        argv = tuple(command) if command is not None else _default_command()
        if not argv or any(not part for part in argv):
            raise ValueError("command must contain only nonblank arguments")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                "--mode",
                "rpc",
                "--no-session",
                "--no-approve",
                "--offline",
                cwd=str(cwd or Path.cwd()),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_MAX_RECORD_BYTES,
            )
        except OSError as exc:
            raise ToolsetUnavailableError(f"PI could not start: {exc}") from exc
        return cls(process, timeout_seconds=timeout_seconds)

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

    async def close(self) -> None:
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            self._process.stdin.close()
            try:
                await self._process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if self._process.returncode is not None:
            return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=1.0)
            return
        except TimeoutError:
            self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=1.0)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()

    async def _request(self, command: str) -> Mapping[str, Any]:
        async with self._request_lock:
            if self._process.stdin is None or self._process.stdout is None:
                raise ToolsetProtocolError("PI process pipes are unavailable")
            if self._process.returncode is not None:
                raise ToolsetUnavailableError(await self._exit_message())

            self._request_sequence += 1
            request_id = f"nocturne-{self._request_sequence}"
            wire = json.dumps(
                {"id": request_id, "type": command},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self._process.stdin.write(wire + b"\n")
            try:
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ToolsetUnavailableError(await self._exit_message()) from exc

            while True:
                record = await self._read_record()
                if record.get("type") != "response" or record.get("id") != request_id:
                    continue
                if record.get("command") != command:
                    raise ToolsetProtocolError("PI correlated the wrong RPC command")
                if record.get("success") is not True:
                    error = record.get("error")
                    detail = error if isinstance(error, str) and error else "request refused"
                    raise ToolsetProtocolError(f"PI {command} failed: {detail}")
                return record

    async def _read_record(self) -> Mapping[str, Any]:
        assert self._process.stdout is not None
        try:
            raw = await asyncio.wait_for(
                self._process.stdout.readuntil(b"\n"),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise ToolsetProtocolError("PI RPC response timed out") from exc
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            raise ToolsetProtocolError(await self._exit_message()) from exc

        if len(raw) > _MAX_RECORD_BYTES:
            raise ToolsetProtocolError("PI RPC record exceeded the one-MiB seam bound")
        if raw.endswith(b"\n"):
            raw = raw[:-1]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolsetProtocolError("PI emitted malformed UTF-8 JSONL") from exc
        if not isinstance(decoded, Mapping):
            raise ToolsetProtocolError("PI emitted a non-object RPC record")
        return decoded

    async def _exit_message(self) -> str:
        detail = ""
        if self._process.stderr is not None and self._process.returncode is not None:
            raw = await self._process.stderr.read(4096)
            detail = " ".join(raw.decode("utf-8", errors="replace").split())
        suffix = f": {detail}" if detail else ""
        return f"PI RPC process ended unexpectedly{suffix}"
