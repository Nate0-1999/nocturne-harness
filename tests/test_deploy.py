from __future__ import annotations

import copy
import io
import json
import stat
import subprocess
import sys
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

import harness.deploy as deploy_module
import harness.spine_client as spine_client_module
from harness.deploy import (
    ARTIFACT_HOST,
    BREAKER_BUILD_ACCOUNT,
    BREAKER_FUNCTION,
    BREAKER_RUNTIME_ACCOUNT,
    BREAKER_TOPIC,
    BREAKER_TRIGGER_ACCOUNT,
    CLOUD_RUN_SERVICE,
    DATABASE_NAME,
    DATABASE_URL_SECRET,
    DATABASE_USER,
    EMBED_BASE_URL,
    EMBED_MODEL,
    IMAGE_PACKAGE,
    OPENROUTER_SECRET,
    PROJECT_ID,
    REGION,
    RUNTIME_SERVICE_ACCOUNT_EMAIL,
    SPINE_TOKEN_SECRET,
    SQL_CONNECTION_NAME,
    SQL_INSTANCE,
    BreakerState,
    DeployBackend,
    DeployBlocked,
    DeployError,
    DeployIncomplete,
    DeployStage,
    DeployTarget,
    GcloudDeployBackend,
    HumanTerminalRequired,
    ObservedDeployment,
    PackagedDeploySource,
    PlanAction,
    PlanStep,
    ResourceState,
    TargetDiscoveryBlocked,
    build_plan,
    create_owner_cloud_backup,
    deploy,
    deploy_source_digest,
    invoke_packaged_breaker,
    local_image_build_argv,
    packaged_spine_source,
)

TARGET = DeployTarget(
    "ABCDEF-123456-789ABC",
    "billingAccounts/ABCDEF-123456-789ABC/budgets/nocturne-100",
)

STAGE_FIELDS = {
    DeployStage.SQL_PROTECTION: "sql_protection",
    DeployStage.DATABASE: "database",
    DeployStage.DATABASE_USER: "database_user",
    DeployStage.MIGRATIONS: "migrations",
    DeployStage.DATABASE_URL_SECRET: "database_url_secret",
    DeployStage.SPINE_TOKEN_SECRET: "spine_token_secret",
    DeployStage.OPENROUTER_SECRET: "openrouter_secret",
    DeployStage.RUNTIME_IDENTITY: "runtime_identity",
    DeployStage.RUNTIME_CLOUDSQL_IAM: "runtime_cloudsql_iam",
    DeployStage.RUNTIME_DATABASE_SECRET_IAM: "runtime_database_secret_iam",
    DeployStage.RUNTIME_TOKEN_SECRET_IAM: "runtime_token_secret_iam",
    DeployStage.RUNTIME_OPENROUTER_SECRET_IAM: "runtime_openrouter_secret_iam",
    DeployStage.ARTIFACT_REPOSITORY: "artifact_repository",
    DeployStage.SPINE_IMAGE: "spine_image",
    DeployStage.CLOUD_RUN_SERVICE: "cloud_run_service",
    DeployStage.REMOTE_VERIFICATION: "remote_verification",
}


def observed(**updates: object) -> ObservedDeployment:
    values: dict[str, object] = {
        "project_active": True,
        "billing_enabled": True,
        "sql_foundation": ResourceState.EXACT,
        **{field: ResourceState.EXACT for field in STAGE_FIELDS.values()},
        "breaker": BreakerState.ARMED,
    }
    values.update(updates)
    return ObservedDeployment(**values)  # type: ignore[arg-type]


