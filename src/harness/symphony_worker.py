"""Run a supervised Symphony brief through the ordinary model and workspace hands."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import subprocess
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, PromptedOutput, capture_run_messages
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.usage import UsageLimits

from harness.agent import ExtractionCandidateDraft
from harness.conductor import ProductBaton, SmokeGateResult, TypedDistillate
from harness.config import HarnessSettings
from harness.judge_panel import (
    JudgeEvidence,
    JudgeFeedback,
    JudgePanelError,
    JudgeVerdict,
    MetricAssessment,
    validate_judge_verdict,
)
from harness.model_policy import ModelPolicyResolver
from harness.model_router import CompletionRouter, model_settings_for
from harness.pydantic_ai_adapter import WorkspaceCapability, adopted_skill_capabilities
from harness.receipt_queue import SpendReceiptQueue
from harness.spend import SpendLineage, model_response_receipts
from harness.spine_client import SpineClient
from harness.symphony_context import WorkerContext
from harness.tools_memory import MemoryToolContext
from harness.toolset_runtime import LazyStandardToolset
from harness.visualization import observe_worker


class WorkResult(BaseModel):
    """A worker's bounded return; full tool and model history stays on disk. [G15]"""

    completed: bool
    claims: list[str]
    evidence_refs: list[str]
    uncertainties: list[str]
    memories: list[ExtractionCandidateDraft]


class MetricObservation(BaseModel):
    """The judge supplies evidence; the sealed charter owns metric names. [D.2 102]"""

    observed: str
    passed: bool
    evidence_ref: str


class JudgeAssessment(BaseModel):
    """Model-authored judgment, without asking a model to copy provenance. [ADR-012]"""

    outcome: Literal["pass", "fail"]
    selected_attempt_id: str | None
    rationale: str
    evidence_refs: tuple[str, ...]
    feedback: tuple[JudgeFeedback, ...]
    metrics: tuple[MetricObservation, ...] = ()

    def bind(self, session: dict, sealed: JudgeEvidence) -> JudgeVerdict:
        names = sealed.charter.metrics if session["seat"] == "performance" else ()
        if len(names) != len(self.metrics):
            raise ValueError(
                f"Return exactly {len(names)} metric observations, not {len(self.metrics)}. "
                f"One observation for each complete charter entry: {json.dumps(names)}. "
                "Do not split an entry into separate observations for its subchecks."
            )
        verdict = JudgeVerdict(
            schema_version=1,
            **{
                key: session[key]
                for key in ("seat", "judge_session_id", "charter_sha256", "evidence_sha256")
            },
            **self.model_dump(exclude={"metrics", "feedback", "evidence_refs"}),
            evidence_refs=self.evidence_refs,
            feedback=self.feedback,
            metrics=tuple(
                MetricAssessment(metric=name, **observation.model_dump())
                for name, observation in zip(names, self.metrics, strict=True)
            ),
        )
        validate_judge_verdict(
            verdict,
            session=session,
            charter=sealed.charter,
            candidate_ids={candidate.attempt_id for candidate in sealed.candidates},
        )
        return verdict


