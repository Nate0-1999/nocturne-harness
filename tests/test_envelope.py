from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from harness.envelope import (
    ActiveRunSnapshot,
    Envelope,
    EnvelopeFactory,
    GateCommitPayload,
    GateDismissPayload,
    GateOpenPayload,
    MessageType,
    PromptQueuedPayload,
    PromptSubmitPayload,
    RunCancelPayload,
    RunDeltaEventPayload,
    RunDeltaTextPayload,
    RunDeltaThinkingPayload,
    RunDonePayload,
    RunStartedPayload,
    RunUsagePayload,
    StopReason,
    ThreadSnapshotRequestPayload,
    ThreadSnapshotResponsePayload,
    generate_ulid,
)

ENVELOPE_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"
PROMPT_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAX"
SECOND_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAY"
INJECTION_ID = "32345678-1234-5678-1234-567812345678"
MEMORY_ID = "42345678-1234-5678-1234-567812345678"


def scored_card() -> dict[str, object]:
    return {
        "memory_id": MEMORY_ID,
        "label": "Preferred editor",
        "body": "Use the configured editor for text changes.",
        "kind": "preference",
        "pin": False,
        "score": 0.85,
        "features": {
            "sem": 0.9,
            "kw": 0.8,
            "time": 0.7,
            "proj": 0.6,
            "freq": 0.5,
            "hist": 0.4,
        },
        "rank": 1,
    }


def gate_open_payload(**extensions: object) -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "kind": "memory_gate",
        "stage": "review",
        "injection_id": INJECTION_ID,
        "snapshot_ts": "2026-07-21T12:00:00Z",
        "scorer_version": "m1-v1",
        "injected": [scored_card()],
        "near_misses": [],
        "wrong_removed": [],
        "resolution_error": None,
        **extensions,
    }


def gate_commit_payload() -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "injection_id": INJECTION_ID,
        "removed": [{"memory_id": MEMORY_ID, "reason": "not_relevant"}],
        "added_back": [],
        "wrong_resolution": None,
    }


def wrong_unit() -> dict[str, object]:
    return {
        "memory_id": MEMORY_ID,
        "principal_id": "principal-1",
        "label": "Wrong memory",
        "body": "Current body",
        "kind": "fact",
        "keywords": [],
        "project_key": None,
        "thread_origin": "thread-1",
        "origin_path": None,
        "pin": False,
        "status": "active",
        "revision": 2,
        "stats": {},
        "bias": 0.0,
        "embedding_model": "test-embedding",
        "created_at": "2026-07-20T12:00:00Z",
        "updated_at": "2026-07-21T12:00:00Z",
    }


def valid_envelope() -> dict[str, object]:
    return {
        "v": 1,
        "id": ENVELOPE_ID,
        "ts": "2026-07-17T12:00:00Z",
        "machine_id": "machine-1",
        "agent_id": "agent-1",
        "thread_id": "thread-1",
        "type": "prompt.submit",
        "payload": {"prompt": "hello"},
    }


def envelope_for(message_type: str, payload: object) -> Envelope:
    return Envelope.model_validate({**valid_envelope(), "type": message_type, "payload": payload})


def test_valid_c7_envelope_has_named_type_and_typed_payload() -> None:
    envelope = Envelope.model_validate(valid_envelope())

    assert envelope.v == 1
    assert envelope.type is MessageType.PROMPT_SUBMIT
    assert isinstance(envelope.payload, PromptSubmitPayload)
    assert envelope.payload.prompt == "hello"
    assert isinstance(envelope.ts, datetime)


def test_message_types_cover_m1_and_reserved_names() -> None:
    assert {message_type.value for message_type in MessageType} == {
        "thread.create",
        "thread.snapshot",
        "prompt.submit",
        "prompt.queued",
        "gate.open",
        "gate.commit",
        "gate.dismiss",
        "run.started",
        "run.cancel",
        "run.delta",
        "run.usage",
        "run.done",
        "memory.panel.update",
        "error",
        "run.steer",
        "plan.update",
        "checkpoint.created",
        "checkpoint.restore",
        "presence.update",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("v", 2),
        ("v", True),
        ("id", "not-a-ulid"),
        ("id", "81ARZ3NDEKTSV4RRFFQ69G5FAV"),
        ("type", ""),
        ("type", " \t\n"),
        ("type", 3),
    ],
)
def test_rejects_invalid_outer_values(field: str, value: object) -> None:
    raw = valid_envelope()
    raw[field] = value

    with pytest.raises(ValidationError):
        Envelope.model_validate(raw)


