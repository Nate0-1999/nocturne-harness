import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID

import httpx
import pytest
from vitals_fixture import vitals_payload

from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    CreateMemoryRequest,
    DuplicateMemoryConflict,
    FeedbackRequest,
    InjectCommitRequest,
    InjectionEventAnnotationInput,
    InjectionEventAnnotationsRequest,
    InjectPrepareRequest,
    LabelConflict,
    ListMemoriesParams,
    MemoryGraphQuery,
    MemoryKind,
    MemorySplitChild,
    MemorySplitRequest,
    MemorySplitResponse,
    MemoryStatus,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
    ScorerConsoleQuery,
    ScorerSimulationRequest,
    SearchRequest,
    SimilarMemoriesResponse,
    SpendEvent,
    SpendEventsRequest,
    SpineClient,
    SpineProblemError,
    SpineResponseError,
    SpineTransportError,
)

JSON = "application/json"
PROBLEM_JSON = "application/problem+json"
MEMORY_ID = "12345678-1234-5678-1234-567812345678"
THREAD_ID = "22345678-1234-5678-1234-567812345678"
INJECTION_ID = "32345678-1234-5678-1234-567812345678"
type VitalsMutation = Callable[[dict[str, Any]], object]


def memory_unit_payload() -> dict[str, Any]:
    return {
        "memory_id": MEMORY_ID,
        "principal_id": "principal-1",
        "label": "Editor preference",
        "body": "The user prefers tabs.",
        "kind": "preference",
        "keywords": ["editor", "tabs"],
        "project_key": None,
        "thread_origin": None,
        "origin_thread_id": None,
        "origin_path": "src/editor.py",
        "pin": False,
        "status": "active",
        "revision": 1,
        "stats": {
            "injections": 0,
            "removals": 0,
            "citations": 0,
            "never_kills": 0,
            "last_injected_at": None,
        },
        "bias": 0.0,
        "embedding_model": "contract-deterministic-v1",
        "created_at": "2026-07-20T12:00:00Z",
        "updated_at": "2026-07-20T12:00:00Z",
    }


def similarity_card_payload() -> dict[str, Any]:
    return {
        "memory_id": MEMORY_ID,
        "label": "Editor preference",
        "body": "The user prefers tabs.",
        "kind": "preference",
        "pin": False,
        "score": 0.85,
        "features": None,
        "rank": None,
    }


def problem_payload(status: int = 503) -> dict[str, Any]:
    return {
        "type": "about:blank",
        "title": "Service Unavailable",
        "status": status,
        "detail": "The embedding provider could not complete the request.",
        "instance": "/v1/search",
        "endpoint": "POST /v1/search",
        "trace_id": "trace-1",
    }


def response(status: int, payload: object, media_type: str = JSON) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers={"content-type": f"{media_type}; charset=utf-8"},
    )


def raw_json_response(status: int, payload: object, media_type: str = JSON) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": f"{media_type}; charset=utf-8"},
    )


async def _assert_vitals_payload_rejected(payload: dict[str, Any]) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return response(200, payload)

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineResponseError, match="outside C.4"):
            await client.vitals_snapshot()


def spend_table_payload() -> dict[str, Any]:
    metrics = {
        "input_tokens": "1200.5",
        "kv_cache_tokens": "400",
        "reasoning_tokens": "72",
        "output_tokens": "180",
        "total_usd": "0.042500000000",
        "total_receipt_lines": 4,
        "total_unpriced_lines": 0,
        "spend_per_hour_usd": "0.012500000000",
        "hourly_receipt_lines": 2,
        "hourly_unpriced_lines": 0,
    }
    return {
        "as_of": "2026-08-31T17:00:00Z",
        "window_minutes": 60,
        "threads": [
            {
                "thread_id": THREAD_ID,
                "models": [{"model": "openai/gpt-5.4", **metrics}],
                **metrics,
            }
        ],
        "purposes": [{"purpose": "embedding", "label": "Embeddings", **metrics}],
    }


def curator_activity_payload() -> dict[str, Any]:
    return {
        "principal_id": "principal-1",
        "admitted_writes": 9,
        "last_run_writes": 4,
        "pressure_events": 2,
        "last_run_pressure": 1,
        "trigger_every": 25,
        "pressure_trigger_every": 3,
        "writes_until_run": 20,
        "pressure_until_run": 2,
        "latest_run": None,
        "pending_cards": 1,
    }


