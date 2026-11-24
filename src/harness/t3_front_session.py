"""Adapt one local ACP connection to the daemon's ordinary, journaled run."""

import asyncio
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from harness.t3_client import TERMINAL, T3Error

MODELS = {
    "models": {
        "currentModelId": "default",
        "availableModels": [{"modelId": "default", "name": "Nocturne home strategy"}],
    }
}


class FrontSession:
    def __init__(self, front, native, reader, writer):
        self.front, self.reader, self.writer = front, reader, writer
        self.native = native
        self.session = None
        self.cwd = None
        self.workspace_root = None
        self.turn = None
        self.thread = None
        self.run = None
        self.stopping = False
        self.cancel_sent = False
        self.card = None

    async def send(self, **message):
        self.writer.write(json.dumps({"jsonrpc": "2.0", **message}).encode() + b"\n")
        await self.writer.drain()

    async def update(self, **fields):
        await self.send(
            method="session/update", params={"sessionId": self.session, "update": fields}
        )

    async def cancel(self):
        self.stopping = True
        if self.run and not self.cancel_sent:
            self.cancel_sent = True
            await self.front.loop.cancel(thread_id=self.thread, run_id=self.run)

    async def serve(self):
        try:
            while raw := await self.reader.readline():
                request = json.loads(raw)
                method = request.get("method")
                if method is None:
                    # A T3 acknowledgement never decides a Deck card.
                    continue
                params = request.get("params", {})
                rid = request.get("id")
                if method == "initialize":
                    result = {
                        "protocolVersion": 1,
                        "agentCapabilities": {
                            "loadSession": True,
                            "sessionCapabilities": {"list": {}},
                        },
                        "authMethods": [],
                        "agentInfo": {"name": "Nocturne", "version": "1"},
                    }
                elif method == "session/list":
                    cwd = params.get("cwd")
                    sessions = [
                        {
                            "sessionId": row.thread_id,
                            "cwd": row.workspace_root or str(self.front.default_root),
                            "title": row.title,
                            "updatedAt": row.updated_at,
                        }
                        for row in self.front.journal.catalog()
                        if not row.archived
                        and (not cwd or (row.workspace_root or str(self.front.default_root)) == cwd)
                    ]
                    start = int(params.get("cursor") or 0)
                    result = {"sessions": sessions[start : start + 256]}
                    if start + 256 < len(sessions):
                        result["nextCursor"] = str(start + 256)
                elif method in {"session/new", "session/load"}:
                    self.cwd = Path(params["cwd"]).resolve(strict=True)
                    self.workspace_root = str(self.cwd)
                    if method == "session/new":
                        if self.native:
                            client = await self.front.client()
                            self.session = str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"nocturne:t3:{client.environment_id}/{self.native}",
                                )
                            )
                        else:
                            self.session = str(uuid4())
                        result = {**MODELS, "sessionId": self.session}
                    else:
                        transcript = self.front.journal.current_thread(params["sessionId"])
                        if (
                            transcript is None
                            and self.native
                            and params["sessionId"] == self.native
                        ):
                            client = await self.front.client()
                            key = str(
                                uuid5(
                                    NAMESPACE_URL,
                                    f"nocturne:t3:{client.environment_id}/{self.native}",
                                )
                            )
                            transcript = self.front.journal.current_thread(key)
                        if transcript is not None and (
                            not transcript.workspace_root
                            or Path(transcript.workspace_root) == self.cwd
                        ):
                            self.thread = transcript.thread_id
                            self.session = params["sessionId"]
                            self.workspace_root = transcript.workspace_root
                            for item in transcript.messages:
                                role = item["role"]
                                if role in {"user", "assistant"} and item.get("content"):
                                    await self.update(
                                        sessionUpdate="user_message_chunk"
                                        if role == "user"
                                        else "agent_message_chunk",
                                        messageId=item["message_id"],
                                        content={"type": "text", "text": item["content"]},
                                    )
                            result = dict(MODELS)
                        else:
                            await self.send(
                                id=rid,
                                error={
                                    "code": -32602,
                                    "message": "Unknown conversation in this project.",
                                },
                            )
                            continue
                elif params.get("sessionId") != self.session:
                    if rid is not None:
                        await self.send(
                            id=rid, error={"code": -32602, "message": "Unknown conversation."}
                        )
                    continue
                elif method == "session/cancel":
                    await self.cancel()
                    continue
                elif method == "session/prompt":
                    if self.turn is not None and not self.turn.done():
                        await self.send(
                            id=rid, error={"code": -32600, "message": "A turn is already running."}
                        )
                    else:
                        self.stopping = self.cancel_sent = False
                        self.turn = asyncio.create_task(self.prompt(rid, params.get("prompt", [])))
                    continue
                elif method == "session/set_model" and params.get("modelId") == "default":
                    result = {}
                else:
                    if rid is not None:
                        await self.send(
                            id=rid, error={"code": -32601, "message": "Unsupported method."}
                        )
                    continue
                await self.send(id=rid, result=result)
        finally:
            if self.turn is not None:
                if not self.turn.done():
                    await self.cancel()
                await asyncio.gather(self.turn, return_exceptions=True)

    async def prompt(self, rid, blocks):
        loop = self.front.loop
        events = asyncio.Queue()
        sink = events.put
        try:
            if (
                not self.native
                or self.cwd is None
                or not blocks
                or any(block.get("type") != "text" for block in blocks)
            ):
                raise T3Error("Open a project conversation and send a text prompt.")
            client = await self.front.client()
            projection = await client.call(
                "orchestration.getThreadProjection", {"threadId": self.native}
            )
            runs = [run for run in projection["runs"] if run["status"] not in TERMINAL]
            if len(runs) != 1 or runs[0]["providerInstanceId"] != "nocturne":
                raise T3Error("T3 could not identify one active Nocturne turn.")
            message_id = runs[0]["userMessageId"]
            message = next(m for m in projection["messages"] if m["id"] == message_id)
            if message["role"] != "user" or message.get("attachments"):
                raise T3Error("This Nocturne conversation accepts text prompts.")
            self.thread = self.thread or self.session
            await loop.request_snapshot(self.thread, sink, workspace_root=self.workspace_root)
            snapshot = (await events.get()).payload
            replay = next(
                (
                    m
                    for m in snapshot.messages
                    if m.get("role") == "user"
                    and m["message_id"] == message_id
                    and m["content"] == message["text"]
                ),
                None,
            )
            prompt_id = (
                replay["message_id"]
                if replay
                else self.front.journal.bind_front_prompt(
                    self.thread, client.environment_id, self.native, message_id
                )
            )
            prior = next((m for m in snapshot.messages if m["message_id"] == prompt_id), None)
            if prior is not None:
                answer = next(
                    (
                        m
                        for m in snapshot.messages
                        if m["role"] == "assistant" and m.get("run_id") == prior["run_id"]
                    ),
                    None,
                )
                if answer and prior.get("state") == "end_turn" and not answer.get("partial", True):
                    await self.text(answer["content"])
                    await self.send(id=rid, result={"stopReason": "end_turn"})
                    return
                raise T3Error("Nocturne already accepted this turn. Open its journal to review it.")
            self.run = await loop.submit(
                thread_id=self.thread, prompt_id=prompt_id, prompt=message["text"], sink=sink
            )
            if self.stopping:
                await self.cancel()
            while True:
                envelope = await events.get()
                payload = envelope.payload
                if getattr(payload, "run_id", None) != self.run:
                    continue
                if envelope.type == "run.delta":
                    if payload.kind == "text":
                        await self.text(payload.text)
                    elif (
                        payload.kind == "event"
                        and payload.event.get("event_kind") == "boundary_card"
                    ):
                        if payload.event.get("decision") == "owner_action":
                            await self.show_card("Review the crossing on Nocturne’s Deck")
                        else:
                            await self.dismiss_card(client)
                elif envelope.type == "gate.open":
                    await self.show_card("Review the memories on Nocturne’s Deck")
                elif envelope.type == "gate.dismiss":
                    await self.dismiss_card(client)
                elif envelope.type == "run.done":
                    await self.dismiss_card(client)
                    self.run = None
                    if payload.stop_reason not in {"cancelled", "end_turn"}:
                        raise T3Error(payload.error_message or "Nocturne stopped the turn.")
                    await self.send(id=rid, result={"stopReason": payload.stop_reason})
                    break
        except (ConnectionError, asyncio.CancelledError):
            await self.cancel()
            raise
        except Exception as exc:
            await self.cancel()
            await self.send(
                id=rid,
                error={
                    "code": -32603,
                    "message": str(exc)
                    if isinstance(exc, T3Error)
                    else "Nocturne could not confirm the conversation turn.",
                },
            )
        finally:
            self.run = None
            await loop.detach(sink)

    async def text(self, value):
        if value:
            await self.update(
                sessionUpdate="agent_message_chunk", content={"type": "text", "text": value}
            )

    async def show_card(self, title):
        if self.card is not None:
            return
        call_id = str(uuid4())
        self.card = call_id
        call = {"toolCallId": call_id, "title": title, "kind": "other"}
        await self.update(sessionUpdate="tool_call", **call, status="pending")
        await self.send(
            id=call_id,
            method="session/request_permission",
            params={
                "sessionId": self.session,
                "toolCall": call,
                "options": [
                    {"optionId": "seen", "name": "Review on the Deck", "kind": "allow_once"}
                ],
            },
        )

    async def dismiss_card(self, client):
        if self.card is None:
            return
        call_id = self.card
        for _ in range(12):
            projection = await client.call(
                "orchestration.getThreadProjection", {"threadId": self.native}
            )
            card = next(
                (
                    request
                    for request in projection["runtimeRequests"]
                    if (request.get("nativeRequestRef") or {}).get("nativeId") == call_id
                ),
                None,
            )
            if card is not None:
                if card["status"] == "pending":
                    # The Deck already decided. Retire only this ACP notification.
                    await client.dispatch(
                        self.native,
                        "runtime-request.respond",
                        requestId=card["id"],
                        decision="cancel",
                    )
                break
            await asyncio.sleep(0.1)
        await self.update(sessionUpdate="tool_call_update", toolCallId=call_id, status="completed")
        self.card = None