def test_rejects_extra_outer_fields() -> None:
    raw = valid_envelope()
    raw["localhost"] = True

    with pytest.raises(ValidationError):
        Envelope.model_validate(raw)


@pytest.mark.parametrize("field", ["v", "id", "ts", "machine_id", "type", "payload"])
def test_rejects_missing_required_outer_fields(field: str) -> None:
    raw = valid_envelope()
    del raw[field]

    with pytest.raises(ValidationError):
        Envelope.model_validate(raw)


def test_optional_agent_and_thread_ids_may_be_absent_for_untyped_extension() -> None:
    raw = valid_envelope()
    del raw["agent_id"]
    del raw["thread_id"]
    raw["type"] = "relay.extension"

    envelope = Envelope.model_validate(raw)

    assert envelope.agent_id is None
    assert envelope.thread_id is None


@pytest.mark.parametrize(
    ("message_type", "payload", "expected_class"),
    [
        (
            "run.started",
            {"run_id": RUN_ID, "prompt_id": PROMPT_ID},
            RunStartedPayload,
        ),
        ("run.cancel", {"run_id": RUN_ID}, RunCancelPayload),
        (
            "prompt.queued",
            {"run_id": RUN_ID, "prompt_id": PROMPT_ID},
            PromptQueuedPayload,
        ),
        (
            "run.usage",
            {
                "run_id": RUN_ID,
                "requests": 1,
                "input_tokens": 2,
                "output_tokens": 3,
            },
            RunUsagePayload,
        ),
        ("gate.open", gate_open_payload(), GateOpenPayload),
        ("gate.commit", gate_commit_payload(), GateCommitPayload),
        ("gate.dismiss", {"run_id": RUN_ID}, GateDismissPayload),
    ],
)
def test_known_minimum_payloads_are_typed(
    message_type: str,
    payload: dict[str, object],
    expected_class: type[object],
) -> None:
    envelope = envelope_for(message_type, payload)

    assert isinstance(envelope.payload, expected_class)
    assert envelope.model_dump(mode="json")["payload"] == payload


@pytest.mark.parametrize(
    ("payload", "expected_class"),
    [
        (
            {"run_id": RUN_ID, "kind": "text", "text": "answer"},
            RunDeltaTextPayload,
        ),
        (
            {"run_id": RUN_ID, "kind": "thinking", "text": "reasoning"},
            RunDeltaThinkingPayload,
        ),
        (
            {"run_id": RUN_ID, "kind": "event", "event": {"name": "tool", "ok": True}},
            RunDeltaEventPayload,
        ),
    ],
)
def test_run_delta_is_discriminated(
    payload: dict[str, object], expected_class: type[object]
) -> None:
    envelope = envelope_for("run.delta", payload)

    assert isinstance(envelope.payload, expected_class)
    assert envelope.model_dump(mode="json")["payload"] == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": RUN_ID, "kind": "unknown", "text": "x"},
        {"run_id": RUN_ID, "kind": "text"},
        {"run_id": RUN_ID, "kind": "event", "event": ["not", "an", "object"]},
    ],
)
def test_run_delta_rejects_wrong_variant_shape(payload: object) -> None:
    with pytest.raises(ValidationError):
        envelope_for("run.delta", payload)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_run_usage_requires_strict_nonnegative_integers(value: object) -> None:
    with pytest.raises(ValidationError):
        envelope_for(
            "run.usage",
            {
                "run_id": RUN_ID,
                "requests": value,
                "input_tokens": 0,
                "output_tokens": 0,
            },
        )


@pytest.mark.parametrize(
    ("stop_reason", "partial"),
    [
        ("end_turn", False),
        ("cancelled", True),
        ("error", True),
        ("budget_exceeded", True),
    ],
)
def test_run_done_enforces_stop_reason_partial_invariant(stop_reason: str, partial: bool) -> None:
    envelope = envelope_for(
        "run.done",
        {"run_id": RUN_ID, "stop_reason": stop_reason, "partial": partial},
    )

    assert isinstance(envelope.payload, RunDonePayload)
    assert envelope.payload.stop_reason is StopReason(stop_reason)

    with pytest.raises(ValidationError):
        envelope_for(
            "run.done",
            {"run_id": RUN_ID, "stop_reason": stop_reason, "partial": not partial},
        )


def test_prompt_submit_requires_nonblank_prompt_and_outer_thread() -> None:
    for prompt in ("", "  \n"):
        with pytest.raises(ValidationError):
            envelope_for("prompt.submit", {"prompt": prompt})

    for thread_id in (None, " \t"):
        raw = {**valid_envelope(), "thread_id": thread_id}
        with pytest.raises(ValidationError):
            Envelope.model_validate(raw)


