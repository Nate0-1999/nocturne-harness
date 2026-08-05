"""A-038 proofs for durable, replay-safe, fail-open receipt spooling."""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from harness.receipt_queue import SpendReceiptQueue
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
