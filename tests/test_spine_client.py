import inspect
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflict,
    CreateMemoryRequest,
    DuplicateMemoryConflict,
    InjectCommitResponse,
    InjectPrepareRequest,
    InjectPrepareResponse,
    LabelConflict,
    ListMemoriesParams,
    MemoryCard,
    MemoryKind,
    MemoryUnit,
    PagedMemoryListResponse,
    PatchMemoryConflict,
    PatchMemoryRequest,
    PatchMemoryResponse,
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
        "create_memory",
        "patch_memory",
        "list_memories",
        "search",
        "record_spend_events",
        "vitals_snapshot",
    }


def test_prepare_request_mirrors_named_c4_fields() -> None:
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
    response = InjectPrepareResponse(
        injection_id="22345678-1234-5678-1234-567812345678",
        snapshot_ts="2026-07-17T12:00:00Z",
        scorer_version="v0",
        injected=[scored_card_payload()],
        near_misses=[],
        final_block=None,
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
        )


def test_commit_response_includes_current_wrong_units() -> None:
    response = InjectCommitResponse(
        final_block="<memory_system></memory_system>",
        wrong_removed=[memory_unit_payload()],
    )

    assert response.wrong_removed[0].revision == 1


def test_create_request_has_machine_id_and_similar_band_force() -> None:
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
    created = CreatedMemoryResponse(created=memory_unit_payload())
    similar = SimilarMemoriesResponse(created=None, similar=[similarity_card_payload()])

    assert created.created.memory_id == similar.similar[0].memory_id
    assert similar.similar[0].features is None


def test_create_conflicts_cover_duplicate_and_active_label() -> None:
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
    raw = deepcopy(memory_unit_payload())
    raw["embedding"] = [0.0]

    with pytest.raises(ValidationError):
        MemoryUnit.model_validate(raw)


def test_search_default_is_literal_c4_value() -> None:
    request = SearchRequest(principal_id="principal-1", query="tabs")

    assert request.k == 10
    assert SearchRequest(principal_id="principal-1", query="tabs", k=1).k == 1
    assert SearchRequest(principal_id="principal-1", query="tabs", k=50).k == 50
    for invalid in (0, 51, True):
        with pytest.raises(ValidationError):
            SearchRequest(principal_id="principal-1", query="tabs", k=invalid)


def test_prepare_requires_positive_model_context() -> None:
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