def test_gate_commit_requires_outer_thread() -> None:
    raw = {
        **valid_envelope(),
        "thread_id": None,
        "type": "gate.commit",
        "payload": gate_commit_payload(),
    }

    with pytest.raises(ValidationError):
        Envelope.model_validate(raw)


@pytest.mark.parametrize(
    "payload",
    [
        {**gate_open_payload(), "scorer_version": "  "},
        {**gate_open_payload(), "injected": [{**scored_card(), "features": None}]},
        {**gate_open_payload(), "near_misses": [{**scored_card(), "rank": None}]},
        {**gate_commit_payload(), "removed": [{"memory_id": MEMORY_ID, "reason": "later"}]},
    ],
)
def test_memory_gate_payloads_enforce_exact_c4_member_types(
    payload: dict[str, object],
) -> None:
    message_type = "gate.commit" if "removed" in payload else "gate.open"
    with pytest.raises(ValidationError):
        envelope_for(message_type, payload)


@pytest.mark.parametrize(
    "card_update",
    [
        {"rank": 0},
        {"rank": True},
        {"score": True},
        {"features": {**scored_card()["features"], "sem": -0.01}},
        {"features": {**scored_card()["features"], "hist": 1.01}},
    ],
)
def test_gate_open_rejects_cards_the_browser_cannot_render_truthfully(
    card_update: dict[str, object],
) -> None:
    payload = gate_open_payload(injected=[{**scored_card(), **card_update}])

    with pytest.raises(ValidationError):
        envelope_for("gate.open", payload)


def test_gate_open_rejects_duplicate_membership_across_card_arrays() -> None:
    payload = gate_open_payload(near_misses=[scored_card()])

    with pytest.raises(ValidationError):
        envelope_for("gate.open", payload)


def test_wrong_resolution_gate_and_decision_are_typed() -> None:
    opened = envelope_for(
        "gate.open",
        gate_open_payload(
            stage="wrong_resolution",
            injected=[],
            wrong_removed=[wrong_unit()],
            resolution_error="Review the latest revision.",
        ),
    )
    assert isinstance(opened.payload, GateOpenPayload)
    assert opened.payload.stage == "wrong_resolution"
    assert opened.payload.wrong_removed[0].revision == 2

    committed = envelope_for(
        "gate.commit",
        {
            **gate_commit_payload(),
            "removed": [],
            "wrong_resolution": {
                "memory_id": MEMORY_ID,
                "expected_revision": 2,
                "action": "edit",
                "body": "Corrected body",
            },
        },
    )
    assert isinstance(committed.payload, GateCommitPayload)
    assert committed.payload.wrong_resolution is not None
    assert committed.payload.wrong_resolution.body == "Corrected body"


@pytest.mark.parametrize(
    "payload",
    [
        gate_open_payload(stage="wrong_resolution", injected=[], wrong_removed=[]),
        gate_open_payload(stage="wrong_resolution", wrong_removed=[wrong_unit()]),
        gate_open_payload(wrong_removed=[wrong_unit()]),
        {
            **gate_commit_payload(),
            "wrong_resolution": {
                "memory_id": MEMORY_ID,
                "expected_revision": 2,
                "action": "edit",
                "body": "   ",
            },
        },
        {
            **gate_commit_payload(),
            "wrong_resolution": {
                "memory_id": MEMORY_ID,
                "expected_revision": 2,
                "action": "expire",
                "body": "must be absent",
            },
        },
    ],
)
def test_wrong_resolution_rejects_inconsistent_stage_shapes(
    payload: dict[str, object],
) -> None:
    message_type = "gate.open" if "kind" in payload else "gate.commit"
    with pytest.raises(ValidationError):
        envelope_for(message_type, payload)


def test_thread_snapshot_request_requires_outer_thread() -> None:
    request = envelope_for("thread.snapshot", {"request": True})
    assert isinstance(request.payload, ThreadSnapshotRequestPayload)

    raw = {
        **valid_envelope(),
        "thread_id": None,
        "type": "thread.snapshot",
        "payload": {"request": True},
    }
    with pytest.raises(ValidationError):
        Envelope.model_validate(raw)


def test_thread_snapshot_request_extensions_cannot_reclassify_its_direction() -> None:
    request = envelope_for(
        "thread.snapshot",
        {
            "request": True,
            "messages": [],
            "open_gate": None,
            "active_run": None,
        },
    )

    assert isinstance(request.payload, ThreadSnapshotRequestPayload)


