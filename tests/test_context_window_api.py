from datetime import UTC, datetime

from fastapi.testclient import TestClient

from harness.context_window import ContextCategories, ContextObservation, ContextWindowSnapshot
from harness.daemon import create_app


def test_public_rack_query_returns_current_context_observation() -> None:
    """A-039 is defended by verifying that public rack query returns current context
    observation; this prevents drift in the truthful Context Bars observation contract.
    """
    observation = ContextObservation(
        thread_id="thread-a",
        model="openrouter:test/model",
        observed_at=datetime(2026, 8, 4, tzinfo=UTC),
        used_tokens=80,
        context_tokens=100,
        threshold_tokens=80,
        categories=ContextCategories(system=10, history=50, memory=15, tools=5),
    )

    def read_context(thread_id: str | None) -> ContextWindowSnapshot:
        return ContextWindowSnapshot(
            scope="CURRENT",
            selected_thread_id=thread_id,
            observations=[observation],
            aggregate=observation,
        )

    response = TestClient(create_app(context_window_reader=read_context)).get(
        "/v1/rack/query?resource=context_window&as_of=now&thread_id=thread-a"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live"
    assert body["data"]["aggregate"]["used_tokens"] == 80
    assert body["data"]["aggregate"]["categories"]["memory"] == 15


def test_context_history_is_not_fabricated() -> None:
    """A-039 is defended by verifying that context history is not fabricated; this prevents
    drift in the truthful Context Bars observation contract.
    """
    response = TestClient(create_app(context_window_reader=lambda _: None)).get(
        "/v1/rack/query?resource=context_window&as_of=2026-08-01T00:00:00Z"
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "historical_unavailable",
        "as_of": "2026-08-01T00:00:00Z",
        "data": None,
    }