@pytest.mark.asyncio
async def test_spend_table_uses_repeated_thread_filters_and_tolerates_older_palace() -> None:
    """M3SP adds one optional authenticated read without broadening the browser boundary."""
    seen: list[httpx.Request] = []
    responses = [response(200, spend_table_payload()), response(404, {})]

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0)

    second = "32345678-1234-5678-1234-567812345678"
    async with SpineClient(
        "https://spine.invalid/prefix",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        snapshot = await client.spend_table([UUID(THREAD_ID), UUID(second)])
        missing = await client.spend_table()

    assert snapshot is not None
    assert snapshot.threads[0].models[0].reasoning_tokens == "72"
    assert seen[0].url.path == "/prefix/v1/spend/table"
    assert seen[0].url.params["scope"] == "threads"
    assert seen[0].url.params.get_list("thread_id") == [THREAD_ID, second]
    assert missing is None


@pytest.mark.asyncio
async def test_curator_activity_contains_only_an_older_palace_404() -> None:
    """PLAN M3QA/F062/P2: absent curator capability degrades in Palace State only."""
    seen: list[httpx.Request] = []
    responses = [
        response(200, curator_activity_payload()),
        response(404, {}),
        response(503, problem_payload(), PROBLEM_JSON),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0)

    async with SpineClient(
        "https://spine.invalid/prefix",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        activity = await client.curator_activity("principal-1")
        missing = await client.curator_activity("principal-1")
        with pytest.raises(SpineProblemError) as failure:
            await client.curator_activity("principal-1")

    assert activity is not None
    assert activity.pending_cards == 1
    assert missing is None
    assert failure.value.status_code == 503
    assert [request.url.path for request in seen] == [
        "/prefix/v1/curation",
        "/prefix/v1/curation",
        "/prefix/v1/curation",
    ]
    assert all(request.url.params.get("principal_id") == "principal-1" for request in seen)


@pytest.mark.asyncio
async def test_global_instrument_requests_preserve_required_null_scope_fields() -> None:
    """F020/A-035/A-047 require explicit null scope fields for lawful GLOBAL
    reads and simulations.
    """
    seen: dict[str, object] = {}
    values = {
        "tau": 0.55,
        "top_k": 8,
        "memory_context_share": 0.10,
        "half_life_time_days": 30.0,
        "half_life_hist_days": 120.0,
        "weights": {
            "sem": 0.4,
            "kw": 0.2,
            "time": 0.1,
            "proj": 0.1,
            "freq": 0.1,
            "hist": 0.1,
        },
    }
    payloads = {
        "/v1/memory-graph/query": {
            "as_of": "2026-08-08T12:00:00Z",
            "graph_edge_sim": 0.75,
            "nodes": [],
            "edges": [],
            "omitted_memory_ids": [],
        },
        "/v1/scorer-console/query": {
            "as_of": "2026-08-08T12:00:00Z",
            "scope": "GLOBAL",
            "thread_id": None,
            "descriptors": [],
            "active_version": "v0",
            "configurations": [],
            "activations": [],
            "proposed_versions": [],
            "accuracy": [],
            "learning": {
                "eligible_dispositions": 0,
                "hygiene_excluded_dispositions": 0,
                "minimum_dispositions": 25,
                "remaining_to_floor": 25,
                "floor_met": False,
                "share_tuning_minimum": 100,
                "share_tuning_remaining": 100,
                "share_tuning_active": False,
                "retrain_signal_stride": 25,
                "evaluated_through": None,
                "signals_since_last_run": 0,
                "signals_until_next_run": 25,
                "active_scorer_version": "v0",
                "right": 0,
                "wrong": 0,
                "weighted_right": "0",
                "weighted_wrong": "0",
                "weighted_agreement_percent": None,
                "live_agreement": [],
                "retrain_runs": [],
                "annotations": [],
            },
            "candidates": [],
        },
        "/v1/scorer-simulations": {
            "simulation_digest": "a" * 64,
            "base_version": "v0",
            "values": values,
            "source_boundary": None,
            "holdout_dispositions": 0,
            "accuracy_percent": None,
            "incumbent_accuracy_percent": None,
            "delta_percent": None,
            "instant": {"status": "not_requested", "injection_id": None, "candidates": []},
            "slice": {"parameter_id": "scorer.tau", "points": []},
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = json.loads(request.content)
        return response(200, payloads[request.url.path])

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        await client.memory_graph(MemoryGraphQuery(principal_id="owner", memory_ids=None))
        console = await client.scorer_console(
            ScorerConsoleQuery(principal_id="owner", thread_id=None)
        )
        await client.simulate_scorer(
            ScorerSimulationRequest(
                principal_id="owner",
                injection_id=None,
                base_version="v0",
                values=values,
                slice_parameter_id="scorer.tau",
            )
        )

    assert seen["/v1/memory-graph/query"] == {
        "principal_id": "owner",
        "memory_ids": None,
    }
    assert seen["/v1/scorer-console/query"] == {
        "principal_id": "owner",
        "thread_id": None,
        "as_of": "now",
    }
    assert seen["/v1/scorer-simulations"] == {
        "principal_id": "owner",
        "injection_id": None,
        "base_version": "v0",
        "values": values,
        "slice_parameter_id": "scorer.tau",
    }
    assert console.learning["minimum_dispositions"] == 25


@pytest.mark.asyncio
async def test_retrain_uses_the_existing_bodyless_spine_trigger() -> None:
    """A-051/P1.2.3 is defended by keeping FORCE RETRAIN a transparent,
    bodyless transport to Spine's authoritative learner receipt.
    """
    seen: list[httpx.Request] = []
    payload = {
        "status": "insufficient_data",
        "incumbent_version": "v0",
        "proposal_version": None,
        "eligible_dispositions": 7,
        "training_dispositions": 0,
        "holdout_dispositions": 0,
        "training_pairs": 0,
        "incumbent": None,
        "challenger": None,
        "reason": "minimum disposition floor not reached: 7/25",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response(200, payload)

    async with SpineClient(
        "https://spine.invalid/prefix",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        receipt = await client.retrain()

    assert receipt.model_dump(mode="json") == payload
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/prefix/retrain"
    assert seen[0].content == b""
    assert "content-type" not in seen[0].headers


def _measure_reinforced(payload: dict[str, Any]) -> None:
    payload["lifecycle_rates"][1].update(
        status="measured",
        per_hour=0,
        source="invented.reinforcement",
    )


def _measure_queue_depth(payload: dict[str, Any]) -> None:
    payload["palace_counts"][-1].update(
        status="placeholder",
        count=None,
        source=None,
    )


def _move_points_to_open_window_boundary(payload: dict[str, Any]) -> None:
    boundary = "2026-08-02T11:05:30Z"
    payload["spend"]["latest_minute"] = boundary
    for lane in payload["spend"]["lanes"]:
        lane["points"][0]["minute"] = boundary


@pytest.mark.asyncio
async def test_all_routes_send_exact_http_contract() -> None:
    """SPEC C.4 is defended by verifying that all routes send exact http contract; this
    prevents drift in the authenticated Spine transport contract.
    """
    seen: list[httpx.Request] = []
    responses = {
        ("POST", "/prefix/v1/inject/prepare"): response(
            200,
            {
                "injection_id": INJECTION_ID,
                "snapshot_ts": "2026-07-20T12:00:00Z",
                "scorer_version": "v0",
                "injected": [],
                "near_misses": [],
                "final_block": None,
                "memory_allocation": {
                    "memory_context_share": 0.10,
                    "share_tokens": 100,
                    "regular_tokens": 0,
                    "pinned_tokens": 0,
                    "total_tokens": 0,
                    "pinned_overflow_tokens": 0,
                },
            },
        ),
        ("POST", "/prefix/v1/inject/commit"): response(
            200, {"final_block": "<memory_system></memory_system>", "wrong_removed": []}
        ),
        ("POST", "/prefix/v1/feedback"): response(200, {"ok": True}),
        ("POST", "/prefix/v1/injection-event-annotations"): response(
            200,
            {"accepted": 1},
        ),
        ("POST", "/prefix/v1/memories"): response(201, {"created": memory_unit_payload()}),
        ("POST", "/prefix/v1/memory-splits"): response(
            201,
            {
                "source": {
                    **memory_unit_payload(),
                    "label": "Split source",
                    "body": "Fact one. Fact two.",
                    "status": "tombstoned",
                },
                "created": [memory_unit_payload(), memory_unit_payload()],
            },
        ),
        ("PATCH", f"/prefix/v1/memories/{MEMORY_ID}"): response(200, memory_unit_payload()),
        ("GET", "/prefix/v1/memories"): response(
            200,
            {"items": [memory_unit_payload()], "total": 1, "limit": 25, "offset": 5},
        ),
        ("POST", "/prefix/v1/search"): response(200, {"results": []}),
        ("POST", "/prefix/v1/spend/events"): response(200, {"accepted": 1}),
        ("GET", "/prefix/v1/vitals"): response(200, vitals_payload()),
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer contract-token"
        assert request.headers["accept"] == f"{JSON}, {PROBLEM_JSON}"
        assert request.extensions["timeout"] == {
            "connect": 30.0,
            "read": 30.0,
            "write": 30.0,
            "pool": 30.0,
        }
        return responses[(request.method, request.url.path)]

    async with SpineClient(
        "https://spine.invalid/prefix",
        "contract-token",
        transport=httpx.MockTransport(handler),
    ) as client:
        prepared = await client.prepare_injection(
            InjectPrepareRequest(
                thread_id=THREAD_ID,
                agent_id="agent-1",
                machine_id="machine-1",
                principal_id="principal-1",
                prompt="hello",
                model_context_tokens=200_000,
            )
        )
        committed = await client.commit_injection(
            InjectCommitRequest(injection_id=INJECTION_ID, removed=[], added_back=[])
        )
        feedback = await client.submit_feedback(
            FeedbackRequest(
                injection_id=INJECTION_ID,
                memory_id=MEMORY_ID,
                signal="cited",
            )
        )
        annotations = await client.annotate_injection_events(
            InjectionEventAnnotationsRequest(
                annotations=[
                    InjectionEventAnnotationInput(
                        target_event_uid="01KY2JE3JKY1MXYCKVZ93KY399",
                        expected_principal_id="d1-principal",
                        expected_machine_id="d1-relay",
                        reason="Legacy D1 deploy verification artifact.",
                        annotator_principal_id="m2za-sop-verification",
                        annotator_machine_id="m2za-sop-verification",
                        annotator_origin_agent="verification:m2za",
                    )
                ]
            )
        )
        created = await client.create_memory(
            CreateMemoryRequest(
                principal_id="principal-1",
                label="Editor preference",
                body="The user prefers tabs.",
                kind=MemoryKind.PREFERENCE,
                origin_path="src/editor.py",
                editor="user",
                machine_id="machine-1",
            )
        )
        split = await client.create_memory_split(
            MemorySplitRequest(
                principal_id="principal-1",
                source_body="Fact one. Fact two.",
                children=[
                    MemorySplitChild(
                        label="First",
                        body="Fact one.",
                        keywords=["fact", "one"],
                    ),
                    MemorySplitChild(
                        label="Second",
                        body="Fact two.",
                        keywords=["fact", "two"],
                    ),
                ],
                thread_origin=THREAD_ID,
                origin_path="src/editor.py",
                editor="user",
                machine_id="machine-1",
            )
        )
        patched = await client.patch_memory(
            MEMORY_ID,
            PatchMemoryRequest(
                expected_revision=1,
                origin_path="src/editor.py",
                editor="user",
                reason="locate source",
                machine_id="machine-1",
            ),
        )
        listed = await client.list_memories(
            ListMemoriesParams(status=MemoryStatus.ACTIVE, limit=25, offset=5)
        )
        searched = await client.search(SearchRequest(principal_id="principal-1", query="tabs", k=5))
        spend = await client.record_spend_events(
            SpendEventsRequest(
                events=[
                    SpendEvent(
                        event_uid="01K1M2A0000000000000000001",
                        ts="2026-08-01T12:00:00Z",
                        product_type="llm.request",
                        quantity_type="output",
                        unit_of_measure="tokens",
                        quantity=10,
                        cost_usd="0.0001",
                        basis="measured",
                        behavior="variable",
                        purpose="building",
                        principal_id="principal-1",
                        machine_id="machine-1",
                        origin_agent="agent-1",
                        thread_id=THREAD_ID,
                        run_id="01K1M2A0000000000000000002",
                        prompt_id="01K1M2A0000000000000000003",
                        model="vendor/model",
                        provider="vendor",
                        ref="generation-1",
                    )
                ]
            )
        )
        vitals = await client.vitals_snapshot()

    assert prepared.scorer_version == "v0"
    assert committed.wrong_removed == []
    assert feedback.ok is True
    assert annotations.accepted == 1
    assert isinstance(created, CreatedMemoryResponse)
    assert isinstance(split, MemorySplitResponse)
    assert split.source.status is MemoryStatus.TOMBSTONED
    assert len(split.created) == 2
    assert created.created.origin_path == "src/editor.py"
    assert patched.origin_path == "src/editor.py"
    assert listed.total == 1
    assert searched.results == []
    assert spend.accepted == 1
    assert vitals.window_minutes == 60
    assert vitals.spend.source_view == "v_spend_rate"
    assert vitals.spend.lanes[0].points[0].cost_usd == "0.001200000000"
    assert vitals.lifecycle_rates[1].per_hour is None

    requests = {(item.method, item.url.path): item for item in seen}
    create_body = json.loads(requests[("POST", "/prefix/v1/memories")].content)
    assert create_body["origin_path"] == "src/editor.py"
    assert create_body["force"] is False
    assert "project_key" not in create_body
    annotation_body = json.loads(
        requests[("POST", "/prefix/v1/injection-event-annotations")].content
    )
    assert annotation_body == {
        "annotations": [
            {
                "target_event_uid": "01KY2JE3JKY1MXYCKVZ93KY399",
                "expected_principal_id": "d1-principal",
                "expected_machine_id": "d1-relay",
                "reason": "Legacy D1 deploy verification artifact.",
                "annotator_principal_id": "m2za-sop-verification",
                "annotator_machine_id": "m2za-sop-verification",
                "annotator_origin_agent": "verification:m2za",
            }
        ]
    }
    split_body = json.loads(requests[("POST", "/prefix/v1/memory-splits")].content)
    assert split_body == {
        "principal_id": "principal-1",
        "source_body": "Fact one. Fact two.",
        "children": [
            {"label": "First", "body": "Fact one.", "keywords": ["fact", "one"]},
            {"label": "Second", "body": "Fact two.", "keywords": ["fact", "two"]},
        ],
        "thread_origin": THREAD_ID,
        "origin_path": "src/editor.py",
        "editor": "user",
        "machine_id": "machine-1",
    }
    patch_body = json.loads(requests[("PATCH", f"/prefix/v1/memories/{MEMORY_ID}")].content)
    assert patch_body["origin_path"] == "src/editor.py"
    assert "body" not in patch_body
    list_query = requests[("GET", "/prefix/v1/memories")].url.params
    assert dict(list_query) == {"status": "active", "limit": "25", "offset": "5"}
    spend_body = json.loads(requests[("POST", "/prefix/v1/spend/events")].content)
    assert spend_body["events"][0]["cost_usd"] == "0.0001"
    assert requests[("GET", "/prefix/v1/vitals")].url.query == b""


@pytest.mark.asyncio
async def test_vitals_rejects_a_numeric_cost_that_would_lose_decimal_wire_truth() -> None:
    """SPEC C.4 is defended by verifying that vitals rejects a numeric cost that would lose
    decimal wire truth; this prevents drift in the authenticated Spine transport contract.
    """
    payload = vitals_payload()
    payload["spend"]["lanes"][0]["points"][0]["cost_usd"] = 0.0012

    await _assert_vitals_payload_rejected(payload)


@pytest.mark.asyncio
async def test_vitals_accepts_the_a029_reserved_model_key_escape() -> None:
    """SPEC C.4 is defended by verifying that vitals accepts the a029 reserved model key
    escape; this prevents drift in the authenticated Spine transport contract.
    """
    payload = vitals_payload()
    model_lane = payload["spend"]["lanes"][-1]
    model_lane.update(key="~unreported", label="unreported")

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(200, payload)

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        snapshot = await client.vitals_snapshot()

    assert snapshot.spend.lanes[-1].key == "~unreported"
    assert snapshot.spend.lanes[-1].label == "unreported"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload["lifecycle_rates"][1].pop("per_hour"),
            id="missing-null-lifecycle-value",
        ),
        pytest.param(
            lambda payload: payload["palace_counts"][-1].pop("count"),
            id="missing-null-palace-value",
        ),
        pytest.param(
            lambda payload: payload["lifecycle_rates"].pop(),
            id="missing-lifecycle-gauge",
        ),
        pytest.param(
            lambda payload: payload["palace_counts"].append(deepcopy(payload["palace_counts"][-1])),
            id="duplicate-palace-gauge",
        ),
        pytest.param(
            lambda payload: payload["lifecycle_rates"].reverse(),
            id="lifecycle-order",
        ),
        pytest.param(_measure_reinforced, id="reinforced-cannot-be-measured"),
        pytest.param(_measure_queue_depth, id="queue-must-be-measured"),
    ],
)
@pytest.mark.asyncio
async def test_vitals_requires_the_exact_a028_gauge_contract(mutate: VitalsMutation) -> None:
    """SPEC C.4 is defended by verifying that vitals requires the exact a028 gauge contract;
    this prevents drift in the authenticated Spine transport contract.
    """
    payload = vitals_payload()
    mutate(payload)

    await _assert_vitals_payload_rejected(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload["spend"]["lanes"][0]["points"][0].update(
                receipt_lines=1,
                unpriced_lines=2,
            ),
            id="unpriced-exceeds-receipts",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][0]["points"][0].update(cost_usd=None),
            id="priced-lines-require-cost",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][0]["points"][0].update(unpriced_lines=3),
            id="all-unpriced-requires-null-cost",
        ),
    ],
)
@pytest.mark.asyncio
async def test_vitals_rejects_dishonest_spend_points(mutate: VitalsMutation) -> None:
    """SPEC C.4 is defended by verifying that vitals rejects dishonest spend points; this
    prevents drift in the authenticated Spine transport contract.
    """
    payload = vitals_payload()
    mutate(payload)

    await _assert_vitals_payload_rejected(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda payload: payload["spend"]["lanes"].reverse(),
            id="lane-order",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"].append(
                deepcopy(payload["spend"]["lanes"][-1])
            ),
            id="duplicate-lane",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][-1].update(
                key="~vendor/model",
                label="vendor/model",
            ),
            id="noncanonical-model-key-escape",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][-1].update(
                key="~~unreported",
                label="unreported",
            ),
            id="escaped-model-label-mismatch",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][0]["points"].append(
                deepcopy(payload["spend"]["lanes"][0]["points"][0])
            ),
            id="duplicate-minute",
        ),
        pytest.param(
            lambda payload: payload["spend"].update(latest_minute="2026-08-02T12:04:00Z"),
            id="latest-minute",
        ),
        pytest.param(_move_points_to_open_window_boundary, id="open-window-boundary"),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][1]["points"][0].update(receipt_lines=2),
            id="receipt-conservation",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][1]["points"][0].update(unpriced_lines=0),
            id="unpriced-conservation",
        ),
        pytest.param(
            lambda payload: payload["spend"]["lanes"][1]["points"][0].update(
                cost_usd="0.001100000000"
            ),
            id="dollar-conservation",
        ),
    ],
)
@pytest.mark.asyncio
async def test_vitals_rejects_noncanonical_or_unconserved_lanes(
    mutate: VitalsMutation,
) -> None:
    """SPEC C.4 is defended by verifying that vitals rejects noncanonical or unconserved lanes;
    this prevents drift in the authenticated Spine transport contract.
    """
    payload = vitals_payload()
    mutate(payload)

    await _assert_vitals_payload_rejected(payload)


