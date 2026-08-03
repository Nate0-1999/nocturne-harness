import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any

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
    InjectPrepareRequest,
    LabelConflict,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
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


def _measure_reinforced(payload: dict[str, Any]) -> None:
    payload["lifecycle_rates"][1].update(
        status="measured",
        per_hour=0,
        source="invented.reinforcement",
    )


def _measure_queue_depth(payload: dict[str, Any]) -> None:
    payload["palace_counts"][-1].update(
        status="measured",
        count=0,
        source="invented.queue",
    )


def _move_points_to_open_window_boundary(payload: dict[str, Any]) -> None:
    boundary = "2026-08-02T11:05:30Z"
    payload["spend"]["latest_minute"] = boundary
    for lane in payload["spend"]["lanes"]:
        lane["points"][0]["minute"] = boundary


@pytest.mark.asyncio
async def test_all_routes_send_exact_http_contract() -> None:
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
            },
        ),
        ("POST", "/prefix/v1/inject/commit"): response(
            200, {"final_block": "<memory_system></memory_system>", "wrong_removed": []}
        ),
        ("POST", "/prefix/v1/feedback"): response(200, {"ok": True}),
        ("POST", "/prefix/v1/memories"): response(201, {"created": memory_unit_payload()}),
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
    assert isinstance(created, CreatedMemoryResponse)
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
    payload = vitals_payload()
    payload["spend"]["lanes"][0]["points"][0]["cost_usd"] = 0.0012

    await _assert_vitals_payload_rejected(payload)


@pytest.mark.asyncio
async def test_vitals_accepts_the_a029_reserved_model_key_escape() -> None:
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
        pytest.param(_measure_queue_depth, id="queue-must-be-placeholder"),
    ],
)
@pytest.mark.asyncio
async def test_vitals_requires_the_exact_a028_gauge_contract(mutate: VitalsMutation) -> None:
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
    payload = vitals_payload()
    mutate(payload)

    await _assert_vitals_payload_rejected(payload)


@pytest.mark.asyncio
async def test_create_similar_response_is_distinct_from_created_status() -> None:
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
    transport = CloseAwareTransport()

    async with SpineClient(
        "https://spine.invalid",
        "token",
        transport=transport,
    ) as client:
        await client.search(SearchRequest(principal_id="principal-1", query="tabs"))

    assert transport.closed is True


def test_constructor_rejects_missing_connection_values() -> None:
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
    with pytest.raises(ValueError, match="base_url"):
        SpineClient(base_url, "token")


@pytest.mark.asyncio
async def test_base_url_normalization_preserves_encoded_path_segments() -> None:
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