def _write(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


async def run(assignment_path: Path) -> None:
    """Keep credentials outside worktrees and meter real responses at every event."""

    assignment = json.loads(assignment_path.read_text())
    output = assignment_path.parent
    settings = HarnessSettings(_env_file=assignment["env_file"])
    root = Path.cwd()
    stage = assignment["stage"]
    router = CompletionRouter(settings)
    resolver = ModelPolicyResolver(
        policy=assignment["model_policy"],
        static_model=settings.chat_model,
        static_context_tokens=settings.model_context_tokens,
        catalog=router.catalog,
    )
    resolution = await resolver.resolve(assignment["thread_id"])
    output_type = {
        "smoke": SmokeGateResult,
        "completion": WorkResult,
        "judge": JudgeAssessment,
    }[stage]
    agent = Agent(
        deps_type=MemoryToolContext,
        capabilities=[WorkspaceCapability(), *adopted_skill_capabilities(())],
        output_type=PromptedOutput(output_type),
        name=f"symphony-{stage}",
        instructions=(
            "You are checking whether proposed work can START. Missing output files are "
            "expected before implementation and are not a readiness failure. Check only "
            "prerequisites such as the workspace and required input files. The signed "
            "stratagem may name a prerequisite: execute its check and fail readiness if "
            "it is absent. The absence of code using a dependency does not prove it exists. "
            "acceptance criteria will be checked by independent judges AFTER implementation. "
            "Do not implement anything during this readiness check."
            if stage == "smoke"
            else None
        ),
    )
    toolset = LazyStandardToolset(
        cwd=root,
        workspace_root=Path(assignment.get("workspace_root", str(root))),
        agent_id=assignment["origin_agent"],
        machine_id=settings.machine_id,
    )
    spine = SpineClient(
        settings.spine_url,
        settings.spine_token.get_secret_value(),
        principal_id=settings.principal_id,
    )
    context = MemoryToolContext(
        spine=spine,
        principal_id=settings.principal_id,
        machine_id=settings.machine_id,
        agent_id=assignment["origin_agent"],
        thread_id=UUID(assignment["thread_id"]),
        project_key=assignment["project_key"],
        toolset=toolset,
    )
    lineage = SpendLineage(
        principal_id=settings.principal_id,
        machine_id=settings.machine_id,
        origin_agent=assignment["origin_agent"],
        thread_id=context.thread_id,
        run_id=assignment["run_id"],
        prompt_id=assignment["prompt_id"],
    )
    captured = []
    worker_context = WorkerContext(
        assignment=assignment,
        output=output,
        context=context,
        resolution=resolution,
    )

    async def instructions(_ctx):
        return await worker_context.render(captured)

    def receipt():
        return model_response_receipts(
            [message for message in captured if isinstance(message, ModelResponse)],
            lineage=lineage,
            purpose="judge" if stage == "judge" else "building",
        )

    async def observe(_context, events):
        async for _event in events:
            observe_worker(
                output, assignment, toolset.location(), "running", toolset.presence_events()
            )
            worker_context.publish(captured)
            request = receipt()
            if request is not None:
                _write(
                    output / "meter.json",
                    json.dumps(
                        {
                            "cost_usd": str(sum(event.cost_usd or 0 for event in request.events)),
                            "unpriced": any(event.cost_usd is None for event in request.events),
                        }
                    ),
                )

    observe_worker(output, assignment, toolset.location(), "running")
    prompt = assignment["brief"]
    if stage == "judge":
        # WALL attention / ADR-012: judges see sealed artifacts, never builder history.
        while not (root / "JUDGE_SESSION.json").exists():
            await asyncio.sleep(0.01)
        prompt += "\n" + (root / "JUDGE_BRIEF.json").read_text()
        prompt += "\n" + (root / "JUDGE_SESSION.json").read_text()
        sealed = JudgeEvidence.model_validate_json((root / "JUDGE_BRIEF.json").read_text())
        session = json.loads((root / "JUDGE_SESSION.json").read_text())

        @agent.output_validator
        def validate_return(_ctx, verdict):
            try:
                return verdict.bind(session, sealed)
            except (JudgePanelError, ValueError) as exc:
                raise ModelRetry(str(exc)) from exc

        metric_count = len(sealed.charter.metrics) if session["seat"] == "performance" else 0
        prompt += (
            f"\nYour current directory is {root}. Candidate artifact_root values are absolute "
            "paths; use them exactly as given. "
            "\nInspect the actual candidate files and run the charter's checks. "
            "Do not edit candidate work. Return your own assessment. "
            "A failed metric or missing evidence is FAIL."
            " The performance seat must return one observation per charter metric, "
            "in the given order; the other seats return an empty metrics list."
            f" This seat requires exactly {metric_count} observations."
        )
    elif stage == "smoke":
        prompt = (
            "Assess readiness for the following proposed work. You are already in the "
            "isolated worktree. Read the directory and identify prerequisites; do not write "
            "files or implement the proposal during this smoke stage.\nProposed work:\n"
            + prompt
            + "\nEND OF PROPOSED WORK. You are the readiness checker, not its judge. "
            "A prior judge's repair request is work to perform AFTER readiness passes. "
            "Missing outputs that this step must CREATE are never missing prerequisites. "
            "Do not apply completion acceptance criteria to this readiness verdict."
        )
    else:
        prompt += (
            "\nDo the requested work using your workspace tools. Verify the actual files. "
            "Your current directory IS the isolated attempt; do not invent another folder. "
            "Return concise claims and direct evidence paths; name any unfinished work. "
            "Do not commit: the supervisor captures your exact patch. You have no memory tools. "
            "Return any durable lessons as atomic memories of at most 128 tokens each, "
            "or an empty memories list when nothing was learned."
        )
    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        with capture_run_messages() as captured:
            result = await agent.run(
                prompt,
                deps=context,
                model=router.model_for(resolution.model),
                model_settings=model_settings_for(resolution, assignment["thread_id"]),
                usage_limits=UsageLimits(
                    request_limit=settings.run_request_limit,
                    total_tokens_limit=settings.run_total_tokens_limit,
                ),
                event_stream_handler=observe,
                instructions=instructions,
            )
        worker_context.publish(captured)
        if stage == "completion":
            subprocess.run(["git", "add", "-A"], check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Nocturne",
                    "-c",
                    "user.email=nocturne@localhost",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "Symphony: capture verified attempt",
                ],
                check=True,
                capture_output=True,
            )
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            work = result.output
            _write(
                output / "memories.json",
                json.dumps([memory.model_dump() for memory in work.memories]),
            )
            value = TypedDistillate.model_validate_json(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "completed" if work.completed else "failed",
                        "claims": work.claims,
                        "evidence_refs": work.evidence_refs,
                        "uncertainties": work.uncertainties,
                        "metrics_refs": [str(output / "meter.json")],
                        "artifacts": work.evidence_refs,
                        "patch": None,
                        "product": ProductBaton(kind="commit", commit=commit).model_dump(),
                    }
                )
            )
        else:
            value = result.output
        _write(output / "result.json", value.model_dump_json(indent=2))
        if stage == "judge":
            _write(root / "judge-verdict.json", value.model_dump_json(indent=2))
    finally:
        asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)
        observe_worker(output, assignment, toolset.location(), "stopped", toolset.presence_events())
        _write(output / "messages.json", ModelMessagesTypeAdapter.dump_json(captured).decode())
        request = receipt()
        if request is not None:
            _write(output / "receipts.json", request.model_dump_json(indent=2))
            _write(
                output / "meter.json",
                json.dumps(
                    {
                        "cost_usd": str(sum(event.cost_usd or 0 for event in request.events)),
                        "unpriced": any(event.cost_usd is None for event in request.events),
                    }
                ),
            )
            queue = SpendReceiptQueue(Path(assignment["home"]) / "receipt-queue")
            try:
                response = await spine.record_spend_events(request)
                if response.accepted != len(request.events):
                    await queue.enqueue(request)
            except Exception:
                await queue.enqueue(request)
        await toolset.close()
        await spine.aclose()
        await router.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("assignment", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.assignment))


if __name__ == "__main__":
    main()
