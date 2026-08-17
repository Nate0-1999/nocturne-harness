"""Independent Symphony judge sessions, unanimous verdicts, and feedback minting."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.conductor import (
    Conductor,
    JudgeCharter,
    JudgeSeat,
    SearchAttemptRecord,
    SearchJudgmentStatus,
)
from harness.supervisor import WorkerSupervisor

_MAX_JUDGE_RECORD_BYTES = 64 * 1024
_SAFE_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "TMPDIR")


class JudgePanelError(RuntimeError):
    """The panel cannot advance without weakening independence or provenance."""


class JudgeOutcome(str):
    """Literal namespace retained for readable result construction."""

    PASS = "pass"
    FAIL = "fail"


class MetricAssessment(BaseModel):
    """One performance-judge observation against a deliberation-fixed metric."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    metric: str
    observed: str
    passed: bool
    evidence_ref: str

    @model_validator(mode="after")
    def _validate_metric(self) -> MetricAssessment:
        if any(not value.strip() for value in (self.metric, self.observed, self.evidence_ref)):
            raise ValueError("metric assessments require nonblank observation and evidence")
        return self


class JudgeFeedback(BaseModel):
    """A judge-authored delta that can become one scoped feedback packet."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    problem: str
    desired_observation: str
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_feedback(self) -> JudgeFeedback:
        if (
            not self.problem.strip()
            or not self.desired_observation.strip()
            or not self.evidence_refs
            or any(not value.strip() for value in self.evidence_refs)
        ):
            raise ValueError("judge feedback requires a problem, observable exit, and evidence")
        return self


class JudgeVerdict(BaseModel):
    """One fresh seat's complete, artifact-bound verdict."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    seat: str
    judge_session_id: str
    charter_sha256: str
    evidence_sha256: str
    outcome: Literal["pass", "fail"]
    selected_attempt_id: str | None
    rationale: str
    evidence_refs: tuple[str, ...]
    feedback: tuple[JudgeFeedback, ...]
    metrics: tuple[MetricAssessment, ...] = ()

    @model_validator(mode="after")
    def _validate_verdict(self) -> JudgeVerdict:
        if (
            not self.judge_session_id.strip()
            or not self.rationale.strip()
            or not self.evidence_refs
            or any(not value.strip() for value in self.evidence_refs)
        ):
            raise ValueError("judge verdicts require session, rationale, and direct evidence")
        for label, digest in (
            ("charter", self.charter_sha256),
            ("evidence", self.evidence_sha256),
        ):
            if not _is_sha256(digest):
                raise ValueError(f"{label} digest must be lowercase SHA-256")
        if self.outcome == JudgeOutcome.PASS:
            if self.selected_attempt_id is None or self.feedback:
                raise ValueError("a PASS selects one attempt and carries no repair feedback")
        elif self.selected_attempt_id is not None or not self.feedback:
            raise ValueError("a FAIL selects no attempt and carries repair feedback")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class JudgeEvidence(BaseModel):
    """The complete why plus artifacts, never builder reasoning or ambient context."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    packet_id: str
    search_child_id: str
    packet_charge_sha256: str
    child_charge: str
    motivation_chain: tuple[str, ...]
    surfaces: tuple[str, ...]
    charter: JudgeCharter
    candidates: tuple[SearchAttemptRecord, ...]
    attempt_lineage: tuple[SearchAttemptRecord, ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


class JudgeLaunch(BaseModel):
    """One caller-supplied headless command and its fresh session directory."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    command: tuple[str, ...]
    location: Path

    @model_validator(mode="after")
    def _validate_launch(self) -> JudgeLaunch:
        if not self.command or any(not value for value in self.command):
            raise ValueError("judge launch commands must be nonempty")
        location = self.location.expanduser().resolve(strict=True)
        if not location.is_dir():
            raise ValueError("judge session location must be an existing directory")
        object.__setattr__(self, "location", location)
        return self


class JudgeSession(BaseModel):
    """The process-evidenced identity of one independent judge seat."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    seat: str
    judge_session_id: str
    worker_id: str
    model_policy: str
    charter_sha256: str
    evidence_sha256: str
    brief_path: Path
    session_path: Path
    pid: int = Field(gt=0)


class FeedbackPacketDraft(BaseModel):
    """A deterministic packet request crossing the injected Garden adapter seam."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    packet_id: str
    title: str
    charge: str
    source_verdict_sha256: str

    @model_validator(mode="after")
    def _validate_draft(self) -> FeedbackPacketDraft:
        if (
            not self.packet_id.strip()
            or not self.title.strip()
            or not self.charge.strip()
            or not _is_sha256(self.source_verdict_sha256)
        ):
            raise ValueError("feedback drafts require identity, charge, and verdict provenance")
        return self


