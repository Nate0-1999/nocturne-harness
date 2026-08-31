import inspect
from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflict,
    CreateMemoryRequest,
    DuplicateMemoryConflict,
    InjectCommitResponse,
    InjectionEventAnnotationInput,
    InjectionEventAnnotationsRequest,
    InjectionEventAnnotationsResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    LabelConflict,
    ListMemoriesParams,
    MemoryAllocation,
    MemoryCard,
    MemoryKind,
    MemorySplitChild,
    MemorySplitRequest,
    MemorySplitResponse,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryConflict,
    PatchMemoryRequest,
    PatchMemoryResponse,
    RetrainResponse,
    RevisionConflict,
    SearchRequest,
    SearchResponse,
    SimilarMemoriesResponse,
    SpineClient,
)


def memory_unit_payload() -> dict[str, object]:
    return {
        "memory_id": "12345678-1234-5678-1234-567812345678",
        "principal_id": "principal-1",
        "label": "Editor preference",
        "body": "The user prefers tabs.",
        "kind": "preference",
        "keywords": ["editor", "tabs"],
        "project_key": None,
        "thread_origin": None,
        "origin_thread_id": None,
        "origin_path": None,
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
        "embedding_model": "text-embedding-3-small",
        "created_at": "2026-07-17T12:00:00Z",
        "updated_at": "2026-07-17T12:00:00Z",
    }


def memory_allocation() -> MemoryAllocation:
    return MemoryAllocation(
        memory_context_share=0.10,
        share_tokens=100,
        regular_tokens=1,
        pinned_tokens=0,
        total_tokens=1,
        pinned_overflow_tokens=0,
    )


def similarity_card_payload() -> dict[str, object]:
    return {
        "memory_id": "12345678-1234-5678-1234-567812345678",
        "label": "Editor preference",
        "body": "The user prefers tabs.",
        "kind": "preference",
        "pin": False,
        "score": 0.87,
        "features": None,
        "rank": None,
    }


def scored_card_payload() -> dict[str, object]:
    payload = similarity_card_payload()
    payload["features"] = {
        "sem": 0.9,
        "kw": 0.5,
        "time": 1.0,
        "proj": 0.5,
        "freq": 0.0,
        "hist": 0.0,
    }
    payload["rank"] = 1
    return payload