@pytest.mark.asyncio
async def test_create_similar_response_is_distinct_from_created_status() -> None:
    """SPEC C.4 is defended by verifying that create similar response is distinct from created
    status; this prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(200, {"created": None, "similar": [similarity_card_payload()]})

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.create_memory(
            CreateMemoryRequest(
                principal_id="principal-1",
                label="Preference",
                body="Similar body",
                kind=MemoryKind.PREFERENCE,
                editor="user",
                machine_id="machine-1",
            )
        )

    assert isinstance(result, SimilarMemoriesResponse)
    assert result.similar[0].score == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_a049_split_preserves_existing_similar_and_conflict_status_bodies() -> None:
    """A-049, C.4, and SPEC B.6 rule 12 are defended here.
    Atomic split reuses exact near-similar 200 and conflict 409 bodies, never partial success.
    """
    outcomes = [
        response(200, {"created": None, "similar": [similarity_card_payload()]}),
        response(
            409,
            {"label_conflict": {"memory_id": MEMORY_ID, "label": "Editor preference"}},
        ),
    ]

    async def handler(_: httpx.Request) -> httpx.Response:
        return outcomes.pop(0)

    request = MemorySplitRequest(
        principal_id="principal-1",
        source_body="Fact one. Fact two.",
        children=[
            MemorySplitChild(label="First", body="Fact one.", keywords=["fact", "one"]),
            MemorySplitChild(label="Second", body="Fact two.", keywords=["fact", "two"]),
        ],
        editor="user",
        machine_id="machine-1",
    )
    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        similar = await client.create_memory_split(request)
        with pytest.raises(CreateMemoryConflictError) as caught:
            await client.create_memory_split(request)

    assert isinstance(similar, SimilarMemoriesResponse)
    assert str(similar.similar[0].memory_id) == MEMORY_ID
    assert isinstance(caught.value.conflict, LabelConflict)


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        (
            {"label_conflict": {"memory_id": MEMORY_ID, "label": "Editor preference"}},
            LabelConflict,
        ),
        ({"duplicate_of": similarity_card_payload()}, DuplicateMemoryConflict),
    ],
)
@pytest.mark.asyncio
async def test_create_409_is_a_typed_domain_conflict(
    payload: object, expected_type: type[object]
) -> None:
    """SPEC C.4 is defended by verifying that create 409 is a typed domain conflict; this
    prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(409, payload)

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(CreateMemoryConflictError) as caught:
            await client.create_memory(
                CreateMemoryRequest(
                    principal_id="principal-1",
                    label="Editor preference",
                    body="Body",
                    kind=MemoryKind.PREFERENCE,
                    editor="user",
                    machine_id="machine-1",
                )
            )

    assert isinstance(caught.value.conflict, expected_type)
    assert caught.value.response.status_code == 409


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        (
            {"label_conflict": {"memory_id": MEMORY_ID, "label": "Editor preference"}},
            LabelConflict,
        ),
        ({"conflict": memory_unit_payload()}, RevisionConflict),
    ],
)
@pytest.mark.asyncio
async def test_patch_409_is_a_typed_domain_conflict(
    payload: object, expected_type: type[object]
) -> None:
    """SPEC C.4 is defended by verifying that patch 409 is a typed domain conflict; this
    prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(409, payload)

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(PatchMemoryConflictError) as caught:
            await client.patch_memory(
                MEMORY_ID,
                PatchMemoryRequest(
                    expected_revision=1,
                    label="Editor preference",
                    editor="user",
                    reason="rename",
                    machine_id="machine-1",
                ),
            )

    assert isinstance(caught.value.conflict, expected_type)
    assert caught.value.response.status_code == 409


@pytest.mark.parametrize(
    ("route", "status"),
    [("search", 503), ("create", 409), ("patch", 409)],
)
@pytest.mark.asyncio
async def test_rfc7807_errors_remain_typed_problems(route: str, status: int) -> None:
    """SPEC C.4 is defended by verifying that rfc7807 errors remain typed problems; this
    prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(status, problem_payload(status), PROBLEM_JSON)

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineProblemError) as caught:
            if route == "search":
                await client.search(SearchRequest(principal_id="principal-1", query="tabs"))
            elif route == "create":
                await client.create_memory(
                    CreateMemoryRequest(
                        principal_id="principal-1",
                        label="Preference",
                        body="Body",
                        kind=MemoryKind.PREFERENCE,
                        editor="user",
                        machine_id="machine-1",
                    )
                )
            else:
                await client.patch_memory(
                    MEMORY_ID,
                    PatchMemoryRequest(
                        expected_revision=1,
                        label="Preference",
                        editor="user",
                        reason="rename",
                        machine_id="machine-1",
                    ),
                )

    assert caught.value.problem.status == status
    assert caught.value.problem.endpoint == "POST /v1/search"
    assert caught.value.problem.model_extra == {"trace_id": "trace-1"}
    assert "trace-1" not in str(caught.value)