def absent_managed(*, breaker: BreakerState = BreakerState.ARMED) -> ObservedDeployment:
    return observed(
        **{field: ResourceState.ABSENT for field in STAGE_FIELDS.values()},
        breaker=breaker,
    )


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_remote_verifier_uses_distinct_label_for_duplicate_probe_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC C.4 requires the duplicate probe to pass label checks and clean up."""

    memory_id = UUID("12345678-1234-5678-1234-567812345678")
    injection_id = UUID("22345678-1234-5678-1234-567812345678")
    requests: list[spine_client_module.CreateMemoryRequest] = []
    cleaned: list[UUID] = []

    class FakeSpineClient:
        def __init__(self, base_url: str, token: str, *, timeout: float) -> None:
            assert (base_url, token, timeout) == ("https://spine.invalid", "token", 45.0)

        async def __aenter__(self) -> FakeSpineClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def create_memory(self, request: spine_client_module.CreateMemoryRequest) -> object:
            requests.append(request)
            if len(requests) == 1:
                return SimpleNamespace(created=SimpleNamespace(memory_id=memory_id))

            source = requests[0]
            response = httpx.Response(409)
            if request.label == source.label:
                conflict: spine_client_module.CreateMemoryConflict = (
                    spine_client_module.LabelConflict(
                        label_conflict=spine_client_module.LabelConflictTarget(
                            memory_id=memory_id,
                            label=source.label,
                        )
                    )
                )
            else:
                assert request.principal_id == source.principal_id
                assert request.body == source.body
                conflict = spine_client_module.DuplicateMemoryConflict(
                    duplicate_of=spine_client_module.SimilarityMemoryCard(
                        memory_id=memory_id,
                        label=source.label,
                        body=source.body,
                        kind=source.kind,
                        pin=False,
                        score=1.0,
                        features=None,
                        rank=None,
                    )
                )
            raise spine_client_module.CreateMemoryConflictError(response, conflict)

        async def prepare_injection(self, request: object) -> object:
            return SimpleNamespace(
                injection_id=injection_id,
                injected=[SimpleNamespace(memory_id=memory_id)],
            )

        async def commit_injection(self, request: object) -> object:
            return SimpleNamespace(final_block="<memory_system>verified</memory_system>")

        async def list_memories(self, params: object) -> object:
            return SimpleNamespace(items=[SimpleNamespace(memory_id=memory_id, revision=1)])

        async def patch_memory(self, target: UUID, request: object) -> object:
            assert target == memory_id
            assert request.status is spine_client_module.MemoryStatus.TOMBSTONED
            cleaned.append(target)
            return SimpleNamespace(status=spine_client_module.MemoryStatus.TOMBSTONED)

    class FakeVitalsClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 45.0

        async def __aenter__(self) -> FakeVitalsClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
            assert url == "https://spine.invalid/v1/vitals"
            assert headers == {"Authorization": "Bearer token"}
            return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(spine_client_module, "SpineClient", FakeSpineClient)
    monkeypatch.setattr(
        deploy_module,
        "httpx",
        SimpleNamespace(AsyncClient=FakeVitalsClient),
    )

    await deploy_module._verify_remote_spine_async("https://spine.invalid", "token")

    assert len(requests) == 2
    source, duplicate = requests
    assert duplicate.label != source.label
    assert 0 < len(duplicate.label) <= 64
    assert duplicate.principal_id == source.principal_id
    assert duplicate.body == source.body
    assert cleaned == [memory_id]


class FakeBackend(DeployBackend):
    def __init__(self, state: ObservedDeployment) -> None:
        self.state = state
        self.observations = 0
        self.executed: list[tuple[PlanStep, Path | None]] = []
        self.armed: list[Path] = []
        self.alignments = 0
        self.attempts = 0
        self.attempt_active = False
        self.events: list[str] = []
        self.credentials_managed = True

    def observe(self, target: DeployTarget) -> ObservedDeployment:
        assert target == TARGET
        self.observations += 1
        return self.state

    def execute(
        self,
        step: PlanStep,
        *,
        target: DeployTarget,
        source_dir: Path | None,
    ) -> None:
        assert target == TARGET
        self.executed.append((step, source_dir))
        self.events.append(str(step.stage))
        self.state = replace(self.state, **{STAGE_FIELDS[step.stage]: ResourceState.EXACT})

    def begin_mutation_attempt(self) -> Path:
        if not self.attempt_active:
            self.attempts += 1
            self.attempt_active = True
            self.events.append("backup_receipt")
        return Path("/private/verified-backup.json")

    def align_owner_cloud_credentials_once(self) -> Path:
        self.alignments += 1
        self.begin_mutation_attempt()
        self.events.append("credential_alignment")
        self.credentials_managed = True
        self.state = replace(self.state, migrations=ResourceState.UPDATABLE)
        return Path("/private/verified-backup.json")

    def owner_credentials_managed(self) -> bool:
        return self.credentials_managed

    def arm_breaker(
        self,
        *,
        target: DeployTarget,
        source_dir: Path,
        stdin: io.TextIOBase,
        stdout: io.TextIOBase,
    ) -> None:
        assert target == TARGET
        assert stdin.isatty() and stdout.isatty()
        self.armed.append(source_dir)
        self.state = replace(self.state, breaker=BreakerState.ARMED)


TOPIC_RESOURCE = f"projects/{PROJECT_ID}/topics/{BREAKER_TOPIC}"
FUNCTION_RESOURCE = f"projects/{PROJECT_ID}/locations/{REGION}/functions/{BREAKER_FUNCTION}"
RUN_SERVICE_RESOURCE = f"projects/{PROJECT_ID}/locations/{REGION}/services/{BREAKER_FUNCTION}"
TRIGGER_RESOURCE = f"projects/{PROJECT_ID}/locations/{REGION}/triggers/{BREAKER_FUNCTION}-fixture"
SUBSCRIPTION_RESOURCE = f"projects/{PROJECT_ID}/subscriptions/eventarc-fixture"
RUNTIME_ACCOUNT = f"{BREAKER_RUNTIME_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
TRIGGER_ACCOUNT = f"{BREAKER_TRIGGER_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
BUILD_ACCOUNT = f"{BREAKER_BUILD_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"


def exact_breaker_fixture() -> dict[str, object]:
    runtime_member = f"serviceAccount:{RUNTIME_ACCOUNT}"
    trigger_member = f"serviceAccount:{TRIGGER_ACCOUNT}"
    accounts = (RUNTIME_ACCOUNT, TRIGGER_ACCOUNT, BUILD_ACCOUNT)
    return {
        "topics": [{"name": TOPIC_RESOURCE}],
        "functions": [{"name": FUNCTION_RESOURCE}],
        "triggers": [{"name": TRIGGER_RESOURCE}],
        "budget": {
            "name": TARGET.budget_resource,
            "ownershipScope": "BILLING_ACCOUNT",
            "amount": {
                "specifiedAmount": {
                    "currencyCode": "USD",
                    "units": "100",
                    "nanos": "0",
                }
            },
            "budgetFilter": {
                "projects": ["projects/123456789"],
                "calendarPeriod": "MONTH",
                "creditTypesTreatment": "INCLUDE_ALL_CREDITS",
            },
            "notificationsRule": {
                "pubsubTopic": TOPIC_RESOURCE,
                "schemaVersion": "1.0",
            },
        },
        "function": {
            "name": FUNCTION_RESOURCE,
            "environment": "GEN_2",
            "state": "ACTIVE",
            "serviceConfig": {
                "serviceAccountEmail": RUNTIME_ACCOUNT,
                "maxInstanceCount": 1,
                "minInstanceCount": 0,
                "environmentVariables": {
                    "EXPECTED_BILLING_ACCOUNT_ID": TARGET.billing_account_id,
                    "EXPECTED_BUDGET_ID": "nocturne-100",
                },
            },
            "buildConfig": {
                "serviceAccount": f"projects/{PROJECT_ID}/serviceAccounts/{BUILD_ACCOUNT}",
                "runtime": "python312",
                "entryPoint": "stop_billing",
            },
            "eventTrigger": {
                "eventType": "google.cloud.pubsub.topic.v1.messagePublished",
                "pubsubTopic": TOPIC_RESOURCE,
                "retryPolicy": "RETRY_POLICY_DO_NOT_RETRY",
                "serviceAccountEmail": TRIGGER_ACCOUNT,
                "triggerRegion": REGION,
                "trigger": TRIGGER_RESOURCE,
            },
        },
        "topic_description": {"name": TOPIC_RESOURCE, "messageTransforms": []},
        "attached_subscriptions": [SUBSCRIPTION_RESOURCE],
        "subscription_description": {
            "name": SUBSCRIPTION_RESOURCE,
            "topic": TOPIC_RESOURCE,
            "messageTransforms": [],
        },
        "subscription_policy": {"bindings": []},
        "trigger_description": {
            "name": TRIGGER_RESOURCE,
            "eventFilters": {
                "type": "google.cloud.pubsub.topic.v1.messagePublished",
            },
            "serviceAccount": TRIGGER_ACCOUNT,
            "transport": {
                "pubsub": {
                    "topic": TOPIC_RESOURCE,
                    "subscription": SUBSCRIPTION_RESOURCE,
                }
            },
            "destination": {
                "cloudRun": {
                    "service": BREAKER_FUNCTION,
                    "region": REGION,
                }
            },
            "conditions": {"transport": {"code": "OK", "message": ""}},
        },
        "topic_policy": {
            "bindings": [
                {
                    "role": "roles/pubsub.publisher",
                    "members": ["serviceAccount:billing-budget-alert@system.gserviceaccount.com"],
                }
            ]
        },
        "run_policy": {"bindings": [{"role": "roles/run.invoker", "members": [trigger_member]}]},
        "billing_policy": {"bindings": []},
        "service_accounts": [{"email": account} for account in accounts],
        "run_services": [{"metadata": {"name": RUN_SERVICE_RESOURCE}}],
        "project_policy": {
            "bindings": [
                {
                    "role": "roles/billing.projectManager",
                    "members": [runtime_member],
                }
            ]
        },
        "user_keys": {account: [] for account in accounts},
        "account_policies": {account: {"bindings": []} for account in accounts},
        "roles": {
            "roles/billing.projectManager": {
                "name": "roles/billing.projectManager",
                "deleted": False,
                "includedPermissions": [
                    "resourcemanager.projects.createBillingAssignment",
                    "resourcemanager.projects.deleteBillingAssignment",
                ],
            }
        },
    }


class BreakerFixtureBackend(GcloudDeployBackend):
    def __init__(self, fixture: dict[str, object]) -> None:
        super().__init__(image_tag="0.1.0", openrouter_key="fixture")
        self.fixture = fixture
        self._active_account = "owner@example.com"

    def _json_document(self, argv: Sequence[str]) -> object:
        command = tuple(argv)
        key: str
        if command[:4] == ("gcloud", "pubsub", "topics", "list"):
            key = "topics"
        elif command[:4] == ("gcloud", "functions", "list", "--v2"):
            key = "functions"
        elif command[:4] == ("gcloud", "eventarc", "triggers", "list"):
            key = "triggers"
        elif command[:4] == ("gcloud", "billing", "budgets", "describe"):
            key = "budget"
        elif command[:3] == ("gcloud", "functions", "describe"):
            key = "function"
        elif command[:4] == ("gcloud", "pubsub", "topics", "describe"):
            key = "topic_description"
        elif command[:4] == ("gcloud", "pubsub", "topics", "list-subscriptions"):
            key = "attached_subscriptions"
        elif command[:4] == ("gcloud", "pubsub", "topics", "get-iam-policy"):
            key = "topic_policy"
        elif command[:4] == ("gcloud", "run", "services", "get-iam-policy"):
            key = "run_policy"
        elif command[:4] == ("gcloud", "billing", "accounts", "get-iam-policy"):
            key = "billing_policy"
        elif command[:4] == ("gcloud", "pubsub", "subscriptions", "describe"):
            key = "subscription_description"
        elif command[:4] == (
            "gcloud",
            "pubsub",
            "subscriptions",
            "get-iam-policy",
        ):
            key = "subscription_policy"
        elif command[:4] == ("gcloud", "eventarc", "triggers", "describe"):
            key = "trigger_description"
        elif command[:5] == ("gcloud", "iam", "service-accounts", "keys", "list"):
            account = next(
                value.split("=", 1)[1] for value in command if value.startswith("--iam-account=")
            )
            return copy.deepcopy(self.fixture["user_keys"])[account]  # type: ignore[index]
        elif command[:4] == ("gcloud", "iam", "service-accounts", "get-iam-policy"):
            return copy.deepcopy(self.fixture["account_policies"])[command[4]]  # type: ignore[index]
        elif command[:4] == ("gcloud", "iam", "roles", "describe"):
            role = command[4] if command[4].startswith("roles/") else command[4]
            return copy.deepcopy(self.fixture["roles"])[role]  # type: ignore[index]
        else:
            raise AssertionError(f"unexpected fixture command: {command!r}")
        return copy.deepcopy(self.fixture[key])


def breaker_state(fixture: dict[str, object]) -> BreakerState:
    backend = BreakerFixtureBackend(fixture)
    return backend._breaker_state(
        target=TARGET,
        project_number="123456789",
        service_accounts=fixture["service_accounts"],  # type: ignore[arg-type]
        run_services=fixture["run_services"],  # type: ignore[arg-type]
        project_policy=fixture["project_policy"],  # type: ignore[arg-type]
    )


def mutate_fixture(path: tuple[str | int, ...], value: object) -> dict[str, object]:
    fixture = exact_breaker_fixture()
    current: object = fixture
    for component in path[:-1]:
        current = current[component]  # type: ignore[index]
    current[path[-1]] = copy.deepcopy(value)  # type: ignore[index]
    return fixture


def source_provider(
    root: Path, calls: list[PackagedDeploySource]
) -> Iterator[PackagedDeploySource]:
    app = root / "app"
    breaker = root / "breaker"
    app.mkdir(parents=True, exist_ok=True)
    breaker.mkdir(parents=True, exist_ok=True)
    source = PackagedDeploySource(app=app, breaker=breaker)
    calls.append(source)
    yield source


def test_exact_armed_plan_is_all_noop() -> None:
    """ADR-019 is defended by verifying that exact armed plan is all noop; this prevents drift
    in the fixed-project deploy and drift-safety contract.
    """
    plan = build_plan(observed())

    assert len(plan.steps) == 20
    assert not plan.blocked
    assert plan.mutations == ()
    assert {step.action for step in plan.steps} == {PlanAction.NOOP}


def test_lawful_absent_managed_states_have_only_create_or_forward_update() -> None:
    """ADR-019 is defended by verifying that lawful absent managed states have only create or
    forward update; this prevents drift in the fixed-project deploy and drift-safety
    contract.
    """
    plan = build_plan(absent_managed())
    expected_updates = {
        DeployStage.SQL_PROTECTION,
        DeployStage.MIGRATIONS,
        DeployStage.RUNTIME_CLOUDSQL_IAM,
        DeployStage.RUNTIME_DATABASE_SECRET_IAM,
        DeployStage.RUNTIME_TOKEN_SECRET_IAM,
        DeployStage.RUNTIME_OPENROUTER_SECRET_IAM,
        DeployStage.REMOTE_VERIFICATION,
    }

    assert not plan.blocked
    for stage in STAGE_FIELDS:
        expected = PlanAction.UPDATE if stage in expected_updates else PlanAction.CREATE
        assert plan.step(stage).action is expected
    assert plan.step(DeployStage.BILLING_BREAKER).action is PlanAction.NOOP


@pytest.mark.parametrize(
    ("field", "stage"),
    [(field, stage) for stage, field in STAGE_FIELDS.items()],
)
def test_every_managed_drift_blocks(field: str, stage: DeployStage) -> None:
    """ADR-019 is defended by verifying that every managed drift blocks; this prevents drift in
    the fixed-project deploy and drift-safety contract.
    """
    plan = build_plan(observed(**{field: ResourceState.DRIFTED}))

    assert plan.blocked
    assert plan.step(stage).action is PlanAction.BLOCKED


def test_deploy_blocks_a_schema_revision_outside_the_packaged_forward_graph() -> None:
    """SPEC D.2 099 and B.6 rule 12 keep deploy from treating reverse skew as an update."""

    migration = build_plan(observed(migrations=ResourceState.DRIFTED)).step(DeployStage.MIGRATIONS)

    assert migration.action is PlanAction.BLOCKED
    assert "incompatible" in migration.detail


@pytest.mark.parametrize(
    ("updates", "foundation_stage"),
    [
        ({"project_active": False}, DeployStage.PROJECT),
        ({"billing_enabled": False}, DeployStage.BILLING),
        ({"sql_foundation": ResourceState.ABSENT}, DeployStage.SQL_FOUNDATION),
        ({"sql_foundation": ResourceState.UPDATABLE}, DeployStage.SQL_FOUNDATION),
        ({"sql_foundation": ResourceState.DRIFTED}, DeployStage.SQL_FOUNDATION),
    ],
)
def test_every_foundation_failure_blocks_all_managed_steps(
    updates: dict[str, object], foundation_stage: DeployStage
) -> None:
    """ADR-019 is defended by verifying that every foundation failure blocks all managed steps;
    this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    plan = build_plan(observed(**updates))

    assert plan.step(foundation_stage).action is PlanAction.BLOCKED
    assert all(plan.step(stage).action is PlanAction.BLOCKED for stage in STAGE_FIELDS)


