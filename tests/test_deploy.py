from __future__ import annotations

import copy
import io
import json
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

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
    deploy,
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


class FakeBackend(DeployBackend):
    def __init__(self, state: ObservedDeployment) -> None:
        self.state = state
        self.observations = 0
        self.executed: list[tuple[PlanStep, Path | None]] = []
        self.armed: list[Path] = []

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
        self.state = replace(self.state, **{STAGE_FIELDS[step.stage]: ResourceState.EXACT})

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
    plan = build_plan(observed())

    assert len(plan.steps) == 20
    assert not plan.blocked
    assert plan.mutations == ()
    assert {step.action for step in plan.steps} == {PlanAction.NOOP}


def test_lawful_absent_managed_states_have_only_create_or_forward_update() -> None:
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
    plan = build_plan(observed(**{field: ResourceState.DRIFTED}))

    assert plan.blocked
    assert plan.step(stage).action is PlanAction.BLOCKED


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
    plan = build_plan(observed(**updates))

    assert plan.blocked
    assert plan.step(DeployStage.DATABASE).action is PlanAction.BLOCKED
    assert plan.step(DeployStage.DATABASE_USER).action is PlanAction.BLOCKED


def test_dry_run_only_observes_and_never_materializes_or_mutates() -> None:
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


def test_apply_converges_once_then_second_apply_has_zero_mutations(tmp_path: Path) -> None:
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
    backend = FakeBackend(absent_managed(breaker=BreakerState.ABSENT))

    with pytest.raises(HumanTerminalRequired, match="real interactive"):
        deploy(backend, TARGET, dry_run=False, stdin=io.StringIO(), stdout=io.StringIO())

    assert backend.observations == 1
    assert backend.executed == []
    assert backend.armed == []


def test_absent_breaker_is_armed_only_through_packaged_source_and_tty(
    tmp_path: Path,
) -> None:
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
    backend = FakeBackend(observed(breaker=BreakerState.PARTIAL_OR_DRIFTED))

    with pytest.raises(DeployBlocked) as error:
        deploy(backend, TARGET, dry_run=False, stdout=io.StringIO())

    assert error.value.plan.step(DeployStage.BILLING_BREAKER).action is PlanAction.BLOCKED
    assert backend.observations == 1
    assert backend.executed == []
    assert backend.armed == []


def test_exact_canonical_d2_evidence_is_armed() -> None:
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
    assert breaker_state(mutate_fixture(path, value)) is BreakerState.PARTIAL_OR_DRIFTED


def test_untrusted_billing_account_controller_blocks_armed_state() -> None:
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
    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")

    state = backend._cloud_run_state(exact_cloud_run_service(backend), policy)
    assert state is ResourceState.DRIFTED


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
        ([{"name": DATABASE_USER}], ResourceState.DRIFTED),
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
def test_sql_user_identity_requires_one_builtin_user(
    users: list[dict[str, object]], expected: ResourceState
) -> None:
    assert sql_user_state(users) is expected


def test_database_url_round_trips_only_the_exact_cloud_sql_socket_shape() -> None:
    producer = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")
    producer._database_password = "p@ss/word"
    database_url = producer._database_url()
    consumer = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")

    consumer._remember_database_password(database_url)

    assert consumer._database_password == "p@ss/word"


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
    backend = GcloudDeployBackend(image_tag="0.1.0", openrouter_key="fixture")

    with pytest.raises(DeployError, match="unexpected identity"):
        backend._remember_database_password(database_url)


def test_packaged_source_materializes_separate_complete_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from spine import deploy_resources

    resources = tmp_path / "resources"
    breaker = resources / "billing-breaker"
    breaker.mkdir(parents=True)
    (resources / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
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
        assert (source.app / "src" / "spine" / "deploy_resources.py").is_file()
        assert (source.app / "infra" / "billing-breaker" / "deploy.sh").is_file()
        assert (source.breaker / "deploy.sh").stat().st_mode & 0o111
    assert not temporary_root.exists()


def test_packaged_breaker_uses_exact_argv_without_shell_or_confirmation_synthesis(
    tmp_path: Path,
) -> None:
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


@pytest.mark.parametrize("image_ref", ["", " ", "repo/image:tag with-space", "\ttag"])
def test_local_build_rejects_non_single_argv_image_refs(image_ref: str) -> None:
    with pytest.raises(ValueError):
        local_image_build_argv(Path("/source"), image_ref)


def test_execute_refuses_non_mutation_and_unknown_stages() -> None:
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