@pytest.mark.parametrize(
    "make_response",
    [
        pytest.param(
            lambda: httpx.Response(200, text="not json", headers={"content-type": JSON}),
            id="invalid-json",
        ),
        pytest.param(
            lambda: response(200, {"results": []}, "text/plain"),
            id="wrong-media-type",
        ),
        pytest.param(
            lambda: response(200, {"unexpected": []}),
            id="wrong-shape",
        ),
        pytest.param(
            lambda: response(201, {"results": []}),
            id="wrong-success-status",
        ),
        pytest.param(
            lambda: response(503, {**problem_payload(), "status": 500}, PROBLEM_JSON),
            id="problem-status-mismatch",
        ),
        pytest.param(
            lambda: response(503, problem_payload(), JSON),
            id="wrong-problem-media-type",
        ),
        pytest.param(
            lambda: response(
                200,
                {"results": [{**similarity_card_payload(), "score": "0.85"}]},
            ),
            id="coerced-success-scalar",
        ),
        pytest.param(
            lambda: response(503, {**problem_payload(), "status": "503"}, PROBLEM_JSON),
            id="coerced-problem-scalar",
        ),
        pytest.param(
            lambda: raw_json_response(
                200,
                {"results": [{**similarity_card_payload(), "score": float("nan")}]},
            ),
            id="non-standard-json-constant",
        ),
    ],
)
@pytest.mark.asyncio
async def test_response_contract_violations_are_not_silently_accepted(
    make_response: Callable[[], httpx.Response],
) -> None:
    """SPEC C.4 is defended by verifying that response contract violations are not silently
    accepted; this prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return make_response()

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineResponseError):
            await client.search(SearchRequest(principal_id="principal-1", query="tabs"))


@pytest.mark.asyncio
async def test_rfc7807_standard_members_are_optional_but_not_nullable() -> None:
    """SPEC C.4 is defended by verifying that rfc7807 standard members are optional but not
    nullable; this prevents drift in the authenticated Spine transport contract.
    """
    payloads = [{}, {"title": None}]

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(503, payloads.pop(0), PROBLEM_JSON)

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineProblemError) as minimal:
            await client.search(SearchRequest(principal_id="principal-1", query="tabs"))
        with pytest.raises(SpineResponseError) as explicit_null:
            await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert minimal.value.problem.type == "about:blank"
    assert minimal.value.problem.status is None
    assert type(explicit_null.value) is SpineResponseError


@pytest.mark.asyncio
async def test_create_status_and_body_cannot_be_swapped() -> None:
    """SPEC C.4 is defended by verifying that create status and body cannot be swapped; this
    prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return response(200, {"created": memory_unit_payload()})

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineResponseError):
            await client.create_memory(
                CreateMemoryRequest(
                    principal_id="principal-1",
                    label="Preference",
                    body="Body",
                    kind=MemoryKind.PREFERENCE,
                    editor="user",
                    machine_id="machine-1",
                )
            )


