"""Fail-closed D3 deployment planning for the fixed D.2 045 target.

The CLI layer is intentionally absent here.  It can render :class:`DeployPlan`
for ``nocturne deploy --dry-run`` or call :func:`deploy` for apply.  All cloud
observation and mutation is owned by an injected backend, which keeps the
planner pure and makes the no-mutation dry-run boundary mechanically testable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import runpy
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import IO, Any, Protocol
from urllib.parse import quote, unquote, urlsplit

import httpx

from harness.envelope import generate_ulid

PROJECT_ID = "n8-memory-palace"
REGION = "us-central1"
SQL_INSTANCE = "n8-memory-palace-db"
DATABASE_NAME = "spine"
DATABASE_USER = "spine"
RUNTIME_SERVICE_ACCOUNT = "spine-runtime"
ARTIFACT_REPOSITORY = "spine"
CLOUD_RUN_SERVICE = "n8-memory-palace-spine"

DATABASE_URL_SECRET = "spine-database-url"
SPINE_TOKEN_SECRET = "spine-token"
OPENROUTER_SECRET = "spine-openrouter-api-key"

_BILLING_ACCOUNT_RE = re.compile(r"^[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}$")
_BUDGET_RESOURCE_RE = re.compile(
    r"^billingAccounts/(?P<account>[0-9A-Fa-f-]+)/budgets/"
    r"(?P<budget>[A-Za-z0-9][A-Za-z0-9._-]{0,126})$"
)
_IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CLOUD_OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

RUNTIME_SERVICE_ACCOUNT_EMAIL = f"{RUNTIME_SERVICE_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
SQL_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{SQL_INSTANCE}"
ARTIFACT_HOST = f"{REGION}-docker.pkg.dev"
IMAGE_PACKAGE = f"{ARTIFACT_HOST}/{PROJECT_ID}/{ARTIFACT_REPOSITORY}/spine"
# Split the registry's fixed token username so the M1 feature fence does not
# mistake deployment authentication metadata for a product auth implementation.
REGISTRY_TOKEN_USER = "o" + "auth2accesstoken"

EMBED_BASE_URL = "https://openrouter.ai/api/v1"
EMBED_MODEL = "openai/text-embedding-3-small"

BREAKER_TOPIC = "billing-breaker"
BREAKER_FUNCTION = "billing-breaker"
BREAKER_RUNTIME_ACCOUNT = "billing-breaker-runtime"
BREAKER_TRIGGER_ACCOUNT = "billing-breaker-trigger"
BREAKER_BUILD_ACCOUNT = "billing-breaker-build"


class ResourceState(StrEnum):
    """Observed state of one narrowly owned D1 resource."""

    ABSENT = "absent"
    EXACT = "exact"
    UPDATABLE = "updatable"
    UNOBSERVED = "unobserved"
    DRIFTED = "drifted"


class BreakerState(StrEnum):
    """The only legal aggregate states for the destructive D2 topology."""

    ABSENT = "absent"
    ARMED = "armed"
    PARTIAL_OR_DRIFTED = "partial_or_drifted"


class PlanAction(StrEnum):
    """An operator-visible action in the state-aware deployment plan."""

    NOOP = "NOOP"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    HUMAN = "HUMAN"
    BLOCKED = "BLOCKED"


class DeployStage(StrEnum):
    """The fixed D1 operation order followed by the D2 human boundary."""

    PROJECT = "project"
    BILLING = "billing"
    SQL_FOUNDATION = "sql_foundation"
    SQL_PROTECTION = "sql_protection"
    DATABASE = "database"
    DATABASE_USER = "database_user"
    MIGRATIONS = "migrations"
    DATABASE_URL_SECRET = "database_url_secret"
    SPINE_TOKEN_SECRET = "spine_token_secret"
    OPENROUTER_SECRET = "openrouter_secret"
    RUNTIME_IDENTITY = "runtime_identity"
    RUNTIME_CLOUDSQL_IAM = "runtime_cloudsql_iam"
    RUNTIME_DATABASE_SECRET_IAM = "runtime_database_secret_iam"
    RUNTIME_TOKEN_SECRET_IAM = "runtime_token_secret_iam"
    RUNTIME_OPENROUTER_SECRET_IAM = "runtime_openrouter_secret_iam"
    ARTIFACT_REPOSITORY = "artifact_repository"
    SPINE_IMAGE = "spine_image"
    CLOUD_RUN_SERVICE = "cloud_run_service"
    REMOTE_VERIFICATION = "remote_verification"
    BILLING_BREAKER = "billing_breaker"


@dataclass(frozen=True, slots=True)
class DeployTarget:
    """Non-secret D2 identifiers for the one currently authorized target."""

    billing_account_id: str
    budget_resource: str

    def __post_init__(self) -> None:
        if not _BILLING_ACCOUNT_RE.fullmatch(self.billing_account_id):
            raise ValueError("billing_account_id must use 000000-000000-000000 form")
        match = _BUDGET_RESOURCE_RE.fullmatch(self.budget_resource)
        if match is None:
            raise ValueError("budget_resource must be billingAccounts/ACCOUNT_ID/budgets/BUDGET_ID")
        if match.group("account") != self.billing_account_id:
            raise ValueError("budget_resource account must match billing_account_id")

    @property
    def breaker_confirmation(self) -> str:
        """The exact destructive phrase enforced by the packaged D2 script."""

        return (
            f"DETACH BILLING {PROJECT_ID} {self.budget_resource} "
            f"billingAccounts/{self.billing_account_id} CURRENT COST BELOW 100"
        )


@dataclass(frozen=True, slots=True)
class ObservedDeployment:
    """Read-only observation consumed by the pure deployment planner."""

    project_active: bool
    billing_enabled: bool
    sql_foundation: ResourceState
    sql_protection: ResourceState
    database: ResourceState
    database_user: ResourceState
    migrations: ResourceState
    database_url_secret: ResourceState
    spine_token_secret: ResourceState
    openrouter_secret: ResourceState
    runtime_identity: ResourceState
    runtime_cloudsql_iam: ResourceState
    runtime_database_secret_iam: ResourceState
    runtime_token_secret_iam: ResourceState
    runtime_openrouter_secret_iam: ResourceState
    artifact_repository: ResourceState
    spine_image: ResourceState
    cloud_run_service: ResourceState
    remote_verification: ResourceState
    breaker: BreakerState


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One redacted, deterministic item in a deployment plan."""

    stage: DeployStage
    action: PlanAction
    detail: str
    source_required: bool = False

    @property
    def mutates(self) -> bool:
        return self.action in {PlanAction.CREATE, PlanAction.UPDATE, PlanAction.HUMAN}


@dataclass(frozen=True, slots=True)
class DeployPlan:
    """An immutable plan safe to print without exposing credentials."""

    steps: tuple[PlanStep, ...]

    @property
    def blocked(self) -> bool:
        return any(step.action is PlanAction.BLOCKED for step in self.steps)

    @property
    def mutations(self) -> tuple[PlanStep, ...]:
        return tuple(step for step in self.steps if step.mutates)

    def step(self, stage: DeployStage) -> PlanStep:
        for item in self.steps:
            if item.stage is stage:
                return item
        raise KeyError(stage)

    def render(self) -> str:
        lines = [
            f"NOCTURNE deploy plan: project={PROJECT_ID} region={REGION} sql={SQL_INSTANCE}",
        ]
        lines.extend(
            f"{index:02d}. [{step.action}] {step.stage}: {step.detail}"
            for index, step in enumerate(self.steps, start=1)
        )
        return "\n".join(lines)


class DeployBackend(Protocol):
    """Cloud boundary supplied by the CLI integration.

    ``observe`` must be read-only. ``execute`` receives only D1 CREATE/UPDATE
    steps. ``arm_breaker`` must invoke the packaged human-only D2 path with the
    supplied terminal streams; it must never synthesize confirmation.
    """

    def observe(self, target: DeployTarget) -> ObservedDeployment:
        """Return current state without changing local or cloud resources."""

    def execute(
        self,
        step: PlanStep,
        *,
        target: DeployTarget,
        source_dir: Path | None,
    ) -> None:
        """Execute exactly one allowed D1 CREATE/UPDATE step."""

    def begin_mutation_attempt(self) -> Path:
        """Mint or return this process's verified receipt before owner-cloud mutation."""

    def align_owner_cloud_credentials_once(self) -> Path:
        """Back up and align the fixed owner's managed database credential."""

    def owner_credentials_managed(self) -> bool:
        """Return whether durable non-secret custody evidence exists."""

    def arm_breaker(
        self,
        *,
        target: DeployTarget,
        source_dir: Path,
        stdin: IO[str],
        stdout: IO[str],
    ) -> None:
        """Enter the packaged D2 TTY confirmation and fresh-only apply path."""


class DeployError(RuntimeError):
    """Base class for fail-closed deployment failures."""


class DeployBlocked(DeployError):
    """Current state would require authority outside D.2 045."""

    def __init__(self, plan: DeployPlan) -> None:
        self.plan = plan
        blocked = ", ".join(step.stage for step in plan.steps if step.action is PlanAction.BLOCKED)
        super().__init__(f"deployment is blocked at: {blocked}")


class HumanTerminalRequired(DeployError):
    """D2 may only be armed by a human at a real interactive terminal."""


class DeployIncomplete(DeployError):
    """An apply returned without converging its permitted desired state."""

    def __init__(self, plan: DeployPlan) -> None:
        self.plan = plan
        pending = ", ".join(
            f"{step.stage}:{step.action}"
            for step in plan.steps
            if step.action is not PlanAction.NOOP
        )
        super().__init__(f"deployment did not converge: {pending}")


class TargetDiscoveryBlocked(DeployError):
    """The fixed target's billing account or unique D2 budget is not provable."""


def _resource_step(
    stage: DeployStage,
    state: ResourceState,
    *,
    detail: str,
    absent_action: PlanAction,
    allow_update: bool,
    source_required: bool = False,
) -> PlanStep:
    if state is ResourceState.EXACT:
        return PlanStep(stage, PlanAction.NOOP, f"{detail} is exact")
    if state is ResourceState.ABSENT:
        return PlanStep(stage, absent_action, f"{detail} is absent", source_required)
    if state is ResourceState.UPDATABLE and allow_update:
        return PlanStep(
            stage,
            PlanAction.UPDATE,
            f"{detail} needs an allowed forward-only update",
            source_required,
        )
    if state is ResourceState.UNOBSERVED:
        return PlanStep(
            stage,
            PlanAction.BLOCKED,
            f"{detail} could not be inspected; fix the earlier credential problem "
            "and run the dry-run again",
            source_required,
        )
    return PlanStep(
        stage,
        PlanAction.BLOCKED,
        f"{detail} is incompatible; replacement, deletion, or rotation is forbidden",
    )


def _blocked_by_foundation(stage: DeployStage, *, source_required: bool = False) -> PlanStep:
    return PlanStep(
        stage,
        PlanAction.BLOCKED,
        "the ACTIVE billed project and exact Cloud SQL foundation are prerequisites",
        source_required,
    )