@pytest.mark.parametrize(
    ("field", "stage"),
    [
        ("database", DeployStage.DATABASE),
        ("database_user", DeployStage.DATABASE_USER),
        ("database_url_secret", DeployStage.DATABASE_URL_SECRET),
        ("spine_token_secret", DeployStage.SPINE_TOKEN_SECRET),
        ("openrouter_secret", DeployStage.OPENROUTER_SECRET),
        ("runtime_identity", DeployStage.RUNTIME_IDENTITY),
        ("spine_image", DeployStage.SPINE_IMAGE),
    ],
)
def test_non_updatable_resources_block_an_update(field: str, stage: DeployStage) -> None:
    """ADR-019 is defended by verifying that non updatable resources block an update; this
    prevents drift in the fixed-project deploy and drift-safety contract.
    """
    plan = build_plan(observed(**{field: ResourceState.UPDATABLE}))

    assert plan.step(stage).action is PlanAction.BLOCKED


@pytest.mark.parametrize(
    "updates",
    [
        {"database": ResourceState.ABSENT},
        {"database_user": ResourceState.ABSENT},
        {"database_url_secret": ResourceState.ABSENT},
    ],
)
def test_database_user_and_url_secret_partial_topologies_block(
    updates: dict[str, object],
) -> None:
    """ADR-019 is defended by verifying that database user and url secret partial topologies
    block; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    plan = build_plan(observed(**updates))

    assert plan.blocked
    assert plan.step(DeployStage.DATABASE).action is PlanAction.BLOCKED
    assert plan.step(DeployStage.DATABASE_USER).action is PlanAction.BLOCKED


def test_dry_run_only_observes_and_never_materializes_or_mutates() -> None:
    """ADR-019 is defended by verifying that dry run only observes and never materializes or
    mutates; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = FakeBackend(absent_managed(breaker=BreakerState.ABSENT))

    def forbidden_source() -> Iterator[PackagedDeploySource]:
        raise AssertionError("dry-run materialized packaged source")
        yield  # pragma: no cover

    output = io.StringIO()
    plan = deploy(
        backend,
        TARGET,
        dry_run=True,
        stdin=io.StringIO(),
        stdout=output,
        source_provider=contextmanager(forbidden_source),
    )

    assert backend.observations == 1
    assert backend.executed == []
    assert backend.armed == []
    assert plan.mutations
    assert output.getvalue() == f"{plan.render()}\n"


def test_apply_offers_inline_alignment_and_continues_the_same_plan(tmp_path: Path) -> None:
    """SPEC D.2 098 puts local source and image work before credential alignment."""

    backend = FakeBackend(
        observed(
            migrations=ResourceState.UNOBSERVED,
            spine_image=ResourceState.ABSENT,
            cloud_run_service=ResourceState.UPDATABLE,
            remote_verification=ResourceState.UPDATABLE,
        )
    )
    backend.credentials_managed = False

    @contextmanager
    def source() -> Iterator[PackagedDeploySource]:
        backend.events.append("source_materialized")
        yield PackagedDeploySource(tmp_path / "app", tmp_path / "breaker")

    output = io.StringIO()
    deploy(
        backend,
        TARGET,
        dry_run=False,
        stdin=io.StringIO("y\n"),
        stdout=output,
        source_provider=source,
    )

    assert backend.alignments == 1
    assert backend.attempts == 1
    assert backend.events == [
        "source_materialized",
        "backup_receipt",
        "spine_image",
        "credential_alignment",
        "cloud_run_service",
        "migrations",
        "remote_verification",
    ]
    assert [step.stage for step, _ in backend.executed] == [
        DeployStage.SPINE_IMAGE,
        DeployStage.CLOUD_RUN_SERVICE,
        DeployStage.MIGRATIONS,
        DeployStage.REMOTE_VERIFICATION,
    ]
    assert "Back up and align it now?" in output.getvalue()


def test_verification_only_apply_takes_no_infrastructure_receipt() -> None:
    """SPEC D.2 098 keeps remote verification outside the infrastructure grant boundary."""

    backend = FakeBackend(observed(remote_verification=ResourceState.UPDATABLE))

    deploy(
        backend,
        TARGET,
        dry_run=False,
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )

    assert backend.attempts == 0
    assert backend.events == ["remote_verification"]
    assert [step.stage for step, _ in backend.executed] == [DeployStage.REMOTE_VERIFICATION]


def test_secret_only_apply_takes_an_infrastructure_receipt() -> None:
    """SPEC D.2 096/098 receipts every infrastructure mutation, not only owner rollouts."""

    backend = FakeBackend(observed(openrouter_secret=ResourceState.ABSENT))

    deploy(
        backend,
        TARGET,
        dry_run=False,
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )

    assert backend.attempts == 1
    assert backend.events == ["backup_receipt", "openrouter_secret"]


def test_alignment_materializes_source_before_receipt_when_image_is_exact(
    tmp_path: Path,
) -> None:
    """SPEC D.2 098 moves every locally fallible source check ahead of alignment mutation."""

    backend = FakeBackend(observed(migrations=ResourceState.UNOBSERVED))
    backend.credentials_managed = False

    @contextmanager
    def source() -> Iterator[PackagedDeploySource]:
        backend.events.append("source_materialized")
        yield PackagedDeploySource(tmp_path / "app", tmp_path / "breaker")

    deploy(
        backend,
        TARGET,
        dry_run=False,
        stdin=io.StringIO("y\n"),
        stdout=io.StringIO(),
        source_provider=source,
    )

    assert backend.events == [
        "source_materialized",
        "backup_receipt",
        "credential_alignment",
        "migrations",
    ]


def test_alignment_stops_when_pushed_image_does_not_converge(tmp_path: Path) -> None:
    """SPEC D.2 098 proves the image exact before the first service-affecting mutation."""

    class NonConvergingImageBackend(FakeBackend):
        def execute(
            self,
            step: PlanStep,
            *,
            target: DeployTarget,
            source_dir: Path | None,
        ) -> None:
            super().execute(step, target=target, source_dir=source_dir)
            if step.stage is DeployStage.SPINE_IMAGE:
                self.state = replace(self.state, spine_image=ResourceState.ABSENT)

    backend = NonConvergingImageBackend(
        observed(
            migrations=ResourceState.UNOBSERVED,
            spine_image=ResourceState.ABSENT,
            cloud_run_service=ResourceState.UPDATABLE,
            remote_verification=ResourceState.UPDATABLE,
        )
    )
    backend.credentials_managed = False

    @contextmanager
    def source() -> Iterator[PackagedDeploySource]:
        backend.events.append("source_materialized")
        yield PackagedDeploySource(tmp_path / "app", tmp_path / "breaker")

    with pytest.raises(DeployIncomplete):
        deploy(
            backend,
            TARGET,
            dry_run=False,
            stdin=io.StringIO("y\n"),
            stdout=io.StringIO(),
            source_provider=source,
        )

    assert backend.alignments == 0
    assert backend.events == [
        "source_materialized",
        "backup_receipt",
        "spine_image",
    ]


def test_managed_owner_resume_backs_up_before_image_service_migration_and_verification(
    tmp_path: Path,
) -> None:
    """SPEC D.2 096/097 keeps post-custody retries receipt-first and in owner update order."""

    backend = FakeBackend(
        observed(
            migrations=ResourceState.UPDATABLE,
            spine_image=ResourceState.ABSENT,
            cloud_run_service=ResourceState.UPDATABLE,
            remote_verification=ResourceState.UPDATABLE,
        )
    )

    @contextmanager
    def source() -> Iterator[PackagedDeploySource]:
        yield PackagedDeploySource(tmp_path / "app", tmp_path / "breaker")

    deploy(
        backend,
        TARGET,
        dry_run=False,
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        source_provider=source,
    )

    assert backend.alignments == 0
    assert backend.attempts == 1
    assert backend.events == [
        "backup_receipt",
        "spine_image",
        "cloud_run_service",
        "migrations",
        "remote_verification",
    ]