@pytest.mark.asyncio
async def test_transport_failure_is_wrapped_without_request_secrets() -> None:
    """SPEC C.4 is defended by verifying that transport failure is wrapped without request
    secrets; this prevents drift in the authenticated Spine transport contract.
    """
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("dial failed", request=request)

    async with SpineClient(
        "https://spine.invalid",
        "secret-token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineTransportError) as caught:
            await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert isinstance(caught.value.__cause__, httpx.ConnectError)
    assert "secret-token" not in str(caught.value)
    assert calls == 1


@pytest.mark.asyncio
async def test_response_decoding_failure_is_wrapped_as_transport_failure() -> None:
    """SPEC C.4 is defended by verifying that response decoding failure is wrapped as transport
    failure; this prevents drift in the authenticated Spine transport contract.
    """

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not a gzip stream",
            headers={"content-encoding": "gzip", "content-type": JSON},
        )

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineTransportError) as caught:
            await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert isinstance(caught.value.__cause__, httpx.DecodingError)


@pytest.mark.asyncio
async def test_redirects_are_not_followed() -> None:
    """SPEC C.4 is defended by verifying that redirects are not followed; this prevents drift
    in the authenticated Spine transport contract.
    """
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(307, headers={"location": "https://other.invalid/v1/search"})

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(SpineResponseError):
            await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert calls == 1


class CloseAwareTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.closed = False

    async def handle_async_request(self, _: httpx.Request) -> httpx.Response:
        return response(200, {"results": []})

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_context_manager_closes_caller_supplied_transport() -> None:
    """SPEC C.4 is defended by verifying that context manager closes caller supplied transport;
    this prevents drift in the authenticated Spine transport contract.
    """
    transport = CloseAwareTransport()

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=transport,
    ) as client:
        await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert transport.closed is True


def test_constructor_rejects_missing_connection_values() -> None:
    """SPEC C.4 is defended by verifying that constructor rejects missing connection values;
    this prevents drift in the authenticated Spine transport contract.
    """
    for base_url in ("", "   "):
        with pytest.raises(ValueError, match="base_url"):
            SpineClient(base_url, "token")
    for token in ("", "   "):
        with pytest.raises(ValueError, match="token"):
            SpineClient("https://spine.invalid", token)
    with pytest.raises(ValueError, match="token"):
        SpineClient("https://spine.invalid", " token ")


@pytest.mark.parametrize(
    "base_url",
    [
        "spine.invalid/prefix",
        "/prefix",
        "://bad",
        "ftp://spine.invalid/prefix",
        "http://",
        "http://spine.invalid:bad",
        "https://user:pass@spine.invalid/prefix",
        "https://spine.invalid/prefix?mode=test",
        "https://spine.invalid/prefix?",
        "https://spine.invalid/prefix#fragment",
        "https://spine.invalid/prefix#",
    ],
)
def test_constructor_rejects_unsafe_base_urls(base_url: str) -> None:
    """SPEC C.4 is defended by verifying that constructor rejects unsafe base urls; this
    prevents drift in the authenticated Spine transport contract.
    """
    with pytest.raises(ValueError, match="base_url"):
        SpineClient(base_url, "token")


@pytest.mark.asyncio
async def test_base_url_normalization_preserves_encoded_path_segments() -> None:
    """SPEC C.4 is defended by verifying that base url normalization preserves encoded path
    segments; this prevents drift in the authenticated Spine transport contract.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path == b"/tenant%2Fone/v1/search"
        return response(200, {"results": []})

    async with SpineClient(
        "  https://spine.invalid/tenant%2Fone//  ",
        "token",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert result.results == []
