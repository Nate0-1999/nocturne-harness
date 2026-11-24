"""A-038 proofs for durable, replay-safe, fail-open receipt spooling."""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from pydantic_ai.messages import ModelResponse

from harness.envelope import StopReason
from harness.memory_gate import MemoryGateTurnRunner
from harness.model_policy import ThreadModelResolution
from harness.receipt_queue import SpendReceiptQueue
from harness.run_protocol import TurnOutcome
from harness.spend import covered_turn_receipt
from harness.spine_client import SpendEvent, SpendEventsRequest, SpendEventsResponse

NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def request() -> SpendEventsRequest:
    return SpendEventsRequest(
        events=[
            SpendEvent(
                event_uid="01K1ABCDEF0123456789ABCDEF",
                ts=NOW,
                product_type="llm.request",
                quantity_type="output",
                unit_of_measure="tokens",
                quantity=Decimal(7),
                cost_usd=Decimal("0.0007"),
                basis="measured",
                behavior="variable",
                purpose="building",
                principal_id="local",
                machine_id="machine",
                origin_agent="nocturne",
                thread_id=UUID("00000000-0000-4000-8000-000000000001"),
                run_id="01K1ABCDEF0123456789ABCDEE",
                prompt_id="01K1ABCDEF0123456789ABCDED",
                memory_id=None,
                model="openrouter:model",
                provider="openrouter",
                quantization=None,
                ref="generation-1",
                meta={"safe": True},
            )
        ]
    )


@dataclass
class RecordingGateway:
    requests: list[SpendEventsRequest] = field(default_factory=list)

    async def record_spend_events(self, value: SpendEventsRequest) -> SpendEventsResponse:
        self.requests.append(value)
        return SpendEventsResponse(accepted=len(value.events))


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [StopReason.CANCELLED, StopReason.ERROR, StopReason.END_TURN])
async def test_unconfirmed_subscription_result_writes_nothing(reason: StopReason) -> None:
    """A-102: a refusal, cancellation or missing native response cannot claim plan coverage."""
    model = "subscription:codex/" + "a" * 64 + "/native"
    history = () if reason is StopReason.END_TURN else (ModelResponse(parts=[], model_name=model),)
    queue = AsyncMock()
    runner = MemoryGateTurnRunner(
        Mock(), Mock(), Mock(), model_context_tokens=100, receipt_queue=queue
    )
    await runner._record_coverage(
        Mock(), ThreadModelResolution(model, 100, "pinned"), TurnOutcome(reason, history), Mock()
    )
    queue.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_receipt_preserves_completed_identity_across_restart(tmp_path: Path) -> None:
    """A-102: a lost acknowledgement must never turn coverage into another charge or an estimate."""
    line = request().events[0]
    receipt = covered_turn_receipt(
        ModelResponse(
            parts=[], model_name="subscription:codex/" + "a" * 64 + "/native", timestamp=NOW
        ),
        line.principal_id,
        line.thread_id,
        line.run_id,
        line.prompt_id,
    )
    queue = SpendReceiptQueue(tmp_path)
    assert await queue.enqueue(receipt)
    assert await queue.enqueue(receipt)
    gateway = RecordingGateway()
    assert await SpendReceiptQueue(tmp_path).flush(gateway)
    assert gateway.requests == [receipt]
    covered = receipt.events[0]
    assert covered.cost_usd is None and covered.basis == "measured"
    assert covered.event_uid == line.run_id and covered.meta == {"account": "a" * 64}


@pytest.mark.asyncio
async def test_failed_batch_is_mode_0600_estimated_and_replays_by_stable_id(
    tmp_path: Path,
) -> None:
    """A-038: the durable spool preserves identity and deletes only after acceptance."""

    queue = SpendReceiptQueue(tmp_path / "receipt-queue", clock=lambda: NOW)
    assert await queue.enqueue(request()) is True
    files = list(queue.root.glob("*.json"))
    assert len(files) == 1
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600

    queued = SpendEventsRequest.model_validate_json(files[0].read_text("utf-8"))
    assert queued.events[0].event_uid == request().events[0].event_uid
    assert queued.events[0].basis == "estimated"
    assert queued.events[0].meta["receipt_queue"] == {
        "original_basis": "measured",
        "queued_at": NOW.isoformat(),
        "reason": "ledger_unavailable",
    }

    reopened = SpendReceiptQueue(queue.root)
    gateway = RecordingGateway()
    assert await reopened.flush(gateway) is True
    assert gateway.requests == [queued]
    assert reopened.snapshot().status == "clear"
    assert list(queue.root.glob("*.json")) == []


@pytest.mark.asyncio
async def test_unwritable_spool_retains_degraded_memory_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC B.6 rule 11 keeps accounting fail-open and visible after disk-spool failure."""

    queue = SpendReceiptQueue(tmp_path / "receipt-queue", clock=lambda: NOW)

    def fail_write(_request: SpendEventsRequest) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(queue, "_write", fail_write)
    assert await queue.enqueue(request()) is False
    snapshot = queue.snapshot()
    assert snapshot.status == "degraded"
    assert snapshot.pending_lines == 1
    assert snapshot.oldest_queued_at == NOW
