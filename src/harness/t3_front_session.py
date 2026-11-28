"""Adapt one local ACP connection to the daemon's ordinary, journaled run."""

import asyncio
import json
from pathlib import Path
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid4, uuid5

from harness.envelope import ImageInput, StopReason
from harness.project_path import repository_root
from harness.t3_client import T3Error

MODELS = {
    "models": {
        "currentModelId": "default",
        "availableModels": [{"modelId": "default", "name": "Nocturne home strategy"}],
    }
}
CLEARED = "T3 cleared its own context. Start a new thread in Nocturne for a fresh conversation."
IMAGE_GUIDE = "Choose one PNG, JPEG, WebP or GIF image, up to 5 MiB."


def prompt_image(attachments, blocks):
    # T3 prepends missed images on recovery. Only the active message owns the final image.
    if not attachments:
        return None
    if len(attachments) != 1:
        raise ValueError(IMAGE_GUIDE)
    attachment = attachments[0]
    block = next((b for b in reversed(blocks) if b.get("type") != "text"), {})
    if (
        attachment.get("type") != "image"
        or block.get("type") != "image"
        or block.get("mimeType") != attachment.get("mimeType")
    ):
        raise ValueError(IMAGE_GUIDE)
    return ImageInput(kind="image", media_type=block.get("mimeType"), data_base64=block.get("data"))