def test_declining_inline_alignment_changes_nothing() -> None:
    """SPEC D.2 096 makes consent explicit and leaves a plain retry action after decline."""

    backend = FakeBackend(observed(migrations=ResourceState.UNOBSERVED))
    backend.credentials_managed = False

    with pytest.raises(DeployError, match="run nocturne deploy again"):
        deploy(
            backend,
            TARGET,
            dry_run=False,
            stdin=io.StringIO("no\n"),
            stdout=io.StringIO(),
        )

    assert backend.alignments == 0
    assert backend.executed == []


def test_apply_converges_once_then_second_apply_has_zero_mutations(tmp_path: Path) -> None:
    """ADR-019 is defended by verifying that apply converges once then second apply has zero
    mutations; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = FakeBackend(absent_managed())
    source_calls: list[PackagedDeploySource] = []

    def provider() -> AbstractContextManager[PackagedDeploySource]:
        return contextmanager(source_provider)(tmp_path, source_calls)

    first = deploy(
        backend,
        TARGET,
        dry_run=False,
        stdout=io.StringIO(),
        source_provider=provider,
    )

    assert {step.action for step in first.steps} == {PlanAction.NOOP}
    assert len(backend.executed) == len(STAGE_FIELDS)
    assert len(source_calls) == 1
    source = source_calls[0]
    for step, supplied_source in backend.executed:
        expected = source.app if step.source_required else None
        assert supplied_source == expected

    first_execution_count = len(backend.executed)
    second = deploy(
        backend,
        TARGET,
        dry_run=False,
        stdout=io.StringIO(),
        source_provider=provider,
    )

    assert {step.action for step in second.steps} == {PlanAction.NOOP}
    assert len(backend.executed) == first_execution_count
    assert len(source_calls) == 1
    assert backend.armed == []


def test_absent_breaker_requires_tty_before_any_d1_work() -> None:
    """ADR-019 is defended by verifying that absent breaker requires tty before any d1 work;
    this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = FakeBackend(absent_managed(breaker=BreakerState.ABSENT))

    with pytest.raises(HumanTerminalRequired, match="real interactive"):
        deploy(backend, TARGET, dry_run=False, stdin=io.StringIO(), stdout=io.StringIO())

    assert backend.observations == 1
    assert backend.executed == []
    assert backend.armed == []


def test_absent_breaker_is_armed_only_through_packaged_source_and_tty(
    tmp_path: Path,
) -> None:
    """ADR-019 is defended by verifying that absent breaker is armed only through packaged
    source and tty; this prevents drift in the fixed-project deploy and drift-safety
    contract.
    """
    backend = FakeBackend(observed(breaker=BreakerState.ABSENT))
    source_calls: list[PackagedDeploySource] = []

    def provider() -> AbstractContextManager[PackagedDeploySource]:
        return contextmanager(source_provider)(tmp_path, source_calls)

    final = deploy(
        backend,
        TARGET,
        dry_run=False,
        stdin=TtyStringIO(),
        stdout=TtyStringIO(),
        source_provider=provider,
    )

    assert {step.action for step in final.steps} == {PlanAction.NOOP}
    assert backend.executed == []
    assert backend.armed == [source_calls[0].breaker]


def test_partial_breaker_blocks_without_source_or_mutation() -> None:
    """ADR-019 is defended by verifying that partial breaker blocks without source or mutation;
    this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = FakeBackend(observed(breaker=BreakerState.PARTIAL_OR_DRIFTED))

    with pytest.raises(DeployBlocked) as error:
        deploy(backend, TARGET, dry_run=False, stdout=io.StringIO())

    assert error.value.plan.step(DeployStage.BILLING_BREAKER).action is PlanAction.BLOCKED
    assert backend.observations == 1
    assert backend.executed == []
    assert backend.armed == []


def test_exact_canonical_d2_evidence_is_armed() -> None:
    """ADR-019 is defended by verifying that exact canonical d2 evidence is armed; this
    prevents drift in the fixed-project deploy and drift-safety contract.
    """
    assert breaker_state(exact_breaker_fixture()) is BreakerState.ARMED


@pytest.mark.parametrize(
    ("path", "value"),
    [
        pytest.param(("budget", "ownershipScope"), "PROJECT", id="budget-owner"),
        pytest.param(
            ("budget", "amount", "specifiedAmount", "currencyCode"),
            "EUR",
            id="budget-currency",
        ),
        pytest.param(
            ("budget", "amount", "specifiedAmount", "units"),
            "101",
            id="budget-amount",
        ),
        pytest.param(
            ("budget", "budgetFilter", "projects"),
            ["projects/other"],
            id="budget-project",
        ),
        pytest.param(
            ("budget", "budgetFilter", "calendarPeriod"),
            "YEAR",
            id="budget-period",
        ),
        pytest.param(
            ("budget", "budgetFilter", "customPeriod"),
            {"startDate": {}},
            id="budget-custom-period",
        ),
        pytest.param(
            ("budget", "budgetFilter", "services"),
            ["services/compute"],
            id="budget-narrowing",
        ),
        pytest.param(
            ("budget", "budgetFilter", "creditTypesTreatment"),
            "EXCLUDE_ALL_CREDITS",
            id="budget-credits",
        ),
        pytest.param(
            ("budget", "notificationsRule", "pubsubTopic"),
            "projects/other/topics/wrong",
            id="budget-topic",
        ),
        pytest.param(
            ("budget", "notificationsRule", "schemaVersion"),
            "0.1",
            id="budget-schema",
        ),
        pytest.param(("function", "environment"), "GEN_1", id="function-generation"),
        pytest.param(("function", "state"), "FAILED", id="function-state"),
        pytest.param(
            ("function", "serviceConfig", "serviceAccountEmail"),
            "wrong@example.com",
            id="function-runtime-account",
        ),
        pytest.param(
            ("function", "serviceConfig", "maxInstanceCount"),
            2,
            id="function-max",
        ),
        pytest.param(
            ("function", "serviceConfig", "minInstanceCount"),
            1,
            id="function-min",
        ),
        pytest.param(
            (
                "function",
                "serviceConfig",
                "environmentVariables",
                "EXPECTED_BILLING_ACCOUNT_ID",
            ),
            "wrong",
            id="function-billing-env",
        ),
        pytest.param(
            (
                "function",
                "serviceConfig",
                "environmentVariables",
                "EXPECTED_BUDGET_ID",
            ),
            "wrong",
            id="function-budget-env",
        ),
        pytest.param(
            ("function", "buildConfig", "serviceAccount"),
            "projects/wrong/serviceAccounts/wrong",
            id="function-build-account",
        ),
        pytest.param(
            ("function", "buildConfig", "runtime"),
            "python311",
            id="function-runtime",
        ),
        pytest.param(
            ("function", "buildConfig", "entryPoint"),
            "wrong",
            id="function-entrypoint",
        ),
        pytest.param(
            ("function", "eventTrigger", "eventType"),
            "google.cloud.audit.log.v1.written",
            id="function-event-type",
        ),
        pytest.param(
            ("function", "eventTrigger", "pubsubTopic"),
            "projects/other/topics/wrong",
            id="function-event-topic",
        ),
        pytest.param(
            ("function", "eventTrigger", "retryPolicy"),
            "RETRY_POLICY_RETRY",
            id="function-retry",
        ),
        pytest.param(
            ("function", "eventTrigger", "serviceAccountEmail"),
            "wrong@example.com",
            id="function-trigger-account",
        ),
        pytest.param(
            ("function", "eventTrigger", "triggerRegion"),
            "us-east1",
            id="function-trigger-region",
        ),
        pytest.param(
            ("function", "eventTrigger", "trigger"),
            "malformed-trigger",
            id="function-trigger-resource",
        ),
        pytest.param(
            ("topic_description", "name"),
            "projects/other/topics/wrong",
            id="topic-name",
        ),
        pytest.param(
            ("topic_description", "messageTransforms"),
            [{"javascriptUdf": {"code": "return message;"}}],
            id="topic-transform",
        ),
        pytest.param(("attached_subscriptions",), [], id="subscription-missing"),
        pytest.param(
            ("attached_subscriptions",),
            [{"name": "projects/other/subscriptions/wrong"}],
            id="subscription-cross-project",
        ),
        pytest.param(
            ("subscription_description", "name"),
            "projects/other/subscriptions/wrong",
            id="subscription-name",
        ),
        pytest.param(
            ("subscription_description", "topic"),
            "projects/other/topics/wrong",
            id="subscription-topic",
        ),
        pytest.param(
            ("subscription_description", "messageTransforms"),
            [{"javascriptUdf": {"code": "return message;"}}],
            id="subscription-transform",
        ),
        pytest.param(
            ("subscription_policy", "bindings"),
            [{"role": "roles/viewer", "members": ["user:owner@example.com"]}],
            id="subscription-iam",
        ),
        pytest.param(("triggers",), [], id="eventarc-list"),
        pytest.param(
            ("trigger_description", "name"),
            "projects/other/locations/us-central1/triggers/wrong",
            id="eventarc-name",
        ),
        pytest.param(
            ("trigger_description", "eventFilters"),
            {"type": "wrong"},
            id="eventarc-filter",
        ),
        pytest.param(
            ("trigger_description", "serviceAccount"),
            "wrong@example.com",
            id="eventarc-account",
        ),
        pytest.param(
            ("trigger_description", "transport", "pubsub", "topic"),
            "projects/other/topics/wrong",
            id="eventarc-topic",
        ),
        pytest.param(
            ("trigger_description", "transport", "pubsub", "subscription"),
            "projects/other/subscriptions/wrong",
            id="eventarc-subscription",
        ),
        pytest.param(
            ("trigger_description", "destination", "cloudRun", "service"),
            "wrong",
            id="eventarc-destination",
        ),
        pytest.param(
            ("trigger_description", "destination", "cloudRun", "region"),
            "us-east1",
            id="eventarc-destination-region",
        ),
        pytest.param(
            ("trigger_description", "destination", "cloudRun", "path"),
            "/wrong",
            id="eventarc-destination-path",
        ),
        pytest.param(
            ("trigger_description", "conditions", "transport"),
            {"code": "FAILED", "message": "broken"},
            id="eventarc-health",
        ),
        pytest.param(
            ("topic_policy", "bindings"),
            [
                {
                    "role": "roles/pubsub.publisher",
                    "members": [
                        "serviceAccount:billing-budget-alert@system.gserviceaccount.com",
                        "user:attacker@example.com",
                    ],
                }
            ],
            id="topic-policy",
        ),
        pytest.param(
            ("run_policy", "bindings"),
            [
                {
                    "role": "roles/run.invoker",
                    "members": [f"serviceAccount:{TRIGGER_ACCOUNT}"],
                    "condition": {"expression": "true"},
                }
            ],
            id="run-policy",
        ),
        pytest.param(
            ("project_policy", "bindings", 0, "members"),
            [f"serviceAccount:{RUNTIME_ACCOUNT}", "user:attacker@example.com"],
            id="detach-role-members",
        ),
        pytest.param(
            ("project_policy", "bindings", 0, "condition"),
            {"expression": "true"},
            id="detach-role-condition",
        ),
        pytest.param(
            ("project_policy", "bindings"),
            [
                {
                    "role": "roles/billing.projectManager",
                    "members": [f"serviceAccount:{RUNTIME_ACCOUNT}"],
                },
                {
                    "role": "roles/artifactregistry.writer",
                    "members": [f"serviceAccount:{BUILD_ACCOUNT}"],
                },
            ],
            id="temporary-build-role",
        ),
        pytest.param(
            ("user_keys", RUNTIME_ACCOUNT),
            [{"name": "projects/p/serviceAccounts/a/keys/1"}],
            id="service-account-key",
        ),
        pytest.param(
            ("account_policies", TRIGGER_ACCOUNT, "bindings"),
            [{"role": "roles/iam.serviceAccountUser", "members": ["user:owner@example.com"]}],
            id="service-account-policy",
        ),
        pytest.param(
            ("roles", "roles/billing.projectManager", "name"),
            "roles/owner",
            id="role-name",
        ),
        pytest.param(
            ("roles", "roles/billing.projectManager", "deleted"),
            True,
            id="role-deleted",
        ),
        pytest.param(
            ("roles", "roles/billing.projectManager", "includedPermissions"),
            ["billing.accounts.setIamPolicy"],
            id="role-permissions",
        ),
        pytest.param(("service_accounts",), [], id="service-accounts"),
        pytest.param(("run_services",), [], id="function-run-service"),
    ],
)
def test_every_canonical_d2_deviation_is_partial_or_drifted(
    path: tuple[str | int, ...], value: object
) -> None:
    """ADR-019 is defended by verifying that every canonical d2 deviation is partial or
    drifted; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    assert breaker_state(mutate_fixture(path, value)) is BreakerState.PARTIAL_OR_DRIFTED


