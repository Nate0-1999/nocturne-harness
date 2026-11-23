"""The explicitly selected conversation delegate, called downstream of the Palace gate."""

import asyncio
import hashlib
import logging
import re
from contextlib import aclosing

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from harness.envelope import StopReason
from harness.run_protocol import TurnOutcome
from harness.t3_client import TERMINAL, RunTransitions, T3Error, new_id
from harness.t3_sources import resolve_offer

logger = logging.getLogger(__name__)


def _native_names(title: str, project_id: str) -> tuple[str, str]:
    title = title.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-")
    return title or "Nocturne conversation", f"nocturne-{slug or 'conversation'}-{project_id[:8]}"


class SubscriptionTurns:
    def __init__(self, ordinary, server, journal):
        self.ordinary = ordinary
        self.server = server
        self.journal = journal

    async def run(
        self, *, thread_id, prompt, message_history, emit, model_resolution=None, **options
    ):
        if model_resolution is None or not model_resolution.model.startswith("subscription:"):
            return await self.ordinary.run(
                thread_id=thread_id,
                prompt=prompt,
                message_history=message_history,
                emit=emit,
                model_resolution=model_resolution,
                **options,
            )
        if options.get("image") is not None:
            raise T3Error("The subscription route accepts text only.")
        key, source, model = await resolve_offer(self.server, model_resolution.model)
        client = await self.server.client()
        binding = self.journal.subscription_binding(thread_id)
        fresh = binding is None or binding["source"] != key
        if fresh:
            binding = {
                "source": key,
                "environment": hashlib.sha256(client.environment_id.encode()).hexdigest(),
                "native_project": new_id(),
                "native_thread": new_id(),
            }
            title, folder = _native_names(
                self.journal.conversation_title(thread_id), binding["native_project"]
            )
            workspace = self.server.root / "workspace" / folder
            workspace.mkdir(mode=0o700)
            await client.call(
                "projects.mutate",
                {
                    "type": "project.create",
                    "projectId": binding["native_project"],
                    "commandId": new_id(),
                    "title": title,
                    "workspaceRoot": str(workspace),
                },
            )
            self.journal.bind_subscription(thread_id, binding)
        elif binding["environment"] != hashlib.sha256(client.environment_id.encode()).hexdigest():
            raise T3Error("The subscription server no longer matches this conversation.")
        thread = binding["native_thread"]
        if not fresh:
            prior = await client.call("orchestration.getThreadProjection", {"threadId": thread})
            if any(run["status"] not in TERMINAL for run in prior["runs"]):
                raise T3Error("A previous subscription turn is still open.")
        message = new_id()
        context = options.get("dynamic_instructions")
        blocks = []
        if fresh and message_history:
            for entry in message_history:
                for part in entry.parts:
                    if isinstance(part, (UserPromptPart, TextPart)) and isinstance(
                        part.content, str
                    ):
                        role = "User" if isinstance(part, UserPromptPart) else "Assistant"
                        blocks.append(f"{role}: {part.content}")
        if context:
            await context.render()
            if context.memory_block:
                blocks.append(context.memory_block)
        blocks.append(prompt)
        text = "\n\n".join(blocks)
        observer = NativeTurn(client, thread, message, emit)
        if fresh:
            await emit.text(
                f"{source['name']} controls its own actions outside Nocturne’s fence.\n\n"
            )
        send = asyncio.create_task(
            client.launch(
                binding["native_project"], thread, message, text, source["tool"], model["id"], title
            )
            if fresh
            else client.message(
                thread, message, text, archived=prior["thread"]["archivedAt"] is not None
            )
        )
        try:
            acknowledgement = await asyncio.shield(send)
            status = await observer.observe(acknowledgement["sequence"])
        except asyncio.CancelledError:
            # A Stop arriving during submit must follow the accepted message to its actual run.
            await send
            await observer.stop()
            raise
        finally:
            if observer.transitions.finished and source["tool"] == "codex":
                try:
                    await client.archive_codex(thread, message)
                except Exception as exc:
                    logger.warning(
                        "Could not archive native Codex thread for %s (%s). It may remain active.",
                        thread,
                        str(exc) if isinstance(exc, T3Error) else type(exc).__name__,
                    )
        history = tuple(message_history)
        if status == "completed":
            history += (
                ModelRequest(parts=[UserPromptPart(prompt)]),
                ModelResponse(parts=[TextPart(observer.answer)], model_name=key),
            )
        reason = {
            "completed": StopReason.END_TURN,
            "interrupted": StopReason.CANCELLED,
            "cancelled": StopReason.CANCELLED,
        }.get(status, StopReason.ERROR)
        return TurnOutcome(
            reason,
            history,
            error_message="The native turn failed." if reason == StopReason.ERROR else None,
        )


class NativeTurn:
    def __init__(self, client, thread, message, emit):
        self.client, self.thread, self.message, self.emit = client, thread, message, emit
        self.run = None
        self.transitions = RunTransitions()
        self.written = {}
        self.declined = set()
        self.answer = ""

    async def projection(self):
        return await self.client.call(
            "orchestration.getThreadProjection", {"threadId": self.thread}
        )

    async def update(self, msg):
        if msg["role"] != "assistant" or msg.get("runId") != self.run or not self.run:
            return
        text = msg["text"]
        prior = self.written.get(msg["id"], "")
        if text.startswith(prior) and text != prior:
            delta = text[len(prior) :]
            await self.emit.text(delta)
            self.answer += delta
            self.written[msg["id"]] = text

    async def request(self, item):
        if item["status"] == "pending" and item["id"] not in self.declined:
            await self.client.decline(self.thread, item["id"])
            self.declined.add(item["id"])
            await self.emit.text("\nNocturne declined the tool’s approval request.\n")

    async def sync(self):
        projection = await self.projection()
        run = next((r for r in projection["runs"] if r["userMessageId"] == self.message), None)
        if not run:
            return None
        self.run = run["id"]
        for item in projection["runtimeRequests"]:
            await self.request(item)
        for msg in projection["messages"]:
            await self.update(msg)
        return self.transitions.terminal({"type": "run.updated", "payload": run})

    async def observe(self, after):
        status = await self.sync()
        if status:
            return status
        try:
            async with aclosing(self.client.events(self.thread, after)) as stream:
                async for frame in stream:
                    event = frame.get("event", {})
                    kind = event.get("type")
                    payload = event.get("payload", {})
                    if kind == "run.updated" and payload.get("userMessageId") == self.message:
                        self.run = payload["id"]
                        if payload["status"] in TERMINAL:
                            if status := await self.sync():
                                return status
                    elif kind == "message.updated":
                        await self.update(payload)
                    elif kind == "runtime-request.updated":
                        await self.request(payload)
                    elif frame.get("kind") in {"snapshot", "synchronized"}:
                        if status := await self.sync():
                            return status
        except T3Error:
            # Reconcile the confirmed submission without sending a second prompt.
            if status := await self.sync():
                return status
            await self.stop()
            raise
        raise T3Error("The subscription stream ended before the turn was confirmed.")

    async def stop(self):
        sent = False
        async with asyncio.timeout(30):
            while True:
                projection = await self.projection()
                run = next(
                    (r for r in projection["runs"] if r["userMessageId"] == self.message), None
                )
                if run and run["status"] in TERMINAL:
                    self.transitions.terminal({"type": "run.updated", "payload": run})
                    return
                if run and not sent:
                    await self.client.interrupt(self.thread, run["id"])
                    sent = True
                await asyncio.sleep(0.15)
