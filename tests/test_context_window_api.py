from datetime import UTC, datetime

from fastapi.testclient import TestClient

from harness.context_window import (
    ContextCategories,
    ContextCut,
    ContextObservation,
    ContextWindowSnapshot,
    OverwhelmTracker,
    ReturnShareBounds,
)
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


def test_public_rack_query_returns_the_shares_and_cuts_in_force() -> None:
    """SPEC D.2 153 / FL-198: the Security module reads the shares, bounds, cuts and
    send-backs live, so the protection is watchable without demanding attention."""
    bounds = ReturnShareBounds(default_percent=10, min_percent=1, max_percent=25)
    tracker = OverwhelmTracker(bounds)
    share = tracker.share_for("thread-a", 1600)
    tracker.record(
        ContextCut(
            thread_id="thread-a",
            agent_id="agent/worker",
            at=datetime(2026, 9, 22, tzinfo=UTC),
            kind="sub_agent",
            source="worker",
            size_tokens=900,
            share=share,
            action="send_back",
            shorten_by=760,
        )
    )
    tracker.record(
        ContextCut(
            thread_id="thread-b",
            agent_id="agent",
            at=datetime(2026, 9, 22, tzinfo=UTC),
            kind="query",
            source="read_file",
            size_tokens=300,
            share=share,
            action="cut",
        )
    )
    client = TestClient(create_app(overwhelm_reader=tracker.snapshot))

    current = client.get("/v1/rack/query?resource=overwhelm&as_of=now&thread_id=thread-a").json()
    assert current["status"] == "live"
    assert current["data"]["bounds"] == {"default_percent": 10, "min_percent": 1, "max_percent": 25}
    assert current["data"]["shares"] == {
        "thread-a": {"percent": 10, "limit_tokens": 1600, "tokens": 160}
    }
    assert [cut["action"] for cut in current["data"]["cuts"]] == ["send_back"]
    assert current["data"]["cuts"][0]["shorten_by"] == 760

    everything = client.get("/v1/rack/query?resource=overwhelm&as_of=now").json()
    assert [cut["source"] for cut in everything["data"]["cuts"]] == ["worker", "read_file"]
    assert client.get("/v1/rack/query?resource=overwhelm&as_of=2026-08-01T00:00:00Z").json() == {
        "status": "historical_unavailable",
        "as_of": "2026-08-01T00:00:00Z",
        "data": None,
    }