def unsubmitted_messages(transcript, bindings):
    # The full transcript keeps declined files and failed starts after the run projection rolls off.
    items = [row["item"] for row in transcript["items"]]
    failed = {item["runId"] for item in items if item["type"] == "error" and item.get("runId")}
    return {
        item["messageId"]
        for item in items
        if item["type"] == "user_message"
        and (item.get("attachments") or item.get("runId") in failed)
        and item["messageId"] not in bindings
        and not item["messageId"].startswith("nocturne-journal-")
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
        self.card_answered = False
        self.node = None
        self.native_run = None
        self.turn_client = None
        self.events = None
        self.superseded = False
        self.can_show_compaction = False

    async def send(self, **message):
        self.writer.write(json.dumps({"jsonrpc": "2.0", **message}).encode() + b"\n")
        await self.writer.drain()

    async def update(self, **fields):
        await self.send(
            method="session/update", params={"sessionId": self.session, "update": fields}
        )

    async def cancel(self):
        self.stopping = True
        if self.run and not self.cancel_sent and not self.superseded:
            self.cancel_sent = True
            await self.front.loop.cancel(thread_id=self.thread, run_id=self.run)

    async def window_cancel(self):
        # T3 commits the replacement attempt before it interrupts the old provider.
        if self.native_run and self.node:
            try:
                projection = await self.turn_client.call(
                    "orchestration.getThreadProjection", {"threadId": self.native}
                )
            except (T3Error, TimeoutError, OSError):
                # On shutdown the original client may already be gone. Never start a new server.
                await self.cancel()
                return
            run = next((r for r in projection["runs"] if r["id"] == self.native_run), None)
            attempts = [a for a in projection["attempts"] if a["runId"] == self.native_run]
            if (
                run
                and any(
                    a.get("rootNodeId") == self.node and a["status"] == "superseded"
                    for a in attempts
                )
                and any(
                    a["id"] == run["activeAttemptId"] and a["reason"] == "steering_restart"
                    for a in attempts
                )
            ):
                # Release this T3 prompt. Its replacement enters the ordinary FIFO via submit().
                self.superseded = True
                if self.events is not None:
                    self.events.put_nowait(None)
                return
        await self.cancel()

    async def serve(self):
        try:
            while raw := await self.reader.readline():
                request = json.loads(raw)
                method = request.get("method")
                if method is None:
                    # A T3 acknowledgement never decides a Deck card.
                    if request.get("id") == self.card:
                        self.card_answered = True
                    continue
                params = request.get("params", {})
                rid = request.get("id")
                if method == "initialize":
                    session_caps = params.get("clientCapabilities", {}).get("session", {})
                    self.can_show_compaction = "compaction" in session_caps
                    result = {
                        "protocolVersion": 1,
                        "agentCapabilities": {
                            "loadSession": True,
                            "promptCapabilities": {"image": True},
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
                    journal_id = None
                    if self.native:
                        client = await self.front.client()
                        journal_id = str(
                            uuid5(
                                NAMESPACE_URL, f"nocturne:t3:{client.environment_id}/{self.native}"
                            )
                        )
                        if (
                            self.front.journal.current_thread(self.native) is not None
                            and self.front.journal.front_thread(self.native, client.environment_id)
                            == self.native
                        ):
                            journal_id = self.native
                    if method == "session/new":
                        self.thread = journal_id
                        self.session = str(uuid4())
                        if journal_id:
                            self.session = f"{journal_id}/{self.session}"
                            existing = self.front.journal.current_thread(journal_id)
                            if existing:
                                self.workspace_root = existing.workspace_root
                        result = {**MODELS, "sessionId": self.session}
                    else:
                        requested = params["sessionId"]
                        belongs = journal_id is not None and (
                            requested in {self.native, journal_id}
                            or requested.startswith(journal_id + "/")
                        )
                        key = journal_id if belongs else requested
                        transcript = self.front.journal.current_thread(key)
                        if (belongs and transcript is None) or (
                            transcript is not None
                            and (
                                not transcript.workspace_root
                                or Path(transcript.workspace_root)
                                in {self.cwd, repository_root(self.cwd)}
                            )
                        ):
                            self.thread = key
                            self.session = requested
                            if transcript:
                                self.workspace_root = transcript.workspace_root
                            for item in transcript.messages if transcript else ():
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
                    await self.window_cancel()
                    continue
                elif method == "session/prompt":
                    if self.turn is not None and not self.turn.done():
                        await self.send(
                            id=rid, error={"code": -32600, "message": "A turn is already running."}
                        )
                    else:
                        self.stopping = self.cancel_sent = self.superseded = False
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
                if method in {"session/new", "session/load"}:
                    await self.update(
                        sessionUpdate="available_commands_update",
                        availableCommands=[
                            {
                                "name": "compact",
                                "description": "Compact this conversation in Nocturne",
                            }
                        ],
                    )
        finally:
            if self.turn is not None:
                if not self.turn.done():
                    await self.window_cancel()
                await asyncio.gather(self.turn, return_exceptions=True)

    async def admission_reason(self, client, projection, message_id):
        if projection["thread"].get("forkedFrom"):
            return "This fork has T3-only history. Open the original conversation in Nocturne."
        transcript = await client.orchestration_get(
            f"threads/{quote(self.native, safe='')}/transcript"
        )
        native_ids = []
        for row in transcript["items"]:
            item = row["item"]
            if item["type"] != "user_message":
                continue
            if item.get("freshContext"):
                return CLEARED
            if item["messageId"] == message_id:
                break
            native_ids.append(item["messageId"])
        else:
            return "This message has not appeared in T3’s transcript. Open the thread in Nocturne."
        journal = self.front.journal
        bindings = journal.front_prompts(self.thread)
        skipped = unsubmitted_messages(transcript, bindings)
        previous = [
            key.removeprefix("nocturne-journal-")
            if key.startswith("nocturne-journal-")
            else bindings.get(key)
            for key in native_ids
            if key not in skipped
        ]
        history = journal.current_thread(self.thread)
        active = (
            [m["message_id"] for m in history.messages if m["role"] == "user"] if history else []
        )
        if bindings.get(message_id) in active:
            active = active[: active.index(bindings[message_id])]
        if previous != active:
            return "The thread history changed. Open the thread in Nocturne to continue."
        return None

    async def refuse(self, rid, reason):
        await self.text(reason)
        await self.send(id=rid, result={"stopReason": "refusal"})

    async def finish(self, rid, state, run, text, show_compactions=False):
        manual = text.strip() == "/compact"
        if state == "end_turn" and (manual or (show_compactions and self.can_show_compaction)):
            records = [
                r for r in self.front.journal.compaction_records(self.thread) if r["run_id"] == run
            ]
            if manual and not records:
                # A completed ACP prompt for /compact would tell T3 it discarded old context.
                state = "refusal"
            if self.can_show_compaction:
                for record in records:
                    await self.update(
                        sessionUpdate="compaction_update",
                        compactionId=record["event_uid"],
                        status="completed",
                    )
        await self.send(id=rid, result={"stopReason": state})

    async def prompt(self, rid, blocks):
        loop = self.front.loop
        events = asyncio.Queue()
        sink = events.put
        try:
            if not self.native or self.cwd is None or not blocks:
                raise T3Error("Open a project conversation and send a prompt.")
            client = await self.front.client()
            projection = await client.call(
                "orchestration.getThreadProjection", {"threadId": self.native}
            )
            self.thread = self.thread or self.session
            if any(r.thread_id == self.thread and r.archived for r in self.front.journal.catalog()):
                return await self.refuse(
                    rid, "Nocturne archived this thread. Start a new thread to send a message."
                )
            runs = [
                r for r in projection["runs"] if r["status"] in {"starting", "running", "waiting"}
            ]
            if len(runs) != 1 or runs[0]["providerInstanceId"] != "nocturne":
                return await self.refuse(
                    rid,
                    "T3 could not match this turn. Open the thread in Nocturne to continue.",
                )
            message_id = runs[0]["userMessageId"]
            self.node = runs[0].get("rootNodeId")
            self.native_run = runs[0].get("id")
            self.turn_client = client
            message = next(m for m in projection["messages"] if m["id"] == message_id)
            if message["role"] != "user":
                raise T3Error("T3 could not match the user message for this turn.")
            replay = message_id.startswith("nocturne-journal-")
            if replay:
                # Display an existing answer without selecting a thread or creating a model run.
                history = self.front.journal.current_thread(self.thread)
                messages = history.messages if history else ()
                prompt_id = message_id.removeprefix("nocturne-journal-")
            else:
                if runs[0].get("freshContext"):
                    return await self.refuse(rid, CLEARED)
                reason = await self.admission_reason(client, projection, message_id)
                if reason:
                    return await self.refuse(rid, reason)
                try:
                    image = prompt_image(message.get("attachments", []), blocks)
                except ValueError:
                    # The explanation completes the ACP exchange without starting a model turn.
                    await self.text(IMAGE_GUIDE)
                    await self.send(id=rid, result={"stopReason": "end_turn"})
                    return
                await loop.request_snapshot(self.thread, sink, workspace_root=self.workspace_root)
                messages = (await events.get()).payload.messages
                prompt_id = self.front.journal.bind_front_prompt(
                    self.thread, client.environment_id, self.native, message_id
                )
            prior = next(
                (m for m in messages if m["message_id"] == prompt_id and m["role"] == "user"), None
            )
            if replay and (prior is None or prior["content"] != message["text"]):
                raise T3Error("The journal entry changed before T3 could display it.")
            if prior is not None:
                answer = next(
                    (
                        m
                        for m in messages
                        if m["role"] == "assistant" and m.get("run_id") == prior["run_id"]
                    ),
                    None,
                )
                state = prior.get("state")
                if answer and state in StopReason:
                    await self.text(answer.get("content", ""))
                    if state in {"end_turn", "cancelled"}:
                        await self.finish(rid, state, prior["run_id"], message["text"], True)
                        return
                    raise T3Error(f"The Nocturne journal records this turn as {state}.")
                raise T3Error("Nocturne already accepted this turn. Open its journal to review it.")
            self.run = await loop.submit(
                thread_id=self.thread,
                prompt_id=prompt_id,
                prompt=message["text"],
                image=image,
                sink=sink,
            )
            self.events = events
            if self.superseded:
                events.put_nowait(None)
            if self.stopping:
                await self.cancel()
            compacted = False
            while True:
                envelope = await events.get()
                if envelope is None:
                    self.run = None
                    await self.send(id=rid, result={"stopReason": "cancelled"})
                    return
                payload = envelope.payload
                if getattr(payload, "run_id", None) != self.run:
                    continue
                if envelope.type == "run.delta":
                    if payload.kind == "text":
                        await self.text(payload.text)
                    elif (
                        payload.kind == "event"
                        and payload.event.get("event_kind") == "compaction_completed"
                    ):
                        compacted = True
                    elif (
                        payload.kind == "event"
                        and payload.event.get("event_kind") == "boundary_card"
                    ):
                        if payload.event.get("decision") == "owner_action":
                            await self.show_card("Answer the crossing in Nocturne’s window")
                        else:
                            await self.dismiss_card(client)
                elif envelope.type == "gate.open":
                    await self.show_card("Review the memories in Nocturne’s window")
                elif envelope.type == "gate.dismiss":
                    await self.dismiss_card(client)
                elif envelope.type == "run.done":
                    await self.dismiss_card(client)
                    if payload.stop_reason not in {"cancelled", "end_turn"}:
                        self.run = None
                        raise T3Error(payload.error_message or "Nocturne stopped the turn.")
                    await self.finish(
                        rid, payload.stop_reason, self.run, message["text"], compacted
                    )
                    self.run = None
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
            self.native_run = self.events = self.turn_client = None
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
        self.card_answered = False
        call = {"toolCallId": call_id, "title": title, "kind": "other"}
        await self.update(sessionUpdate="tool_call", **call, status="pending")
        await self.send(
            id=call_id,
            method="elicitation/create",
            params={
                "sessionId": self.session,
                "mode": "form",
                "message": title,
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "review": {
                            "type": "string",
                            "title": "Nocturne",
                            "description": title,
                            "enum": ["Answer in Nocturne’s window"],
                        }
                    },
                    "required": ["review"],
                },
            },
        )

    async def dismiss_card(self, client):
        if self.card is None:
            return
        call_id = self.card
        for _ in range(12):
            if self.card_answered:
                break
            projection = await client.call(
                "orchestration.getThreadProjection", {"threadId": self.native}
            )
            card = next(
                (
                    request
                    for request in projection["runtimeRequests"]
                    if request["kind"] == "user_input"
                    and request["nodeId"] == self.node
                    and request["status"] == "pending"
                ),
                None,
            )
            if card is not None:
                # No answers: cancel only this run's informational form after the Deck decides.
                await client.dispatch(self.native, "runtime-request.respond", requestId=card["id"])
                break
            await asyncio.sleep(0.1)
        await self.update(sessionUpdate="tool_call_update", toolCallId=call_id, status="completed")
        self.card = None