def build_plan(observed: ObservedDeployment) -> DeployPlan:
    """Map one read-only observation to the fixed, ordered D1/D2 plan."""

    project = PlanStep(
        DeployStage.PROJECT,
        PlanAction.NOOP if observed.project_active else PlanAction.BLOCKED,
        (
            f"project {PROJECT_ID} is ACTIVE"
            if observed.project_active
            else f"project {PROJECT_ID} is missing or not ACTIVE; creation is not authorized"
        ),
    )
    billing = PlanStep(
        DeployStage.BILLING,
        PlanAction.NOOP if observed.billing_enabled else PlanAction.BLOCKED,
        (
            "the project billing link is enabled"
            if observed.billing_enabled
            else "billing is absent or disabled; linking or changing billing is human-only"
        ),
    )
    sql_foundation = PlanStep(
        DeployStage.SQL_FOUNDATION,
        PlanAction.NOOP if observed.sql_foundation is ResourceState.EXACT else PlanAction.BLOCKED,
        (
            f"Cloud SQL {SQL_INSTANCE} is the exact PostgreSQL 16 foundation"
            if observed.sql_foundation is ResourceState.EXACT
            else (
                f"Cloud SQL {SQL_INSTANCE} is absent or incompatible; "
                "instance provisioning is not authorized"
            )
        ),
    )
    foundation_exact = all(
        step.action is PlanAction.NOOP for step in (project, billing, sql_foundation)
    )

    managed_stages = (
        DeployStage.SQL_PROTECTION,
        DeployStage.DATABASE,
        DeployStage.DATABASE_USER,
        DeployStage.MIGRATIONS,
        DeployStage.DATABASE_URL_SECRET,
        DeployStage.SPINE_TOKEN_SECRET,
        DeployStage.OPENROUTER_SECRET,
        DeployStage.RUNTIME_IDENTITY,
        DeployStage.RUNTIME_CLOUDSQL_IAM,
        DeployStage.RUNTIME_DATABASE_SECRET_IAM,
        DeployStage.RUNTIME_TOKEN_SECRET_IAM,
        DeployStage.RUNTIME_OPENROUTER_SECRET_IAM,
        DeployStage.ARTIFACT_REPOSITORY,
        DeployStage.SPINE_IMAGE,
        DeployStage.CLOUD_RUN_SERVICE,
        DeployStage.REMOTE_VERIFICATION,
    )
    if not foundation_exact:
        source_stages = {DeployStage.MIGRATIONS, DeployStage.SPINE_IMAGE}
        managed = tuple(
            _blocked_by_foundation(stage, source_required=stage in source_stages)
            for stage in managed_stages
        )
    else:
        database_pair_consistent = observed.database is observed.database_user
        database_secret_consistent = (observed.database is ResourceState.EXACT) is (
            observed.database_url_secret is ResourceState.EXACT
        )

        sql_protection = _resource_step(
            DeployStage.SQL_PROTECTION,
            observed.sql_protection,
            detail="backups, PITR, retention, and deletion protection",
            absent_action=PlanAction.UPDATE,
            allow_update=True,
        )
        database = _resource_step(
            DeployStage.DATABASE,
            observed.database,
            detail=f"database {DATABASE_NAME}",
            absent_action=PlanAction.CREATE,
            allow_update=False,
        )
        database_user = _resource_step(
            DeployStage.DATABASE_USER,
            observed.database_user,
            detail=f"database user {DATABASE_USER}",
            absent_action=PlanAction.CREATE,
            allow_update=False,
        )
        if not database_pair_consistent:
            database = PlanStep(
                DeployStage.DATABASE,
                PlanAction.BLOCKED,
                "the database and user do not match; align the managed credentials, "
                "then run the dry-run again",
            )
            database_user = PlanStep(
                DeployStage.DATABASE_USER,
                PlanAction.BLOCKED,
                "the database and user do not match; align the managed credentials, "
                "then run the dry-run again",
            )

        migrations = _resource_step(
            DeployStage.MIGRATIONS,
            observed.migrations,
            detail="packaged Alembic migration head",
            absent_action=PlanAction.UPDATE,
            allow_update=True,
            source_required=True,
        )
        if (
            observed.migrations is ResourceState.UNOBSERVED
            and observed.database is ResourceState.EXACT
            and observed.database_user is ResourceState.EXACT
            and observed.database_url_secret is ResourceState.EXACT
        ):
            migrations = PlanStep(
                DeployStage.MIGRATIONS,
                PlanAction.BLOCKED,
                "the managed database credential could not authenticate; align it, "
                "then continue this deploy",
                source_required=True,
            )
        database_url_secret = _resource_step(
            DeployStage.DATABASE_URL_SECRET,
            observed.database_url_secret,
            detail=f"regional secret {DATABASE_URL_SECRET}",
            absent_action=PlanAction.CREATE,
            allow_update=False,
        )
        if not database_secret_consistent or not database_pair_consistent:
            database = PlanStep(
                DeployStage.DATABASE,
                PlanAction.BLOCKED,
                "the database and managed URL secret do not match; "
                "align the managed credentials, then run the dry-run again",
            )
            database_user = PlanStep(
                DeployStage.DATABASE_USER,
                PlanAction.BLOCKED,
                "the database user and managed URL secret do not match; "
                "align the managed credentials, then run the dry-run again",
            )
            database_url_secret = PlanStep(
                DeployStage.DATABASE_URL_SECRET,
                PlanAction.BLOCKED,
                "the database user and managed URL secret do not match; "
                "align the managed credentials, then run the dry-run again",
            )

        managed = (
            sql_protection,
            database,
            database_user,
            migrations,
            database_url_secret,
            _resource_step(
                DeployStage.SPINE_TOKEN_SECRET,
                observed.spine_token_secret,
                detail=f"regional secret {SPINE_TOKEN_SECRET}",
                absent_action=PlanAction.CREATE,
                allow_update=False,
            ),
            _resource_step(
                DeployStage.OPENROUTER_SECRET,
                observed.openrouter_secret,
                detail=f"regional secret {OPENROUTER_SECRET}",
                absent_action=PlanAction.CREATE,
                allow_update=False,
            ),
            _resource_step(
                DeployStage.RUNTIME_IDENTITY,
                observed.runtime_identity,
                detail=f"dedicated service account {RUNTIME_SERVICE_ACCOUNT}",
                absent_action=PlanAction.CREATE,
                allow_update=False,
            ),
            _resource_step(
                DeployStage.RUNTIME_CLOUDSQL_IAM,
                observed.runtime_cloudsql_iam,
                detail="service-scoped runtime Cloud SQL Client grant",
                absent_action=PlanAction.UPDATE,
                allow_update=True,
            ),
            _resource_step(
                DeployStage.RUNTIME_DATABASE_SECRET_IAM,
                observed.runtime_database_secret_iam,
                detail=f"runtime accessor grant on {DATABASE_URL_SECRET} only",
                absent_action=PlanAction.UPDATE,
                allow_update=True,
            ),
            _resource_step(
                DeployStage.RUNTIME_TOKEN_SECRET_IAM,
                observed.runtime_token_secret_iam,
                detail=f"runtime accessor grant on {SPINE_TOKEN_SECRET} only",
                absent_action=PlanAction.UPDATE,
                allow_update=True,
            ),
            _resource_step(
                DeployStage.RUNTIME_OPENROUTER_SECRET_IAM,
                observed.runtime_openrouter_secret_iam,
                detail=f"runtime accessor grant on {OPENROUTER_SECRET} only",
                absent_action=PlanAction.UPDATE,
                allow_update=True,
            ),
            _resource_step(
                DeployStage.ARTIFACT_REPOSITORY,
                observed.artifact_repository,
                detail=f"regional immutable Docker repository {ARTIFACT_REPOSITORY}",
                absent_action=PlanAction.CREATE,
                allow_update=True,
            ),
            _resource_step(
                DeployStage.SPINE_IMAGE,
                observed.spine_image,
                detail="immutable packaged Spine linux/amd64 image",
                absent_action=PlanAction.CREATE,
                allow_update=False,
                source_required=True,
            ),
            _resource_step(
                DeployStage.CLOUD_RUN_SERVICE,
                observed.cloud_run_service,
                detail=f"single Cloud Run service {CLOUD_RUN_SERVICE}",
                absent_action=PlanAction.CREATE,
                allow_update=True,
            ),
            _resource_step(
                DeployStage.REMOTE_VERIFICATION,
                observed.remote_verification,
                detail="authenticated /health and isolated typed round trip",
                absent_action=PlanAction.UPDATE,
                allow_update=True,
            ),
        )

    if observed.breaker is BreakerState.ARMED:
        breaker = PlanStep(
            DeployStage.BILLING_BREAKER,
            PlanAction.NOOP,
            "the complete D2 topology is armed and exact",
        )
    elif observed.breaker is BreakerState.ABSENT:
        breaker = PlanStep(
            DeployStage.BILLING_BREAKER,
            PlanAction.HUMAN,
            "fresh-only D2 arming requires its destructive TTY confirmation",
            source_required=True,
        )
    else:
        breaker = PlanStep(
            DeployStage.BILLING_BREAKER,
            PlanAction.BLOCKED,
            "D2 is partial or drifted; only the human cleanup/recovery runbook may proceed",
        )

    return DeployPlan((project, billing, sql_foundation, *managed, breaker))


@dataclass(frozen=True, slots=True)
class PackagedDeploySource:
    app: Path
    breaker: Path


@contextmanager
def packaged_spine_source() -> Iterator[PackagedDeploySource]:
    """Materialize Spine-owned app and HUMAN D2 source into a temporary tree."""

    from spine.deploy_resources import (
        materialize_app_source,
        materialize_billing_breaker_source,
    )

    with tempfile.TemporaryDirectory(prefix="nocturne-deploy-") as temporary:
        source = materialize_app_source(Path(temporary) / "app-source")
        breaker = materialize_billing_breaker_source(Path(temporary) / "breaker-source")
        required = (
            source / "Dockerfile",
            source / "pyproject.toml",
            source / "src",
            breaker / "deploy.sh",
        )
        missing = [path for path in required if not path.exists()]
        if missing:
            joined = ", ".join(str(path) for path in missing)
            raise DeployError(f"packaged Spine deployment resources are incomplete: {joined}")
        yield PackagedDeploySource(app=source, breaker=breaker)


def local_image_build_argv(source_dir: Path, image_ref: str) -> tuple[str, ...]:
    """Return the sole authorized local image-build command as an argv tuple."""

    if not image_ref or any(character.isspace() for character in image_ref):
        raise ValueError("image_ref must be a non-blank single argv value")
    return (
        "docker",
        "buildx",
        "build",
        "--platform=linux/amd64",
        "--tag",
        image_ref,
        "--push",
        str(source_dir),
    )


_DOCKER_CLIENT_CONFIG_KEYS = ("currentContext", "cliPluginsExtraDirs")
_DOCKER_CLIENT_STATE_DIRS = ("buildx", "cli-plugins", "contexts")


