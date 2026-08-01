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
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, Any, Protocol
from urllib.parse import quote, unquote, urlsplit

import httpx

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

RUNTIME_SERVICE_ACCOUNT_EMAIL = (
    f"{RUNTIME_SERVICE_ACCOUNT}@{PROJECT_ID}.iam.gserviceaccount.com"
)
SQL_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{SQL_INSTANCE}"
ARTIFACT_HOST = f"{REGION}-docker.pkg.dev"
IMAGE_PACKAGE = f"{ARTIFACT_HOST}/{PROJECT_ID}/{ARTIFACT_REPOSITORY}/spine"

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
            raise ValueError(
                "budget_resource must be billingAccounts/ACCOUNT_ID/budgets/BUDGET_ID"
            )
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
            f"NOCTURNE deploy plan: project={PROJECT_ID} region={REGION} "
            f"sql={SQL_INSTANCE}",
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
        blocked = ", ".join(
            step.stage for step in plan.steps if step.action is PlanAction.BLOCKED
        )
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
        PlanAction.NOOP
        if observed.sql_foundation is ResourceState.EXACT
        else PlanAction.BLOCKED,
        (
            f"Cloud SQL {SQL_INSTANCE} is the exact PostgreSQL 16 foundation"
            if observed.sql_foundation is ResourceState.EXACT
            else f"Cloud SQL {SQL_INSTANCE} is absent or incompatible; instance provisioning is not authorized"
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
        database_secret_consistent = (
            observed.database is ResourceState.EXACT
        ) is (observed.database_url_secret is ResourceState.EXACT)

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
                "database/user partial state cannot be adopted without resetting credentials",
            )
            database_user = PlanStep(
                DeployStage.DATABASE_USER,
                PlanAction.BLOCKED,
                "database/user partial state cannot be adopted without resetting credentials",
            )

        migrations = _resource_step(
            DeployStage.MIGRATIONS,
            observed.migrations,
            detail="packaged Alembic migration head",
            absent_action=PlanAction.UPDATE,
            allow_update=True,
            source_required=True,
        )
        database_url_secret = _resource_step(
            DeployStage.DATABASE_URL_SECRET,
            observed.database_url_secret,
            detail=f"regional secret {DATABASE_URL_SECRET}",
            absent_action=PlanAction.CREATE,
            allow_update=False,
        )
        if not database_secret_consistent:
            database = PlanStep(
                DeployStage.DATABASE,
                PlanAction.BLOCKED,
                "database and managed URL secret state disagree; credential adoption or reset is forbidden",
            )
            database_user = PlanStep(
                DeployStage.DATABASE_USER,
                PlanAction.BLOCKED,
                "database user and managed URL secret state disagree; credential adoption or reset is forbidden",
            )
            database_url_secret = PlanStep(
                DeployStage.DATABASE_URL_SECRET,
                PlanAction.BLOCKED,
                "database/user and URL secret must be wholly absent or exact together; rotation is forbidden",
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


@contextmanager
def packaged_spine_source() -> Iterator[Path]:
    """Materialize Spine-owned app and HUMAN D2 source into a temporary tree."""

    from spine.deploy_resources import materialize_app_source

    with tempfile.TemporaryDirectory(prefix="nocturne-deploy-") as temporary:
        source = materialize_app_source(Path(temporary) / "app-source")
        required = (
            source / "Dockerfile",
            source / "pyproject.toml",
            source / "src",
            source / "infra" / "billing-breaker" / "deploy.sh",
        )
        missing = [path.relative_to(source) for path in required if not path.exists()]
        if missing:
            joined = ", ".join(str(path) for path in missing)
            raise DeployError(f"packaged Spine deployment resources are incomplete: {joined}")
        yield source


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


def invoke_packaged_breaker(
    source_dir: Path,
    target: DeployTarget,
    *,
    stdin: IO[str] = sys.stdin,
    stdout: IO[str] = sys.stdout,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """Invoke the existing human-only D2 script without a shell or input synthesis."""

    breaker_dir = source_dir / "infra" / "billing-breaker"
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


SourceProvider = Callable[[], AbstractContextManager[Path]]


def deploy(
    backend: DeployBackend,
    target: DeployTarget,
    *,
    dry_run: bool,
    stdin: IO[str] = sys.stdin,
    stdout: IO[str] = sys.stdout,
    source_provider: SourceProvider = packaged_spine_source,
) -> DeployPlan:
    """Plan or converge the fixed D1 target, then enter D2's human boundary.

    A blocked initial observation produces no mutation. A dry run performs only
    ``backend.observe`` and does not even materialize packaged resources. Apply
    never cleans up on failure; a later run must re-observe and either continue
    from exact state or block on ambiguity.
    """

    initial = build_plan(backend.observe(target))
    stdout.write(f"{initial.render()}\n")
    if dry_run:
        return initial
    if initial.blocked:
        raise DeployBlocked(initial)

    human_step = initial.step(DeployStage.BILLING_BREAKER)
    if human_step.action is PlanAction.HUMAN and not (
        stdin.isatty() and stdout.isatty()
    ):
        raise HumanTerminalRequired(
            "D2 arming requires a real interactive stdin and stdout; no D1 mutation ran"
        )

    d1_mutations = tuple(
        step
        for step in initial.steps
        if step.action in {PlanAction.CREATE, PlanAction.UPDATE}
    )
    needs_source = any(step.source_required for step in (*d1_mutations, human_step))

    @contextmanager
    def no_source() -> Iterator[Path | None]:
        yield None

    source_context: AbstractContextManager[Path | None]
    source_context = source_provider() if needs_source else no_source()
    with source_context as source_dir:
        for step in d1_mutations:
            backend.execute(
                step,
                target=target,
                source_dir=source_dir if step.source_required else None,
            )

        before_breaker = build_plan(backend.observe(target))
        d1_pending = tuple(
            step
            for step in before_breaker.steps
            if step.stage is not DeployStage.BILLING_BREAKER
            and step.action is not PlanAction.NOOP
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
                source_dir=source_dir,
                stdin=stdin,
                stdout=stdout,
            )

    final = build_plan(backend.observe(target))
    if any(step.action is not PlanAction.NOOP for step in final.steps):
        raise DeployIncomplete(final)
    return final
