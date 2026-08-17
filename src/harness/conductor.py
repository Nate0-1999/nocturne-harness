"""Bounded Symphony conductor: authoritative claim in, typed distillates out."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
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


EventSink = Callable[[Mapping[str, Any]], None]


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
    ) -> None:
        if max_retries != 2:
            raise ValueError("G7 fixes the worker retry count at two")
        self._supervisor = supervisor
        self._event_sink = event_sink
        self._policies = policies or ModelPolicyByBlastRadius()
        self._environment = _scrub_environment(os.environ if environment is None else environment)
        self._max_retries = max_retries
        self._claim: AuthoritativeClaim | None = None
        self._children: dict[str, _ChildRuntime] = {}

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
        locations = {child.location for child in proposed}
        if len(locations) != len(proposed):
            raise ValueError("parallel children require distinct worktree locations")
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

    def _load_distillate(
        self,
        child: _ChildRuntime,
        value: TypedDistillate | Mapping[str, Any] | Path,
    ) -> TypedDistillate:
        if isinstance(value, TypedDistillate):
            result = value
        elif isinstance(value, Path):
            path = value.expanduser().resolve(strict=True)
            location = child.handle.location if child.handle is not None else child.charge.location
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
        location = child.handle.location if child.handle is not None else child.charge.location
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
