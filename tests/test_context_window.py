from datetime import UTC, datetime

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage

from harness.context_window import ContextWindowTracker
from harness.model_policy import ThreadModelResolution


def test_tracker_keeps_measured_total_and_exact_limit_with_estimated_split() -> None:
    """A-039 is defended by verifying that tracker keeps measured total and exact limit with
    estimated split; this prevents drift in the measured context-pressure contract.
    """
    tracker = ContextWindowTracker()
    tracker.record(
        thread_id="thread-a",
        captured=[
            ModelResponse(
                parts=[TextPart("ok")],
                usage=RequestUsage(input_tokens=1_250, output_tokens=12),
                timestamp=datetime(2026, 8, 4, tzinfo=UTC),
            )
        ],
        resolution=ThreadModelResolution(
            model="openrouter:test/model", context_tokens=16_000, policy="pinned:test/model"
        ),
        memory_block="a remembered preference",
    )

    observation = tracker.snapshot("thread-a").aggregate
    assert observation is not None
    assert observation.used_tokens == 1_250
    assert observation.context_tokens == 16_000
    assert observation.threshold_tokens == 12_800
    assert sum(observation.categories.model_dump().values()) == 1_250
    assert observation.breakdown_basis == "estimated"
    assert observation.compaction_active is False


def test_tracker_global_aggregates_only_observed_threads() -> None:
    """A-039 is defended by verifying that tracker global aggregates only observed threads;
    this prevents drift in the measured context-pressure contract.
    """
    tracker = ContextWindowTracker()
    assert tracker.snapshot(None).aggregate is None
    assert tracker.snapshot("not-seen").observations == []

    for thread_id, used in (("b", 20), ("a", 10)):
        tracker.record(
            thread_id=thread_id,
            captured=[ModelResponse(parts=[TextPart("ok")], usage=RequestUsage(input_tokens=used))],
            resolution=ThreadModelResolution(
                model="openrouter:test/model", context_tokens=100, policy="pinned:test/model"
            ),
            memory_block=None,
        )

    snapshot = tracker.snapshot(None)
    assert [item.thread_id for item in snapshot.observations] == ["a", "b"]
    assert snapshot.aggregate is not None
    assert snapshot.aggregate.used_tokens == 30
    assert snapshot.aggregate.context_tokens == 200
