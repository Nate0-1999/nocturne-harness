"""Bounded Symphony conductor: authoritative claim in, typed distillates out."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.model_policy import parse_model_policy
from harness.supervisor import SupervisorError, WorkerSupervisor

_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "TMPDIR")
_MAX_DISTILLATE_BYTES = 64 * 1024


class ConductorError(RuntimeError):
    """The conductor cannot make the requested transition without guessing."""


class ScopeExpansionError(ConductorError):
    """A proposed child adds scope outside its authoritative parent claim."""


class RetryLimitReached(ConductorError):
    """Two successor attempts failed and the child must become a flag."""


class SearchBudgetExceeded(ConductorError):
    """A declared Symphony spend or clock wall has stopped the search node."""


class ChildStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    AWAITING_DISTILLATE = "awaiting_distillate"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FLAGGED = "flagged"


class CancellationState(StrEnum):
    NONE = "none"
    REQUESTED = "requested"
    DRAINING = "draining"
    CANCELLED = "cancelled"


class IrreversibleBoundary(StrEnum):
    CLEAR = "clear"
    RECONCILED = "reconciled"
    UNCERTAIN = "uncertain"


class DistillateStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BLOCKED = "blocked"


class SearchAttemptStatus(StrEnum):
    PLANNED = "planned"
    SMOKE_RUNNING = "smoke_running"
    SMOKE_AWAITING_RESULT = "smoke_awaiting_result"
    SMOKE_PASSED = "smoke_passed"
    SMOKE_FAILED = "smoke_failed"
    COMPLETION_READY = "completion_ready"
    BEAM_PRUNED = "beam_pruned"
    COMPLETION_RUNNING = "completion_running"
    COMPLETION_AWAITING_DISTILLATE = "completion_awaiting_distillate"
    DRAINING = "draining"
    BRAKED = "braked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SearchBrake(StrEnum):
    NONE = "none"
    SPEND = "spend"
    CLOCK = "clock"
    SPEND_AND_CLOCK = "spend_and_clock"


class SmokeGateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class SearchBudget(BaseModel):
    """R22's per-search-node default envelope, overridable only in the charge."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempts: int = Field(default=3, ge=1)
    spend_wall_usd: Decimal = Field(default=Decimal("10"), gt=0)
    max_rounds: int = Field(default=3, ge=1)
    depth_cap: int = Field(default=2, ge=0)
    children_per_attempt: int = Field(default=4, ge=0)
    duration_seconds: float = Field(default=1800.0, gt=0)


class SearchAttemptBrief(BaseModel):
    """One deliberation-authored approach, including its projected beam cost."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt_id: str
    approach: str
    charge: str
    location: Path
    estimated_completion_cost_usd: Decimal = Field(ge=0)
    estimated_completion_seconds: float = Field(gt=0)
    planned_children: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_attempt(self) -> SearchAttemptBrief:
        if _IDENTITY.fullmatch(self.attempt_id) is None:
            raise ValueError("attempt_id must be a compact stable identity")
        if not self.approach.strip() or not self.charge.strip():
            raise ValueError("search approach and charge must be nonblank")
        location = self.location.expanduser().resolve(strict=True)
        if not location.is_dir():
            raise ValueError("search attempt location must be an existing worktree directory")
        object.__setattr__(self, "location", location)
        return self


class SearchNodeDeclaration(BaseModel):
    """A hard step marked for expense during deliberation, never at runtime."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    marker: Literal["symphony"] = "symphony"
    round_number: int = Field(default=1, ge=1)
    depth: int = Field(default=0, ge=0)
    budget: SearchBudget = Field(default_factory=SearchBudget)
    attempts: tuple[SearchAttemptBrief, ...]

    @model_validator(mode="after")
    def _validate_declaration(self) -> SearchNodeDeclaration:
        if len(self.attempts) != self.budget.attempts:
            raise ValueError("a marked search node must declare exactly its budgeted attempts")
        if self.round_number > self.budget.max_rounds:
            raise ValueError("search round exceeds the declared max_rounds brake")
        if self.depth > self.budget.depth_cap:
            raise ValueError("search depth exceeds the declared depth_cap")
        if any(
            attempt.planned_children > self.budget.children_per_attempt for attempt in self.attempts
        ):
            raise ValueError("search attempt exceeds the declared children_per_attempt cap")
        identities = [attempt.attempt_id for attempt in self.attempts]
        if len(set(identities)) != len(identities):
            raise ValueError("search attempt ids must be unique")
        approaches = [" ".join(attempt.approach.split()).casefold() for attempt in self.attempts]
        if len(set(approaches)) != len(approaches):
            raise ValueError("search attempts must declare distinct approaches")
        locations = [attempt.location for attempt in self.attempts]
        if len(set(locations)) != len(locations):
            raise ValueError("search attempts require distinct worktree locations")
        return self


class SmokeGateResult(BaseModel):
    """The cheap compile/coherence result that precedes costly completion."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    status: SmokeGateStatus
    score: Decimal = Field(ge=0, le=1)
    checks: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_smoke(self) -> SmokeGateResult:
        if not self.checks or not self.evidence_refs:
            raise ValueError("a smoke gate requires named checks and direct evidence")
        if any(not value.strip() for value in (*self.checks, *self.evidence_refs)):
            raise ValueError("smoke checks and evidence references must be nonblank")
        return self


class SearchBudgetSnapshot(BaseModel):
    """One actual-meter observation used at every search transition."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    spent_usd: Decimal = Field(ge=0)
    remaining_usd: Decimal = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    remaining_seconds: float = Field(ge=0)
    brake: SearchBrake