def test_client_exposes_all_spine_routes() -> None:
    """SPEC C.4 is defended by verifying that client exposes all spine routes; this prevents
    drift in the typed Harness-Spine client contract.
    """
    methods = {
        name
        for name, value in inspect.getmembers(SpineClient, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }

    assert methods == {
        "aclose",
        "prepare_injection",
        "commit_injection",
        "submit_feedback",
        "annotate_injection_events",
        "create_memory",
        "create_memory_split",
        "patch_memory",
        "list_memories",
        "search",
        "record_spend_events",
        "spend_table",
        "vitals_snapshot",
        "thread_vitals_snapshot",
        "memory_graph",
        "scorer_console",
        "retrain",
        "create_scorer_config",
        "simulate_scorer",
        "audition_scorer",
        "activate_scorer_config",
        "create_extraction",
        "create_seed",
        "approval_queue",
        "curator_activity",
        "stage_symphony_memory",
        "visible_symphony_memories",
        "resolve_symphony_run",
        "decide_queue_item",
        "decide_queue_batch",
        "append_transcripts",
        "transcripts",
        "transcript_status",
    }


def test_injection_event_annotation_contract_is_strict_and_atomic() -> None:
    """A-053/F033 is defended by verifying that annotation batches retain target
    fingerprints, provenance, and unique canonical targets; this prevents ambiguous hygiene
    rewrites at the typed Harness-Spine boundary.
    """
    annotation = InjectionEventAnnotationInput(
        target_event_uid="01KY2JE3JKY1MXYCKVZ93KY399",
        expected_principal_id="d1-4f6500c7-336f-4ce4-871b-9f31ef770f9f",
        expected_machine_id="d1-relay",
        reason="Legacy D1 deploy verification artifact.",
        annotator_principal_id="m2za-sop-verification",
        annotator_machine_id="m2za-sop-verification",
        annotator_origin_agent="verification:m2za",
    )
    request = InjectionEventAnnotationsRequest(annotations=[annotation])

    assert request.model_dump(mode="json") == {
        "annotations": [
            {
                "target_event_uid": "01KY2JE3JKY1MXYCKVZ93KY399",
                "expected_principal_id": "d1-4f6500c7-336f-4ce4-871b-9f31ef770f9f",
                "expected_machine_id": "d1-relay",
                "reason": "Legacy D1 deploy verification artifact.",
                "annotator_principal_id": "m2za-sop-verification",
                "annotator_machine_id": "m2za-sop-verification",
                "annotator_origin_agent": "verification:m2za",
            }
        ]
    }
    historical_fingerprint = InjectionEventAnnotationInput(
        **{
            **annotation.model_dump(),
            "expected_principal_id": " ",
            "expected_machine_id": "",
        }
    )
    assert historical_fingerprint.expected_principal_id == " "
    assert historical_fingerprint.expected_machine_id == ""
    assert InjectionEventAnnotationsResponse(accepted=1).accepted == 1
    with pytest.raises(ValidationError):
        InjectionEventAnnotationsRequest(annotations=[])
    with pytest.raises(ValidationError):
        InjectionEventAnnotationsRequest(annotations=[annotation, annotation])
    with pytest.raises(ValidationError):
        InjectionEventAnnotationInput(
            **{**annotation.model_dump(), "reason": " "},
        )
    with pytest.raises(ValidationError):
        InjectionEventAnnotationInput(
            **{**annotation.model_dump(), "target_event_uid": "not-a-ulid"},
        )
    with pytest.raises(ValidationError):
        InjectionEventAnnotationsResponse(accepted="1")


def test_retrain_response_keeps_learning_receipts_strict_and_server_authored() -> None:
    """A-051/P1.2.3 is defended by rejecting browser-invented or coerced learner
    receipt data at the Harness-Spine boundary.
    """
    payload = {
        "status": "proposed",
        "incumbent_version": "v0",
        "proposal_version": "m2f-a1",
        "eligible_dispositions": 25,
        "training_dispositions": 20,
        "holdout_dispositions": 5,
        "training_pairs": 12,
        "incumbent": {
            "disagreements": 2,
            "weighted_disagreements": "1.25",
            "injected_tokens": 400,
        },
        "challenger": {
            "disagreements": 1,
            "weighted_disagreements": "0.5",
            "injected_tokens": 400,
        },
        "reason": "challenger won replay and remains inactive pending owner activation",
    }

    receipt = RetrainResponse.model_validate(payload)

    assert receipt.proposal_version == "m2f-a1"
    coerced = deepcopy(payload)
    coerced["eligible_dispositions"] = "25"
    with pytest.raises(ValidationError):
        RetrainResponse.model_validate(coerced)
    invented = deepcopy(payload)
    invented["browser_accuracy"] = 96
    with pytest.raises(ValidationError):
        RetrainResponse.model_validate(invented)


def test_prepare_request_mirrors_named_c4_fields() -> None:
    """SPEC C.4 is defended by verifying that prepare request mirrors named c4 fields; this
    prevents drift in the typed Harness-Spine client contract.
    """
    request = InjectPrepareRequest(
        thread_id="12345678-1234-5678-1234-567812345678",
        agent_id="agent-1",
        machine_id="machine-1",
        principal_id="principal-1",
        prompt="hello",
        model_context_tokens=200_000,
    )

    assert set(request.model_dump(exclude_none=True, exclude_defaults=True)) == {
        "thread_id",
        "agent_id",
        "machine_id",
        "principal_id",
        "prompt",
        "model_context_tokens",
    }


def test_memory_unit_is_the_shared_c4_shape() -> None:
    """SPEC C.4 is defended by verifying that memory unit is the shared c4 shape; this prevents
    drift in the typed Harness-Spine client contract.
    """
    unit = MemoryUnit.model_validate(memory_unit_payload())

    assert set(unit.model_dump()) == {
        "memory_id",
        "principal_id",
        "label",
        "body",
        "kind",
        "keywords",
        "project_key",
        "thread_origin",
        "origin_thread_id",
        "origin_path",
        "pin",
        "status",
        "revision",
        "stats",
        "bias",
        "embedding_model",
        "created_at",
        "updated_at",
    }
    assert "embedding" not in MemoryUnit.model_fields


def test_dedup_and_search_cards_require_nullable_features_and_rank() -> None:
    """SPEC C.4 is defended by verifying that dedup and search cards require nullable features
    and rank; this prevents drift in the typed Harness-Spine client contract.
    """
    card = MemoryCard.model_validate(similarity_card_payload())
    search = SearchResponse(results=[similarity_card_payload()])

    assert card.features is None
    assert card.rank is None
    assert search.results[0].score == pytest.approx(0.87)

    missing_features = similarity_card_payload()
    del missing_features["features"]
    with pytest.raises(ValidationError):
        MemoryCard.model_validate(missing_features)


def test_prepare_cards_require_concrete_features_and_rank() -> None:
    """SPEC C.4 is defended by verifying that prepare cards require concrete features and rank;
    this prevents drift in the typed Harness-Spine client contract.
    """
    response = InjectPrepareResponse(
        injection_id="22345678-1234-5678-1234-567812345678",
        snapshot_ts="2026-07-17T12:00:00Z",
        scorer_version="v0",
        injected=[scored_card_payload()],
        near_misses=[],
        final_block=None,
        memory_allocation=memory_allocation(),
    )

    assert response.injected[0].features.sem == pytest.approx(0.9)
    assert response.injected[0].rank == 1
    with pytest.raises(ValidationError):
        InjectPrepareResponse(
            injection_id="22345678-1234-5678-1234-567812345678",
            snapshot_ts="2026-07-17T12:00:00Z",
            scorer_version="v0",
            injected=[similarity_card_payload()],
            near_misses=[],
            final_block=None,
            memory_allocation=memory_allocation(),
        )


def test_commit_response_includes_current_wrong_units() -> None:
    """SPEC C.4 is defended by verifying that commit response includes current wrong units;
    this prevents drift in the typed Harness-Spine client contract.
    """
    response = InjectCommitResponse(
        final_block="<memory_system></memory_system>",
        wrong_removed=[memory_unit_payload()],
    )

    assert response.wrong_removed[0].revision == 1


def test_create_request_has_machine_id_and_similar_band_force() -> None:
    """SPEC C.4 is defended by verifying that create request has machine id and similar band
    force; this prevents drift in the typed Harness-Spine client contract.
    """
    request = CreateMemoryRequest(
        principal_id="principal-1",
        label="Editor preference",
        body="The user prefers tabs.",
        kind=MemoryKind.PREFERENCE,
        editor="user",
        machine_id="machine-1",
    )

    assert request.machine_id == "machine-1"
    assert request.origin_path is None
    assert request.force is False
    assert CreateMemoryRequest(**{**request.model_dump(), "force": True}).force is True


def test_create_success_and_similar_bodies_use_v15_shapes() -> None:
    """SPEC C.4 is defended by verifying that create success and similar bodies use v15 shapes;
    this prevents drift in the typed Harness-Spine client contract.
    """
    created = CreatedMemoryResponse(created=memory_unit_payload())
    similar = SimilarMemoriesResponse(created=None, similar=[similarity_card_payload()])

    assert created.created.memory_id == similar.similar[0].memory_id
    assert similar.similar[0].features is None


def test_a049_memory_split_models_are_closed_exact_c4_shapes() -> None:
    """A-049, C.4, and SPEC B.6 rule 12 are defended here.
    Atomic split models expose only the enacted exact-source, child, and lineage fields.
    """
    request = MemorySplitRequest(
        principal_id="principal-1",
        source_body="Fact one. Fact two.",
        children=[
            MemorySplitChild(label="First", body="Fact one.", keywords=["fact", "one"]),
            MemorySplitChild(label="Second", body="Fact two.", keywords=["fact", "two"]),
        ],
        thread_origin="22345678-1234-5678-1234-567812345678",
        origin_thread_id=UUID("22345678-1234-5678-1234-567812345678"),
        origin_path="/workspace/notes.md",
        editor="user",
        machine_id="machine-1",
    )
    source = memory_unit_payload()
    source.update(label="Split source", body=request.source_body, status="tombstoned")
    response = MemorySplitResponse(
        source=source,
        created=[memory_unit_payload(), memory_unit_payload()],
    )

    assert set(request.model_dump()) == {
        "principal_id",
        "source_body",
        "children",
        "thread_origin",
        "origin_thread_id",
        "origin_path",
        "editor",
        "machine_id",
    }
    assert set(request.children[0].model_dump()) == {"label", "body", "keywords"}
    assert response.source.status == "tombstoned"
    assert len(response.created) == 2
    with pytest.raises(ValidationError):
        MemorySplitRequest.model_validate({**request.model_dump(), "kind": "fact"})


def test_create_conflicts_cover_duplicate_and_active_label() -> None:
    """SPEC C.4 is defended by verifying that create conflicts cover duplicate and active
    label; this prevents drift in the typed Harness-Spine client contract.
    """
    duplicate = DuplicateMemoryConflict(duplicate_of=similarity_card_payload())
    label = LabelConflict(
        label_conflict={
            "memory_id": "12345678-1234-5678-1234-567812345678",
            "label": "Editor preference",
        }
    )

    assert duplicate.duplicate_of.score == pytest.approx(0.87)
    assert label.label_conflict.label == "Editor preference"
    conflicts = TypeAdapter(CreateMemoryConflict)
    assert conflicts.validate_python(duplicate).duplicate_of.features is None
    assert conflicts.validate_python(label).label_conflict.label == "Editor preference"


def test_patch_request_and_exact_success_conflict_bodies() -> None:
    """SPEC C.4 is defended by verifying that patch request and exact success conflict bodies;
    this prevents drift in the typed Harness-Spine client contract.
    """
    request = PatchMemoryRequest(
        expected_revision=1,
        body="The user strongly prefers tabs.",
        label="Editor preference",
        editor="user",
        reason="user correction",
        machine_id="machine-1",
    )
    current = TypeAdapter(PatchMemoryResponse).validate_python(memory_unit_payload())
    conflict = RevisionConflict(conflict=memory_unit_payload())
    label_conflict = LabelConflict(
        label_conflict={
            "memory_id": "12345678-1234-5678-1234-567812345678",
            "label": "Editor preference",
        }
    )
    conflicts = TypeAdapter(PatchMemoryConflict)

    assert request.machine_id == "machine-1"
    assert request.origin_path is None
    assert current.revision == conflict.conflict.revision == 1
    assert conflicts.validate_python(conflict).conflict.revision == 1
    assert conflicts.validate_python(label_conflict).label_conflict.label == request.label


def test_list_params_and_response_mirror_stable_paging_contract() -> None:
    """SPEC C.4 is defended by verifying that list params and response mirror stable paging
    contract; this prevents drift in the typed Harness-Spine client contract.
    """
    params = ListMemoriesParams()
    response = PagedMemoryListResponse(
        items=[memory_unit_payload()], total=1, limit=params.limit, offset=params.offset
    )

    assert params.model_dump() == {
        "project_key": None,
        "status": None,
        "q": None,
        "limit": 50,
        "offset": 0,
    }
    assert response.total == 1
    assert response.items[0].label == "Editor preference"
    with pytest.raises(ValidationError):
        ListMemoriesParams(limit=201)
    with pytest.raises(ValidationError):
        ListMemoriesParams(limit=0)
    with pytest.raises(ValidationError):
        ListMemoriesParams(offset=-1)


def test_contract_models_reject_unspecified_fields() -> None:
    """SPEC C.4 is defended by verifying that contract models reject unspecified fields; this
    prevents drift in the typed Harness-Spine client contract.
    """
    raw = deepcopy(memory_unit_payload())
    raw["embedding"] = [0.0]

    with pytest.raises(ValidationError):
        MemoryUnit.model_validate(raw)


def test_search_default_is_literal_c4_value() -> None:
    """SPEC C.4 is defended by verifying that search default is literal c4 value; this prevents
    drift in the typed Harness-Spine client contract.
    """
    request = SearchRequest(principal_id="principal-1", query="tabs")

    assert request.k == 10
    assert SearchRequest(principal_id="principal-1", query="tabs", k=1).k == 1
    assert SearchRequest(principal_id="principal-1", query="tabs", k=50).k == 50
    for invalid in (0, 51, True):
        with pytest.raises(ValidationError):
            SearchRequest(principal_id="principal-1", query="tabs", k=invalid)


def test_prepare_requires_positive_model_context() -> None:
    """SPEC C.4 is defended by verifying that prepare requires positive model context; this
    prevents drift in the typed Harness-Spine client contract.
    """
    for invalid in (0, -1):
        with pytest.raises(ValidationError):
            InjectPrepareRequest(
                thread_id="12345678-1234-5678-1234-567812345678",
                agent_id="agent-1",
                machine_id="machine-1",
                principal_id="principal-1",
                prompt="hello",
                model_context_tokens=invalid,
            )
