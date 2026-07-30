"""Deterministic real-daemon fixture for H4 browser verification.

Run with::

    uvicorn scenario_app:create_scenario_app --factory \
      --app-dir verification/h4 --host 127.0.0.1 --port 8765

The browser still exercises the production FastAPI/WebSocket/RunLoop path.
Only the model runner and the out-of-band release controls are deterministic.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from harness.daemon import create_app
from harness.envelope import Envelope, EnvelopeFactory, MessageType, StopReason
from harness.model_policy import ThreadModelResolution
from harness.run_loop import RunLoop
from harness.run_protocol import RunEmitter, TurnOutcome, UsageSnapshot

TRACE_PATH = Path(__file__).with_name("trace.jsonl")


class ScenarioControl:
    """Hold deterministic turn boundaries until the verifier releases them."""

    def __init__(self) -> None:
        self.primary = asyncio.Event()
        self.secondary = asyncio.Event()

    def reset(self) -> None:
        self.primary = asyncio.Event()
        self.secondary = asyncio.Event()
        TRACE_PATH.write_text("", encoding="utf-8")

    def release(self, name: str) -> None:
        if name == "primary":
            self.primary.set()
        elif name == "secondary":
            self.secondary.set()
        else:
            raise ValueError(f"unknown scenario gate {name!r}")

    def trace(self, kind: str, **values: object) -> None:
        record = {
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            **values,
        }
        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


class TracingEnvelopeFactory:
    """Delegate envelope construction and retain an exact daemon-side trace."""

    def __init__(self, delegate: EnvelopeFactory, control: ScenarioControl) -> None:
        self._delegate = delegate
        self._control = control

    def new_id(self) -> str:
        return self._delegate.new_id()

    def create(
        self,
        message_type: MessageType | str,
        payload: Any,
        *,
        thread_id: str | None = None,
    ) -> Envelope:
        envelope = self._delegate.create(message_type, payload, thread_id=thread_id)
        self._control.trace(
            "daemon.envelope",
            type=str(envelope.type),
            thread_id=envelope.thread_id,
            payload=envelope.model_dump(mode="json")["payload"],
        )
        return envelope


class ScenarioRunner:
    """Stream stable H4 states without credentials or hosted model calls."""

    def __init__(self, control: ScenarioControl) -> None:
        self._control = control

    async def run(
        self,
        *,
        thread_id: str,
        prompt: str,
        message_history: Sequence[object],
        emit: RunEmitter,
        model_resolution: ThreadModelResolution | None = None,
    ) -> TurnOutcome:
        del model_resolution
        self._control.trace("runner.start", thread_id=thread_id, prompt=prompt)
        try:
            if prompt == "Map the release boundary and hold the queue open.":
                return await self._primary_turn(prompt, message_history, emit)
            if prompt == "Turn that boundary into three calm checks.":
                return await self._secondary_turn(prompt, message_history, emit)
            if prompt == "Keep partial work visible while I stop this run.":
                return await self._cancel_turn(prompt, message_history, emit)
            if prompt == "Show the budget boundary without losing the draft.":
                await emit.usage(UsageSnapshot(2, 180, 34))
                await emit.text("The draft remains visible up to the budget wall.")
                return self._outcome(
                    StopReason.BUDGET_EXCEEDED,
                    prompt,
                    message_history,
                    UsageSnapshot(2, 180, 34),
                )
            if prompt == "Show a recoverable run error with partial work.":
                await emit.usage(UsageSnapshot(1, 48, 9))
                await emit.text("This partial result survives the provider error.")
                return self._outcome(
                    StopReason.ERROR,
                    prompt,
                    message_history,
                    UsageSnapshot(1, 48, 9),
                )

            await emit.usage(UsageSnapshot(1, 32, 14))
            await emit.text("A quiet thread is ready for the next turn.")
            return self._outcome(
                StopReason.END_TURN,
                prompt,
                message_history,
                UsageSnapshot(1, 32, 14),
            )
        except asyncio.CancelledError:
            self._control.trace("runner.cancelled", thread_id=thread_id, prompt=prompt)
            return self._outcome(
                StopReason.CANCELLED,
                prompt,
                message_history,
                UsageSnapshot(1, 64, 12),
            )

    async def _primary_turn(
        self,
        prompt: str,
        history: Sequence[object],
        emit: RunEmitter,
    ) -> TurnOutcome:
        usage = UsageSnapshot(1, 96, 18)
        await emit.thinking("Sequencing the release boundary.")
        await emit.usage(usage)
        await emit.text("I’m mapping the release boundary. ")
        self._control.trace("runner.wait", gate="primary")
        await self._control.primary.wait()
        usage = UsageSnapshot(1, 96, 31)
        await emit.usage(usage)
        await emit.text("The current turn will finish before queued work begins.")
        return self._outcome(StopReason.END_TURN, prompt, history, usage)

    async def _secondary_turn(
        self,
        prompt: str,
        history: Sequence[object],
        emit: RunEmitter,
    ) -> TurnOutcome:
        usage = UsageSnapshot(1, 54, 10)
        await emit.usage(usage)
        await emit.text("Check one: preserve order. ")
        self._control.trace("runner.wait", gate="secondary")
        await self._control.secondary.wait()
        usage = UsageSnapshot(1, 54, 24)
        await emit.usage(usage)
        await emit.text("Check two: hydrate once. Check three: keep attention quiet.")
        return self._outcome(StopReason.END_TURN, prompt, history, usage)

    async def _cancel_turn(
        self,
        prompt: str,
        history: Sequence[object],
        emit: RunEmitter,
    ) -> TurnOutcome:
        usage = UsageSnapshot(1, 64, 12)
        await emit.usage(usage)
        await emit.text("This partial work should remain after Stop.")
        await asyncio.Event().wait()
        return self._outcome(StopReason.END_TURN, prompt, history, usage)

    def _outcome(
        self,
        reason: StopReason,
        prompt: str,
        history: Sequence[object],
        usage: UsageSnapshot,
    ) -> TurnOutcome:
        self._control.trace("runner.done", prompt=prompt, stop_reason=reason.value)
        return TurnOutcome(reason, (*history, f"{prompt}:{reason.value}"), usage)


def create_scenario_app() -> FastAPI:
    """Compose deterministic controls around the production H4 transport."""

    control = ScenarioControl()
    control.reset()
    base_factory = EnvelopeFactory(machine_id="h4-verification", agent_id="fixture-agent")
    factory = TracingEnvelopeFactory(base_factory, control)
    loop = RunLoop(ScenarioRunner(control), factory)  # type: ignore[arg-type]
    harness_app = create_app(run_loop=loop, envelope_factory=factory)  # type: ignore[arg-type]
    app = FastAPI(title="Harness H4 verification")

    @app.get("/__scenario__/health")
    async def scenario_health() -> Mapping[str, bool]:
        return {"ok": True}

    @app.post("/__scenario__/reset")
    async def scenario_reset() -> Mapping[str, bool]:
        control.reset()
        return {"ok": True}

    @app.post("/__scenario__/release/{name}")
    async def scenario_release(name: str) -> Mapping[str, bool]:
        control.release(name)
        return {"ok": True}

    app.mount("/", harness_app)
    return app