def test_untrusted_billing_account_controller_blocks_armed_state() -> None:
    """ADR-019 is defended by verifying that untrusted billing account controller blocks armed
    state; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    fixture = exact_breaker_fixture()
    fixture["billing_policy"] = {
        "bindings": [
            {
                "role": "roles/billing.admin",
                "members": ["user:attacker@example.com"],
            }
        ]
    }
    fixture["roles"]["roles/billing.admin"] = {  # type: ignore[index]
        "name": "roles/billing.admin",
        "deleted": False,
        "includedPermissions": ["billing.budgets.update"],
    }

    assert breaker_state(fixture) is BreakerState.PARTIAL_OR_DRIFTED


def exact_cloud_run_service(backend: GcloudDeployBackend) -> dict[str, object]:
    return {
        "metadata": {
            "annotations": {"run.googleapis.com/ingress": "all"},
            "labels": {"nocturne-image": backend._verification_receipt},
        },
        "status": {"url": f"https://{CLOUD_RUN_SERVICE}-fixture.run.app"},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "run.googleapis.com/execution-environment": "gen2",
                        "run.googleapis.com/cloudsql-instances": SQL_CONNECTION_NAME,
                        "autoscaling.knative.dev/maxScale": "1",
                    }
                },
                "spec": {
                    "serviceAccountName": RUNTIME_SERVICE_ACCOUNT_EMAIL,
                    "containers": [
                        {
                            "image": backend.image_ref,
                            "ports": [{"containerPort": 8000}],
                            "env": [
                                {"name": "SPINE_EMBED_BASE_URL", "value": EMBED_BASE_URL},
                                {"name": "SPINE_EMBED_MODEL", "value": EMBED_MODEL},
                                {
                                    "name": "SPINE_DATABASE_URL",
                                    "valueFrom": {"secretKeyRef": {"secret": DATABASE_URL_SECRET}},
                                },
                                {
                                    "name": "SPINE_TOKEN",
                                    "valueFrom": {"secretKeyRef": {"secret": SPINE_TOKEN_SECRET}},
                                },
                                {
                                    "name": "SPINE_OPENAI_API_KEY",
                                    "valueFrom": {"secretKeyRef": {"secret": OPENROUTER_SECRET}},
                                },
                            ],
                        }
                    ],
                },
            }
        },
    }


def test_cloud_run_is_exact_only_with_sole_unconditional_public_invoker() -> None:
    """ADR-019 is defended by verifying that cloud run is exact only with sole unconditional
    public invoker; this prevents drift in the fixed-project deploy and drift-safety
    contract.
    """
    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")
    service = exact_cloud_run_service(backend)
    exact_policy = {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]}

    assert backend._cloud_run_state(service, exact_policy) is ResourceState.EXACT
    assert backend._cloud_run_state(service, {"bindings": []}) is ResourceState.UPDATABLE
    assert backend._cloud_run_state(service, None) is ResourceState.DRIFTED


@pytest.mark.parametrize(
    "policy",
    [
        {
            "bindings": [
                {"role": "roles/run.invoker", "members": ["allUsers"]},
                {"role": "roles/viewer", "members": ["user:owner@example.com"]},
            ]
        },
        {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": ["allUsers", "allAuthenticatedUsers"],
                }
            ]
        },
        {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": ["allUsers"],
                    "condition": {"expression": "true"},
                }
            ]
        },
    ],
)
def test_cloud_run_extra_or_conditional_public_iam_is_drifted(
    policy: dict[str, object],
) -> None:
    """ADR-019 is defended by verifying that cloud run extra or conditional public iam is
    drifted; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")

    state = backend._cloud_run_state(exact_cloud_run_service(backend), policy)
    assert state is ResourceState.DRIFTED


def test_artifact_image_listing_uses_supported_fully_qualified_package_argv() -> None:
    """ADR-019 is defended by verifying that artifact image listing uses supported fully
    qualified package argv; this prevents drift in the fixed-project deploy and drift-safety
    contract.
    """
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
    )

    assert backend._artifact_images() == []
    assert calls == [
        (
            "gcloud",
            "artifacts",
            "docker",
            "images",
            "list",
            IMAGE_PACKAGE,
            "--include-tags",
            f"--project={PROJECT_ID}",
            "--format=json",
        )
    ]


def test_released_image_requires_the_matching_packaged_source_tag() -> None:
    """SPEC D.2 099 blocks a reused version when its packaged source digest changed."""

    digest = "a" * 64
    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        source_digest=digest,
    )
    row = {
        "package": IMAGE_PACKAGE,
        "tags": [backend.image_tag, backend.source_tag],
        "version": "sha256:fixture",
    }

    assert backend._image_state([row]) is ResourceState.EXACT
    row["tags"] = [backend.image_tag, f"source-{'b' * 64}"]
    assert backend._image_state([row]) is ResourceState.SOURCE_CHANGED
    step = build_plan(observed(spine_image=ResourceState.SOURCE_CHANGED)).step(
        DeployStage.SPINE_IMAGE
    )
    assert step.action is PlanAction.BLOCKED
    assert step.detail == "this version is already released; bump the spine version to ship changes"