class ProductBaton(BaseModel):
    """An explicit product commit or an explicit non-code result."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["commit", "not_applicable"]
    commit: str | None

    @model_validator(mode="after")
    def _validate_baton(self) -> ProductBaton:
        if self.kind == "commit" and (self.commit is None or not self.commit.strip()):
            raise ValueError("a commit product baton requires a nonblank commit")
        if self.kind == "not_applicable" and self.commit is not None:
            raise ValueError("a non-code product baton must carry commit=null")
        return self


class TypedDistillate(BaseModel):
    """The G15 result envelope shared by code and non-code workers."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    status: DistillateStatus
    claims: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    uncertainties: tuple[str, ...]
    metrics_refs: tuple[str, ...]
    artifacts: tuple[str, ...]
    patch: str | None
    product: ProductBaton

    @model_validator(mode="after")
    def _validate_result(self) -> TypedDistillate:
        text_fields = (
            *self.claims,
            *self.evidence_refs,
            *self.uncertainties,
            *self.metrics_refs,
            *self.artifacts,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError("distillate list entries must be nonblank")
        if self.status is DistillateStatus.COMPLETED and (
            not self.claims or not self.evidence_refs
        ):
            raise ValueError("a completed distillate requires claims and evidence")
        if self.status is DistillateStatus.CANCELLED and not self.evidence_refs:
            raise ValueError("a cancelled distillate must preserve partial evidence")
        return self


class AuthoritativeClaim(BaseModel):
    """A claim already acquired through the current Garden/adapter authority."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    packet_id: str
    bead_id: str
    charge_digest: str
    claim_token: str
    accepted_commit: str
    motivation_chain: tuple[str, ...]
    scope: tuple[str, ...]
    status: Literal["in_progress"]

    @model_validator(mode="after")
    def _validate_claim(self) -> AuthoritativeClaim:
        for label, value in (
            ("packet_id", self.packet_id),
            ("bead_id", self.bead_id),
            ("charge_digest", self.charge_digest),
            ("claim_token", self.claim_token),
            ("accepted_commit", self.accepted_commit),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be nonblank")
        if _IDENTITY.fullmatch(self.packet_id) is None:
            raise ValueError("packet_id must be a compact stable identity")
        if not self.motivation_chain or any(not item.strip() for item in self.motivation_chain):
            raise ValueError("the inherited motivation chain must be explicit")
        if not self.scope:
            raise ValueError("the authoritative claim must carry its scope fence")
        normalized = tuple(_normalize_surface(item) for item in self.scope)
        if normalized != self.scope or len(set(normalized)) != len(normalized):
            raise ValueError("claim scope entries must be unique normalized relative paths")
        return self


class ChildCharge(BaseModel):
    """One scope-subdividing child produced by conductor expansion."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    child_id: str
    title: str
    charge: str
    surfaces: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...]
    location: Path
    blast_radius: Literal["leaf", "compounding"] = "leaf"
    search: SearchNodeDeclaration | None = None

    @model_validator(mode="after")
    def _validate_child(self) -> ChildCharge:
        if _IDENTITY.fullmatch(self.child_id) is None:
            raise ValueError("child_id must be a compact stable identity")
        if not self.title.strip() or not self.charge.strip():
            raise ValueError("child title and charge must be nonblank")
        if not self.surfaces or tuple(_normalize_surface(item) for item in self.surfaces) != (
            self.surfaces
        ):
            raise ValueError("child surfaces must be normalized relative paths")
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("child surfaces must be unique")
        if self.child_id in self.depends_on or len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("child dependencies must be unique and cannot include self")
        if not self.evidence_requirements or any(
            not item.strip() for item in self.evidence_requirements
        ):
            raise ValueError("child evidence requirements must be explicit")
        location = self.location.expanduser().resolve(strict=True)
        if not location.is_dir():
            raise ValueError("child location must be an existing worktree directory")
        object.__setattr__(self, "location", location)
        return self


class AdmissionHandle(BaseModel):
    """The typed baton returned after the supervisor admits one worker."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    packet_id: str
    child_id: str
    worker_id: str
    attempt_id: str
    accepted_commit: str
    location: Path
    model_policy: str
    brief_sha256: str
    brief: str
    pid: int
    retry_number: int = Field(ge=0, le=2)


class ModelPolicyByBlastRadius(BaseModel):
    """A-021 policies selected by reviewability and compounding error radius."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    leaf: str = "elbow"
    compounding: str = "max"

    @model_validator(mode="after")
    def _validate_policies(self) -> ModelPolicyByBlastRadius:
        parse_model_policy(self.leaf)
        parse_model_policy(self.compounding)
        return self


@dataclass(slots=True)
class _ChildRuntime:
    charge: ChildCharge
    status: ChildStatus = ChildStatus.PLANNED
    cancellation: CancellationState = CancellationState.NONE
    handle: AdmissionHandle | None = None
    retries: int = 0
    distillate: TypedDistillate | None = None
    attempt_distillates: list[TypedDistillate] = field(default_factory=list)
    result_attempt_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _SearchAttemptRuntime:
    brief: SearchAttemptBrief
    status: SearchAttemptStatus = SearchAttemptStatus.PLANNED
    stage: Literal["smoke", "completion"] | None = None
    handle: AdmissionHandle | None = None
    smoke: SmokeGateResult | None = None
    distillate: TypedDistillate | None = None


@dataclass(slots=True)
class _SearchRuntime:
    child_id: str
    declaration: SearchNodeDeclaration
    started_at: float
    baseline_spend_usd: Decimal
    attempts: dict[str, _SearchAttemptRuntime]
    brake: SearchBrake = SearchBrake.NONE


EventSink = Callable[[Mapping[str, Any]], None]
SearchSpendReader = Callable[[str, str], Decimal]
SearchClock = Callable[[], float]