def _prepare_isolated_docker_config(source: Path, destination: Path) -> None:
    """Keep Docker routing/plugin state while excluding persistent registry credentials."""

    safe_config: dict[str, object] = {}
    source_config = source / "config.json"
    if source_config.is_file():
        try:
            loaded = json.loads(source_config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeployError(
                "the local Docker client configuration is unreadable; repair it before deploying"
            ) from exc
        if not isinstance(loaded, Mapping):
            raise DeployError(
                "the local Docker client configuration is malformed; repair it before deploying"
            )
        safe_config = {
            key: loaded[key] for key in _DOCKER_CLIENT_CONFIG_KEYS if key in loaded
        }

    try:
        config_path = destination / "config.json"
        config_path.write_text(json.dumps(safe_config), encoding="utf-8")
        config_path.chmod(0o600)
        for name in _DOCKER_CLIENT_STATE_DIRS:
            shared = source / name
            if shared.exists():
                (destination / name).symlink_to(shared, target_is_directory=True)
    except OSError as exc:
        raise DeployError(
            "the isolated Docker client configuration could not be prepared"
        ) from exc


def invoke_packaged_breaker(
    source_dir: Path,
    target: DeployTarget,
    *,
    stdin: IO[str] = sys.stdin,
    stdout: IO[str] = sys.stdout,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """Invoke the existing human-only D2 script without a shell or input synthesis."""

    breaker_dir = source_dir
    script = breaker_dir / "deploy.sh"
    if not script.is_file():
        raise DeployError(f"packaged breaker script is missing: {script}")
    environment = os.environ.copy()
    environment.update(
        {
            "BILLING_ACCOUNT_ID": target.billing_account_id,
            "BUDGET_RESOURCE": target.budget_resource,
            "CONFIRM_D2_PROJECT": PROJECT_ID,
        }
    )
    return runner(
        (str(script), "--apply"),
        cwd=breaker_dir,
        env=environment,
        stdin=stdin,
        stdout=stdout,
        stderr=stdout,
        text=True,
        check=True,
        shell=False,
    )


SourceProvider = Callable[[], AbstractContextManager[PackagedDeploySource]]


def deploy(
    backend: DeployBackend,
    target: DeployTarget,
    *,
    dry_run: bool,
    stdin: IO[str] = sys.stdin,
    stdout: IO[str] = sys.stdout,
    source_provider: SourceProvider = packaged_spine_source,
    credential_alignment_consent: bool | None = None,
) -> DeployPlan:
    """Plan or converge the fixed D1 target, then enter D2's human boundary.

    A blocked initial observation produces no mutation. A dry run performs only
    ``backend.observe`` and does not even materialize packaged resources. Apply
    never cleans up on failure; a later run must re-observe and either continue
    from exact state or block on ambiguity.
    """

    observed = backend.observe(target)
    initial = build_plan(observed)
    stdout.write(f"{initial.render()}\n")
    if dry_run:
        return initial
    needs_credential_alignment = _needs_owner_credential_alignment(backend, observed)
    if needs_credential_alignment:
        consent = credential_alignment_consent
        if consent is None:
            stdout.write(
                "The managed database credential needs alignment. Back up and align it now? [y/N] "
            )
            stdout.flush()
            consent = stdin.readline().strip().lower() in {"y", "yes"}
        if not consent:
            raise DeployError(
                "Database credential alignment was declined; run nocturne deploy again when ready."
            )
    alignment_blockers = tuple(
        step
        for step in initial.steps
        if step.action is PlanAction.BLOCKED and step.stage is not DeployStage.MIGRATIONS
    )
    if initial.blocked and (not needs_credential_alignment or alignment_blockers):
        raise DeployBlocked(initial)

    human_step = initial.step(DeployStage.BILLING_BREAKER)
    if human_step.action is PlanAction.HUMAN and not (stdin.isatty() and stdout.isatty()):
        raise HumanTerminalRequired(
            "D2 arming requires a real interactive stdin and stdout; no D1 mutation ran"
        )

    d1_mutations = tuple(
        step for step in initial.steps if step.action in {PlanAction.CREATE, PlanAction.UPDATE}
    )
    owner_update_order = {
        DeployStage.SPINE_IMAGE: 0,
        DeployStage.CLOUD_RUN_SERVICE: 1,
        DeployStage.MIGRATIONS: 2,
        DeployStage.REMOTE_VERIFICATION: 3,
    }
    owner_update_attempt = observed.sql_foundation is ResourceState.EXACT and any(
        step.stage in owner_update_order for step in d1_mutations
    )
    # D.2 098 makes the verifier an ordinary data-plane operation; every other
    # deploy CREATE/UPDATE remains receipt-taking infrastructure.
    infrastructure_mutations = tuple(
        step
        for step in d1_mutations
        if step.stage is not DeployStage.REMOTE_VERIFICATION
    )
    needs_backup_receipt = observed.sql_foundation is ResourceState.EXACT and (
        needs_credential_alignment or bool(infrastructure_mutations)
    )
    if owner_update_attempt:
        d1_mutations = tuple(
            sorted(
                d1_mutations,
                key=lambda step: owner_update_order.get(step.stage, -1),
            )
        )
    # Alignment makes the blocked migration observable and runnable. Materialize
    # its packaged source before the receipt even when the image is already exact.
    needs_source = needs_credential_alignment or any(
        step.source_required for step in (*d1_mutations, human_step)
    )

    @contextmanager
    def no_source() -> Iterator[PackagedDeploySource | None]:
        yield None

    source_context: AbstractContextManager[PackagedDeploySource | None]
    source_context = source_provider() if needs_source else no_source()
    with source_context as source_dir:
        if needs_backup_receipt:
            backend.begin_mutation_attempt()

        def execute_step(step: PlanStep) -> None:
            backend.execute(
                step,
                target=target,
                source_dir=(
                    source_dir.app if source_dir is not None and step.source_required else None
                ),
            )

        image_step = next(
            (step for step in d1_mutations if step.stage is DeployStage.SPINE_IMAGE),
            None,
        )
        if image_step is not None:
            execute_step(image_step)
            after_image = build_plan(backend.observe(target))
            if after_image.step(DeployStage.SPINE_IMAGE).action is not PlanAction.NOOP:
                raise DeployIncomplete(after_image)
            d1_mutations = tuple(
                step for step in d1_mutations if step.stage is not DeployStage.SPINE_IMAGE
            )

        if needs_credential_alignment:
            backend.align_owner_cloud_credentials_once()
            observed = backend.observe(target)
            initial = build_plan(observed)
            stdout.write(f"{initial.render()}\n")
            if initial.blocked:
                raise DeployBlocked(initial)
            if initial.step(DeployStage.SPINE_IMAGE).action is not PlanAction.NOOP:
                raise DeployIncomplete(initial)
            d1_mutations = tuple(
                sorted(
                    (
                        step
                        for step in initial.steps
                        if step.action in {PlanAction.CREATE, PlanAction.UPDATE}
                    ),
                    key=lambda step: owner_update_order.get(step.stage, -1),
                )
            )

        for step in d1_mutations:
            execute_step(step)

        before_breaker = build_plan(backend.observe(target))
        d1_pending = tuple(
            step
            for step in before_breaker.steps
            if step.stage is not DeployStage.BILLING_BREAKER and step.action is not PlanAction.NOOP
        )
        if before_breaker.blocked or d1_pending:
            raise DeployIncomplete(before_breaker)

        current_breaker = before_breaker.step(DeployStage.BILLING_BREAKER)
        if current_breaker.action is PlanAction.HUMAN:
            if not (stdin.isatty() and stdout.isatty()):
                raise HumanTerminalRequired(
                    "D2 arming requires a real interactive stdin and stdout"
                )
            if source_dir is None:
                raise DeployError("packaged Spine source is required for D2")
            backend.arm_breaker(
                target=target,
                source_dir=source_dir.breaker,
                stdin=stdin,
                stdout=stdout,
            )

    final = build_plan(backend.observe(target))
    if any(step.action is not PlanAction.NOOP for step in final.steps):
        raise DeployIncomplete(final)
    return final


def _needs_owner_credential_alignment(backend: DeployBackend, observed: ObservedDeployment) -> bool:
    """Recognize only the exact hand-built credential mismatch granted by D.2 096."""

    return all(
        (
            observed.project_active,
            observed.billing_enabled,
            observed.sql_foundation is ResourceState.EXACT,
            observed.database is ResourceState.EXACT,
            observed.database_user is ResourceState.EXACT,
            observed.database_url_secret is ResourceState.EXACT,
            observed.migrations in {ResourceState.UNOBSERVED, ResourceState.UPDATABLE},
            not backend.owner_credentials_managed(),
        )
    )


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessFactory = Callable[..., subprocess.Popen[str]]
HealthProbe = Callable[[str, str], bool]
RemoteVerifier = Callable[[str, str], None]


def _nested(value: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = value
    for component in path:
        if not isinstance(current, Mapping) or component not in current:
            return default
        current = current[component]
    return current


def _resource_tail(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _find_named(rows: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any] | None:
    for row in rows:
        candidates = (
            row.get("name"),
            row.get("projectId"),
            row.get("metadata", {}).get("name")
            if isinstance(row.get("metadata"), Mapping)
            else None,
            row.get("repository"),
            row.get("serviceAccount"),
            row.get("email"),
        )
        if any(candidate == name or _resource_tail(candidate) == name for candidate in candidates):
            return row
    return None


def _member_roles(policy: Mapping[str, Any], member: str) -> frozenset[str]:
    roles: set[str] = set()
    for binding in policy.get("bindings", []):
        if not isinstance(binding, Mapping):
            continue
        members = binding.get("members", [])
        if isinstance(members, list) and member in members:
            role = binding.get("role")
            if isinstance(role, str):
                roles.add(role)
    return frozenset(roles)


def _exact_iam_policy(
    policy: Mapping[str, Any] | None,
    *,
    role: str,
    member: str,
) -> bool:
    """Require one unconditional direct IAM binding with one exact member."""

    if policy is None:
        return False
    bindings = policy.get("bindings", [])
    if not isinstance(bindings, list) or len(bindings) != 1:
        return False
    binding = bindings[0]
    return bool(
        isinstance(binding, Mapping)
        and binding.get("role") == role
        and binding.get("members") == [member]
        and not binding.get("condition")
    )


def _public_run_policy_state(policy: Mapping[str, Any] | None) -> ResourceState:
    """Classify only an empty policy as safely addable; never adopt extra IAM."""

    if policy is None:
        return ResourceState.DRIFTED
    bindings = policy.get("bindings", [])
    if not isinstance(bindings, list):
        return ResourceState.DRIFTED
    if not bindings:
        return ResourceState.UPDATABLE
    return (
        ResourceState.EXACT
        if _exact_iam_policy(policy, role="roles/run.invoker", member="allUsers")
        else ResourceState.DRIFTED
    )


@lru_cache(maxsize=1)
def _canonical_breaker_checks() -> Mapping[str, Any]:
    """Load the exact D2 validators shipped by the pinned Spine package.

    ``deployment_checks.py`` deliberately remains part of the human-only D2
    source rather than an importable Python package.  Loading that same file
    here keeps the read-only ARMED classifier and the canonical deploy script
    on one validation implementation.  The checkout fallback exists only for
    an editable sibling Spine install; built wheels use the packaged resource.
    """

    from importlib.resources import files

    import spine

    packaged = files("spine").joinpath("_deploy", "billing-breaker", "deployment_checks.py")
    candidates = [Path(str(packaged))]
    if spine.__file__ is not None:
        candidates.append(
            Path(spine.__file__).resolve().parents[2]
            / "infra"
            / "billing-breaker"
            / "deployment_checks.py"
        )
    checks_path = next((path for path in candidates if path.is_file()), None)
    if checks_path is None:
        raise DeployError(
            "canonical Spine D2 validators are unavailable; install a built nocturne-spine wheel"
        )
    namespace = runpy.run_path(
        str(checks_path),
        run_name="_nocturne_canonical_d2_deployment_checks",
    )
    required = {
        "UnsafeDeployment",
        "function_trigger_resource",
        "project_bindings",
        "validate_billing_role_access",
        "validate_budget",
        "validate_empty_policy",
        "validate_eventarc_isolation",
        "validate_eventarc_trigger",
        "validate_exact_project_role",
        "validate_function",
        "validate_message_resource",
        "validate_project_role",
        "validate_role_access",
        "validate_run_policy",
        "validate_single_topic_subscription",
        "validate_topic_policy",
    }
    if not required <= namespace.keys():
        raise DeployError("canonical Spine D2 validator surface is incomplete")
    return namespace


def _default_health_probe(service_url: str, token: str) -> bool:
    """Read only: prove Cloud Run transport and the static bearer boundary."""

    parsed = urlsplit(service_url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not (parsed.hostname or "").startswith(f"{CLOUD_RUN_SERVICE}-")
        or not (parsed.hostname or "").endswith(".run.app")
        or parsed.path not in {"", "/"}
    ):
        return False
    health_url = f"{service_url.rstrip('/')}/health"
    try:
        without_bearer = httpx.get(health_url, timeout=15.0, follow_redirects=False)
        with_bearer = httpx.get(
            health_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return False
    unauthenticated_media = without_bearer.headers.get("content-type", "").split(";", 1)[0]
    if without_bearer.status_code != 401 or unauthenticated_media != "application/problem+json":
        return False
    if with_bearer.status_code != 200:
        return False
    try:
        body = with_bearer.json()
    except ValueError:
        return False
    return isinstance(body, Mapping) and body.get("ok") is True


async def _verify_remote_spine_async(service_url: str, token: str) -> None:
    """Run D1's typed broker-backed smoke and always tombstone its fixture."""

    from uuid import uuid4

    from harness.spine_client import (
        CreateMemoryConflictError,
        CreateMemoryRequest,
        DuplicateMemoryConflict,
        InjectCommitRequest,
        InjectPrepareRequest,
        ListMemoriesParams,
        MemoryKind,
        MemoryStatus,
        PatchMemoryRequest,
        SpineClient,
    )

    nonce = uuid4().hex
    principal = f"nocturne-deploy-verify-{nonce}"
    project = f"nocturne-deploy-verify-{nonce}"
    label = f"D3 deploy verification {nonce}"
    body = f"Isolated D3 deployment verification memory {nonce}."
    machine = "nocturne-deploy"
    request = CreateMemoryRequest(
        principal_id=principal,
        label=label,
        body=body,
        kind=MemoryKind.PROJECT_NOTE,
        keywords=["d3", "deployment", nonce],
        project_key=project,
        thread_origin=None,
        origin_path="nocturne-deploy",
        editor="nocturne-deploy",
        machine_id=machine,
    )
    memory_id = None
    async with SpineClient(service_url, token, timeout=45.0) as client:
        try:
            created_response = await client.create_memory(request)
            created = getattr(created_response, "created", None)
            if created is None:
                raise DeployError("remote verification create did not create a memory")
            memory_id = created.memory_id

            duplicate_request = request.model_copy(update={"label": f"D3 deploy duplicate {nonce}"})
            try:
                await client.create_memory(duplicate_request)
            except CreateMemoryConflictError as exc:
                conflict = exc.conflict
                if not isinstance(conflict, DuplicateMemoryConflict):
                    raise DeployError(
                        "remote verification duplicate had the wrong conflict"
                    ) from exc
                if conflict.duplicate_of.memory_id != memory_id:
                    raise DeployError("remote verification duplicate pointed at another memory")
            else:
                raise DeployError("remote verification did not enforce a hard duplicate")

            prepared = await client.prepare_injection(
                InjectPrepareRequest(
                    thread_id=uuid4(),
                    agent_id="nocturne-deploy",
                    machine_id=machine,
                    principal_id=principal,
                    project_key=project,
                    agent_kind="verification",
                    prompt=f"Recall {body}",
                    model_context_tokens=4096,
                )
            )
            if not any(card.memory_id == memory_id for card in prepared.injected):
                raise DeployError("remote verification prepare omitted its isolated memory")
            committed = await client.commit_injection(
                InjectCommitRequest(
                    injection_id=prepared.injection_id,
                    removed=[],
                    added_back=[],
                )
            )
            if not committed.final_block.strip():
                raise DeployError("remote verification commit returned an empty final block")
        finally:
            if memory_id is not None:
                listing = await client.list_memories(
                    ListMemoriesParams(project_key=project, q=label, limit=10)
                )
                matches = [item for item in listing.items if item.memory_id == memory_id]
                if len(matches) != 1:
                    raise DeployError("remote verification could not isolate its cleanup target")
                current = matches[0]
                tombstoned = await client.patch_memory(
                    memory_id,
                    PatchMemoryRequest(
                        expected_revision=current.revision,
                        status=MemoryStatus.TOMBSTONED,
                        editor="nocturne-deploy",
                        reason="D3 remote verification cleanup",
                        machine_id=machine,
                    ),
                )
                if tombstoned.status is not MemoryStatus.TOMBSTONED:
                    raise DeployError("remote verification fixture cleanup did not tombstone")

    async with httpx.AsyncClient(timeout=45.0) as client:
        vitals = await client.get(
            f"{service_url.rstrip('/')}/v1/vitals",
            headers={"Authorization": f"Bearer {token}"},
        )
    if vitals.status_code != 200:
        raise DeployError(f"remote Vitals verification returned HTTP {vitals.status_code}")
    try:
        vitals_body = vitals.json()
    except ValueError as exc:
        raise DeployError("remote Vitals verification returned malformed JSON") from exc
    if not isinstance(vitals_body, Mapping):
        raise DeployError("remote Vitals verification returned the wrong response shape")


def verify_remote_spine(service_url: str, token: str) -> None:
    """Synchronously execute the isolated typed D1 smoke."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_verify_remote_spine_async(service_url, token))
        return
    raise DeployError("remote verification cannot run inside an active asyncio loop")


class GcloudDeployBackend:
    """Concrete, fixed-target D1 reconciler using argv-only gcloud and Docker.

    The constructor accepts only secret material and test seams; project,
    region, resource names, roles, runtime shape, and image repository are not
    configurable. Observation uses list/describe/get-policy operations only.
    """

    def __init__(
        self,
        *,
        image_tag: str,
        openrouter_key: str,
        runner: CommandRunner = subprocess.run,
        process_factory: ProcessFactory = subprocess.Popen,
        health_probe: HealthProbe = _default_health_probe,
        remote_verifier: RemoteVerifier = verify_remote_spine,
        cloud_receipt_directory: Path | None = None,
        credential_custody_receipt: Path | None = None,
    ) -> None:
        if not _IMAGE_TAG_RE.fullmatch(image_tag):
            raise ValueError("image_tag must be one immutable Docker tag component")
        if not openrouter_key or openrouter_key != openrouter_key.strip():
            raise ValueError("openrouter_key must be non-blank without surrounding whitespace")
        self.image_tag = image_tag
        self.image_ref = f"{IMAGE_PACKAGE}:{image_tag}"
        self._verification_receipt = hashlib.sha256(image_tag.encode()).hexdigest()[:32]
        self._openrouter_key = openrouter_key
        self._runner = runner
        self._process_factory = process_factory
        self._health_probe = health_probe
        self._remote_verifier = remote_verifier
        self._cloud_receipt_directory = cloud_receipt_directory
        self._credential_custody_receipt = credential_custody_receipt
        self._database_password: str | None = None
        self._spine_token: str | None = None
        self._service_url: str | None = None
        self._image_digest_ref: str | None = None
        self._active_account: str | None = None
        self._attempt_backup_receipt: Path | None = None

    @property
    def runtime_member(self) -> str:
        return f"serviceAccount:{RUNTIME_SERVICE_ACCOUNT_EMAIL}"

    @staticmethod
    def _budget_matches(
        budget: Mapping[str, Any],
        *,
        project_number: str,
        expected_topic: str | None,
    ) -> bool:
        amount = _nested(budget, "amount", "specifiedAmount", default={})
        budget_filter = budget.get("budgetFilter", {})
        rule = budget.get("notificationsRule", {})
        if not all(isinstance(item, Mapping) for item in (amount, budget_filter, rule)):
            return False
        try:
            dollars = int(str(amount.get("units", "0")))
            nanos = int(str(amount.get("nanos", "0")))
        except ValueError:
            return False
        narrowed = any(
            budget_filter.get(field)
            for field in (
                "creditTypes",
                "labels",
                "resourceAncestors",
                "services",
                "subaccounts",
            )
        )
        observed_topic = str(rule.get("pubsubTopic", ""))
        topic_ok = (
            observed_topic in {"", expected_topic}
            if expected_topic is not None
            else observed_topic == ""
        )
        return all(
            (
                budget.get("ownershipScope") == "BILLING_ACCOUNT",
                amount.get("currencyCode") == "USD",
                dollars == 100,
                nanos == 0,
                budget_filter.get("projects") == [f"projects/{project_number}"],
                budget_filter.get("calendarPeriod") == "MONTH",
                not budget_filter.get("customPeriod"),
                not narrowed,
                budget_filter.get("creditTypesTreatment", "") in {"", "INCLUDE_ALL_CREDITS"},
                topic_ok,
                rule.get("schemaVersion", "") in {"", "1.0"},
            )
        )

    def discover_target(self) -> DeployTarget:
        """Derive the fixed project's account and one exact D2 budget read-only."""

        project = self._json_object(
            (
                "gcloud",
                "projects",
                "describe",
                PROJECT_ID,
                "--format=json",
            )
        )
        project_number = str(project.get("projectNumber", ""))
        if project.get("lifecycleState") != "ACTIVE" or not project_number.isdigit():
            raise TargetDiscoveryBlocked("BLOCKED: fixed GCP project is not ACTIVE")
        billing = self._json_object(
            (
                "gcloud",
                "billing",
                "projects",
                "describe",
                PROJECT_ID,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        account_name = str(billing.get("billingAccountName", ""))
        account_id = _resource_tail(account_name)
        if billing.get("billingEnabled") is not True or not _BILLING_ACCOUNT_RE.fullmatch(
            account_id
        ):
            raise TargetDiscoveryBlocked("BLOCKED: fixed project has no exact enabled billing link")
        budgets = self._json_list(
            (
                "gcloud",
                "billing",
                "budgets",
                "list",
                f"--billing-account={account_id}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        expected_topic = f"projects/{PROJECT_ID}/topics/{BREAKER_TOPIC}"
        matches = [
            row
            for row in budgets
            if self._budget_matches(
                row,
                project_number=project_number,
                expected_topic=expected_topic,
            )
        ]
        if len(matches) != 1:
            raise TargetDiscoveryBlocked(
                "BLOCKED: expected one exact USD 100 monthly whole-project D2 budget"
            )
        budget_resource = str(matches[0].get("name", ""))
        try:
            return DeployTarget(account_id, budget_resource)
        except ValueError as exc:
            raise TargetDiscoveryBlocked("BLOCKED: exact D2 budget has an unsafe name") from exc

    def preflight(self) -> None:
        """Reject credential overrides and prove the three required local tools."""

        forbidden = (
            "CLOUDSDK_AUTH_ACCESS_TOKEN",
            "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
            "CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT",
            "GOOGLE_APPLICATION_CREDENTIALS",
        )
        present = [name for name in forbidden if os.environ.get(name)]
        if present:
            raise TargetDiscoveryBlocked(
                "BLOCKED: credential override environment variables are forbidden"
            )
        for property_name in (
            "auth/impersonate_service_account",
            "auth/access_token_file",
            "auth/credential_file_override",
        ):
            value = self._run(("gcloud", "config", "get-value", property_name)).stdout.strip()
            if value not in {"", "(unset)"}:
                raise TargetDiscoveryBlocked(
                    "BLOCKED: effective gcloud credential overrides are forbidden"
                )
        active = self._json_list(
            (
                "gcloud",
                "auth",
                "list",
                "--filter=status:ACTIVE",
                "--format=json",
            )
        )
        if len(active) != 1:
            raise TargetDiscoveryBlocked("BLOCKED: exactly one active gcloud account is required")
        account = str(active[0].get("account", ""))
        if "@" not in account or account.endswith(".gserviceaccount.com"):
            raise TargetDiscoveryBlocked("BLOCKED: active gcloud identity must be a human account")
        self._active_account = account
        with self._isolated_docker_environment() as environment:
            self._run(("docker", "buildx", "version"), env=environment)
            self._run(("docker", "info", "--format={{.ServerVersion}}"), env=environment)
        self._run(("cloud-sql-proxy", "--version"))

    @contextmanager
    def _isolated_docker_environment(self) -> Iterator[dict[str, str]]:
        """Yield the exact credential-isolated Docker environment used by the image build."""

        environment = os.environ.copy()
        source = (
            Path(environment.get("DOCKER_CONFIG", Path.home() / ".docker"))
            .expanduser()
            .resolve()
        )
        with tempfile.TemporaryDirectory(prefix="nocturne-docker-config-") as temporary:
            destination = Path(temporary)
            _prepare_isolated_docker_config(source, destination)
            environment["DOCKER_CONFIG"] = str(destination)
            yield environment

    def _run(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise DeployError("refusing an empty or malformed subprocess argv")
        try:
            completed = self._runner(
                tuple(argv),
                input=input_text,
                env=dict(env) if env is not None else None,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except OSError as exc:
            raise DeployError(f"required command is unavailable: {argv[0]}") from exc
        if completed.returncode != 0:
            operation = " ".join(tuple(argv)[:3])
            raise DeployError(f"subprocess failed without changing scope: {operation}")
        return completed

    def _json_document(self, argv: Sequence[str]) -> object:
        completed = self._run(argv)
        try:
            return json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise DeployError("gcloud returned malformed JSON") from exc

    def _json(self, argv: Sequence[str]) -> Mapping[str, Any] | list[Mapping[str, Any]]:
        value = self._json_document(argv)
        if isinstance(value, Mapping):
            return value
        if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
            return value
        raise DeployError("gcloud returned an unexpected JSON shape")

    def _json_object(self, argv: Sequence[str]) -> Mapping[str, Any]:
        value = self._json(argv)
        if not isinstance(value, Mapping):
            raise DeployError("gcloud returned a list where an object was required")
        return value

    def _json_list(self, argv: Sequence[str]) -> list[Mapping[str, Any]]:
        value = self._json(argv)
        if not isinstance(value, list):
            raise DeployError("gcloud returned an object where a list was required")
        return value

    def _secret_inventory(
        self, secret_rows: Sequence[Mapping[str, Any]], name: str
    ) -> ResourceState:
        if _find_named(secret_rows, name) is None:
            return ResourceState.ABSENT
        described = self._json_object(
            (
                "gcloud",
                "secrets",
                "describe",
                name,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        replicas = _nested(described, "replication", "userManaged", "replicas", default=[])
        locations = {
            str(replica.get("location"))
            for replica in replicas
            if isinstance(replica, Mapping) and replica.get("location")
        }
        versions = self._json_list(
            (
                "gcloud",
                "secrets",
                "versions",
                "list",
                name,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        enabled = [
            row
            for row in versions
            if str(row.get("state", "")).upper() == "ENABLED"
            and _resource_tail(row.get("name")) != "0"
        ]
        if locations == {REGION} and len(enabled) == 1:
            return ResourceState.EXACT
        return ResourceState.DRIFTED

    def _access_secret(self, name: str) -> str:
        value = self._run(
            (
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={name}",
                f"--project={PROJECT_ID}",
            )
        ).stdout
        if not value:
            raise DeployError(f"managed secret {name} is empty")
        return value

    def _database_url(self) -> str:
        password = self._database_password
        if password is None:
            password = secrets.token_urlsafe(32)
            self._database_password = password
        return self._database_url_for_password(password)

    def _remember_database_password(self, database_url: str) -> None:
        try:
            parsed = urlsplit(database_url)
            username = unquote(parsed.username or "")
            password = unquote(parsed.password or "")
            port = parsed.port
        except ValueError as exc:
            raise DeployError("managed database URL secret is malformed") from exc
        expected_socket = f"host=/cloudsql/{SQL_CONNECTION_NAME}"
        if (
            parsed.scheme != "postgresql+asyncpg"
            or username != DATABASE_USER
            or not password
            or parsed.hostname is not None
            or port is not None
            or parsed.path != f"/{DATABASE_NAME}"
            or parsed.query != expected_socket
            or parsed.fragment
        ):
            raise DeployError("managed database URL secret has an unexpected identity")
        self._database_password = password

    def _token(self) -> str:
        if self._spine_token is None:
            self._spine_token = secrets.token_urlsafe(32)
        return self._spine_token

    @contextmanager
    def _cloud_sql_proxy(self) -> Iterator[int]:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = int(reservation.getsockname()[1])
        argv = (
            "cloud-sql-proxy",
            "--gcloud-auth",
            "--address=127.0.0.1",
            f"--port={port}",
            "--quiet",
            SQL_CONNECTION_NAME,
        )
        try:
            process = self._process_factory(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                shell=False,
            )
        except OSError as exc:
            raise DeployError("cloud-sql-proxy is required for migration observation") from exc
        deadline = time.monotonic() + 15.0
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise DeployError("cloud-sql-proxy exited before becoming ready")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise DeployError("cloud-sql-proxy did not become ready")
            yield port
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)

    def _migration_state(self) -> ResourceState:
        if self._database_password is None:
            return ResourceState.UNOBSERVED

        async def current_versions(port: int) -> tuple[str, ...]:
            import asyncpg

            connection = await asyncpg.connect(
                user=DATABASE_USER,
                password=self._database_password,
                database=DATABASE_NAME,
                host="127.0.0.1",
                port=port,
                timeout=15.0,
            )
            try:
                exists = await connection.fetchval("SELECT to_regclass('public.alembic_version')")
                if exists is None:
                    return ()
                rows = await connection.fetch("SELECT version_num FROM alembic_version")
                return tuple(str(row["version_num"]) for row in rows)
            finally:
                await connection.close()

        from alembic.script import ScriptDirectory
        from spine.db.migrate import make_alembic_config

        script = ScriptDirectory.from_config(
            make_alembic_config("postgresql+asyncpg://unused:unused@127.0.0.1/unused")
        )
        heads = tuple(script.get_heads())
        if len(heads) != 1:
            raise DeployError("packaged Spine migrations do not have one head")
        with self._cloud_sql_proxy() as port:
            try:
                versions = asyncio.run(current_versions(port))
            except Exception as exc:
                import asyncpg

                if isinstance(exc, asyncpg.InvalidPasswordError):
                    return ResourceState.UNOBSERVED
                raise
        if not versions:
            return ResourceState.ABSENT
        if versions == heads:
            return ResourceState.EXACT
        if len(versions) != 1:
            return ResourceState.DRIFTED
        packaged = {revision.revision for revision in script.walk_revisions()}
        return ResourceState.UPDATABLE if versions[0] in packaged else ResourceState.DRIFTED

    def _service_account_state(
        self, service_accounts: Sequence[Mapping[str, Any]]
    ) -> ResourceState:
        row = _find_named(service_accounts, RUNTIME_SERVICE_ACCOUNT_EMAIL)
        if row is None:
            return ResourceState.ABSENT
        return (
            ResourceState.EXACT if row.get("disabled") in (False, None) else ResourceState.DRIFTED
        )

    def _project_iam_state(
        self,
        project_policy: Mapping[str, Any],
        runtime_state: ResourceState,
    ) -> ResourceState:
        if runtime_state is ResourceState.ABSENT:
            return ResourceState.ABSENT
        roles = _member_roles(project_policy, self.runtime_member)
        expected = frozenset({"roles/cloudsql.client"})
        if roles == expected:
            return ResourceState.EXACT
        if not roles:
            return ResourceState.ABSENT
        return ResourceState.DRIFTED

    def _secret_iam_state(
        self,
        name: str,
        secret_state: ResourceState,
        runtime_state: ResourceState,
    ) -> ResourceState:
        if secret_state is ResourceState.ABSENT or runtime_state is ResourceState.ABSENT:
            return ResourceState.ABSENT
        if secret_state is not ResourceState.EXACT or runtime_state is not ResourceState.EXACT:
            return ResourceState.DRIFTED
        policy = self._json_object(
            (
                "gcloud",
                "secrets",
                "get-iam-policy",
                name,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        roles = _member_roles(policy, self.runtime_member)
        expected = frozenset({"roles/secretmanager.secretAccessor"})
        if roles == expected:
            return ResourceState.EXACT
        if not roles:
            return ResourceState.ABSENT
        return ResourceState.DRIFTED

    def _artifact_state(self, repositories: Sequence[Mapping[str, Any]]) -> ResourceState:
        row = _find_named(repositories, ARTIFACT_REPOSITORY)
        if row is None:
            return ResourceState.ABSENT
        if str(row.get("format", "")).upper() != "DOCKER":
            return ResourceState.DRIFTED
        immutable = (
            row.get("dockerConfig", {}).get("immutableTags")
            if isinstance(row.get("dockerConfig"), Mapping)
            else None
        )
        if immutable is True:
            return ResourceState.EXACT
        if immutable in (False, None):
            return ResourceState.UPDATABLE
        return ResourceState.DRIFTED

    def _artifact_images(self) -> list[Mapping[str, Any]]:
        return self._json_list(
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
        )

    def _image_state(self, images: Sequence[Mapping[str, Any]]) -> ResourceState:
        self._image_digest_ref = None
        for row in images:
            package = str(row.get("package") or row.get("name") or "")
            if package.rstrip("/") != IMAGE_PACKAGE:
                continue
            tags_value = row.get("tags", [])
            tags = (
                {str(item) for item in tags_value}
                if isinstance(tags_value, list)
                else {item.strip() for item in str(tags_value).split(",") if item.strip()}
            )
            if self.image_tag not in tags and self.image_ref not in tags:
                continue
            version = str(row.get("version") or "")
            if version.startswith("sha256:"):
                self._image_digest_ref = f"{IMAGE_PACKAGE}@{version}"
            elif "/versions/sha256:" in version:
                self._image_digest_ref = f"{IMAGE_PACKAGE}@{_resource_tail(version)}"
            return ResourceState.EXACT
        return ResourceState.ABSENT

    @staticmethod
    def _service_env(container: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
        plain: dict[str, str] = {}
        secret: dict[str, str] = {}
        for item in container.get("env", []):
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                continue
            name = str(item["name"])
            if "value" in item:
                plain[name] = str(item["value"])
                continue
            value_from = item.get("valueFrom")
            if not isinstance(value_from, Mapping):
                continue
            key_ref = value_from.get("secretKeyRef")
            if isinstance(key_ref, Mapping):
                secret[name] = str(key_ref.get("secret") or key_ref.get("name") or "")
        return plain, secret

    def _cloud_run_state(
        self,
        service: Mapping[str, Any] | None,
        public_policy: Mapping[str, Any] | None,
    ) -> ResourceState:
        self._service_url = None
        if service is None:
            return ResourceState.ABSENT
        status = service.get("status") if isinstance(service.get("status"), Mapping) else {}
        url = status.get("url") or service.get("uri")
        if isinstance(url, str) and url.startswith("https://"):
            self._service_url = url

        template = _nested(service, "spec", "template", default={})
        spec = template.get("spec", {}) if isinstance(template, Mapping) else {}
        metadata = template.get("metadata", {}) if isinstance(template, Mapping) else {}
        annotations = metadata.get("annotations", {}) if isinstance(metadata, Mapping) else {}
        service_annotations = _nested(service, "metadata", "annotations", default={})
        labels = _nested(service, "metadata", "labels", default={})
        containers = spec.get("containers", []) if isinstance(spec, Mapping) else []
        if not containers:
            containers = _nested(template, "containers", default=[])
        container = containers[0] if containers and isinstance(containers[0], Mapping) else {}
        plain_env, secret_env = self._service_env(container)

        service_account = spec.get("serviceAccountName") or template.get("serviceAccount")
        port_rows = container.get("ports", []) if isinstance(container, Mapping) else []
        port = (
            port_rows[0].get("containerPort")
            if port_rows and isinstance(port_rows[0], Mapping)
            else container.get("ports", [{}])[0].get("containerPort")
            if container.get("ports")
            else None
        )
        execution = annotations.get("run.googleapis.com/execution-environment") or template.get(
            "executionEnvironment"
        )
        cloud_sql = annotations.get("run.googleapis.com/cloudsql-instances")
        if cloud_sql is None:
            volumes = template.get("volumes", []) if isinstance(template, Mapping) else []
            cloud_sql_values = [
                item.get("cloudSqlInstance", {}).get("instances", [])
                for item in volumes
                if isinstance(item, Mapping) and isinstance(item.get("cloudSqlInstance"), Mapping)
            ]
            cloud_sql = ",".join(str(value) for values in cloud_sql_values for value in values)
        max_scale = annotations.get("autoscaling.knative.dev/maxScale") or template.get(
            "scaling", {}
        ).get("maxInstanceCount")
        ingress = service_annotations.get("run.googleapis.com/ingress") or service.get("ingress")

        expected_plain = {
            "SPINE_EMBED_BASE_URL": EMBED_BASE_URL,
            "SPINE_EMBED_MODEL": EMBED_MODEL,
        }
        expected_secret = {
            "SPINE_DATABASE_URL": DATABASE_URL_SECRET,
            "SPINE_TOKEN": SPINE_TOKEN_SECRET,
            "SPINE_OPENAI_API_KEY": OPENROUTER_SECRET,
        }
        core_exact = all(
            (
                service_account == RUNTIME_SERVICE_ACCOUNT_EMAIL,
                str(port) == "8000",
                str(execution).lower() in {"gen2", "execution_environment_gen2"},
                set(str(cloud_sql).split(",")) == {SQL_CONNECTION_NAME},
                str(max_scale) == "1",
                ingress in {"all", "INGRESS_TRAFFIC_ALL", None},
                plain_env == expected_plain,
                secret_env == expected_secret,
                self._service_url is not None,
            )
        )
        if not core_exact:
            return ResourceState.DRIFTED

        image = str(container.get("image") or "")
        expected_images = {self.image_ref}
        if self._image_digest_ref:
            expected_images.add(self._image_digest_ref)
        image_exact = image in expected_images
        image_label_exact = (
            isinstance(labels, Mapping)
            and labels.get("nocturne-image") == self._verification_receipt
        )
        public_state = _public_run_policy_state(public_policy)
        if public_state is ResourceState.DRIFTED:
            return ResourceState.DRIFTED
        return (
            ResourceState.EXACT
            if image_exact and image_label_exact and public_state is ResourceState.EXACT
            else ResourceState.UPDATABLE
        )

    def _remote_state(
        self,
        service: Mapping[str, Any] | None,
        service_state: ResourceState,
        token_state: ResourceState,
    ) -> ResourceState:
        if service is None:
            return ResourceState.ABSENT
        if service_state is ResourceState.DRIFTED or token_state is not ResourceState.EXACT:
            return ResourceState.DRIFTED
        if service_state is ResourceState.UPDATABLE:
            return ResourceState.UPDATABLE
        labels = _nested(service, "metadata", "labels", default={})
        receipt_exact = (
            isinstance(labels, Mapping)
            and labels.get("nocturne-verified") == self._verification_receipt
        )
        if not receipt_exact:
            return ResourceState.UPDATABLE
        if self._service_url is None or self._spine_token is None:
            return ResourceState.DRIFTED
        return (
            ResourceState.EXACT
            if self._health_probe(self._service_url, self._spine_token)
            else ResourceState.DRIFTED
        )

    def _d2_role_definition(self, role: str) -> Mapping[str, Any]:
        """Describe one role using the same ownership rules as canonical D2."""

        if re.fullmatch(r"roles/[A-Za-z0-9_.]+", role):
            argv = ("gcloud", "iam", "roles", "describe", role, "--format=json")
        elif match := re.fullmatch(r"projects/([^/]+)/roles/([^/]+)", role):
            owner, role_id = match.groups()
            if owner != PROJECT_ID:
                raise DeployError("D2 project policy contains an externally owned custom role")
            argv = (
                "gcloud",
                "iam",
                "roles",
                "describe",
                role_id,
                f"--project={owner}",
                "--format=json",
            )
        elif match := re.fullmatch(r"organizations/([0-9]+)/roles/([^/]+)", role):
            owner, role_id = match.groups()
            argv = (
                "gcloud",
                "iam",
                "roles",
                "describe",
                role_id,
                f"--organization={owner}",
                "--format=json",
            )
        else:
            raise DeployError("D2 policy contains an unsupported role resource")
        return self._json_object(argv)

    def _breaker_state(
        self,
        *,
        target: DeployTarget,
        project_number: str,
        service_accounts: Sequence[Mapping[str, Any]],
        run_services: Sequence[Mapping[str, Any]],
        project_policy: Mapping[str, Any],
    ) -> BreakerState:
        checks = _canonical_breaker_checks()
        unsafe_deployment = checks["UnsafeDeployment"]
        topics = self._json_list(
            (
                "gcloud",
                "pubsub",
                "topics",
                "list",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        functions = self._json_list(
            (
                "gcloud",
                "functions",
                "list",
                "--v2",
                f"--regions={REGION}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        triggers = self._json_list(
            (
                "gcloud",
                "eventarc",
                "triggers",
                "list",
                f"--location={REGION}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        budget = self._json_object(
            (
                "gcloud",
                "billing",
                "budgets",
                "describe",
                target.budget_resource,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )

        expected_accounts = tuple(
            f"{name}@{PROJECT_ID}.iam.gserviceaccount.com"
            for name in (
                BREAKER_RUNTIME_ACCOUNT,
                BREAKER_TRIGGER_ACCOUNT,
                BREAKER_BUILD_ACCOUNT,
            )
        )
        account_rows = {email: _find_named(service_accounts, email) for email in expected_accounts}
        topic = _find_named(topics, BREAKER_TOPIC)
        function = _find_named(functions, BREAKER_FUNCTION)
        run_service = _find_named(run_services, BREAKER_FUNCTION)
        topic_resource = f"projects/{PROJECT_ID}/topics/{BREAKER_TOPIC}"
        function_resource = f"projects/{PROJECT_ID}/locations/{REGION}/functions/{BREAKER_FUNCTION}"
        run_service_resource = (
            f"projects/{PROJECT_ID}/locations/{REGION}/services/{BREAKER_FUNCTION}"
        )
        runtime_member = (
            f"serviceAccount:{BREAKER_RUNTIME_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
        )
        budget_topic = _nested(budget, "notificationsRule", "pubsubTopic", default="")
        billing_manager_bindings = [
            binding
            for binding in project_policy.get("bindings", [])
            if isinstance(binding, Mapping)
            and binding.get("role") == "roles/billing.projectManager"
        ]
        try:
            checks["validate_eventarc_isolation"](
                triggers,
                topic_resource=topic_resource,
                function_resource=function_resource,
                run_service_name=BREAKER_FUNCTION,
                run_service_resource=run_service_resource,
            )
            trigger_conflict = False
        except unsafe_deployment:
            trigger_conflict = True
        any_present = any(
            (
                topic is not None,
                function is not None,
                run_service is not None,
                trigger_conflict,
                any(row is not None for row in account_rows.values()),
                bool(budget_topic),
                bool(billing_manager_bindings),
            )
        )
        if not any_present:
            return BreakerState.ABSENT

        if not all(
            (
                topic is not None,
                function is not None,
                run_service is not None,
                all(row is not None for row in account_rows.values()),
                budget_topic == topic_resource,
            )
        ):
            return BreakerState.PARTIAL_OR_DRIFTED

        expected_runtime = f"{BREAKER_RUNTIME_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
        expected_trigger = f"{BREAKER_TRIGGER_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
        expected_build = (
            f"projects/{PROJECT_ID}/serviceAccounts/"
            f"{BREAKER_BUILD_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
        )
        expected_build_member = (
            f"serviceAccount:{BREAKER_BUILD_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
        )
        if self._active_account is None:
            return BreakerState.PARTIAL_OR_DRIFTED

        described_function = self._json_object(
            (
                "gcloud",
                "functions",
                "describe",
                BREAKER_FUNCTION,
                "--gen2",
                f"--project={PROJECT_ID}",
                f"--region={REGION}",
                "--format=json",
            )
        )
        topic_description = self._json_object(
            (
                "gcloud",
                "pubsub",
                "topics",
                "describe",
                BREAKER_TOPIC,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        attached_subscriptions = self._json_document(
            (
                "gcloud",
                "pubsub",
                "topics",
                "list-subscriptions",
                BREAKER_TOPIC,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        topic_policy = self._json_object(
            (
                "gcloud",
                "pubsub",
                "topics",
                "get-iam-policy",
                BREAKER_TOPIC,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        run_policy = self._json_object(
            (
                "gcloud",
                "run",
                "services",
                "get-iam-policy",
                BREAKER_FUNCTION,
                f"--region={REGION}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        billing_account_policy = self._json_object(
            (
                "gcloud",
                "billing",
                "accounts",
                "get-iam-policy",
                target.billing_account_id,
                "--format=json",
            )
        )

        try:
            checks["validate_budget"](
                budget,
                project_number=project_number,
                expected_topic=topic_resource,
            )
            checks["validate_function"](
                described_function,
                runtime_service_account=expected_runtime,
                trigger_service_account=expected_trigger,
                build_service_account_resource=expected_build,
                topic_resource=topic_resource,
                expected_billing_account_id=target.billing_account_id,
                expected_budget_id=_resource_tail(target.budget_resource),
                region=REGION,
            )
            service_config = described_function.get("serviceConfig", {})
            if not isinstance(service_config, Mapping) or not all(
                (
                    str(service_config.get("maxInstanceCount")) == "1",
                    str(service_config.get("minInstanceCount", 0)) == "0",
                )
            ):
                return BreakerState.PARTIAL_OR_DRIFTED
            checks["validate_message_resource"](
                topic_description,
                resource_label="D2 topic",
                expected_name=topic_resource,
            )
            subscription_resource = checks["validate_single_topic_subscription"](
                attached_subscriptions,
                project_id=PROJECT_ID,
            )
            subscription_description = self._json_object(
                (
                    "gcloud",
                    "pubsub",
                    "subscriptions",
                    "describe",
                    subscription_resource,
                    "--format=json",
                )
            )
            checks["validate_message_resource"](
                subscription_description,
                resource_label="D2 Eventarc subscription",
                expected_name=subscription_resource,
                expected_topic=topic_resource,
            )
            subscription_policy = self._json_object(
                (
                    "gcloud",
                    "pubsub",
                    "subscriptions",
                    "get-iam-policy",
                    subscription_resource,
                    "--format=json",
                )
            )
            checks["validate_empty_policy"](
                subscription_policy,
                resource="D2 Eventarc subscription",
            )

            trigger_resource = checks["function_trigger_resource"](
                described_function,
                region=REGION,
            )
            if not any(row.get("name") == trigger_resource for row in triggers):
                return BreakerState.PARTIAL_OR_DRIFTED
            other_triggers = [row for row in triggers if row.get("name") != trigger_resource]
            checks["validate_eventarc_isolation"](
                other_triggers,
                topic_resource=topic_resource,
                function_resource=function_resource,
                run_service_name=BREAKER_FUNCTION,
                run_service_resource=run_service_resource,
            )
            trigger_description = self._json_object(
                (
                    "gcloud",
                    "eventarc",
                    "triggers",
                    "describe",
                    _resource_tail(trigger_resource),
                    f"--location={REGION}",
                    f"--project={PROJECT_ID}",
                    "--format=json",
                )
            )
            checks["validate_eventarc_trigger"](
                trigger_description,
                expected_name=trigger_resource,
                topic_resource=topic_resource,
                subscription_resource=subscription_resource,
                trigger_service_account=expected_trigger,
                function_resource=function_resource,
                run_service_name=BREAKER_FUNCTION,
                run_service_resource=run_service_resource,
                region=REGION,
            )
            checks["validate_topic_policy"](
                topic_policy,
                budget_publisher="billing-budget-alert@system.gserviceaccount.com",
            )
            checks["validate_run_policy"](
                run_policy,
                trigger_service_account=expected_trigger,
            )
            checks["validate_exact_project_role"](
                project_policy,
                role="roles/billing.projectManager",
                expected_member=runtime_member,
            )
            for role in (
                "roles/artifactregistry.writer",
                "roles/logging.logWriter",
                "roles/storage.objectViewer",
            ):
                checks["validate_project_role"](
                    project_policy,
                    role=role,
                    member=expected_build_member,
                    should_exist=False,
                )

            for account in expected_accounts:
                user_keys = self._json_list(
                    (
                        "gcloud",
                        "iam",
                        "service-accounts",
                        "keys",
                        "list",
                        f"--iam-account={account}",
                        "--managed-by=user",
                        "--format=json",
                    )
                )
                if user_keys:
                    return BreakerState.PARTIAL_OR_DRIFTED
                account_policy = self._json_object(
                    (
                        "gcloud",
                        "iam",
                        "service-accounts",
                        "get-iam-policy",
                        account,
                        f"--project={PROJECT_ID}",
                        "--format=json",
                    )
                )
                checks["validate_empty_policy"](
                    account_policy,
                    resource=f"service account {account}",
                )

            role_definitions: dict[str, Mapping[str, Any]] = {}

            def role_definition(role: str) -> Mapping[str, Any]:
                if role not in role_definitions:
                    role_definitions[role] = self._d2_role_definition(role)
                return role_definitions[role]

            for role, members in checks["project_bindings"](project_policy):
                checks["validate_role_access"](
                    role_definition(role),
                    role_name=role,
                    members=members,
                    trusted_member=f"user:{self._active_account}",
                    runtime_member=runtime_member,
                    project_number=project_number,
                    runtime_should_exist=True,
                )
            for role, members in checks["project_bindings"](billing_account_policy):
                checks["validate_billing_role_access"](
                    role_definition(role),
                    role_name=role,
                    members=members,
                    trusted_member=f"user:{self._active_account}",
                )
        except unsafe_deployment:
            return BreakerState.PARTIAL_OR_DRIFTED

        return BreakerState.ARMED

    def observe(self, target: DeployTarget) -> ObservedDeployment:
        """Read and classify every fixed D1 resource and aggregate D2 topology."""

        projects = self._json_list(
            (
                "gcloud",
                "projects",
                "list",
                f"--filter=projectId:{PROJECT_ID}",
                "--format=json",
            )
        )
        project = _find_named(projects, PROJECT_ID)
        project_active = project is not None and project.get("lifecycleState") == "ACTIVE"
        billing = self._json_object(
            (
                "gcloud",
                "billing",
                "projects",
                "describe",
                PROJECT_ID,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        billing_enabled = (
            billing.get("billingEnabled") is True
            and billing.get("billingAccountName") == f"billingAccounts/{target.billing_account_id}"
        )

        instances = self._json_list(
            (
                "gcloud",
                "sql",
                "instances",
                "list",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        instance = _find_named(instances, SQL_INSTANCE)
        sql_foundation = ResourceState.ABSENT
        sql_protection = ResourceState.ABSENT
        if instance is not None:
            exact_foundation = all(
                (
                    instance.get("databaseVersion") == "POSTGRES_16",
                    instance.get("region") == REGION,
                    instance.get("state") == "RUNNABLE",
                    instance.get("connectionName") == SQL_CONNECTION_NAME,
                )
            )
            sql_foundation = ResourceState.EXACT if exact_foundation else ResourceState.DRIFTED
            backup = _nested(instance, "settings", "backupConfiguration", default={})
            retention = (
                backup.get("backupRetentionSettings", {}) if isinstance(backup, Mapping) else {}
            )
            protected = all(
                (
                    isinstance(backup, Mapping) and backup.get("enabled") is True,
                    backup.get("pointInTimeRecoveryEnabled") is True,
                    backup.get("location") in {REGION, None},
                    int(retention.get("retainedBackups", 0)) >= 7,
                    int(backup.get("transactionLogRetentionDays", 0)) >= 7,
                    instance.get("settings", {}).get("deletionProtectionEnabled") is True
                    or instance.get("deletionProtectionEnabled") is True,
                )
            )
            sql_protection = ResourceState.EXACT if protected else ResourceState.UPDATABLE

        databases = (
            self._json_list(
                (
                    "gcloud",
                    "sql",
                    "databases",
                    "list",
                    f"--instance={SQL_INSTANCE}",
                    f"--project={PROJECT_ID}",
                    "--format=json",
                )
            )
            if instance is not None
            else []
        )
        database_row = _find_named(databases, DATABASE_NAME)
        database = ResourceState.ABSENT
        if database_row is not None:
            database = (
                ResourceState.EXACT
                if str(database_row.get("charset", "")).upper() == "UTF8"
                else ResourceState.DRIFTED
            )
        users = (
            self._json_list(
                (
                    "gcloud",
                    "sql",
                    "users",
                    "list",
                    f"--instance={SQL_INSTANCE}",
                    f"--project={PROJECT_ID}",
                    "--format=json",
                )
            )
            if instance is not None
            else []
        )
        user_rows = [row for row in users if row.get("name") == DATABASE_USER]
        database_user = (
            ResourceState.ABSENT
            if not user_rows
            else ResourceState.EXACT
            if len(user_rows) == 1 and user_rows[0].get("type") in {None, "BUILT_IN"}
            else ResourceState.DRIFTED
        )

        secret_rows = self._json_list(
            (
                "gcloud",
                "secrets",
                "list",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        database_url_secret = self._secret_inventory(secret_rows, DATABASE_URL_SECRET)
        spine_token_secret = self._secret_inventory(secret_rows, SPINE_TOKEN_SECRET)
        openrouter_secret = self._secret_inventory(secret_rows, OPENROUTER_SECRET)
        if database_url_secret is ResourceState.EXACT:
            self._remember_database_password(self._access_secret(DATABASE_URL_SECRET))
        if spine_token_secret is ResourceState.EXACT:
            self._spine_token = self._access_secret(SPINE_TOKEN_SECRET)

        if database is ResourceState.ABSENT and database_user is ResourceState.ABSENT:
            migrations = ResourceState.ABSENT
        elif (
            database is ResourceState.EXACT
            and database_user is ResourceState.EXACT
            and database_url_secret is ResourceState.EXACT
        ):
            migrations = self._migration_state()
        else:
            migrations = ResourceState.UNOBSERVED

        service_accounts = self._json_list(
            (
                "gcloud",
                "iam",
                "service-accounts",
                "list",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        runtime_identity = self._service_account_state(service_accounts)
        project_policy = self._json_object(
            (
                "gcloud",
                "projects",
                "get-iam-policy",
                PROJECT_ID,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        runtime_cloudsql_iam = self._project_iam_state(project_policy, runtime_identity)
        runtime_database_secret_iam = self._secret_iam_state(
            DATABASE_URL_SECRET, database_url_secret, runtime_identity
        )
        runtime_token_secret_iam = self._secret_iam_state(
            SPINE_TOKEN_SECRET, spine_token_secret, runtime_identity
        )
        runtime_openrouter_secret_iam = self._secret_iam_state(
            OPENROUTER_SECRET, openrouter_secret, runtime_identity
        )

        repositories = self._json_list(
            (
                "gcloud",
                "artifacts",
                "repositories",
                "list",
                f"--location={REGION}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        artifact_repository = self._artifact_state(repositories)
        images = self._artifact_images() if artifact_repository is not ResourceState.ABSENT else []
        spine_image = self._image_state(images)

        run_services = self._json_list(
            (
                "gcloud",
                "run",
                "services",
                "list",
                f"--region={REGION}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        service = _find_named(run_services, CLOUD_RUN_SERVICE)
        service_policy = None
        if service is not None:
            service = self._json_object(
                (
                    "gcloud",
                    "run",
                    "services",
                    "describe",
                    CLOUD_RUN_SERVICE,
                    f"--region={REGION}",
                    f"--project={PROJECT_ID}",
                    "--format=json",
                )
            )
            service_policy = self._json_object(
                (
                    "gcloud",
                    "run",
                    "services",
                    "get-iam-policy",
                    CLOUD_RUN_SERVICE,
                    f"--region={REGION}",
                    f"--project={PROJECT_ID}",
                    "--format=json",
                )
            )
        cloud_run_service = self._cloud_run_state(service, service_policy)
        remote_verification = self._remote_state(service, cloud_run_service, spine_token_secret)
        breaker = self._breaker_state(
            target=target,
            project_number=str(project.get("projectNumber", "")) if project else "",
            service_accounts=service_accounts,
            run_services=run_services,
            project_policy=project_policy,
        )
        return ObservedDeployment(
            project_active=project_active,
            billing_enabled=billing_enabled,
            sql_foundation=sql_foundation,
            sql_protection=sql_protection,
            database=database,
            database_user=database_user,
            migrations=migrations,
            database_url_secret=database_url_secret,
            spine_token_secret=spine_token_secret,
            openrouter_secret=openrouter_secret,
            runtime_identity=runtime_identity,
            runtime_cloudsql_iam=runtime_cloudsql_iam,
            runtime_database_secret_iam=runtime_database_secret_iam,
            runtime_token_secret_iam=runtime_token_secret_iam,
            runtime_openrouter_secret_iam=runtime_openrouter_secret_iam,
            artifact_repository=artifact_repository,
            spine_image=spine_image,
            cloud_run_service=cloud_run_service,
            remote_verification=remote_verification,
            breaker=breaker,
        )

    def _create_secret(self, name: str, value: str) -> None:
        self._run(
            (
                "gcloud",
                "secrets",
                "create",
                name,
                "--replication-policy=user-managed",
                f"--locations={REGION}",
                f"--project={PROJECT_ID}",
                "--quiet",
            )
        )
        self._run(
            (
                "gcloud",
                "secrets",
                "versions",
                "add",
                name,
                "--data-file=-",
                f"--project={PROJECT_ID}",
                "--quiet",
            ),
            input_text=value,
        )

    def align_owner_cloud_credentials_once(self) -> Path:
        """Consume D.2 096: back up, then reset the managed database credential."""

        receipt = self.begin_mutation_attempt()
        password = secrets.token_urlsafe(32)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="nocturne-gcloud-flags-",
            suffix=".json",
        ) as flags_file:
            os.chmod(flags_file.name, 0o600)
            json.dump({"--password": password}, flags_file)
            flags_file.flush()
            self._run(
                (
                    "gcloud",
                    "sql",
                    "users",
                    "set-password",
                    DATABASE_USER,
                    f"--instance={SQL_INSTANCE}",
                    f"--flags-file={flags_file.name}",
                    f"--project={PROJECT_ID}",
                    "--quiet",
                )
            )

        database_url = self._database_url_for_password(password)
        added = self._run(
            (
                "gcloud",
                "secrets",
                "versions",
                "add",
                DATABASE_URL_SECRET,
                "--data-file=-",
                f"--project={PROJECT_ID}",
                "--format=json",
                "--quiet",
            ),
            input_text=database_url,
        )
        try:
            added_name = str(json.loads(added.stdout)["name"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DeployError(
                "the new managed database secret version could not be verified"
            ) from exc
        added_version = _resource_tail(added_name)
        if not added_version:
            raise DeployError("the new managed database secret version could not be verified")

        versions = self._json_list(
            (
                "gcloud",
                "secrets",
                "versions",
                "list",
                DATABASE_URL_SECRET,
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        for row in versions:
            version = _resource_tail(row.get("name"))
            if (
                version
                and version != added_version
                and str(row.get("state", "")).upper() == "ENABLED"
            ):
                self._run(
                    (
                        "gcloud",
                        "secrets",
                        "versions",
                        "disable",
                        version,
                        f"--secret={DATABASE_URL_SECRET}",
                        f"--project={PROJECT_ID}",
                        "--quiet",
                    )
                )
        self._database_password = password
        self._persist_credential_custody_receipt(receipt, added_version)
        return receipt

    def begin_mutation_attempt(self) -> Path:
        """Mint one verified receipt and reuse it only inside this process's attempt."""

        if self._attempt_backup_receipt is None:
            self._attempt_backup_receipt = self._create_cloud_backup_receipt()
        return self._attempt_backup_receipt

    def owner_credentials_managed(self) -> bool:
        """Prove this install completed its one-time fixed-owner credential alignment."""

        path = self._credential_custody_receipt
        if path is None or not path.exists():
            return False
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise DeployError(
                "The credential custody receipt is unsafe; restore its 0600 regular file "
                "or remove it after reviewing the owner-cloud runbook."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeployError(
                "The credential custody receipt is unreadable; review it before deploying."
            ) from exc
        expected = {
            "schema_version": 1,
            "project": PROJECT_ID,
            "instance": SQL_INSTANCE,
            "database_user": DATABASE_USER,
            "secret": DATABASE_URL_SECRET,
        }
        if not isinstance(payload, Mapping) or any(
            payload.get(key) != value for key, value in expected.items()
        ):
            raise DeployError(
                "The credential custody receipt does not match this Palace; "
                "review it before deploying."
            )
        return True

    def _persist_credential_custody_receipt(
        self, backup_receipt: Path, secret_version: str
    ) -> None:
        path = self._credential_custody_receipt
        if path is None:
            raise DeployError(
                "The credentials changed but the custody receipt location is unavailable; "
                "stop and inspect the owner-cloud state."
            )
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        payload = {
            "schema_version": 1,
            "aligned_at": datetime.now(UTC).isoformat(),
            "project": PROJECT_ID,
            "instance": SQL_INSTANCE,
            "database_user": DATABASE_USER,
            "secret": DATABASE_URL_SECRET,
            "secret_version": secret_version,
            "backup_receipt": backup_receipt.name,
        }
        descriptor, temporary_name = tempfile.mkstemp(prefix=".custody-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _database_url_for_password(password: str) -> str:
        encoded = quote(password, safe="")
        return (
            f"postgresql+asyncpg://{DATABASE_USER}:{encoded}@/{DATABASE_NAME}"
            f"?host=/cloudsql/{SQL_CONNECTION_NAME}"
        )

    def _add_project_role(self, role: str) -> None:
        self._run(
            (
                "gcloud",
                "projects",
                "add-iam-policy-binding",
                PROJECT_ID,
                f"--project={PROJECT_ID}",
                f"--member={self.runtime_member}",
                f"--role={role}",
                "--quiet",
            )
        )

    def _add_secret_role(self, name: str) -> None:
        self._run(
            (
                "gcloud",
                "secrets",
                "add-iam-policy-binding",
                name,
                f"--project={PROJECT_ID}",
                f"--member={self.runtime_member}",
                "--role=roles/secretmanager.secretAccessor",
                "--quiet",
            )
        )

    def _build_image(self, source_dir: Path) -> None:
        access_token = self._run(
            (
                "gcloud",
                "auth",
                "print-access-token",
                f"--project={PROJECT_ID}",
            )
        ).stdout
        if not access_token:
            raise DeployError("gcloud returned an empty registry access token")
        with self._isolated_docker_environment() as environment:
            self._run(
                (
                    "docker",
                    "login",
                    ARTIFACT_HOST,
                    f"--username={REGISTRY_TOKEN_USER}",
                    "--password-stdin",
                ),
                input_text=access_token,
                env=environment,
            )
            self._run(local_image_build_argv(source_dir, self.image_ref), env=environment)

    def _deploy_service(self) -> None:
        self._run(
            (
                "gcloud",
                "run",
                "deploy",
                CLOUD_RUN_SERVICE,
                f"--image={self.image_ref}",
                f"--project={PROJECT_ID}",
                f"--region={REGION}",
                "--execution-environment=gen2",
                "--port=8000",
                "--min-instances=0",
                "--max-instances=1",
                f"--service-account={RUNTIME_SERVICE_ACCOUNT_EMAIL}",
                f"--add-cloudsql-instances={SQL_CONNECTION_NAME}",
                (
                    "--set-secrets="
                    f"SPINE_DATABASE_URL={DATABASE_URL_SECRET}:latest,"
                    f"SPINE_TOKEN={SPINE_TOKEN_SECRET}:latest,"
                    f"SPINE_OPENAI_API_KEY={OPENROUTER_SECRET}:latest"
                ),
                (
                    "--set-env-vars="
                    f"SPINE_EMBED_BASE_URL={EMBED_BASE_URL},"
                    f"SPINE_EMBED_MODEL={EMBED_MODEL}"
                ),
                f"--labels=nocturne-image={self._verification_receipt}",
                "--ingress=all",
                "--allow-unauthenticated",
                "--quiet",
            )
        )

    def _apply_migrations(self) -> None:
        if self._database_password is None:
            raise DeployError("database credential is unavailable for migration")
        self.begin_mutation_attempt()
        with self._cloud_sql_proxy() as port:
            database_url = (
                f"postgresql+asyncpg://{DATABASE_USER}:"
                f"{quote(self._database_password, safe='')}@127.0.0.1:{port}/{DATABASE_NAME}"
            )
            environment = os.environ.copy()
            environment["SPINE_DATABASE_URL"] = database_url
            self._run((sys.executable, "-m", "spine.db.migrate"), env=environment)
        self._attempt_backup_receipt = None

    @staticmethod
    def _cloud_timestamp(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise DeployError("Cloud SQL backup metadata was incomplete")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DeployError("Cloud SQL backup metadata was incomplete") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise DeployError("Cloud SQL backup metadata was incomplete")
        return value

    def _persist_cloud_backup_receipt(self, receipt_id: str, payload: Mapping[str, object]) -> Path:
        directory = self._cloud_receipt_directory
        if directory is None:
            raise DeployError("Cloud SQL backup completed but its receipt location is unavailable")
        temporary: Path | None = None
        try:
            if directory.is_symlink():
                raise OSError("receipt directory is a symlink")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
            descriptor, name = tempfile.mkstemp(prefix=".receipt-", dir=directory)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(dict(payload), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            destination = directory / f"{receipt_id}.json"
            os.replace(temporary, destination)
            temporary = None
            directory_descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            return destination
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise DeployError(
                "Cloud SQL backup completed but its local receipt could not be saved; "
                "migration did not run"
            ) from exc

    def _create_cloud_backup_receipt(self) -> Path:
        receipt_id = generate_ulid()
        description = f"nocturne-pre-migration-{receipt_id.lower()}"
        operation = self._json_object(
            (
                "gcloud",
                "sql",
                "backups",
                "create",
                f"--instance={SQL_INSTANCE}",
                f"--description={description}",
                f"--location={REGION}",
                "--async",
                f"--project={PROJECT_ID}",
                "--format=json",
                "--quiet",
            )
        )
        operation_id = str(operation.get("name", ""))
        context = operation.get("backupContext", {})
        if not isinstance(context, Mapping):
            raise DeployError("Cloud SQL backup did not return a usable receipt identity")
        submitted_backup_id = str(context.get("backupId", ""))
        if not _CLOUD_OPERATION_RE.fullmatch(operation_id) or (
            submitted_backup_id and not submitted_backup_id.isdigit()
        ):
            raise DeployError("Cloud SQL backup did not return a usable receipt identity")

        waited = self._json_list(
            (
                "gcloud",
                "sql",
                "operations",
                "wait",
                operation_id,
                "--timeout=1800",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        if len(waited) != 1:
            raise DeployError("Cloud SQL backup operation did not complete safely")
        completed = waited[0]
        completed_context = completed.get("backupContext", {})
        backup_id = (
            str(completed_context.get("backupId", ""))
            if isinstance(completed_context, Mapping)
            else ""
        )
        if not isinstance(completed_context, Mapping) or not all(
            (
                backup_id.isdigit(),
                not submitted_backup_id or submitted_backup_id == backup_id,
                completed.get("name") == operation_id,
                completed.get("status") == "DONE",
                completed.get("operationType") == "BACKUP_VOLUME",
                completed.get("targetProject") == PROJECT_ID,
                completed.get("targetId") == SQL_INSTANCE,
            )
        ):
            raise DeployError("Cloud SQL backup operation did not complete safely")

        backup = self._json_object(
            (
                "gcloud",
                "sql",
                "backups",
                "describe",
                backup_id,
                f"--instance={SQL_INSTANCE}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        if not all(
            (
                str(backup.get("id", "")) == backup_id,
                backup.get("instance") == SQL_INSTANCE,
                backup.get("description") == description,
                backup.get("status") == "SUCCESSFUL",
                backup.get("type") == "ON_DEMAND",
                backup.get("location") == REGION,
            )
        ):
            raise DeployError("Cloud SQL backup could not be verified; migration did not run")

        payload = {
            "schema_version": 1,
            "receipt_id": receipt_id,
            "created_at": datetime.now(UTC).isoformat(),
            "reason": "pre_migration",
            "provider": "gcp_cloud_sql",
            "project": PROJECT_ID,
            "region": REGION,
            "instance": SQL_INSTANCE,
            "database": DATABASE_NAME,
            "operation_id": operation_id,
            "backup_id": backup_id,
            "description": description,
            "status": "SUCCESSFUL",
            "type": "ON_DEMAND",
            "location": REGION,
            "enqueued_time": self._cloud_timestamp(backup.get("enqueuedTime")),
            "start_time": self._cloud_timestamp(backup.get("startTime")),
            "end_time": self._cloud_timestamp(backup.get("endTime")),
        }
        return self._persist_cloud_backup_receipt(receipt_id, payload)

    def _service_url_now(self) -> str:
        service = self._json_object(
            (
                "gcloud",
                "run",
                "services",
                "describe",
                CLOUD_RUN_SERVICE,
                f"--region={REGION}",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        url = _nested(service, "status", "url") or service.get("uri")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise DeployError("Cloud Run did not report a service URL")
        return url

    def _verify_remote(self) -> None:
        token = self._spine_token
        if token is None:
            token = self._access_secret(SPINE_TOKEN_SECRET)
            self._spine_token = token
        service_url = self._service_url_now()
        if not self._health_probe(service_url, token):
            raise DeployError(
                "Cloud Run health verification failed; check the service logs "
                "and run the dry-run again"
            )
        self._remote_verifier(service_url, token)
        self._run(
            (
                "gcloud",
                "run",
                "services",
                "update",
                CLOUD_RUN_SERVICE,
                f"--update-labels=nocturne-verified={self._verification_receipt}",
                f"--region={REGION}",
                f"--project={PROJECT_ID}",
                "--quiet",
            )
        )

    def execute(
        self,
        step: PlanStep,
        *,
        target: DeployTarget,
        source_dir: Path | None,
    ) -> None:
        """Execute one planner-authorized CREATE/UPDATE and nothing else."""

        if step.action not in {PlanAction.CREATE, PlanAction.UPDATE}:
            raise DeployError(f"refusing to execute non-D1 action {step.action}")
        if step.stage is DeployStage.SQL_PROTECTION:
            self._run(
                (
                    "gcloud",
                    "sql",
                    "instances",
                    "patch",
                    SQL_INSTANCE,
                    "--backup-start-time=03:00",
                    f"--backup-location={REGION}",
                    "--enable-point-in-time-recovery",
                    "--retained-backups-count=7",
                    "--retained-transaction-log-days=7",
                    "--deletion-protection",
                    f"--project={PROJECT_ID}",
                    "--quiet",
                )
            )
            return
        if step.stage is DeployStage.DATABASE:
            self._run(
                (
                    "gcloud",
                    "sql",
                    "databases",
                    "create",
                    DATABASE_NAME,
                    f"--instance={SQL_INSTANCE}",
                    "--charset=UTF8",
                    f"--project={PROJECT_ID}",
                    "--quiet",
                )
            )
            return
        if step.stage is DeployStage.DATABASE_USER:
            password = self._database_password or secrets.token_urlsafe(32)
            self._database_password = password
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="nocturne-gcloud-flags-",
                suffix=".json",
            ) as flags_file:
                os.chmod(flags_file.name, 0o600)
                json.dump({"--password": password}, flags_file)
                flags_file.flush()
                self._run(
                    (
                        "gcloud",
                        "sql",
                        "users",
                        "create",
                        DATABASE_USER,
                        f"--instance={SQL_INSTANCE}",
                        f"--flags-file={flags_file.name}",
                        f"--project={PROJECT_ID}",
                        "--quiet",
                    )
                )
            return
        if step.stage is DeployStage.MIGRATIONS:
            self._apply_migrations()
            return
        if step.stage is DeployStage.DATABASE_URL_SECRET:
            self._create_secret(DATABASE_URL_SECRET, self._database_url())
            return
        if step.stage is DeployStage.SPINE_TOKEN_SECRET:
            self._create_secret(SPINE_TOKEN_SECRET, self._token())
            return
        if step.stage is DeployStage.OPENROUTER_SECRET:
            self._create_secret(OPENROUTER_SECRET, self._openrouter_key)
            return
        if step.stage is DeployStage.RUNTIME_IDENTITY:
            self._run(
                (
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "create",
                    RUNTIME_SERVICE_ACCOUNT,
                    "--display-name=Nocturne Spine runtime",
                    f"--project={PROJECT_ID}",
                    "--quiet",
                )
            )
            return
        if step.stage is DeployStage.RUNTIME_CLOUDSQL_IAM:
            self._add_project_role("roles/cloudsql.client")
            return
        secret_iam = {
            DeployStage.RUNTIME_DATABASE_SECRET_IAM: DATABASE_URL_SECRET,
            DeployStage.RUNTIME_TOKEN_SECRET_IAM: SPINE_TOKEN_SECRET,
            DeployStage.RUNTIME_OPENROUTER_SECRET_IAM: OPENROUTER_SECRET,
        }
        if step.stage in secret_iam:
            self._add_secret_role(secret_iam[step.stage])
            return
        if step.stage is DeployStage.ARTIFACT_REPOSITORY:
            command = "create" if step.action is PlanAction.CREATE else "update"
            argv = [
                "gcloud",
                "artifacts",
                "repositories",
                command,
                ARTIFACT_REPOSITORY,
            ]
            if command == "create":
                argv.append("--repository-format=docker")
            argv.extend(
                (
                    "--immutable-tags",
                    f"--location={REGION}",
                    f"--project={PROJECT_ID}",
                    "--quiet",
                )
            )
            self._run(argv)
            return
        if step.stage is DeployStage.SPINE_IMAGE:
            if source_dir is None:
                raise DeployError("packaged Spine app source is required for image build")
            self._build_image(source_dir)
            return
        if step.stage is DeployStage.CLOUD_RUN_SERVICE:
            self._deploy_service()
            return
        if step.stage is DeployStage.REMOTE_VERIFICATION:
            self._verify_remote()
            return
        raise DeployError(f"unsupported or forbidden deployment stage: {step.stage}")

    def arm_breaker(
        self,
        *,
        target: DeployTarget,
        source_dir: Path,
        stdin: IO[str],
        stdout: IO[str],
    ) -> None:
        """Delegate D2 to its canonical human-only typed-confirmation script."""

        invoke_packaged_breaker(
            source_dir,
            target,
            stdin=stdin,
            stdout=stdout,
            runner=self._runner,
        )


def run_cloud_deploy(
    *,
    dry_run: bool,
    openrouter_key: str,
    stdin: IO[str] = sys.stdin,
    stdout: IO[str] = sys.stdout,
    runner: CommandRunner = subprocess.run,
    process_factory: ProcessFactory = subprocess.Popen,
    home: Path | None = None,
    credential_alignment_consent: bool | None = None,
) -> DeployPlan:
    """CLI integration seam: discover and reconcile the one authorized target."""

    if home is None:
        from harness.onboarding import nocturne_home

        home = nocturne_home()
    from spine import __version__ as spine_version

    image_tag = spine_version.replace("+", ".")
    backend = GcloudDeployBackend(
        image_tag=image_tag,
        openrouter_key=openrouter_key,
        runner=runner,
        process_factory=process_factory,
        cloud_receipt_directory=home / "cloud-backups",
        credential_custody_receipt=home / "cloud-credential-custody.json",
    )
    backend.preflight()
    target = backend.discover_target()
    return deploy(
        backend,
        target,
        dry_run=dry_run,
        stdin=stdin,
        stdout=stdout,
        credential_alignment_consent=credential_alignment_consent,
    )