def sql_user_state(users: list[dict[str, object]]) -> ResourceState:
    instance = {
        "name": SQL_INSTANCE,
        "databaseVersion": "POSTGRES_16",
        "region": REGION,
        "state": "RUNNABLE",
        "connectionName": SQL_CONNECTION_NAME,
        "settings": {
            "deletionProtectionEnabled": True,
            "backupConfiguration": {
                "enabled": True,
                "pointInTimeRecoveryEnabled": True,
                "location": REGION,
                "transactionLogRetentionDays": 7,
                "backupRetentionSettings": {"retainedBackups": 7},
            },
        },
    }

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        if command[:3] == ("gcloud", "projects", "list"):
            value: object = [
                {
                    "projectId": PROJECT_ID,
                    "projectNumber": "123456789",
                    "lifecycleState": "ACTIVE",
                }
            ]
        elif command[:4] == ("gcloud", "billing", "projects", "describe"):
            value = {
                "billingEnabled": True,
                "billingAccountName": f"billingAccounts/{TARGET.billing_account_id}",
            }
        elif command[:4] == ("gcloud", "sql", "instances", "list"):
            value = [instance]
        elif command[:4] == ("gcloud", "sql", "databases", "list"):
            value = [{"name": DATABASE_NAME, "charset": "UTF8"}]
        elif command[:4] == ("gcloud", "sql", "users", "list"):
            value = users
        elif command[:4] in {
            ("gcloud", "secrets", "list", f"--project={PROJECT_ID}"),
            ("gcloud", "iam", "service-accounts", "list"),
            ("gcloud", "artifacts", "repositories", "list"),
            ("gcloud", "run", "services", "list"),
            ("gcloud", "pubsub", "topics", "list"),
            ("gcloud", "functions", "list", "--v2"),
            ("gcloud", "eventarc", "triggers", "list"),
        }:
            value = []
        elif command[:3] == ("gcloud", "secrets", "list"):
            value = []
        elif command[:4] == ("gcloud", "projects", "get-iam-policy", PROJECT_ID):
            value = {"bindings": []}
        elif command[:4] == ("gcloud", "billing", "budgets", "describe"):
            value = {}
        else:
            raise AssertionError(f"unexpected SQL-user fixture command: {command!r}")
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
    )
    return backend.observe(TARGET).database_user


@pytest.mark.parametrize(
    ("users", "expected"),
    [
        ([{"name": DATABASE_USER, "type": "BUILT_IN"}], ResourceState.EXACT),
        ([{"name": DATABASE_USER, "type": "CLOUD_IAM_USER"}], ResourceState.DRIFTED),
        ([{"name": DATABASE_USER}], ResourceState.EXACT),
        (
            [
                {"name": DATABASE_USER, "type": "BUILT_IN"},
                {"name": DATABASE_USER, "type": "BUILT_IN"},
            ],
            ResourceState.DRIFTED,
        ),
        ([], ResourceState.ABSENT),
    ],
)
def test_sql_user_identity_accepts_postgres_builtin_shape_and_rejects_iam_or_duplicates(
    users: list[dict[str, object]], expected: ResourceState
) -> None:
    """ADR-019 accepts gcloud's omitted type for a PostgreSQL built-in but rejects IAM or twins."""
    assert sql_user_state(users) is expected


def test_database_url_round_trips_only_the_exact_cloud_sql_socket_shape() -> None:
    """ADR-019 is defended by verifying that database url round trips only the exact cloud sql
    socket shape; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    producer = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")
    producer._database_password = "p@ss/word"
    database_url = producer._database_url()
    consumer = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")

    consumer._remember_database_password(database_url)

    assert consumer._database_password == "p@ss/word"


def test_owner_credential_alignment_backs_up_before_private_reset_and_secret_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 094 requires backup-first ordering while credentials stay off argv."""

    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    private_flag_payloads: list[dict[str, str]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append((command, kwargs))
        for value in command:
            if value.startswith("--flags-file="):
                private_flag_payloads.append(
                    json.loads(Path(value.split("=", 1)[1]).read_text(encoding="utf-8"))
                )
        if command[:5] == ("gcloud", "secrets", "versions", "add", DATABASE_URL_SECRET):
            output = {"name": f"projects/fixture/secrets/{DATABASE_URL_SECRET}/versions/2"}
        elif command[:5] == ("gcloud", "secrets", "versions", "list", DATABASE_URL_SECRET):
            output = [
                {
                    "name": f"projects/fixture/secrets/{DATABASE_URL_SECRET}/versions/1",
                    "state": "ENABLED",
                },
                {
                    "name": f"projects/fixture/secrets/{DATABASE_URL_SECRET}/versions/2",
                    "state": "ENABLED",
                },
            ]
        else:
            output = {}
        return subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
        cloud_receipt_directory=tmp_path,
        credential_custody_receipt=tmp_path / "cloud-credential-custody.json",
    )
    receipt = tmp_path / "verified-backup.json"
    monkeypatch.setattr(backend, "_create_cloud_backup_receipt", lambda: receipt)

    assert backend.align_owner_cloud_credentials_once() == receipt

    argvs = [argv for argv, _ in calls]
    reset_index = next(
        i for i, argv in enumerate(argvs) if argv[:4] == ("gcloud", "sql", "users", "set-password")
    )
    add_index = next(
        i
        for i, argv in enumerate(argvs)
        if argv[:5] == ("gcloud", "secrets", "versions", "add", DATABASE_URL_SECRET)
    )
    disable_index = next(
        i
        for i, argv in enumerate(argvs)
        if argv[:4] == ("gcloud", "secrets", "versions", "disable")
    )
    assert reset_index < add_index < disable_index
    assert all(backend._database_password not in argv for argv in argvs)
    assert private_flag_payloads == [{"--password": backend._database_password}]
    add_kwargs = calls[add_index][1]
    assert backend._database_password not in str(add_kwargs.get("env"))
    assert "postgresql+asyncpg://" in str(add_kwargs["input"])
    assert backend.owner_credentials_managed()
    custody = json.loads((tmp_path / "cloud-credential-custody.json").read_text(encoding="utf-8"))
    assert custody["backup_receipt"] == receipt.name
    assert custody["secret_version"] == "2"


def test_unobserved_migration_reports_credential_cause_and_remedy() -> None:
    """SPEC D.2 095 prevents credential disagreement from being mislabeled as schema drift."""

    plan = build_plan(
        observed(
            migrations=ResourceState.UNOBSERVED,
            database_url_secret=ResourceState.DRIFTED,
        )
    )

    migration = plan.step(DeployStage.MIGRATIONS)
    assert migration.action is PlanAction.BLOCKED
    assert "could not be inspected" in migration.detail
    assert "run the dry-run again" in migration.detail
    assert "incompatible" not in migration.detail


@pytest.mark.parametrize(
    "database_url",
    [
        (
            f"postgresql+asyncpg://{DATABASE_USER}:password@evil.example/{DATABASE_NAME}"
            f"?host=/cloudsql/{SQL_CONNECTION_NAME}"
        ),
        (
            f"postgresql+asyncpg://{DATABASE_USER}:password@:5432/{DATABASE_NAME}"
            f"?host=/cloudsql/{SQL_CONNECTION_NAME}"
        ),
        (
            f"postgresql+asyncpg://{DATABASE_USER}:password@/{DATABASE_NAME}"
            f"?host=/cloudsql/{SQL_CONNECTION_NAME}&ssl=require"
        ),
        (
            f"postgresql+asyncpg://{DATABASE_USER}:password@/{DATABASE_NAME}"
            f"?host=/cloudsql/{SQL_CONNECTION_NAME}#fragment"
        ),
    ],
)
def test_database_url_rejects_remote_port_extra_query_and_fragment(
    database_url: str,
) -> None:
    """ADR-019 is defended by verifying that database url rejects remote port extra query and
    fragment; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")

    with pytest.raises(DeployError, match="unexpected identity"):
        backend._remember_database_password(database_url)


def test_packaged_source_materializes_separate_complete_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 is defended by verifying that packaged source materializes separate complete
    trees; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    from spine import deploy_resources

    resources = tmp_path / "resources"
    breaker = resources / "billing-breaker"
    breaker.mkdir(parents=True)
    (resources / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (resources / "README.md").write_text("# Spine\n", encoding="utf-8")
    (resources / "pyproject.toml").write_text("[project]\nname='spine'\n", encoding="utf-8")
    for filename in (
        "README.md",
        "billing_breaker.py",
        "deploy.sh",
        "deployment_checks.py",
        "main.py",
        "requirements.txt",
    ):
        (breaker / filename).write_text(f"fixture:{filename}\n", encoding="utf-8")
    monkeypatch.setattr(deploy_resources, "_packaged_deploy_resources", lambda: resources)

    with packaged_spine_source() as source:
        temporary_root = source.app.parent
        assert source.app != source.breaker
        assert (source.app / "Dockerfile").read_text(encoding="utf-8") == "FROM scratch\n"
        assert (source.app / "README.md").read_text(encoding="utf-8") == "# Spine\n"
        assert (source.app / "src" / "spine" / "deploy_resources.py").is_file()
        assert (source.app / "infra" / "billing-breaker" / "deploy.sh").is_file()
        assert (source.breaker / "deploy.sh").stat().st_mode & 0o111
    assert not temporary_root.exists()


def test_deploy_source_digest_tracks_paths_modes_and_bytes(tmp_path: Path) -> None:
    """SPEC D.2 099 binds an immutable release tag to the exact packaged source tree."""

    source = tmp_path / "source"
    source.mkdir()
    first = source / "first.py"
    second = source / "second.py"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    baseline = deploy_source_digest(source)

    assert deploy_source_digest(source) == baseline
    second.write_text("changed\n", encoding="utf-8")
    assert deploy_source_digest(source) != baseline
    second.write_text("second\n", encoding="utf-8")
    second.chmod(0o755)
    assert deploy_source_digest(source) != baseline


def test_packaged_breaker_uses_exact_argv_without_shell_or_confirmation_synthesis(
    tmp_path: Path,
) -> None:
    """ADR-019 is defended by verifying that packaged breaker uses exact argv without shell or
    confirmation synthesis; this prevents drift in the fixed-project deploy and drift-safety
    contract.
    """
    script = tmp_path / "deploy.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    stdin = TtyStringIO()
    stdout = TtyStringIO()
    invoke_packaged_breaker(
        tmp_path,
        TARGET,
        stdin=stdin,
        stdout=stdout,
        runner=runner,
    )

    argv, kwargs = calls[0]
    assert argv == (str(script), "--apply")
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is stdin
    assert kwargs["stdout"] is stdout
    assert kwargs["env"]["BILLING_ACCOUNT_ID"] == TARGET.billing_account_id  # type: ignore[index]
    assert TARGET.breaker_confirmation not in argv


def test_build_and_execute_commands_stay_inside_the_argv_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 is defended by verifying that build and execute commands stay inside the argv
    fence; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    openrouter_key = "sk-or-v1-super-secret"
    access_token = "registry-access-token"
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        stdout = access_token if argv[:3] == ("gcloud", "auth", "print-access-token") else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key=openrouter_key,
        runner=runner,
    )
    monkeypatch.setattr(backend, "_apply_migrations", lambda: None)
    monkeypatch.setattr(backend, "_verify_remote", lambda: None)
    update_stages = {
        DeployStage.SQL_PROTECTION,
        DeployStage.MIGRATIONS,
        DeployStage.RUNTIME_CLOUDSQL_IAM,
        DeployStage.RUNTIME_DATABASE_SECRET_IAM,
        DeployStage.RUNTIME_TOKEN_SECRET_IAM,
        DeployStage.RUNTIME_OPENROUTER_SECRET_IAM,
        DeployStage.REMOTE_VERIFICATION,
    }
    steps = [
        PlanStep(
            stage,
            PlanAction.UPDATE if stage in update_stages else PlanAction.CREATE,
            "fixture",
        )
        for stage in STAGE_FIELDS
    ]
    for step in steps:
        backend.execute(step, target=TARGET, source_dir=tmp_path)

    argvs = [argv for argv, _ in calls]
    assert local_image_build_argv(tmp_path, backend.image_ref) in argvs
    assert any(argv[:3] == ("docker", "login", ARTIFACT_HOST) for argv in argvs)
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all("delete" not in argv and "remove" not in argv for argv in argvs)
    assert all(argv[:3] != ("gcloud", "builds", "submit") for argv in argvs)
    assert all(openrouter_key not in argv and access_token not in argv for argv in argvs)
    roles = {
        value.split("=", 1)[1] for argv in argvs for value in argv if value.startswith("--role=")
    }
    assert roles == {"roles/cloudsql.client", "roles/secretmanager.secretAccessor"}


def test_source_guard_build_publishes_version_and_digest_tags(tmp_path: Path) -> None:
    """SPEC D.2 099 publishes one digest companion for the immutable version tag."""

    digest = "a" * 64
    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        source_digest=digest,
    )

    assert local_image_build_argv(tmp_path, backend.image_ref, backend.source_ref) == (
        "docker",
        "buildx",
        "build",
        "--platform=linux/amd64",
        "--tag",
        backend.image_ref,
        "--tag",
        f"{IMAGE_PACKAGE}:source-{digest}",
        "--push",
        str(tmp_path),
    )


def test_isolated_docker_environment_keeps_routing_but_drops_registry_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 097 keeps pre-receipt proof identical to the credential-isolated build."""

    persistent = tmp_path / "persistent-docker"
    persistent.mkdir()
    (persistent / "config.json").write_text(
        json.dumps(
            {
                "auths": {"registry.example": {"auth": "encoded-secret"}},
                "credsStore": "desktop",
                "credHelpers": {"registry.example": "helper"},
                "currentContext": "colima",
                "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"],
            }
        ),
        encoding="utf-8",
    )
    for name in ("buildx", "cli-plugins", "contexts"):
        (persistent / name).mkdir()
    monkeypatch.setenv("DOCKER_CONFIG", str(persistent))

    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")
    with backend._isolated_docker_environment() as environment:
        isolated = Path(environment["DOCKER_CONFIG"])
        rendered = json.loads((isolated / "config.json").read_text(encoding="utf-8"))
        assert rendered == {
            "currentContext": "colima",
            "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"],
        }
        assert stat.S_IMODE((isolated / "config.json").stat().st_mode) == 0o600
        for name in ("buildx", "cli-plugins", "contexts"):
            assert (isolated / name).is_symlink()
            assert (isolated / name).resolve() == (persistent / name).resolve()
    assert not isolated.exists()


