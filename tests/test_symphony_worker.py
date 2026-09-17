from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.function import FunctionModel

from harness import symphony_worker
from harness.spine_client import InjectPrepareResponse, MemoryAllocation
from harness.symphony_context import COMPONENT_REGISTRY, WorkerContext, write_json
from harness.toolset import AgentLocation


@pytest.mark.asyncio
async def test_judge_retries_missing_metrics_and_writes_the_panel_return(tmp_path, monkeypatch):
    """M3SY / ADR-012: a real worker uses the panel contract before publishing PASS."""
    session = {
        "schema_version": 1,
        "seat": "performance",
        "judge_session_id": "judge-session",
        "charter_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "model_policy": "pinned:openrouter:test/model",
    }
    charter = {
        "seat": "performance",
        "rubric": ["Exact result"],
        "evidence_requirements": ["result.txt"],
        "metrics": ["café checksum = 150"],
    }
    brief = {
        "schema_version": 1,
        "packet_id": "packet",
        "search_child_id": "child",
        "packet_charge_sha256": "c" * 64,
        "child_charge": "Write result.txt",
        "motivation_chain": ["Verify real work"],
        "surfaces": ["."],
        "charter": charter,
        "candidates": [
            {
                "attempt_id": "attempt-1",
                "approach": "direct",
                "artifact_root": str(tmp_path),
                "accepted_commit": "base",
                "status": "completed",
                "smoke": None,
                "distillate": None,
            }
        ],
        "attempt_lineage": [],
    }
    (tmp_path / "JUDGE_SESSION.json").write_text(json.dumps(session))
    (tmp_path / "JUDGE_BRIEF.json").write_text(json.dumps(brief))
    (tmp_path / "env").write_text("SPINE_TOKEN='test'\nPRINCIPAL_ID='verification-test'\n")
    assignment = {
        "stage": "judge",
        "brief": "Judge the result",
        "env_file": str(tmp_path / "env"),
        "model_policy": "pinned:openrouter:test/model",
        "origin_agent": "test/root",
        "thread_id": "12345678-1234-5678-1234-567812345678",
        "project_key": str(tmp_path),
        "run_id": "01M2GX8AQXEFGES6DDHNB3N178",
        "prompt_id": "01M2GX8AQXEFGES6DDHNB3N179",
        "home": str(tmp_path),
        "followups": str(tmp_path / "followups.json"),
        "attempt_id": "judge-performance",
    }
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment))
    calls = []

    async def respond(messages, info):
        calls.append(messages)
        verdict = {
            "outcome": "pass",
            "selected_attempt_id": "attempt-1",
            "rationale": "Read and checked the exact file",
            "evidence_refs": ["result.txt"],
            "feedback": [],
            "metrics": []
            if len(calls) == 1
            else [
                {
                    "observed": "checksum returned 150",
                    "passed": True,
                    "evidence_ref": "result.txt",
                }
            ],
        }
        yield json.dumps(verdict)

    router = SimpleNamespace(
        catalog=None, model_for=lambda _: FunctionModel(stream_function=respond), aclose=AsyncMock()
    )
    monkeypatch.setattr(symphony_worker, "CompletionRouter", lambda _: router)
    resolver = SimpleNamespace(
        resolve=AsyncMock(
            return_value=SimpleNamespace(
                model="test/model",
                context_tokens=10000,
            )
        )
    )
    monkeypatch.setattr(symphony_worker, "ModelPolicyResolver", lambda **_: resolver)
    monkeypatch.setattr(symphony_worker, "model_settings_for", lambda *_: {})
    spine = SimpleNamespace(aclose=AsyncMock(), record_spend_events=AsyncMock())
    monkeypatch.setattr(symphony_worker, "SpineClient", lambda *_, **__: spine)
    monkeypatch.chdir(tmp_path)

    await symphony_worker.run(assignment_path)

    result = json.loads((tmp_path / "judge-verdict.json").read_text())
    assert len(calls) == 2
    assert result["outcome"] == "pass"
    assert result["metrics"][0]["metric"] == "café checksum = 150"
    assert result["charter_sha256"] == session["charter_sha256"]
    assert json.loads((tmp_path / "result.json").read_text()) == result


@pytest.mark.asyncio
async def test_worker_context_injects_without_a_gate_and_reacts_to_selection(tmp_path):
    """A-059 / FL-096/097: leaf startup carries real memory selection and tree context."""
    prepared = InjectPrepareResponse(
        injection_id="12345678-1234-5678-1234-567812345678",
        snapshot_ts=datetime.now(UTC),
        scorer_version="test",
        injected=[],
        near_misses=[],
        final_block="<memories>UTF-8 checksum</memories>",
        memory_allocation=MemoryAllocation(
            memory_context_share=0.05,
            share_tokens=500,
            regular_tokens=4,
            pinned_tokens=0,
            total_tokens=4,
            pinned_overflow_tokens=0,
        ),
    )
    spine = SimpleNamespace(prepare_injection=AsyncMock(return_value=prepared))
    location = AgentLocation("worker", "machine", "session", tmp_path, tmp_path, False)
    context = SimpleNamespace(
        spine=spine,
        agent_id="worker",
        machine_id="machine",
        principal_id="verification",
        project_key=str(tmp_path),
        toolset=SimpleNamespace(location=lambda: location),
    )
    assignment = dict(
        stage="completion",
        brief="Implement checksum",
        prompt_id="worker-id",
        attempt_id="attempt",
        followups=str(tmp_path / "followups.json"),
    )
    worker = WorkerContext(
        assignment=assignment,
        output=tmp_path,
        context=context,
        resolution=SimpleNamespace(context_tokens=10000, model="test"),
    )
    rendered = await worker.render([])
    assert COMPONENT_REGISTRY in rendered and "UTF-8 checksum" in rendered
    assert spine.prepare_injection.call_args.args[0].mode == "gate"
    await worker.render([])
    assert spine.prepare_injection.call_count == 1
    removed = "22345678-1234-5678-1234-567812345678"
    write_json(tmp_path / "memory-selection.json", {"removed": [removed], "added": []})
    await worker.render([])
    assert str(spine.prepare_injection.call_args.args[0].excluded_memory_ids[0]) == removed
    assignment["stage"] = "judge"
    judge = WorkerContext(
        assignment=assignment, output=tmp_path, context=context, resolution=worker.resolution
    )
    assert "UTF-8 checksum" not in await judge.render([])
    assert spine.prepare_injection.call_count == 2