def test_thread_snapshot_response_types_nested_authoritative_state() -> None:
    payload = {
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "par", "partial": True},
        ],
        "open_gate": gate_open_payload(),
        "active_run": {
            "run_id": RUN_ID,
            "prompt_id": PROMPT_ID,
            "state": "waiting_gate",
            "usage": {"requests": 1, "input_tokens": 2, "output_tokens": 3},
            "queued": [{"run_id": SECOND_ID, "prompt_id": ENVELOPE_ID, "prompt": "next"}],
        },
        "revision": 7,
    }

    snapshot = envelope_for("thread.snapshot", payload)

    assert isinstance(snapshot.payload, ThreadSnapshotResponsePayload)
    assert isinstance(snapshot.payload.open_gate, GateOpenPayload)
    assert isinstance(snapshot.payload.active_run, ActiveRunSnapshot)
    assert snapshot.model_dump(mode="json")["payload"] == payload


@pytest.mark.parametrize(
    "message_type",
    ["run.steer", "plan.update", "checkpoint.restore", "relay.connect"],
)
def test_reserved_and_unknown_types_preserve_arbitrary_json(message_type: str) -> None:
    payload = {"future": [1, "two", True, None], "nested": {"ok": False}}
    envelope = envelope_for(message_type, payload)

    expected_type = (
        MessageType(message_type)
        if message_type in MessageType._value2member_map_
        else message_type
    )
    assert envelope.type == expected_type
    assert envelope.payload == payload
    assert envelope.model_dump(mode="json")["payload"] == payload


def test_unknown_type_rejects_non_json_python_payload() -> None:
    with pytest.raises(ValidationError):
        envelope_for("relay.connect", {"at": datetime.now(UTC)})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_unknown_and_extensible_known_payloads_reject_nonfinite_numbers(
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        envelope_for("relay.connect", {"value": value})
    with pytest.raises(ValidationError):
        envelope_for(
            "run.delta",
            {"run_id": RUN_ID, "kind": "event", "event": {"value": value}},
        )
    with pytest.raises(ValidationError):
        envelope_for(
            "gate.open",
            gate_open_payload(weight=value),
        )


def test_minimum_payload_extensions_are_json_typed_and_preserved() -> None:
    payload = gate_open_payload(
        candidate_ids=["a", "b"],
        details={"count": 2},
    )
    envelope = envelope_for("gate.open", payload)

    assert envelope.model_dump(mode="json")["payload"] == payload

    with pytest.raises(ValidationError):
        envelope_for(
            "gate.open",
            gate_open_payload(at=datetime.now(UTC)),
        )


def test_factory_injects_fresh_ids_timestamps_and_daemon_metadata() -> None:
    ids: Iterator[str] = iter((ENVELOPE_ID, SECOND_ID))
    times: Iterator[datetime] = iter(
        (
            datetime(2026, 7, 20, 12, tzinfo=UTC),
            datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC),
        )
    )
    factory = EnvelopeFactory(
        machine_id="daemon-1",
        agent_id="agent-1",
        id_factory=lambda: next(ids),
        clock=lambda: next(times),
    )

    first = factory.create(
        MessageType.RUN_STARTED,
        RunStartedPayload(run_id=RUN_ID, prompt_id=PROMPT_ID),
        thread_id="thread-1",
    )
    second = factory.create("relay.extension", {"ok": True}, thread_id="thread-1")

    assert (first.id, second.id) == (ENVELOPE_ID, SECOND_ID)
    assert first.ts == datetime(2026, 7, 20, 12, tzinfo=UTC)
    assert second.ts == datetime(2026, 7, 20, 12, 0, 1, tzinfo=UTC)
    assert first.machine_id == second.machine_id == "daemon-1"
    assert first.agent_id == second.agent_id == "agent-1"
    assert isinstance(first.payload, RunStartedPayload)


def test_factory_and_generator_emit_valid_ulids() -> None:
    generated = generate_ulid(datetime(2026, 7, 20, tzinfo=UTC))
    factory = EnvelopeFactory(machine_id="daemon-1", id_factory=lambda: generated)

    assert factory.new_id() == generated
    assert len(generated) == 26
    Envelope.model_validate(
        {
            **valid_envelope(),
            "id": generated,
            "type": "relay.extension",
        }
    )


def test_factory_rejects_invalid_injected_id() -> None:
    factory = EnvelopeFactory(machine_id="daemon-1", id_factory=lambda: "bad")

    with pytest.raises(ValueError, match="ULID"):
        factory.new_id()