class Conductor:
    """The one fully booted mind coordinating bounded worker attempts."""

    def __init__(
        self,
        *,
        supervisor: WorkerSupervisor,
        event_sink: EventSink,
        policies: ModelPolicyByBlastRadius | None = None,
        environment: Mapping[str, str] | None = None,
        max_retries: Literal[2] = 2,
        search_spend_reader: SearchSpendReader | None = None,
        search_clock: SearchClock = time.monotonic,
    ) -> None:
        if max_retries != 2:
            raise ValueError("G7 fixes the worker retry count at two")
        self._supervisor = supervisor
        self._event_sink = event_sink
        self._policies = policies or ModelPolicyByBlastRadius()
        self._environment = _scrub_environment(os.environ if environment is None else environment)
        self._max_retries = max_retries
        self._search_spend_reader = search_spend_reader
        self._search_clock = search_clock
        self._claim: AuthoritativeClaim | None = None
        self._children: dict[str, _ChildRuntime] = {}
        self._searches: dict[str, _SearchRuntime] = {}

    @property
    def claim_handle(self) -> AuthoritativeClaim | None:
        return self._claim

    def claim(self, claim: AuthoritativeClaim) -> AuthoritativeClaim:
        """Accept one externally authoritative packet claim as the conductor baton."""

        if self._claim is not None:
            raise ConductorError("one conductor session may hold only one packet claim")
        self._emit(
            "claim_accepted",
            packet_id=claim.packet_id,
            bead_id=claim.bead_id,
            charge_digest=claim.charge_digest,
            claim_token=claim.claim_token,
            accepted_commit=claim.accepted_commit,
        )
        self._claim = claim
        return claim

    def expand(self, children: Sequence[ChildCharge]) -> tuple[ChildCharge, ...]:
        """Subdivide the claim while mechanically refusing every scope addition."""

        claim = self._require_claim()
        if self._children:
            raise ConductorError("packet expansion is immutable once accepted")
        proposed = tuple(children)
        if not proposed:
            raise ValueError("packet expansion requires at least one child")
        ids = {child.child_id for child in proposed}
        if len(ids) != len(proposed):
            raise ValueError("expanded child ids must be unique")
        locations = [child.location for child in proposed]
        locations.extend(
            attempt.location
            for child in proposed
            if child.search is not None
            for attempt in child.search.attempts
        )
        if len(set(locations)) != len(locations):
            raise ValueError("parallel children and search attempts require distinct locations")
        for child in proposed:
            additions = sorted(set(child.surfaces) - set(claim.scope))
            if additions:
                raise ScopeExpansionError(
                    f"child {child.child_id!r} adds surfaces outside the claim: {additions}"
                )
            unknown_dependencies = sorted(set(child.depends_on) - ids)
            if unknown_dependencies:
                raise ValueError(
                    f"child {child.child_id!r} depends on unknown children: {unknown_dependencies}"
                )
        self._assert_acyclic(proposed)
        self._emit(
            "packet_expanded",
            packet_id=claim.packet_id,
            children=[child.model_dump(mode="json") for child in proposed],
        )
        self._children = {child.child_id: _ChildRuntime(charge=child) for child in proposed}
        return proposed

    def explode_search(
        self,
        child_id: str,
        smoke_commands: Mapping[str, Sequence[str]],
    ) -> tuple[AdmissionHandle, ...]:
        """Explode one deliberation-marked child into its declared cheap smoke attempts."""

        claim = self._require_claim()
        child = self._child(child_id)
        declaration = child.charge.search
        if declaration is None:
            raise ConductorError("expense is opt-in: only a deliberation-marked child may explode")
        if child.status is not ChildStatus.PLANNED or child_id in self._searches:
            raise ConductorError("a search node may explode exactly once from planned state")
        incomplete = [
            dependency
            for dependency in child.charge.depends_on
            if self._child(dependency).status is not ChildStatus.COMPLETED
        ]
        if incomplete:
            raise ConductorError(f"search node dependencies are not complete: {incomplete}")
        expected = {attempt.attempt_id for attempt in declaration.attempts}
        if set(smoke_commands) != expected:
            raise ValueError("smoke commands must match every declared attempt exactly")
        baseline = self._read_search_spend(child_id)
        started_at = self._search_clock()
        attempts = {
            attempt.attempt_id: _SearchAttemptRuntime(brief=attempt)
            for attempt in declaration.attempts
        }
        runtime = _SearchRuntime(
            child_id=child_id,
            declaration=declaration,
            started_at=started_at,
            baseline_spend_usd=baseline,
            attempts=attempts,
        )
        self._searches[child_id] = runtime
        self._emit(
            "search_exploded",
            packet_id=claim.packet_id,
            child_id=child_id,
            round_number=declaration.round_number,
            depth=declaration.depth,
            budget=declaration.budget.model_dump(mode="json"),
            attempts=[
                {
                    "attempt_id": attempt.attempt_id,
                    "approach": attempt.approach,
                    "planned_children": attempt.planned_children,
                }
                for attempt in declaration.attempts
            ],
        )
        handles: list[AdmissionHandle] = []
        for attempt in declaration.attempts:
            handle = self._launch_search_stage(
                child,
                runtime,
                attempts[attempt.attempt_id],
                stage="smoke",
                command=smoke_commands[attempt.attempt_id],
            )
            handles.append(handle)
        child.status = ChildStatus.RUNNING
        return tuple(handles)

    def observe_search_attempt(
        self,
        child_id: str,
        attempt_id: str,
    ) -> SearchAttemptStatus:
        """Refresh one search stage from the supervisor's process evidence."""

        attempt = self._search_attempt(child_id, attempt_id)
        running_states = {
            SearchAttemptStatus.SMOKE_RUNNING,
            SearchAttemptStatus.COMPLETION_RUNNING,
            SearchAttemptStatus.DRAINING,
        }
        if attempt.status not in running_states or attempt.handle is None:
            return attempt.status
        if self._supervisor.heartbeat(attempt.handle.worker_id):
            return attempt.status
        if attempt.status is SearchAttemptStatus.DRAINING and attempt.stage == "smoke":
            self._supervisor.certify_dead(attempt.handle.worker_id)
            attempt.status = SearchAttemptStatus.CANCELLED
            self._settle_search_parent(child_id)
        elif attempt.status is SearchAttemptStatus.SMOKE_RUNNING:
            attempt.status = SearchAttemptStatus.SMOKE_AWAITING_RESULT
        elif attempt.status is SearchAttemptStatus.COMPLETION_RUNNING:
            attempt.status = SearchAttemptStatus.COMPLETION_AWAITING_DISTILLATE
        self._emit(
            "search_stage_stopped",
            child_id=child_id,
            attempt_id=attempt_id,
            stage=attempt.stage,
            status=attempt.status.value,
        )
        return attempt.status

    def accept_smoke_gate(
        self,
        child_id: str,
        attempt_id: str,
        value: SmokeGateResult | Mapping[str, Any] | Path,
    ) -> SmokeGateResult:
        """Accept one stopped attempt's cheap compile/coherence gate result."""

        attempt = self._search_attempt(child_id, attempt_id)
        if self.observe_search_attempt(child_id, attempt_id) is not (
            SearchAttemptStatus.SMOKE_AWAITING_RESULT
        ):
            raise ConductorError("a smoke result requires one stopped smoke worker")
        result = self._load_smoke_result(attempt, value)
        assert attempt.handle is not None
        self._supervisor.certify_dead(attempt.handle.worker_id)
        attempt.smoke = result
        attempt.status = (
            SearchAttemptStatus.SMOKE_PASSED
            if result.status is SmokeGateStatus.PASS
            else SearchAttemptStatus.SMOKE_FAILED
        )
        self._emit(
            "search_smoke_decided",
            child_id=child_id,
            attempt_id=attempt_id,
            status=result.status.value,
            score=str(result.score),
            checks=list(result.checks),
            evidence_refs=list(result.evidence_refs),
            completion_admissible=result.status is SmokeGateStatus.PASS,
        )
        return result

    def narrow_search_beam(self, child_id: str) -> tuple[SearchAttemptBrief, ...]:
        """Keep the highest smoke scores that fit projected remaining spend and time."""

        runtime = self._search(child_id)
        snapshot = self.search_budget_snapshot(child_id)
        if snapshot.brake is not SearchBrake.NONE:
            self._engage_search_brake(runtime, snapshot.brake)
            raise SearchBudgetExceeded(f"search stopped at its {snapshot.brake.value} wall")
        unsettled = [
            attempt.brief.attempt_id
            for attempt in runtime.attempts.values()
            if attempt.status
            not in {SearchAttemptStatus.SMOKE_PASSED, SearchAttemptStatus.SMOKE_FAILED}
        ]
        if unsettled:
            raise ConductorError(f"the smoke stage is not settled: {unsettled}")
        ranked = sorted(
            (
                attempt
                for attempt in runtime.attempts.values()
                if attempt.status is SearchAttemptStatus.SMOKE_PASSED
            ),
            key=lambda attempt: (
                -attempt.smoke.score if attempt.smoke is not None else Decimal(0),
                attempt.brief.attempt_id,
            ),
        )
        remaining_spend = snapshot.remaining_usd
        selected: list[_SearchAttemptRuntime] = []
        pruned: list[_SearchAttemptRuntime] = []
        for attempt in ranked:
            fits_spend = attempt.brief.estimated_completion_cost_usd <= remaining_spend
            fits_clock = attempt.brief.estimated_completion_seconds <= snapshot.remaining_seconds
            if fits_spend and fits_clock:
                attempt.status = SearchAttemptStatus.COMPLETION_READY
                remaining_spend -= attempt.brief.estimated_completion_cost_usd
                selected.append(attempt)
            else:
                attempt.status = SearchAttemptStatus.BEAM_PRUNED
                pruned.append(attempt)
        self._emit(
            "search_beam_narrowed",
            child_id=child_id,
            kept=[attempt.brief.attempt_id for attempt in selected],
            pruned=[attempt.brief.attempt_id for attempt in pruned],
            spent_usd=str(snapshot.spent_usd),
            remaining_usd=str(snapshot.remaining_usd),
            remaining_seconds=snapshot.remaining_seconds,
        )
        self._settle_search_parent(child_id)
        return tuple(attempt.brief for attempt in selected)

    def dispatch_search_completion(
        self,
        child_id: str,
        attempt_id: str,
        command: Sequence[str],
    ) -> AdmissionHandle:
        """Start expensive completion only after smoke pass and beam admission."""

        runtime = self._search(child_id)
        attempt = self._search_attempt(child_id, attempt_id)
        if attempt.status is not SearchAttemptStatus.COMPLETION_READY:
            raise ConductorError("completion requires a smoke-passed, beam-admitted attempt")
        snapshot = self.search_budget_snapshot(child_id)
        if snapshot.brake is not SearchBrake.NONE:
            self._engage_search_brake(runtime, snapshot.brake)
            raise SearchBudgetExceeded(f"search stopped at its {snapshot.brake.value} wall")
        if (
            attempt.brief.estimated_completion_cost_usd > snapshot.remaining_usd
            or attempt.brief.estimated_completion_seconds > snapshot.remaining_seconds
        ):
            attempt.status = SearchAttemptStatus.BEAM_PRUNED
            self._emit(
                "search_attempt_pruned",
                child_id=child_id,
                attempt_id=attempt_id,
                reason="projected_budget_changed",
            )
            raise SearchBudgetExceeded("the admitted attempt no longer fits the remaining budget")
        return self._launch_search_stage(
            self._child(child_id),
            runtime,
            attempt,
            stage="completion",
            command=command,
        )

    def accept_search_distillate(
        self,
        child_id: str,
        attempt_id: str,
        value: TypedDistillate | Mapping[str, Any] | Path,
    ) -> TypedDistillate:
        """Accept a stopped completion result without making a judge decision."""

        attempt = self._search_attempt(child_id, attempt_id)
        observed = self.observe_search_attempt(child_id, attempt_id)
        if observed not in {
            SearchAttemptStatus.COMPLETION_AWAITING_DISTILLATE,
            SearchAttemptStatus.DRAINING,
        }:
            raise ConductorError("a search distillate requires one stopped completion worker")
        assert attempt.handle is not None
        result = self._load_distillate_at(attempt.handle.location, value)
        if observed is SearchAttemptStatus.DRAINING:
            if result.status is not DistillateStatus.CANCELLED:
                raise ConductorError("a braked completion may settle only as cancelled")
            next_status = SearchAttemptStatus.CANCELLED
        elif result.status is DistillateStatus.COMPLETED:
            next_status = SearchAttemptStatus.COMPLETED
        else:
            next_status = SearchAttemptStatus.FAILED
        self._supervisor.certify_dead(attempt.handle.worker_id)
        attempt.distillate = result
        attempt.status = next_status
        self._emit(
            "search_distillate_accepted",
            child_id=child_id,
            attempt_id=attempt_id,
            status=result.status.value,
            result=result.model_dump(mode="json"),
            judge_eligible=result.status is DistillateStatus.COMPLETED,
            memory_admissible=False,
        )
        self._settle_search_parent(child_id)
        return result

    def enforce_search_brakes(
        self,
        child_id: str,
        *,
        irreversible_boundaries: Mapping[str, IrreversibleBoundary] | None = None,
    ) -> SearchBudgetSnapshot:
        """Stop new work at either wall and drain only reconciled expensive work."""

        runtime = self._search(child_id)
        snapshot = self.search_budget_snapshot(child_id)
        if snapshot.brake is SearchBrake.NONE:
            return snapshot
        self._engage_search_brake(runtime, snapshot.brake)
        boundaries = irreversible_boundaries or {}
        for attempt_id, attempt in runtime.attempts.items():
            if attempt.status is SearchAttemptStatus.SMOKE_RUNNING:
                assert attempt.handle is not None
                self._supervisor.request_termination(attempt.handle.worker_id)
                attempt.status = SearchAttemptStatus.DRAINING
                self._emit(
                    "search_attempt_draining",
                    child_id=child_id,
                    attempt_id=attempt_id,
                    stage="smoke",
                    irreversible_boundary=IrreversibleBoundary.CLEAR.value,
                )
            elif attempt.status is SearchAttemptStatus.COMPLETION_RUNNING:
                boundary = boundaries.get(attempt_id, IrreversibleBoundary.UNCERTAIN)
                if boundary is IrreversibleBoundary.UNCERTAIN:
                    self._emit(
                        "search_attempt_reconciliation_required",
                        child_id=child_id,
                        attempt_id=attempt_id,
                        brake=snapshot.brake.value,
                    )
                    continue
                assert attempt.handle is not None
                self._supervisor.request_termination(attempt.handle.worker_id)
                attempt.status = SearchAttemptStatus.DRAINING
                self._emit(
                    "search_attempt_draining",
                    child_id=child_id,
                    attempt_id=attempt_id,
                    stage="completion",
                    irreversible_boundary=boundary.value,
                )
        return snapshot

    def search_budget_snapshot(self, child_id: str) -> SearchBudgetSnapshot:
        """Read actual parent-attributed spend plus monotonic wall time."""

        runtime = self._search(child_id)
        current_spend = self._read_search_spend(child_id)
        if current_spend < runtime.baseline_spend_usd:
            raise ConductorError("authoritative search spend cannot move backwards")
        now = self._search_clock()
        if now < runtime.started_at:
            raise ConductorError("the monotonic search clock cannot move backwards")
        spent = current_spend - runtime.baseline_spend_usd
        elapsed = now - runtime.started_at
        budget = runtime.declaration.budget
        spend_hit = spent >= budget.spend_wall_usd
        clock_hit = elapsed >= budget.duration_seconds
        if spend_hit and clock_hit:
            brake = SearchBrake.SPEND_AND_CLOCK
        elif spend_hit:
            brake = SearchBrake.SPEND
        elif clock_hit:
            brake = SearchBrake.CLOCK
        else:
            brake = SearchBrake.NONE
        return SearchBudgetSnapshot(
            spent_usd=spent,
            remaining_usd=max(Decimal(0), budget.spend_wall_usd - spent),
            elapsed_seconds=elapsed,
            remaining_seconds=max(0.0, budget.duration_seconds - elapsed),
            brake=brake,
        )

    def search_attempt_status(self, child_id: str, attempt_id: str) -> SearchAttemptStatus:
        return self._search_attempt(child_id, attempt_id).status

    def search_results(self, child_id: str) -> tuple[TypedDistillate, ...]:
        """Return completion evidence for SYM8; no result is promoted here."""

        runtime = self._search(child_id)
        return tuple(
            attempt.distillate
            for attempt in runtime.attempts.values()
            if attempt.distillate is not None
        )

    def dispatch(self, child_id: str, command: Sequence[str]) -> AdmissionHandle:
        """Admit one dependency-ready child behind the supervisor launch gate."""

        claim = self._require_claim()
        child = self._child(child_id)
        if child.status is not ChildStatus.PLANNED:
            raise ConductorError("only a planned child may be dispatched")
        incomplete = [
            dependency
            for dependency in child.charge.depends_on
            if self._child(dependency).status is not ChildStatus.COMPLETED
        ]
        if incomplete:
            raise ConductorError(f"child dependencies are not complete: {incomplete}")
        policy = self._policy_for(child.charge)
        brief = self.render_worker_brief(child.charge, policy=policy, retry_number=0)
        worker_id = f"{claim.packet_id}:{child.charge.child_id}"
        attempt = self._supervisor.spawn(
            worker_id,
            command,
            location=child.charge.location,
            accepted_commit=self._checkpoint_for(child),
            environment=self._environment,
        )
        handle = self._admission(child, attempt, brief=brief, policy=policy)
        child.handle = handle
        child.status = ChildStatus.RUNNING
        self._emit("worker_admitted", **handle.model_dump(mode="json", exclude={"brief"}))
        return handle

    def observe(self, child_id: str) -> ChildStatus:
        """Refresh supervisor evidence without treating elapsed time as completion."""

        child = self._child(child_id)
        if child.status is not ChildStatus.RUNNING:
            return child.status
        if self._supervisor.heartbeat(self._worker_id(child)):
            return ChildStatus.RUNNING
        child.status = ChildStatus.AWAITING_DISTILLATE
        self._emit("worker_stopped", child_id=child_id, attempt_id=self._attempt_id(child))
        return child.status

    def certify_failure(self, child_id: str) -> ChildStatus:
        """Turn a stopped, resultless attempt into retryable failure or a flag."""

        child = self._child(child_id)
        if child.cancellation is not CancellationState.NONE:
            raise ConductorError("a cancellation must settle through its typed cancelled result")
        if self.observe(child_id) is ChildStatus.RUNNING:
            raise ConductorError("a live worker cannot be failed by the conductor")
        certificate = self._supervisor.certify_dead(self._worker_id(child))
        if child.retries >= self._max_retries:
            child.status = ChildStatus.FLAGGED
            self._emit(
                "child_flagged",
                child_id=child_id,
                attempt_id=certificate.attempt_id,
                reason="retry_limit_reached",
            )
            return child.status
        child.status = ChildStatus.FAILED
        self._emit(
            "attempt_failed",
            child_id=child_id,
            attempt_id=certificate.attempt_id,
            reason=certificate.reason,
            accepted_commit=certificate.accepted_commit,
        )
        return child.status

    def retry(
        self,
        child_id: str,
        command: Sequence[str],
        *,
        fresh_location: Path,
    ) -> AdmissionHandle:
        """Run an explicit successor from the last accepted commit in fresh ground."""

        child = self._child(child_id)
        if child.status is not ChildStatus.FAILED or child.handle is None:
            raise ConductorError("retry requires one certified failed attempt")
        if child.retries >= self._max_retries:
            child.status = ChildStatus.FLAGGED
            raise RetryLimitReached("two retries failed; mint a flag instead of another worker")
        canonical = fresh_location.expanduser().resolve(strict=True)
        original_locations = {runtime.charge.location for runtime in self._children.values()}
        admitted_locations = {
            runtime.handle.location
            for runtime in self._children.values()
            if runtime.handle is not None
        }
        if canonical in original_locations or canonical in admitted_locations:
            raise ConductorError("a successor requires a fresh worktree location")
        child.retries += 1
        policy = self._policy_for(child.charge)
        brief = self.render_worker_brief(
            child.charge,
            policy=policy,
            retry_number=child.retries,
            location=canonical,
        )
        attempt = self._supervisor.recover(
            self._worker_id(child),
            command,
            location=canonical,
            accepted_commit=child.handle.accepted_commit,
            environment=self._environment,
        )
        handle = self._admission(child, attempt, brief=brief, policy=policy)
        child.handle = handle
        child.status = ChildStatus.RUNNING
        self._emit("worker_readmitted", **handle.model_dump(mode="json", exclude={"brief"}))
        return handle

    def request_cancel(self, child_id: str) -> CancellationState:
        """Record requested before any process stop can begin."""

        child = self._child(child_id)
        if (
            child.status is not ChildStatus.RUNNING
            or child.cancellation is not CancellationState.NONE
        ):
            raise ConductorError("only one live, uncancelled attempt can receive cancellation")
        self._emit("cancellation_requested", child_id=child_id, attempt_id=self._attempt_id(child))
        child.cancellation = CancellationState.REQUESTED
        return child.cancellation

    def begin_draining(
        self,
        child_id: str,
        *,
        boundary: IrreversibleBoundary,
    ) -> CancellationState:
        """Stop new work only after the current irreversible boundary is known."""

        child = self._child(child_id)
        if child.cancellation is not CancellationState.REQUESTED:
            raise ConductorError("cancellation must be requested before draining")
        if boundary is IrreversibleBoundary.UNCERTAIN:
            raise ConductorError(
                "an uncertain irreversible action must reconcile before cancellation can drain"
            )
        self._emit(
            "cancellation_draining",
            child_id=child_id,
            attempt_id=self._attempt_id(child),
            irreversible_boundary=boundary.value,
        )
        child.cancellation = CancellationState.DRAINING
        self._supervisor.request_termination(self._worker_id(child))
        return child.cancellation

    def accept_distillate(
        self,
        child_id: str,
        value: TypedDistillate | Mapping[str, Any] | Path,
    ) -> TypedDistillate:
        """Accept exactly one stopped worker's typed envelope and no implicit result."""

        child = self._child(child_id)
        attempt_id = self._attempt_id(child)
        if attempt_id in child.result_attempt_ids:
            raise ConductorError("an attempt distillate is immutable once accepted")
        if self.observe(child_id) is ChildStatus.RUNNING:
            raise ConductorError("a live worker cannot commit a terminal distillate")
        distillate = self._load_distillate(child, value)
        final_distillate = False
        if child.cancellation is CancellationState.DRAINING:
            if distillate.status is not DistillateStatus.CANCELLED:
                raise ConductorError("a draining attempt may settle only as cancelled")
            self._supervisor.certify_dead(self._worker_id(child))
            next_cancellation = CancellationState.CANCELLED
            next_status = ChildStatus.CANCELLED
            final_distillate = True
        elif child.cancellation is not CancellationState.NONE:
            raise ConductorError("requested cancellation is not terminal until draining completes")
        elif distillate.status is DistillateStatus.COMPLETED:
            next_cancellation = child.cancellation
            next_status = ChildStatus.COMPLETED
            final_distillate = True
        else:
            self._supervisor.certify_dead(self._worker_id(child))
            next_cancellation = child.cancellation
            next_status = (
                ChildStatus.FLAGGED if child.retries >= self._max_retries else ChildStatus.FAILED
            )
            final_distillate = next_status is ChildStatus.FLAGGED
        digest = hashlib.sha256(
            distillate.model_dump_json(exclude_none=False).encode("utf-8")
        ).hexdigest()
        self._emit(
            "distillate_accepted",
            child_id=child_id,
            attempt_id=self._attempt_id(child),
            status=distillate.status.value,
            cancellation=next_cancellation.value,
            digest=digest,
            result=distillate.model_dump(mode="json"),
            winner_eligible=distillate.status is DistillateStatus.COMPLETED,
            memory_admissible=False,
        )
        child.cancellation = next_cancellation
        child.status = next_status
        child.attempt_distillates.append(distillate)
        child.result_attempt_ids.add(attempt_id)
        if final_distillate:
            child.distillate = distillate
        return distillate

    def child_status(self, child_id: str) -> ChildStatus:
        return self._child(child_id).status

    def cancellation_state(self, child_id: str) -> CancellationState:
        return self._child(child_id).cancellation

    def results(self) -> tuple[TypedDistillate, ...]:
        """Return accepted results only; stdout and worker prestige are not batons."""

        return tuple(
            distillate
            for child in self._children.values()
            for distillate in child.attempt_distillates
        )

    def render_worker_brief(
        self,
        child: ChildCharge,
        *,
        policy: str,
        retry_number: int,
        location: Path | None = None,
    ) -> str:
        """Append one assignment to the packaged standing mini-boot."""

        claim = self._require_claim()
        standing = (
            resources.files("harness").joinpath("WORKER_BRIEF.md").read_text(encoding="utf-8")
        )
        assignment = {
            "packet_id": claim.packet_id,
            "bead_id": claim.bead_id,
            "child_id": child.child_id,
            "title": child.title,
            "charge": child.charge,
            "motivation_chain": list(claim.motivation_chain),
            "allowed_surfaces": list(child.surfaces),
            "evidence_requirements": list(child.evidence_requirements),
            "accepted_commit": self._checkpoint_for(self._child(child.child_id)),
            "location": str((location or child.location).resolve(strict=True)),
            "model_policy": policy,
            "retry_number": retry_number,
        }
        rendered_assignment = json.dumps(assignment, indent=2)
        return f"{standing.rstrip()}\n\n## Assignment\n\n```json\n{rendered_assignment}\n```\n"

    def _launch_search_stage(
        self,
        child: _ChildRuntime,
        runtime: _SearchRuntime,
        attempt: _SearchAttemptRuntime,
        *,
        stage: Literal["smoke", "completion"],
        command: Sequence[str],
    ) -> AdmissionHandle:
        policy = self._policies.leaf
        brief = self._render_search_brief(child, runtime, attempt, stage=stage, policy=policy)
        worker_id = (
            f"{self._require_claim().packet_id}:{child.charge.child_id}:"
            f"{attempt.brief.attempt_id}:{stage}"
        )
        process_attempt = self._supervisor.spawn(
            worker_id,
            command,
            location=attempt.brief.location,
            accepted_commit=self._checkpoint_for(child),
            environment=self._environment,
        )
        if process_attempt.pid is None:
            raise SupervisorError("an admitted search worker lacks a process identity")
        handle = AdmissionHandle(
            packet_id=self._require_claim().packet_id,
            child_id=f"{child.charge.child_id}.{attempt.brief.attempt_id}.{stage}",
            worker_id=process_attempt.worker_id,
            attempt_id=process_attempt.attempt_id,
            accepted_commit=process_attempt.accepted_commit,
            location=process_attempt.location,
            model_policy=policy,
            brief_sha256=hashlib.sha256(brief.encode("utf-8")).hexdigest(),
            brief=brief,
            pid=process_attempt.pid,
            retry_number=0,
        )
        attempt.handle = handle
        attempt.stage = stage
        attempt.status = (
            SearchAttemptStatus.SMOKE_RUNNING
            if stage == "smoke"
            else SearchAttemptStatus.COMPLETION_RUNNING
        )
        self._emit(
            "search_worker_admitted",
            search_child_id=child.charge.child_id,
            search_attempt_id=attempt.brief.attempt_id,
            stage=stage,
            **handle.model_dump(mode="json", exclude={"brief"}),
        )
        return handle

    def _render_search_brief(
        self,
        child: _ChildRuntime,
        runtime: _SearchRuntime,
        attempt: _SearchAttemptRuntime,
        *,
        stage: Literal["smoke", "completion"],
        policy: str,
    ) -> str:
        claim = self._require_claim()
        standing = (
            resources.files("harness").joinpath("WORKER_BRIEF.md").read_text(encoding="utf-8")
        )
        assignment = {
            "packet_id": claim.packet_id,
            "bead_id": claim.bead_id,
            "child_id": child.charge.child_id,
            "search_attempt_id": attempt.brief.attempt_id,
            "search_marker": runtime.declaration.marker,
            "stage": stage,
            "stage_fence": (
                "Run only cheap compile/coherence checks; do not perform completion."
                if stage == "smoke"
                else "Complete only the declared approach and return a typed distillate."
            ),
            "approach": attempt.brief.approach,
            "charge": attempt.brief.charge,
            "motivation_chain": list(claim.motivation_chain),
            "allowed_surfaces": list(child.charge.surfaces),
            "evidence_requirements": list(child.charge.evidence_requirements),
            "accepted_commit": self._checkpoint_for(child),
            "location": str(attempt.brief.location),
            "model_policy": policy,
            "round_number": runtime.declaration.round_number,
            "depth": runtime.declaration.depth,
            "budget": runtime.declaration.budget.model_dump(mode="json"),
        }
        rendered_assignment = json.dumps(assignment, indent=2)
        return (
            f"{standing.rstrip()}\n\n## Search assignment\n\n```json\n{rendered_assignment}\n```\n"
        )

    def _load_smoke_result(
        self,
        attempt: _SearchAttemptRuntime,
        value: SmokeGateResult | Mapping[str, Any] | Path,
    ) -> SmokeGateResult:
        if isinstance(value, SmokeGateResult):
            result = value
        elif isinstance(value, Path):
            path = value.expanduser().resolve(strict=True)
            if not path.is_relative_to(attempt.brief.location):
                raise ConductorError("smoke result must stay inside the attempt location")
            if path.stat().st_size > _MAX_DISTILLATE_BYTES:
                raise ConductorError("smoke result exceeds the bounded result size")
            try:
                raw = path.read_text(encoding="utf-8")
                json.loads(raw, parse_constant=_reject_constant)
                result = SmokeGateResult.model_validate_json(raw)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise ConductorError("smoke result is not trustworthy JSON") from exc
        else:
            result = SmokeGateResult.model_validate(value)
        if len(result.model_dump_json().encode("utf-8")) > _MAX_DISTILLATE_BYTES:
            raise ConductorError("smoke result exceeds the bounded result size")
        return result

    def _load_distillate(
        self,
        child: _ChildRuntime,
        value: TypedDistillate | Mapping[str, Any] | Path,
    ) -> TypedDistillate:
        location = child.handle.location if child.handle is not None else child.charge.location
        return self._load_distillate_at(location, value)

    def _load_distillate_at(
        self,
        location: Path,
        value: TypedDistillate | Mapping[str, Any] | Path,
    ) -> TypedDistillate:
        if isinstance(value, TypedDistillate):
            result = value
        elif isinstance(value, Path):
            path = value.expanduser().resolve(strict=True)
            if not path.is_relative_to(location):
                raise ConductorError("distillate path must stay inside the worker location")
            if path.stat().st_size > _MAX_DISTILLATE_BYTES:
                raise ConductorError("distillate exceeds the bounded result size")
            try:
                raw = path.read_text(encoding="utf-8")
                json.loads(raw, parse_constant=_reject_constant)
                result = TypedDistillate.model_validate_json(raw)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise ConductorError("worker distillate is not trustworthy JSON") from exc
        else:
            result = TypedDistillate.model_validate(value)
        if len(result.model_dump_json(exclude_none=False).encode("utf-8")) > _MAX_DISTILLATE_BYTES:
            raise ConductorError("distillate exceeds the bounded result size")
        for artifact in result.artifacts:
            artifact_path = PurePosixPath(artifact)
            if artifact_path.is_absolute() or ".." in artifact_path.parts:
                raise ConductorError(
                    "artifact references must stay relative to the worker location"
                )
            resolved = (location / Path(*artifact_path.parts)).resolve(strict=False)
            if not resolved.is_relative_to(location):
                raise ConductorError("artifact reference escapes the worker location")
        return result

    def _read_search_spend(self, child_id: str) -> Decimal:
        if self._search_spend_reader is None:
            raise ConductorError("search requires an authoritative parent-attributed spend reader")
        try:
            value = self._search_spend_reader(self._require_claim().packet_id, child_id)
        except Exception as exc:
            raise ConductorError("authoritative search spend is unavailable") from exc
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ConductorError("authoritative search spend must be a finite non-negative Decimal")
        return value

    def _search(self, child_id: str) -> _SearchRuntime:
        try:
            return self._searches[child_id]
        except KeyError as exc:
            raise KeyError(f"unknown exploded search node {child_id!r}") from exc

    def _search_attempt(self, child_id: str, attempt_id: str) -> _SearchAttemptRuntime:
        runtime = self._search(child_id)
        try:
            return runtime.attempts[attempt_id]
        except KeyError as exc:
            raise KeyError(f"unknown search attempt {attempt_id!r}") from exc

    def _engage_search_brake(self, runtime: _SearchRuntime, brake: SearchBrake) -> None:
        if runtime.brake is brake:
            return
        runtime.brake = brake
        stopped = []
        for attempt in runtime.attempts.values():
            if attempt.status in {
                SearchAttemptStatus.PLANNED,
                SearchAttemptStatus.SMOKE_AWAITING_RESULT,
                SearchAttemptStatus.SMOKE_PASSED,
                SearchAttemptStatus.COMPLETION_READY,
            }:
                attempt.status = SearchAttemptStatus.BRAKED
                stopped.append(attempt.brief.attempt_id)
        self._emit(
            "search_brake_engaged",
            child_id=runtime.child_id,
            brake=brake.value,
            stopped=stopped,
        )
        self._settle_search_parent(runtime.child_id)

    def _settle_search_parent(self, child_id: str) -> None:
        runtime = self._search(child_id)
        terminal = {
            SearchAttemptStatus.SMOKE_FAILED,
            SearchAttemptStatus.BEAM_PRUNED,
            SearchAttemptStatus.BRAKED,
            SearchAttemptStatus.COMPLETED,
            SearchAttemptStatus.FAILED,
            SearchAttemptStatus.CANCELLED,
        }
        if all(attempt.status in terminal for attempt in runtime.attempts.values()):
            self._child(child_id).status = ChildStatus.AWAITING_DISTILLATE
            self._emit(
                "search_ready_for_judging",
                child_id=child_id,
                completed=[
                    attempt.brief.attempt_id
                    for attempt in runtime.attempts.values()
                    if attempt.status is SearchAttemptStatus.COMPLETED
                ],
            )

    def _admission(
        self,
        child: _ChildRuntime,
        attempt: Any,
        *,
        brief: str,
        policy: str,
    ) -> AdmissionHandle:
        if attempt.pid is None:
            raise SupervisorError("an admitted worker lacks a process identity")
        return AdmissionHandle(
            packet_id=self._require_claim().packet_id,
            child_id=child.charge.child_id,
            worker_id=attempt.worker_id,
            attempt_id=attempt.attempt_id,
            accepted_commit=attempt.accepted_commit,
            location=attempt.location,
            model_policy=policy,
            brief_sha256=hashlib.sha256(brief.encode("utf-8")).hexdigest(),
            brief=brief,
            pid=attempt.pid,
            retry_number=child.retries,
        )

    def _policy_for(self, child: ChildCharge) -> str:
        return self._policies.leaf if child.blast_radius == "leaf" else self._policies.compounding

    def _checkpoint_for(self, child: _ChildRuntime) -> str:
        claim = self._require_claim()
        checkpoint = claim.accepted_commit
        for dependency_id in child.charge.depends_on:
            dependency = self._child(dependency_id)
            if dependency.distillate is not None and dependency.distillate.product.kind == "commit":
                assert dependency.distillate.product.commit is not None
                checkpoint = dependency.distillate.product.commit
        return checkpoint

    def _worker_id(self, child: _ChildRuntime) -> str:
        if child.handle is None:
            raise ConductorError("child has no admitted worker")
        return child.handle.worker_id

    def _attempt_id(self, child: _ChildRuntime) -> str:
        if child.handle is None:
            raise ConductorError("child has no admitted attempt")
        return child.handle.attempt_id

    def _child(self, child_id: str) -> _ChildRuntime:
        try:
            return self._children[child_id]
        except KeyError as exc:
            raise KeyError(f"unknown conductor child {child_id!r}") from exc

    def _require_claim(self) -> AuthoritativeClaim:
        if self._claim is None:
            raise ConductorError("the conductor requires an authoritative claim first")
        return self._claim

    def _emit(self, event: str, **payload: Any) -> None:
        self._event_sink({"schema_version": 1, "event": event, **payload})

    @staticmethod
    def _assert_acyclic(children: Sequence[ChildCharge]) -> None:
        dependencies = {child.child_id: set(child.depends_on) for child in children}
        ready = [child_id for child_id, deps in dependencies.items() if not deps]
        visited: set[str] = set()
        while ready:
            current = ready.pop()
            if current in visited:
                continue
            visited.add(current)
            for child_id, deps in dependencies.items():
                if current in deps and deps.issubset(visited):
                    ready.append(child_id)
        if len(visited) != len(children):
            raise ValueError("expanded child dependencies must be acyclic")


def _normalize_surface(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("surface paths must be nonblank without surrounding whitespace")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or ".." in path.parts or "." in path.parts:
        raise ValueError("surface paths must be normalized workspace-relative paths")
    return value


def _scrub_environment(environment: Mapping[str, str]) -> dict[str, str]:
    scrubbed = {
        key: value
        for key in _SAFE_ENVIRONMENT
        if isinstance((value := environment.get(key)), str) and value
    }
    scrubbed["PYTHONUNBUFFERED"] = "1"
    return scrubbed


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")