def test_preflight_proves_the_exact_isolated_buildx_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 097 spends no receipt before isolated Buildx and its daemon both work."""

    persistent = tmp_path / "persistent-docker"
    persistent.mkdir()
    (persistent / "config.json").write_text(
        json.dumps(
            {
                "auths": {"registry.example": {"auth": "encoded-secret"}},
                "currentContext": "colima",
                "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCKER_CONFIG", str(persistent))
    for variable in (
        "CLOUDSDK_AUTH_ACCESS_TOKEN",
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        monkeypatch.delenv(variable, raising=False)

    calls: list[tuple[str, ...]] = []
    isolated_paths: list[Path] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[:3] == ("gcloud", "config", "get-value"):
            return subprocess.CompletedProcess(argv, 0, "(unset)\n", "")
        if argv[:3] == ("gcloud", "auth", "list"):
            return subprocess.CompletedProcess(argv, 0, '[{"account":"owner@example.com"}]', "")
        if argv[:2] == ("docker", "buildx") or argv[:2] == ("docker", "info"):
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            isolated = Path(environment["DOCKER_CONFIG"])
            isolated_paths.append(isolated)
            config = json.loads((isolated / "config.json").read_text(encoding="utf-8"))
            assert "auths" not in config
            assert config["currentContext"] == "colima"
        return subprocess.CompletedProcess(argv, 0, "fixture", "")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
    )
    backend.preflight()

    assert ("docker", "buildx", "version") in calls
    assert ("docker", "info", "--format={{.ServerVersion}}") in calls
    assert len(isolated_paths) == 2
    assert isolated_paths[0] == isolated_paths[1]
    assert not isolated_paths[0].exists()


def test_failed_build_uses_one_secret_free_isolated_config_and_cleans_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 097 keeps a failed image build credential-isolated and ephemeral."""

    persistent = tmp_path / "persistent-docker"
    persistent.mkdir()
    (persistent / "config.json").write_text(
        json.dumps(
            {
                "auths": {"registry.example": {"auth": "persistent-secret"}},
                "currentContext": "colima",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCKER_CONFIG", str(persistent))
    access_token = "short-lived-registry-token"
    isolated_paths: list[Path] = []
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if argv[:3] == ("gcloud", "auth", "print-access-token"):
            return subprocess.CompletedProcess(argv, 0, access_token, "")
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        isolated = Path(environment["DOCKER_CONFIG"])
        isolated_paths.append(isolated)
        config = json.loads((isolated / "config.json").read_text(encoding="utf-8"))
        assert "auths" not in config
        if argv[:2] == ("docker", "login"):
            assert kwargs["input"] == access_token
            return subprocess.CompletedProcess(argv, 0, "", "")
        assert argv[:3] == ("docker", "buildx", "build")
        assert kwargs["input"] is None
        return subprocess.CompletedProcess(argv, 1, access_token, "registry failure")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
    )
    with pytest.raises(DeployError) as error:
        backend._build_image(tmp_path / "source")

    assert str(error.value) == "subprocess failed without changing scope: docker buildx build"
    assert access_token not in str(error.value)
    assert len(isolated_paths) == 2
    assert isolated_paths[0] == isolated_paths[1]
    assert not isolated_paths[0].exists()
    assert all(access_token not in argv for argv, _ in calls)


@pytest.mark.parametrize("image_ref", ["", " ", "repo/image:tag with-space", "\ttag"])
def test_local_build_rejects_non_single_argv_image_refs(image_ref: str) -> None:
    """ADR-019 is defended by verifying that local build rejects non single argv image refs;
    this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    with pytest.raises(ValueError):
        local_image_build_argv(Path("/source"), image_ref)


def test_execute_refuses_non_mutation_and_unknown_stages() -> None:
    """ADR-019 is defended by verifying that execute refuses non mutation and unknown stages;
    this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="secret")

    with pytest.raises(DeployError, match="non-D1"):
        backend.execute(
            PlanStep(DeployStage.DATABASE, PlanAction.NOOP, "fixture"),
            target=TARGET,
            source_dir=None,
        )
    with pytest.raises(DeployError, match="unsupported or forbidden"):
        backend.execute(
            PlanStep(DeployStage.BILLING, PlanAction.UPDATE, "fixture"),
            target=TARGET,
            source_dir=None,
        )


def test_deploy_target_accepts_only_matching_canonical_identifiers() -> None:
    """ADR-019 is defended by verifying that deploy target accepts only matching canonical
    identifiers; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    assert TARGET.breaker_confirmation == (
        "DETACH BILLING n8-memory-palace "
        "billingAccounts/ABCDEF-123456-789ABC/budgets/nocturne-100 "
        "billingAccounts/ABCDEF-123456-789ABC CURRENT COST BELOW 100"
    )


@pytest.mark.parametrize(
    ("account", "budget"),
    [
        ("abcdef", "billingAccounts/abcdef/budgets/budget"),
        (
            "ABCDEF-123456-789ABC",
            "billingAccounts/000000-000000-000000/budgets/budget",
        ),
        ("ABCDEF-123456-789ABC", "projects/p/budgets/budget"),
        ("ABCDEF-123456-789ABC", "billingAccounts/ABCDEF-123456-789ABC/budgets/../x"),
    ],
)
def test_deploy_target_rejects_unsafe_or_mismatched_identifiers(account: str, budget: str) -> None:
    """ADR-019 is defended by verifying that deploy target rejects unsafe or mismatched
    identifiers; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    with pytest.raises(ValueError):
        DeployTarget(account, budget)


@pytest.mark.parametrize(
    "variable",
    [
        "CLOUDSDK_AUTH_ACCESS_TOKEN",
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ],
)
def test_preflight_blocks_every_credential_override_before_subprocesses(
    variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-019 is defended by verifying that preflight blocks every credential override before
    subprocesses; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    forbidden = (
        "CLOUDSDK_AUTH_ACCESS_TOKEN",
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT",
        "GOOGLE_APPLICATION_CREDENTIALS",
    )
    for name in forbidden:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, "present")

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("preflight ran a subprocess despite credential override")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="secret",
        runner=runner,
    )
    with pytest.raises(TargetDiscoveryBlocked, match="credential override"):
        backend.preflight()