class FeedbackPacketReceipt(BaseModel):
    """The adapter's graph identity returned after scoped mint authorization."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    packet_id: str
    bead_id: str
    charge_digest: str
    minter_role: Literal["judge"]

    @model_validator(mode="after")
    def _validate_receipt(self) -> FeedbackPacketReceipt:
        if (
            not self.packet_id.strip()
            or not self.bead_id.strip()
            or not _is_sha256(self.charge_digest)
        ):
            raise ValueError("feedback receipts require graph identity and charge digest")
        return self


class FeedbackMinter(Protocol):
    """Injected adapter authority; the panel never receives owner/gate mint power."""

    def __call__(self, draft: FeedbackPacketDraft) -> FeedbackPacketReceipt: ...


class PanelDecision(BaseModel):
    """One append-only full-lineage panel record."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    packet_id: str
    search_child_id: str
    status: SearchJudgmentStatus
    winner_attempt_id: str | None
    evidence_sha256: str
    verdicts: tuple[JudgeVerdict, ...]
    attempt_lineage: tuple[SearchAttemptRecord, ...]
    feedback_packets: tuple[FeedbackPacketReceipt, ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()


EventSink = Callable[[Mapping[str, Any]], None]


class JudgePanel:
    """Dispatch and resolve the three deliberation-fixed, independent judge seats."""

    def __init__(
        self,
        *,
        conductor: Conductor,
        search_child_id: str,
        supervisor: WorkerSupervisor,
        event_sink: EventSink,
        feedback_minter: FeedbackMinter,
    ) -> None:
        claim = conductor.claim_handle
        if claim is None:
            raise JudgePanelError("a judge panel requires the conductor's authoritative claim")
        self._conductor = conductor
        self._search_child_id = search_child_id
        self._supervisor = supervisor
        self._event_sink = event_sink
        self._feedback_minter = feedback_minter
        self._claim = claim
        self._candidates = conductor.search_results(search_child_id)
        self._lineage = conductor.search_lineage(search_child_id)
        charters = conductor.search_charters(search_child_id)
        self._seat_order = tuple(charter.seat for charter in charters)
        self._charters = {charter.seat: charter for charter in charters}
        self._surfaces = conductor.search_surface_fence(search_child_id)
        self._child_charge = conductor.search_charge(search_child_id)
        self._sessions: dict[str, JudgeSession] = {}
        self._verdicts: dict[str, JudgeVerdict] = {}
        self._decision: PanelDecision | None = None

    def dispatch(self, launches: Mapping[str, JudgeLaunch]) -> tuple[JudgeSession, ...]:
        """Launch three distinct OS processes from three sealed briefs."""

        if self._sessions:
            raise JudgePanelError("judge sessions may be dispatched exactly once")
        normalized = {str(seat): launch for seat, launch in launches.items()}
        if set(normalized) != set(self._seat_order) or len(normalized) != len(launches):
            raise ValueError("dispatch requires every deliberation-fixed judge seat exactly once")
        locations = [normalized[seat].location for seat in self._seat_order]
        if len(set(locations)) != len(locations):
            raise ValueError("fresh judge sessions require distinct directories")
        sessions: list[JudgeSession] = []
        for seat in self._seat_order:
            charter = self._charters[seat]
            evidence = self._evidence(charter)
            launch = normalized[seat]
            brief_path = launch.location / "JUDGE_BRIEF.json"
            _write_private_json(brief_path, evidence.model_dump_json(indent=2))
            worker_id = f"{self._claim.packet_id}:{self._search_child_id}:judge:{seat}"
            attempt = self._supervisor.spawn(
                worker_id,
                launch.command,
                location=launch.location,
                accepted_commit=self._claim.accepted_commit,
                environment=_safe_environment(),
            )
            if attempt.pid is None:
                raise JudgePanelError("a judge session lacks process evidence")
            session = JudgeSession(
                seat=seat,
                judge_session_id=attempt.attempt_id,
                worker_id=worker_id,
                model_policy=charter.model_policy,
                charter_sha256=charter.digest,
                evidence_sha256=evidence.digest,
                brief_path=brief_path,
                session_path=launch.location / "JUDGE_SESSION.json",
                pid=attempt.pid,
            )
            _write_private_json(
                session.session_path,
                json.dumps(
                    {
                        "schema_version": 1,
                        "seat": seat,
                        "judge_session_id": session.judge_session_id,
                        "model_policy": session.model_policy,
                        "charter_sha256": session.charter_sha256,
                        "evidence_sha256": session.evidence_sha256,
                    },
                    indent=2,
                ),
            )
            self._sessions[seat] = session
            sessions.append(session)
            self._emit(
                "judge_session_dispatched",
                **session.model_dump(mode="json", exclude={"brief_path", "session_path"}),
            )
        if len({session.judge_session_id for session in sessions}) != 3:
            raise JudgePanelError("fresh judge sessions must have distinct process attempts")
        return tuple(sessions)

    def accept_verdict(self, seat: str, path: Path | None = None) -> JudgeVerdict:
        """Accept one stopped session's exact artifact-bound verdict."""

        seat_id = str(seat)
        if seat_id in self._verdicts:
            raise JudgePanelError("a judge verdict is immutable once accepted")
        try:
            session = self._sessions[seat_id]
        except KeyError as exc:
            raise JudgePanelError("the judge seat was not dispatched") from exc
        if self._supervisor.heartbeat(session.worker_id):
            raise JudgePanelError("a live judge session cannot return a terminal verdict")
        verdict_path = (path or session.brief_path.with_name("judge-verdict.json")).resolve(
            strict=True
        )
        location = session.brief_path.parent
        if not verdict_path.is_relative_to(location):
            raise JudgePanelError("judge verdicts must stay inside the fresh session directory")
        if verdict_path.stat().st_size > _MAX_JUDGE_RECORD_BYTES:
            raise JudgePanelError("judge verdict exceeds the bounded record size")
        try:
            raw = verdict_path.read_text(encoding="utf-8")
            json.loads(raw, parse_constant=_reject_constant)
            verdict = JudgeVerdict.model_validate_json(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise JudgePanelError("judge verdict is not trustworthy JSON") from exc
        self._validate_verdict(session, verdict)
        self._supervisor.certify_dead(session.worker_id)
        self._verdicts[seat_id] = verdict
        self._emit(
            "judge_verdict_accepted",
            seat=seat_id,
            judge_session_id=session.judge_session_id,
            verdict_sha256=verdict.digest,
            outcome=verdict.outcome,
            selected_attempt_id=verdict.selected_attempt_id,
        )
        return verdict

    def resolve(self) -> PanelDecision:
        """Pass one shared candidate only on 3/3; otherwise mint feedback and fail."""

        if self._decision is not None:
            raise JudgePanelError("a panel decision is immutable once resolved")
        if set(self._verdicts) != set(self._seat_order):
            raise JudgePanelError("all deliberation-fixed fresh verdicts are required")
        verdicts = tuple(self._verdicts[seat] for seat in self._seat_order)
        selections = {verdict.selected_attempt_id for verdict in verdicts}
        unanimous = (
            all(verdict.outcome == JudgeOutcome.PASS for verdict in verdicts)
            and len(selections) == 1
            and None not in selections
        )
        if unanimous:
            winner = next(iter(selections))
            assert winner is not None
            status = SearchJudgmentStatus.UNANIMOUS_PASS
            receipts: tuple[FeedbackPacketReceipt, ...] = ()
        else:
            winner = None
            status = SearchJudgmentStatus.FAILED_JUDGMENT
            drafts = self._feedback_drafts(verdicts)
            receipts = tuple(self._feedback_minter(draft) for draft in drafts)
            if not receipts:
                raise JudgePanelError("FAILED_JUDGMENT must persist at least one feedback packet")
            if tuple(receipt.packet_id for receipt in receipts) != tuple(
                draft.packet_id for draft in drafts
            ):
                raise JudgePanelError("feedback mint receipts do not match their requests")
            if any(
                receipt.charge_digest != hashlib.sha256(draft.charge.encode()).hexdigest()
                for draft, receipt in zip(drafts, receipts, strict=True)
            ):
                raise JudgePanelError("feedback mint receipt does not bind the requested charge")
        decision = PanelDecision(
            packet_id=self._claim.packet_id,
            search_child_id=self._search_child_id,
            status=status,
            winner_attempt_id=winner,
            evidence_sha256=self._panel_evidence_digest(),
            verdicts=verdicts,
            attempt_lineage=self._lineage,
            feedback_packets=receipts,
        )
        self._conductor.record_search_judgment(
            self._search_child_id,
            status=status,
            decision_digest=decision.digest,
            winner_attempt_id=winner,
            feedback_packet_ids=tuple(receipt.packet_id for receipt in receipts),
        )
        self._decision = decision
        self._emit("judge_panel_resolved", decision=decision.model_dump(mode="json"))
        return decision

    def _evidence(self, charter: JudgeCharter) -> JudgeEvidence:
        return JudgeEvidence(
            packet_id=self._claim.packet_id,
            search_child_id=self._search_child_id,
            packet_charge_sha256=self._claim.charge_digest,
            child_charge=self._child_charge,
            motivation_chain=self._claim.motivation_chain,
            surfaces=self._surfaces,
            charter=charter,
            candidates=self._candidates,
            attempt_lineage=self._lineage,
        )

    def _validate_verdict(self, session: JudgeSession, verdict: JudgeVerdict) -> None:
        if (
            verdict.seat != session.seat
            or verdict.judge_session_id != session.judge_session_id
            or verdict.charter_sha256 != session.charter_sha256
            or verdict.evidence_sha256 != session.evidence_sha256
        ):
            raise JudgePanelError("judge verdict does not match its sealed fresh session")
        candidate_ids = {candidate.attempt_id for candidate in self._candidates}
        if (
            verdict.selected_attempt_id is not None
            and verdict.selected_attempt_id not in candidate_ids
        ):
            raise JudgePanelError("judge selected a non-candidate attempt")
        charter = self._charters[session.seat]
        metric_names = tuple(metric.metric for metric in verdict.metrics)
        if session.seat == JudgeSeat.PERFORMANCE:
            if metric_names != charter.metrics:
                raise JudgePanelError("performance verdict must assess every fixed metric in order")
            if verdict.outcome == JudgeOutcome.PASS and any(
                not metric.passed for metric in verdict.metrics
            ):
                raise JudgePanelError("performance cannot PASS a failed fixed metric")
        elif verdict.metrics:
            raise JudgePanelError("only the performance seat may return metric assessments")

    def _feedback_drafts(self, verdicts: Sequence[JudgeVerdict]) -> tuple[FeedbackPacketDraft, ...]:
        failed = [verdict for verdict in verdicts if verdict.outcome == JudgeOutcome.FAIL]
        if failed:
            feedback_items = [
                (verdict.seat, feedback) for verdict in failed for feedback in verdict.feedback
            ]
            feedback = JudgeFeedback(
                problem=" ".join(
                    f"{seat} judge: {_one_line(item.problem)}" for seat, item in feedback_items
                ),
                desired_observation=" ".join(
                    _one_line(item.desired_observation) for _seat, item in feedback_items
                ),
                evidence_refs=tuple(
                    reference for _seat, item in feedback_items for reference in item.evidence_refs
                ),
            )
        else:
            selection_text = "; ".join(
                f"{verdict.seat} selected {verdict.selected_attempt_id}: "
                f"{_one_line(verdict.rationale)}"
                for verdict in verdicts
            )
            panel_feedback = JudgeFeedback(
                problem=f"The three passing seats selected different attempts. {selection_text}",
                desired_observation="One revised attempt earns all three fixed charter passes.",
                evidence_refs=tuple(
                    reference for verdict in verdicts for reference in verdict.evidence_refs
                ),
            )
            feedback = panel_feedback
        source_digest = hashlib.sha256(
            "|".join(verdict.digest for verdict in verdicts).encode()
        ).hexdigest()
        return (self._feedback_packet("panel", source_digest, feedback),)

    def _feedback_packet(
        self,
        source: str,
        source_digest: str,
        feedback: JudgeFeedback,
    ) -> FeedbackPacketDraft:
        identity_source = (
            f"{self._claim.packet_id}|{self._search_child_id}|{source}|"
            f"{source_digest}|{feedback.model_dump_json()}"
        )
        packet_id = f"FB{hashlib.sha256(identity_source.encode()).hexdigest()[:20].upper()}"
        surfaces = ", ".join(self._surfaces)
        evidence = ", ".join(feedback.evidence_refs)
        charge = (
            f"MOTIVATION: P3 — {_one_line(feedback.problem)}\n"
            f"RECIPE: deps —; surfaces {surfaces}; excl none; parallel: OPEN\n"
            "AUTHORITY: none beyond CONTRACTS\n"
            f"DELIVER: {_one_line(feedback.desired_observation)} Evidence: {_one_line(evidence)}. "
            f"Source verdict: {source_digest}.\n"
            f"EXIT: The {source} judge's failed observation is directly re-proved."
        )
        return FeedbackPacketDraft(
            packet_id=packet_id,
            title=f"{self._claim.packet_id} {source} judge feedback",
            charge=charge,
            source_verdict_sha256=source_digest,
        )

    def _panel_evidence_digest(self) -> str:
        payload = {
            "packet_id": self._claim.packet_id,
            "search_child_id": self._search_child_id,
            "charters": [self._charters[seat].model_dump(mode="json") for seat in self._seat_order],
            "lineage": [record.model_dump(mode="json") for record in self._lineage],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _emit(self, event: str, **payload: Any) -> None:
        self._event_sink({"schema_version": 1, "event": event, **payload})


def _safe_environment() -> dict[str, str]:
    environment = {
        key: value
        for key in _SAFE_ENVIRONMENT
        if isinstance((value := os.environ.get(key)), str) and value
    }
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _write_private_json(path: Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o600)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _is_sha256(value: str) -> bool:
    return (
        len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")
