"""ADR-024 / M3SR: real asynchronous request boundaries and receipt acknowledgement."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from harness.spend import SpendLineage, model_response_receipts
from harness.spend_walls import SpendLimits, SpendWallModel, SpendWalls
from harness.spine_client import DailySpend, SpendEventsResponse, SpendTableSnapshot


class Gateway:
    def __init__(self):
        self.total = Decimal(0)

    async def record_spend_events(self, request):
        self.total += sum(Decimal(event.cost_usd or "0") for event in request.events)
        return SpendEventsResponse(accepted=len(request.events))

    async def read(self):
        now = datetime.now(UTC)
        return SpendTableSnapshot(
            as_of=now,
            window_minutes=60,
            threads=[],
            purposes=[],
            days=[
                DailySpend(
                    day=now.replace(hour=0, minute=0, second=0, microsecond=0),
                    model_usd=str(self.total),
                    infrastructure_usd=None,
                    total_usd=str(self.total),
                    unpriced_lines=0,
                )
            ],
        )


class Emitter:
    def __init__(self):
        self.events = []
        self.paused = asyncio.Event()

    async def event(self, value):
        self.events.append(value)
        if value["decision"] == "owner_action":
            self.paused.set()


@pytest.mark.asyncio
async def test_run_wall_stops_next_model_request_and_resumes_after_explicit_raise(tmp_path):
    """ADR-024: a reached wall must stop purchases, retain the run, and honor new authority."""
    gateway, emitter = Gateway(), Emitter()
    walls = SpendWalls(tmp_path / "walls.json", gateway, gateway.read)
    await walls.configure(SpendLimits(run_usd=Decimal("0.01")))
    calls = []

    def respond(messages, info):
        calls.append(True)
        return ModelResponse(
            parts=[TextPart("done")],
            usage=RequestUsage(input_tokens=1, output_tokens=1),
            provider_response_id=f"request-{len(calls)}",
            provider_details={"cost": "0.02"},
        )

    model = SpendWallModel(FunctionModel(respond))

    async def run():
        with walls.bind("01K1M2A0000000000000000003", emitter):
            await model.request([], None, ModelRequestParameters())
            await model.request([], None, ModelRequestParameters())

    task = asyncio.create_task(run())
    await asyncio.wait_for(emitter.paused.wait(), 1)
    assert len(calls) == 1
    assert not task.done()
    assert "Run spend $0.02" in emitter.events[-1]["reason"]
    await walls.configure(SpendLimits(run_usd=Decimal("0.05")))
    await asyncio.wait_for(task, 1)
    assert len(calls) == 2
    assert emitter.events[-1]["decision"] == "resumed"
    assert SpendWalls(walls.path, gateway, gateway.read).limits.run_usd == Decimal("0.05")


@pytest.mark.asyncio
async def test_daily_wall_counts_pending_once_and_cancellation_releases_wait(tmp_path):
    """ADR-024: ledger acknowledgement must not double charge in-flight purchases."""
    from uuid import UUID

    gateway, emitter = Gateway(), Emitter()
    walls = SpendWalls(tmp_path / "walls.json", gateway, gateway.read)
    await walls.configure(SpendLimits(day_usd=Decimal("0.03")))
    response = ModelResponse(
        parts=[TextPart("done")],
        usage=RequestUsage(input_tokens=1, output_tokens=1),
        provider_response_id="request-one",
        provider_details={"cost": "0.02"},
    )
    model = SpendWallModel(FunctionModel(lambda messages, info: response))
    run_id = "01K1M2A0000000000000000003"
    with walls.bind(run_id, emitter):
        await model.request([], None, ModelRequestParameters())
        await walls.check_current()  # $0.02 pending is below $0.03.
        receipts = model_response_receipts(
            [response],
            lineage=SpendLineage(
                principal_id="test",
                machine_id="test",
                origin_agent="test",
                thread_id=UUID("11111111-1111-4111-8111-111111111111"),
                run_id=run_id,
                prompt_id="01K1M2A0000000000000000004",
            ),
            purpose="building",
        )
        await walls.record_spend_events(receipts)
        await asyncio.wait_for(walls.check_current(), 1)  # Still $0.02, not $0.04.
        await walls.configure(SpendLimits(day_usd=Decimal("0.01")))
        paused = asyncio.create_task(walls.check_current())
        await asyncio.wait_for(emitter.paused.wait(), 1)
        paused.cancel()
        with pytest.raises(asyncio.CancelledError):
            await paused
        await asyncio.wait_for(walls.configure(SpendLimits()), 1)


@pytest.mark.asyncio
async def test_completed_response_pauses_with_a_snapshot_card_before_terminal(tmp_path):
    """ADR-024 / C.7: a final receipt crossing preserves text while the run awaits authority."""
    from harness.envelope import EnvelopeFactory, MessageType, StopReason
    from harness.run_loop import RunLoop
    from harness.run_protocol import TurnOutcome

    gateway = Gateway()
    walls = SpendWalls(tmp_path / "walls.json", gateway, gateway.read)
    await walls.configure(SpendLimits(run_usd=Decimal("0.01")))
    model = SpendWallModel(
        FunctionModel(
            lambda messages, info: ModelResponse(
                parts=[TextPart("answer")],
                usage=RequestUsage(input_tokens=1, output_tokens=1),
                provider_response_id="final",
                provider_details={"cost": "0.02"},
            )
        )
    )

    class Runner:
        async def run(self, *, emit, message_history, **kwargs):
            response = await model.request([], None, ModelRequestParameters())
            await emit.text("answer")
            return TurnOutcome(StopReason.END_TURN, (*message_history, response))

    envelopes = []
    paused, done = asyncio.Event(), asyncio.Event()

    async def sink(envelope):
        envelopes.append(envelope)
        if envelope.type == MessageType.THREAD_SNAPSHOT:
            active = envelope.payload.active_run
            if active and active.state == "waiting_gate":
                paused.set()
        if envelope.type == MessageType.RUN_DONE:
            done.set()

    loop = RunLoop(Runner(), EnvelopeFactory(machine_id="test"), spend_walls=walls)
    await loop.attach(sink)
    try:
        await loop.submit(
            thread_id="11111111-1111-4111-8111-111111111111",
            prompt_id="01K1M2A0000000000000000004",
            prompt="hello",
            sink=sink,
        )
        await asyncio.wait_for(paused.wait(), 1)
        assert not done.is_set()
        await walls.configure(SpendLimits(run_usd=Decimal("0.03")))
        await asyncio.wait_for(done.wait(), 1)
    finally:
        await loop.close()
