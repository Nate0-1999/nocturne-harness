"""S1-S2 contract assertions against a live Spine and pgvector database."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from harness.envelope import StopReason, generate_ulid
from harness.memory_gate import MemoryGateTurnRunner
from harness.memory_panel import ThreadMemoryContextRegistry
from harness.run_protocol import TurnOutcome
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryConflictError,
    CreateMemoryRequest,
    DuplicateMemoryConflict,
    LabelConflict,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RevisionConflict,
    SimilarMemoriesResponse,
    SpendEvent,
    SpendEventsRequest,
    SpineClient,
    SpineProblemError,
)
from harness.tools_memory import MemoryToolContext

pytestmark = [pytest.mark.contract, pytest.mark.asyncio]

HARD_SOURCE = "A contract test must reject an exact duplicate memory body."
HARD_CANDIDATE = HARD_SOURCE
SIMILAR_SOURCE = (
    "The Palace stores durable memories for the owner and retrieves them when relevant."
)
SIMILAR_CANDIDATE = (
    "The Palace keeps persistent memories for its owner and finds the useful records later."
)
CAS_ORIGINAL = "H2 CAS original"
CAS_PATCHED = "H2 CAS patched"
RUN_FACT = "The contract lighthouse lamp is amber."
RUN_PROMPT = "What colour is the contract lighthouse lamp?"


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required for live Spine contract tests")
    return value


@pytest_asyncio.fixture
async def spine_client():
    async with SpineClient(
        _required_environment("SPINE_URL"),
        _required_environment("SPINE_TOKEN"),
    ) as client:
        yield client


@pytest.fixture(scope="session")
def expected_embedding_model() -> str:
    """Return the model identity the selected live environment must report."""

    return _required_environment("SPINE_EXPECTED_EMBEDDING_MODEL")


def _create_request(
    *,
    principal_id: str,
    label: str,
    body: str,
    project_key: str,
    force: bool = False,
) -> CreateMemoryRequest:
    return CreateMemoryRequest(
        principal_id=principal_id,
        label=label,
        body=body,
        kind=MemoryKind.FACT,
        keywords=["h2", "contract"],
        project_key=project_key,
        thread_origin="h2-live-contract",
        origin_thread_id=uuid4(),
        origin_path="tests/contract",
        editor="user",
        machine_id="h2-contract-runner",
        force=force,
    )


async def test_live_create_conflicts_and_dedup_bands(
    spine_client: SpineClient,
    expected_embedding_model: str,
) -> None:
    """SPEC C.4 and SPEC B.6 rules 10 and 12 require strict live create, dedup, and
    provider evidence; this prevents a fixture-only expectation from rejecting the real broker.
    """
    run_id = uuid4().hex
    project_key = f"h2-{run_id}"

    hard_principal = f"hard-{run_id}"
    hard_source = await spine_client.create_memory(
        _create_request(
            principal_id=hard_principal,
            label=f"Hard source {run_id}",
            body=HARD_SOURCE,
            project_key=project_key,
        )
    )
    assert isinstance(hard_source, CreatedMemoryResponse)
    assert hard_source.created.embedding_model == expected_embedding_model
    assert hard_source.created.origin_path == "tests/contract"
    assert hard_source.created.origin_thread_id is not None

    with pytest.raises(CreateMemoryConflictError) as label_error:
        await spine_client.create_memory(
            _create_request(
                principal_id=hard_principal,
                label=hard_source.created.label,
                body=SIMILAR_SOURCE,
                project_key=project_key,
            )
        )
    assert label_error.value.response.status_code == 409
    assert isinstance(label_error.value.conflict, LabelConflict)
    assert label_error.value.conflict.label_conflict.memory_id == hard_source.created.memory_id

    with pytest.raises(CreateMemoryConflictError) as duplicate_error:
        await spine_client.create_memory(
            _create_request(
                principal_id=hard_principal,
                label=hard_source.created.label,
                body=HARD_CANDIDATE,
                project_key=project_key,
                force=True,
            )
        )
    assert duplicate_error.value.response.status_code == 409
    assert isinstance(duplicate_error.value.conflict, DuplicateMemoryConflict)
    duplicate = duplicate_error.value.conflict.duplicate_of
    assert duplicate.memory_id == hard_source.created.memory_id
    assert 0.92 <= duplicate.score <= 1.0
    assert duplicate.features is None
    assert duplicate.rank is None

    similar_principal = f"similar-{run_id}"
    similar_source = await spine_client.create_memory(
        _create_request(
            principal_id=similar_principal,
            label=f"Similar source {run_id}",
            body=SIMILAR_SOURCE,
            project_key=project_key,
        )
    )
    assert isinstance(similar_source, CreatedMemoryResponse)

    candidate_request = _create_request(
        principal_id=similar_principal,
        label=f"Similar candidate {run_id}",
        body=SIMILAR_CANDIDATE,
        project_key=project_key,
    )
    similar = await spine_client.create_memory(candidate_request)
    assert isinstance(similar, SimilarMemoriesResponse)
    assert similar.created is None
    assert len(similar.similar) == 1
    assert similar.similar[0].memory_id == similar_source.created.memory_id
    assert 0.80 <= similar.similar[0].score < 0.92
    assert similar.similar[0].features is None
    assert similar.similar[0].rank is None

    forced = await spine_client.create_memory(candidate_request.model_copy(update={"force": True}))
    assert isinstance(forced, CreatedMemoryResponse)
    assert forced.created.label == candidate_request.label


async def test_live_patch_cas_tombstone_and_list(
    spine_client: SpineClient,
    expected_embedding_model: str,
) -> None:
    """SPEC C.4 and SPEC B.6 rules 10 and 12 require strict live patch, CAS, and
    provider evidence; this prevents a fixture-only expectation from rejecting the real broker.
    """
    run_id = uuid4().hex
    principal_id = f"cas-{run_id}"
    project_key = f"h2-{run_id}"
    label = f"CAS memory {run_id}"

    created_response = await spine_client.create_memory(
        _create_request(
            principal_id=principal_id,
            label=label,
            body=CAS_ORIGINAL,
            project_key=project_key,
        )
    )
    assert isinstance(created_response, CreatedMemoryResponse)
    created = created_response.created
    assert created.revision == 1

    patched = await spine_client.patch_memory(
        created.memory_id,
        PatchMemoryRequest(
            expected_revision=1,
            body=CAS_PATCHED,
            origin_path="tests/contract/patched",
            editor="user",
            reason="exercise live CAS",
            machine_id="h2-contract-runner",
        ),
    )
    assert patched.memory_id == created.memory_id
    assert patched.body == CAS_PATCHED
    assert patched.origin_path == "tests/contract/patched"
    assert patched.embedding_model == expected_embedding_model
    assert patched.revision == 2

    with pytest.raises(PatchMemoryConflictError) as stale_error:
        await spine_client.patch_memory(
            created.memory_id,
            PatchMemoryRequest(
                expected_revision=1,
                label=f"Stale {run_id}",
                editor="user",
                reason="force stale conflict",
                machine_id="h2-contract-runner",
            ),
        )
    assert stale_error.value.response.status_code == 409
    assert isinstance(stale_error.value.conflict, RevisionConflict)
    assert stale_error.value.conflict.conflict.memory_id == created.memory_id
    assert stale_error.value.conflict.conflict.revision == 2
    assert stale_error.value.conflict.conflict.label == label

    tombstoned = await spine_client.patch_memory(
        created.memory_id,
        PatchMemoryRequest(
            expected_revision=2,
            status=MemoryStatus.TOMBSTONED,
            editor="user",
            reason="prove tombstone is not delete",
            machine_id="h2-contract-runner",
        ),
    )
    assert tombstoned.status is MemoryStatus.TOMBSTONED
    assert tombstoned.revision == 3

    replacement = await spine_client.create_memory(
        _create_request(
            principal_id=principal_id,
            label=label,
            body=CAS_PATCHED,
            project_key=project_key,
        )
    )
    assert isinstance(replacement, CreatedMemoryResponse)
    assert replacement.created.memory_id != tombstoned.memory_id
    assert replacement.created.revision == 1

    active = await spine_client.list_memories(
        ListMemoriesParams(
            project_key=project_key,
            status=MemoryStatus.ACTIVE,
            q=label.upper(),
            limit=1,
            offset=0,
        )
    )
    assert active.total == 1
    assert active.limit == 1
    assert active.offset == 0
    assert [unit.memory_id for unit in active.items] == [replacement.created.memory_id]

    historical = await spine_client.list_memories(
        ListMemoriesParams(
            project_key=project_key,
            status=MemoryStatus.TOMBSTONED,
            q=label,
            limit=1,
            offset=0,
        )
    )
    assert historical.total == 1
    assert [unit.memory_id for unit in historical.items] == [tombstoned.memory_id]


async def test_live_spend_receipt_is_atomic_and_idempotent(spine_client: SpineClient) -> None:
    """SPEC C.4 is defended by verifying that live spend receipt is atomic and idempotent; this
    prevents drift in the live Harness-Spine contract.
    """
    event = SpendEvent(
        event_uid="01K1M2A0000000000000000001",
        ts=datetime(2026, 8, 1, 12, tzinfo=UTC),
        product_type="llm.request",
        quantity_type="output",
        unit_of_measure="tokens",
        quantity=10,
        cost_usd="0.0001",
        basis="measured",
        behavior="variable",
        purpose="building",
        principal_id="contract-owner",
        machine_id="contract-machine",
        origin_agent="contract-agent",
        ref="contract-generation-1",
    )
    request = SpendEventsRequest(events=[event])

    first = await spine_client.record_spend_events(request)
    replay = await spine_client.record_spend_events(request)

    assert first.accepted == replay.accepted == 1
    with pytest.raises(SpineProblemError) as conflict:
        await spine_client.record_spend_events(
            SpendEventsRequest(events=[event.model_copy(update={"quantity": Decimal(11)})])
        )
    assert conflict.value.status_code == 409


async def test_live_workflow_run_gets_its_memories_and_a_bare_mode_does_not(
    spine_client: SpineClient,
) -> None:
    """A-088 / F138: the real Palace gives a saved workflow's run its memories with no gate and
    no human lock, and still refuses the same call for a thread that is no run.
    """
    tag = uuid4().hex
    principal, machine, project_key = f"run-{tag}", f"run-machine-{tag}", f"run-{tag}"
    fact = await spine_client.create_memory(
        _create_request(
            principal_id=principal, label=f"Lamp {tag}", body=RUN_FACT, project_key=project_key
        )
    )
    assert isinstance(fact, CreatedMemoryResponse)
    blocks: list[str | None] = []

    class Delegate:
        async def run(self, *, message_history, dynamic_instructions, **_) -> TurnOutcome:
            await dynamic_instructions.render()
            blocks.append(dynamic_instructions.memory_block)
            return TurnOutcome(StopReason.END_TURN, tuple(message_history))

    async with SpineClient(
        _required_environment("SPINE_URL"),
        _required_environment("SPINE_TOKEN"),
        principal_id=principal,
    ) as client:
        job = await client.job_write(
            "PUT",
            f"v1/jobs/{generate_ulid()}",
            {
                "machine_id": machine,
                "definition": {
                    "name": f"Lamp {tag}",
                    "prompt": RUN_PROMPT,
                    "folder": "/tmp",
                    "model_policy": "elbow",
                    "budget_usd": "0.1",
                    "exit_condition": "true",
                },
                "expected_revision": 0,
            },
        )
        assert job["definition"]["memory_scope"] == "workspace"
        run = await client.job_write(
            "POST",
            f"v1/jobs/{job['job_id']}/runs",
            {
                "machine_id": machine,
                "run_id": generate_ulid(),
                "thread_id": str(uuid4()),
                "trigger_key": "manual",
                "expected_revision": job["revision"],
                "manual": True,
            },
        )

        def context(thread_id: str) -> MemoryToolContext:
            return MemoryToolContext(
                spine=client,
                principal_id=principal,
                machine_id=machine,
                agent_id="contract-agent",
                thread_id=UUID(thread_id),
                project_key=project_key,
            )

        contexts = ThreadMemoryContextRegistry()
        runner = MemoryGateTurnRunner(
            Delegate(), client, context, model_context_tokens=100_000, contexts=contexts
        )
        turn = {"prompt": RUN_PROMPT, "message_history": (), "emit": None}
        await runner.run_workflow(memory_scope="workspace", thread_id=run["thread_id"], **turn)
        assert len(blocks) == 1 and RUN_FACT in blocks[0]
        entered = contexts.snapshot(run["thread_id"])
        assert entered.member_ids == {fact.created.memory_id}
        assert entered.confirmed_memory_ids == frozenset()
        restored = await client.restore_injection(UUID(run["thread_id"]), principal)
        assert restored is not None and not restored.pending
        assert restored.confirmed_memory_ids == []

        with pytest.raises(SpineProblemError) as refused:
            await runner.run_workflow(memory_scope="workspace", thread_id=str(uuid4()), **turn)
        assert refused.value.status_code == 409
        assert len(blocks) == 1