def test_subprocess_failure_redacts_secret_input_and_cloud_output() -> None:
    """ADR-019 is defended by verifying that subprocess failure redacts secret input and cloud
    output; this prevents drift in the fixed-project deploy and drift-safety contract.
    """
    secret = "sk-or-v1-do-not-print"

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["input"] == secret
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=f"provider echoed {secret}",
            stderr=f"credential={secret}",
        )

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key=secret,
        runner=runner,
    )
    with pytest.raises(DeployError) as error:
        backend._run(("gcloud", "secrets", "versions"), input_text=secret)

    rendered = str(error.value)
    assert rendered == "subprocess failed without changing scope: gcloud secrets versions"
    assert secret not in rendered
    assert secret not in build_plan(absent_managed()).render()


def test_missing_command_is_normalized_without_leaking_os_error() -> None:
    """ADR-019 is defended by verifying that missing command is normalized without leaking os
    error; this prevents drift in the fixed-project deploy and drift-safety contract.
    """

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("sensitive host path")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
    )
    with pytest.raises(DeployError) as error:
        backend._run(("gcloud", "projects", "list"))

    assert str(error.value) == "required command is unavailable: gcloud"
    assert "sensitive host path" not in str(error.value)


def test_cloud_migration_waits_for_verified_private_backup_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A-046 prevents owner-cloud Alembic from outrunning completed recovery evidence."""

    calls: list[tuple[str, ...]] = []
    receipt_id = "01J00000000000000000000000"
    backup_id = "1785900000000"
    operation_id = "backup-operation-1"
    description = f"nocturne-pre-migration-{receipt_id.lower()}"

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if command[:4] == ("gcloud", "sql", "backups", "create"):
            value: object = {
                "name": operation_id,
                "backupContext": {"backupId": backup_id},
            }
        elif command[:4] == ("gcloud", "sql", "operations", "wait"):
            value = [
                {
                    "name": operation_id,
                    "status": "DONE",
                    "operationType": "BACKUP_VOLUME",
                    "targetProject": PROJECT_ID,
                    "targetId": SQL_INSTANCE,
                    "backupContext": {"backupId": backup_id},
                }
            ]
        elif command[:4] == ("gcloud", "sql", "backups", "describe"):
            value = {
                "id": backup_id,
                "instance": SQL_INSTANCE,
                "description": description,
                "status": "SUCCESSFUL",
                "type": "ON_DEMAND",
                "location": REGION,
                "enqueuedTime": "2026-08-04T20:00:00Z",
                "startTime": "2026-08-04T20:00:01Z",
                "endTime": "2026-08-04T20:00:22Z",
            }
        elif command[:3] == (sys.executable, "-m", "spine.db.migrate"):
            receipt = tmp_path / "cloud-backups" / f"{receipt_id}.json"
            assert receipt.is_file()
            value = ""
        else:
            raise AssertionError(f"unexpected command: {command!r}")
        stdout = value if isinstance(value, str) else json.dumps(value)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    @contextmanager
    def proxy() -> Iterator[int]:
        yield 54321

    monkeypatch.setattr("harness.deploy.generate_ulid", lambda: receipt_id)
    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
        cloud_receipt_directory=tmp_path / "cloud-backups",
    )
    backend._database_password = "database-secret"
    monkeypatch.setattr(backend, "_cloud_sql_proxy", proxy)

    backend._apply_migrations()

    receipt_path = tmp_path / "cloud-backups" / f"{receipt_id}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["backup_id"] == backup_id
    assert receipt["operation_id"] == operation_id
    assert receipt["status"] == "SUCCESSFUL"
    assert receipt["type"] == "ON_DEMAND"
    assert stat.S_IMODE((tmp_path / "cloud-backups").stat().st_mode) == 0o700
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert calls[-1][:3] == (sys.executable, "-m", "spine.db.migrate")


def test_cloud_backup_verification_failure_stops_before_migration(tmp_path: Path) -> None:
    """A-046 fails closed when the provider cannot prove the requested backup succeeded."""

    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if command[:4] == ("gcloud", "sql", "backups", "create"):
            value: object = {
                "name": "backup-operation-2",
                "backupContext": {"backupId": "1785900000001"},
            }
        elif command[:4] == ("gcloud", "sql", "operations", "wait"):
            value = [
                {
                    "name": "backup-operation-2",
                    "status": "DONE",
                    "operationType": "BACKUP_VOLUME",
                    "targetProject": PROJECT_ID,
                    "targetId": SQL_INSTANCE,
                    "backupContext": {"backupId": "1785900000001"},
                }
            ]
        elif command[:4] == ("gcloud", "sql", "backups", "describe"):
            value = {
                "id": "1785900000001",
                "instance": SQL_INSTANCE,
                "description": "not-the-requested-backup",
                "status": "SUCCESSFUL",
                "type": "ON_DEMAND",
                "location": REGION,
            }
        else:
            raise AssertionError("migration ran after failed backup verification")
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
        cloud_receipt_directory=tmp_path / "cloud-backups",
    )
    backend._database_password = "database-secret"

    with pytest.raises(DeployError, match="could not be verified"):
        backend._apply_migrations()
    assert not (tmp_path / "cloud-backups").exists()
    assert all(command[:3] != (sys.executable, "-m", "spine.db.migrate") for command in calls)


def test_owner_cloud_backup_reuses_verified_receipt_without_deploy_or_grants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 099 gives Rung 2 backup owner hands without deployment grant machinery."""

    receipt = tmp_path / "cloud-backups" / "manual.json"
    events: list[object] = []

    def verify(self: GcloudDeployBackend) -> None:
        events.append("owner-credentials")

    def backup(self: GcloudDeployBackend, *, reason: str = "pre_migration") -> Path:
        events.append((reason, self._cloud_receipt_directory))
        return receipt

    monkeypatch.setattr(GcloudDeployBackend, "verify_owner_credentials", verify)
    monkeypatch.setattr(GcloudDeployBackend, "_create_cloud_backup_receipt", backup)
    monkeypatch.setattr(
        GcloudDeployBackend,
        "preflight",
        lambda self: pytest.fail("manual backup entered deploy preflight"),
    )
    monkeypatch.setattr(
        GcloudDeployBackend,
        "discover_target",
        lambda self: pytest.fail("manual backup discovered deployment grants"),
    )

    assert (
        create_owner_cloud_backup(
            openrouter_key="fixture",
            home=tmp_path,
        )
        == receipt
    )
    assert events == ["owner-credentials", ("manual", tmp_path / "cloud-backups")]


def test_manual_cloud_backup_receipt_names_manual_on_demand_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 099 requires a verified ON_DEMAND receipt for an owner backup command."""

    receipt_id = "01J00000000000000000000000"
    backup_id = "1785900000002"
    operation_id = "backup-operation-3"
    description = f"nocturne-manual-{receipt_id.lower()}"

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        if command[:4] == ("gcloud", "sql", "backups", "create"):
            value: object = {
                "name": operation_id,
                "backupContext": {"backupId": backup_id},
            }
        elif command[:4] == ("gcloud", "sql", "operations", "wait"):
            value = [
                {
                    "name": operation_id,
                    "status": "DONE",
                    "operationType": "BACKUP_VOLUME",
                    "targetProject": PROJECT_ID,
                    "targetId": SQL_INSTANCE,
                    "backupContext": {"backupId": backup_id},
                }
            ]
        elif command[:4] == ("gcloud", "sql", "backups", "describe"):
            value = {
                "id": backup_id,
                "instance": SQL_INSTANCE,
                "description": description,
                "status": "SUCCESSFUL",
                "type": "ON_DEMAND",
                "location": REGION,
                "enqueuedTime": "2026-08-08T20:00:00Z",
                "startTime": "2026-08-08T20:00:01Z",
                "endTime": "2026-08-08T20:00:22Z",
            }
        else:
            raise AssertionError(f"unexpected command: {command!r}")
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    monkeypatch.setattr("harness.deploy.generate_ulid", lambda: receipt_id)
    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
        cloud_receipt_directory=tmp_path / "cloud-backups",
    )

    receipt_path = backend._create_cloud_backup_receipt(reason="manual")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["reason"] == "manual"
    assert receipt["description"] == description
    assert receipt["type"] == "ON_DEMAND"


def test_same_attempt_alignment_receipt_is_reused_for_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC D.2 096 uses one fresh receipt for reset and migration in the same deploy."""

    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    @contextmanager
    def proxy() -> Iterator[int]:
        yield 54321

    backend = GcloudDeployBackend(
        image_tag="0.1.0",
        openrouter_key="fixture",
        runner=runner,
        cloud_receipt_directory=tmp_path,
    )
    backend._database_password = "database-secret"
    backend._attempt_backup_receipt = tmp_path / "fresh-attempt.json"
    monkeypatch.setattr(backend, "_cloud_sql_proxy", proxy)
    monkeypatch.setattr(
        backend,
        "_create_cloud_backup_receipt",
        lambda: pytest.fail("migration created a second receipt in the same attempt"),
    )

    backend._apply_migrations()

    assert calls == [(sys.executable, "-m", "spine.db.migrate")]
    assert backend._attempt_backup_receipt is None
