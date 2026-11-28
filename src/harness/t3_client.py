"""Local T3 orchestration protocol 2. Only Nocturne's conversation operations are exposed."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from harness import __version__
from harness.t3_install import VERSION

TERMINAL = {"completed", "failed", "interrupted", "cancelled"}
# Even with application DEBUG logging the RPC upgrade URL and headers are private.
_socket_log = logging.Logger("private-t3-socket")
_socket_log.disabled = True


class T3Error(RuntimeError):
    """A diagnostic safe to show in a Nocturne conversation."""


def new_id() -> str:
    return str(uuid4())


class RunTransitions:
    """Reduce the server's state updates, including replay, to one terminal per run."""

    def __init__(self):
        self.finished = set()

    def terminal(self, event: dict) -> str | None:
        if event.get("type") != "run.updated":
            return None
        run = event["payload"]
        if run["status"] not in TERMINAL or run["id"] in self.finished:
            return None
        self.finished.add(run["id"])
        return run["status"]


class T3Client:
    def __init__(self, port: int, *, codex_binary=None, native_env=None):
        self.origin = f"http://127.0.0.1:{port}"
        self.socket = f"ws://127.0.0.1:{port}/ws"
        self.session = ""
        self.environment_id = ""
        self.codex_binary = codex_binary
        self.native_env = native_env

    async def _http(self, path: str, *, form=None, authorized=False):
        headers = {"Authorization": f"Bearer {self.session}"} if authorized else {}
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=15) as http:
                response = await http.request(
                    "POST" if authorized or form else "GET",
                    self.origin + path,
                    data=form,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise T3Error("Local T3 authentication or discovery failed.") from None

    async def orchestration_get(self, path: str):
        async with httpx.AsyncClient(trust_env=False, timeout=60) as http:
            response = await http.get(
                self.origin + "/api/orchestration/" + path,
                headers={
                    "Authorization": f"Bearer {self.session}",
                    "x-t3-orchestration-protocol": "2",
                },
            )
            response.raise_for_status()
            return response.json()

    async def authenticate(self, code: str, *, scopes="orchestration:read orchestration:operate"):
        descriptor = await self._http("/.well-known/t3/environment")
        if (
            descriptor.get("serverVersion") != VERSION
            or descriptor.get("orchestrationProtocolVersion") != 2
        ):
            raise T3Error("The installed T3 server has an incompatible version or protocol.")
        self.environment_id = descriptor["environmentId"]
        session = await self._http(
            "/oauth/token",
            form={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token_type": "urn:t3:params:oauth:token-type:environment-bootstrap",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "subject_token": code,
                "scope": scopes,
            },
        )
        self.session = session["access_token"]

    @asynccontextmanager
    async def _connection(self):
        ticket = await self._http("/api/auth/websocket-ticket/rpc", authorized=True)
        query = urlencode({"wsTicket": ticket["ticket"], "orchestrationProtocol": 2})
        try:
            async with connect(
                f"{self.socket}?{query}", proxy=None, max_size=20 * 1024 * 1024, logger=_socket_log
            ) as ws:
                yield ws
        except (WebSocketException, OSError, ValueError, TimeoutError):
            raise T3Error("The local T3 connection closed before confirmation.") from None

    async def _frames(self, method: str, payload: dict) -> AsyncIterator[dict]:
        async with self._connection() as ws:
            rid = new_id()
            await ws.send(
                json.dumps(dict(_tag="Request", id=rid, tag=method, payload=payload, headers=[]))
            )
            while True:
                raw = json.loads(await ws.recv())
                for frame in raw if isinstance(raw, list) else [raw]:
                    if frame.get("_tag") == "Defect":
                        raise T3Error("The local T3 server rejected the request.")
                    if frame.get("requestId") != rid:
                        continue
                    if frame["_tag"] == "Exit":
                        if frame["exit"]["_tag"] != "Success":
                            raise T3Error(f"T3 could not confirm {method}.")
                        yield frame
                        return
                    if frame["_tag"] == "Chunk":
                        yield frame
                        await ws.send(json.dumps(dict(_tag="Ack", requestId=rid)))

    async def call(self, method: str, payload: dict):
        from contextlib import aclosing

        async with asyncio.timeout(90), aclosing(self._frames(method, payload)) as frames:
            async for frame in frames:
                if frame["_tag"] == "Exit":
                    return frame["exit"].get("value")
        raise T3Error("T3 returned no result.")

    async def workspace_project(self, workspace: str, title: str) -> str:
        from contextlib import aclosing

        project = new_id()
        try:
            await self.call(
                "projects.mutate",
                {
                    "type": "project.create",
                    "projectId": project,
                    "commandId": new_id(),
                    "title": title,
                    "workspaceRoot": workspace,
                },
            )
        except T3Error:
            # The pinned server accepts one project per root, even across two simultaneous opens.
            async with (
                asyncio.timeout(90),
                aclosing(self._frames("orchestration.subscribeShell", {})) as frames,
            ):
                async for frame in frames:
                    for item in frame.get("values", ()):
                        if item.get("kind") == "snapshot":
                            for existing in item["snapshot"]["projects"]:
                                if existing["workspaceRoot"] == workspace and not existing.get(
                                    "archivedAt"
                                ):
                                    return existing["id"]
                            raise
            raise
        return project

    async def events(self, thread: str, after: int):
        from contextlib import aclosing

        async with aclosing(
            self._frames(
                "orchestration.subscribeThread",
                {
                    "threadId": thread,
                    "afterSequence": after,
                    "requestCompletionMarker": True,
                },
            )
        ) as frames:
            async for frame in frames:
                for item in frame.get("values", ()):
                    yield item

    async def dispatch(self, thread: str, kind: str, **fields):
        return await self.call(
            "orchestration.dispatchCommand",
            {
                "threadId": thread,
                "type": kind,
                "commandId": new_id(),
                **fields,
            },
        )

    async def archive_codex(self, thread: str, message: str):
        projection = await self.call("orchestration.getThreadProjection", {"threadId": thread})
        run = next(r for r in projection["runs"] if r["userMessageId"] == message)
        for provider in projection["providerThreads"]:
            ref = provider["nativeThreadRef"] or {}
            if (
                provider["id"] == run["providerThreadId"]
                and provider["appThreadId"] == thread
                and ref.get("driver") == "codex"
                and ref.get("nativeId")
            ):
                if session := provider["providerSessionId"]:
                    await self.dispatch(
                        thread, "provider-session.detach", providerSessionId=session
                    )
                await self._archive_native(ref["nativeId"])
                return
        raise T3Error("The confirmed run has no native Codex thread reference.")

    async def _archive_native(self, native_id: str):
        # Ordinary T3 detaches only unsubscribe. Codex owns the active history.
        if not self.codex_binary or not self.native_env:
            raise T3Error("The local Codex app-server is unavailable.")
        proc = await asyncio.create_subprocess_exec(
            self.codex_binary,
            "app-server",
            "--listen",
            "stdio://",
            "-c",
            "analytics.enabled=false",
            cwd=self.native_env["TMPDIR"],
            env=self.native_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def send(frame):
            proc.stdin.write(json.dumps(frame).encode() + b"\n")
            await proc.stdin.drain()

        async def request(rid, method, params):
            await send({"id": rid, "method": method, "params": params})
            while raw := await proc.stdout.readline():
                frame = json.loads(raw)
                if frame.get("id") == rid:
                    if "result" in frame:
                        return
                    break
            raise T3Error(f"Codex did not confirm {method}.")

        try:
            async with asyncio.timeout(15):
                await request(
                    1, "initialize", {"clientInfo": {"name": "nocturne", "version": __version__}}
                )
                await send({"method": "initialized"})
                await request(2, "thread/archive", {"threadId": native_id})
        finally:
            proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except TimeoutError:
                proc.kill()
                await proc.wait()

    async def message(
        self, thread: str, message: str, text: str, selection: dict, *, archived: bool = False
    ):
        if archived:
            # Threads written by the earlier T3-archive build still need reopening.
            await self.dispatch(thread, "thread.unarchive")
        return await self.dispatch(
            thread,
            "message.dispatch",
            createdBy="user",
            creationSource="server",
            messageId=message,
            text=text,
            attachments=[],
            dispatchMode={"type": "start_immediately"},
            modelSelection=selection,
        )

    async def interrupt(self, thread: str, run: str):
        return await self.dispatch(thread, "run.interrupt", runId=run, holdQueue=True)

    async def decline(self, thread: str, request: str):
        return await self.respond(thread, request, allow=False)

    async def respond(self, thread: str, request: str, *, allow: bool):
        return await self.dispatch(
            thread,
            "runtime-request.respond",
            requestId=request,
            decision="accept" if allow else "decline",
        )

    async def launch(
        self,
        project: str,
        thread: str,
        message: str,
        text: str,
        selection: dict,
        title: str,
    ):
        return await self.call(
            "orchestration.launchThread",
            {
                "commandId": new_id(),
                "threadId": thread,
                "projectId": project,
                "title": title,
                "generateTitle": False,
                "modelSelection": selection,
                "runtimeMode": "approval-required",
                "interactionMode": "default",
                "workspaceStrategy": {"type": "root"},
                "initialMessage": {"messageId": message, "text": text, "attachments": []},
            },
        )
