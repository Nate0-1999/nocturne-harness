"""The explicitly selected conversation delegate, called downstream of the Palace gate."""

import asyncio
import hashlib
import logging
import re
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import RequestUsage

from harness.envelope import StopReason
from harness.run_protocol import TurnOutcome
from harness.t3_client import TERMINAL, RunTransitions, T3Error, new_id
from harness.t3_sources import resolve_offer, terminal_context

logger = logging.getLogger(__name__)


class SubscriptionTurns:
    def __init__(self, ordinary, server, journal, location, context_windows=None):
        self.ordinary = ordinary
        self.server = server
        self.journal = journal
        self.location = location
        self.context_windows = context_windows

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
        selection = {"instanceId": source["tool"], "model": model["id"]}
        effort = model_resolution.request_parameters.effort
        if effort is not None:
            thinking = model.get("thinking") or {}
            if effort not in thinking.get("levels", []):
                raise T3Error("This model no longer offers the selected thinking level.")
            selection["options"] = [
                {
                    "id": thinking["id"],
                    "value": effort == "on" if thinking["id"] == "thinking" else effort,
                }
            ]
        binding = self.journal.subscription_binding(thread_id)
        workspace = str(self.location(thread_id).resolve(strict=True))
        environment = hashlib.sha256(client.environment_id.encode()).hexdigest()
        if (
            binding
            and binding.get("native_session")
            and binding["source"] == f"subscription:{source['tool']}/{model['id']}"
        ):
            # Offline history had no account to pin. Bind the verified offer before the first send.
            binding = {**binding, "source": key}
            self.journal.bind_subscription(thread_id, binding)
        same_source = binding is not None and binding["source"] == key
        if same_source:
            if binding["environment"] != environment:
                raise T3Error("The subscription server no longer matches this conversation.")
            prior = await client.call(
                "orchestration.getThreadProjection", {"threadId": binding["native_thread"]}
            )
            if any(run["status"] not in TERMINAL for run in prior["runs"]):
                raise T3Error("A previous subscription turn is still open.")
        if (
            binding
            and binding.get("native_session")
            and (not same_source or binding["location"] != workspace)
        ):
            raise T3Error("The original tool session or conversation folder has changed.")
        fresh = not same_source or binding.get("location") != workspace
        if fresh:
            title = self.journal.conversation_title(thread_id).strip() or "Nocturne conversation"
            binding = {
                "source": key,
                "environment": environment,
                "location": workspace,
                "native_project": await client.workspace_project(workspace, title),
                "native_thread": new_id(),
            }
            self.journal.bind_subscription(thread_id, binding)
        thread = binding["native_thread"]
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

        def allow_conversation():
            binding["permission"] = "allowed_thread"
            self.journal.bind_subscription(thread_id, binding)

        observer = NativeTurn(
            client, thread, message, emit, source["name"], binding, allow_conversation
        )
        if fresh:
            await emit.text(
                f"{source['name']} works in {workspace}, reads its project instructions at startup "
                "and asks before edits or commands. Its steps are outside Nocturne’s fence.\n\n"
            )
        send = asyncio.create_task(
            client.launch(binding["native_project"], thread, message, text, selection, title)
            if fresh
            else client.message(
                thread, message, text, selection, archived=prior["thread"]["archivedAt"] is not None
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
            if (
                observer.transitions.finished
                and source["tool"] == "codex"
                and not binding.get("native_session")
            ):
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
            if self.context_windows is not None and observer.context_usage is not None:
                window, inputs, outputs = observer.context_usage
                response = replace(
                    history[-1], usage=RequestUsage(input_tokens=inputs, output_tokens=outputs)
                )
                self.context_windows.record(
                    thread_id=thread_id,
                    captured=[response],
                    resolution=replace(model_resolution, context_tokens=window),
                    memory_block=context.memory_block if context else None,
                    memory_allocation=getattr(context, "memory_allocation", None),
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
    def __init__(self, client, thread, message, emit, tool, binding, allow_conversation):
        self.client, self.thread, self.message, self.emit = client, thread, message, emit
        self.run = None
        self.transitions = RunTransitions()
        self.written = {}
        self.handled = set()
        self.tool = tool
        self.binding = binding
        self.allow_conversation = allow_conversation
        self.answer = ""
        self.context_usage = None

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

    async def request(self, item, details):
        request = item["id"]
        if item["status"] != "pending" or request in self.handled:
            return
        detail = next(
            (
                d
                for d in details
                if d["type"] == "approval_request"
                and d.get("requestId") == request
                and d.get("runId") == self.run
            ),
            None,
        )
        if detail is None:
            return  # The matching turn item may arrive after the request event.
        description = (
            "\n".join(
                dict.fromkeys(value for key in ("prompt", "reason") if (value := detail.get(key)))
            )
            or item["kind"]
        )
        card = {
            "event_kind": "boundary_card",
            "wall": "subscription",
            "judge": self.tool,
            "policy": self.binding["location"],
            "run_id": self.emit.run_id,
            "card_id": request,
            "reason": re.sub(
                r"[\w.+%-]+@[\w.-]+",
                "[private address]",
                f"{item['kind'].replace('-', ' ').capitalize()}: {description}",
            ),
            "decision": "owner_action",
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.handled.add(request)
        already_allowed = self.binding.get("permission") == "allowed_thread"
        if already_allowed and not detail.get("fullAccessOverride"):
            await self.emit.event({**card, "decision": "requested"})
            decision = "allowed_thread"
        else:
            decision = await self.emit.boundary_decision(card)
        await self.emit.event(
            {**card, "decision": decision, "created_at": datetime.now(UTC).isoformat()}
        )
        if decision == "allowed_thread" and not already_allowed:
            self.allow_conversation()
            await self.emit.text(f"\nYou allowed {self.tool}’s requests for this conversation.\n")
        await self.client.respond(
            self.thread, request, allow=decision in {"allowed_once", "allowed_thread"}
        )
        if decision == "denied":
            await self.emit.text(f"\nYou denied {self.tool}’s request.\n")

    async def sync(self):
        projection = await self.projection()
        run = next((r for r in projection["runs"] if r["userMessageId"] == self.message), None)
        if not run:
            return None
        self.run = run["id"]
        for item in projection["runtimeRequests"]:
            await self.request(item, projection.get("turnItems", ()))
        for msg in projection["messages"]:
            await self.update(msg)
        if run["status"] == "completed":
            self.context_usage = terminal_context(projection, run)
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
                    elif kind == "runtime-request.updated" or (
                        kind == "turn-item.updated" and payload.get("type") == "approval_request"
                    ):
                        if status := await self.sync():
                            return status
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
