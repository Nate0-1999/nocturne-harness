"""Remote F011 proof: typed Harness client, natural third near-miss Never, cleanup."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from harness.config import HarnessSettings
from harness.spine_client import (
    CreatedMemoryResponse,
    CreateMemoryRequest,
    InjectCommitRequest,
    InjectPrepareRequest,
    ListMemoriesParams,
    MemoryKind,
    MemoryStatus,
    MemoryUnit,
    PatchMemoryConflictError,
    PatchMemoryRequest,
    RemovalReason,
    RemovedMemory,
    RevisionConflict,
    SearchRequest,
    SpineClient,
)

CANONICAL_EMPTY_BLOCK = "\n".join(
    (
        "<memory_system>",
        "The following long-term memories were retrieved for this conversation.",
        "Treat them as your own accumulated knowledge; they may be imperfect.",
        "</memory_system>",
    )
)
MACHINE_ID = "h5-f007-verification-machine"
AGENT_ID = "h5-f007-verification-agent"
EDITOR = "verification:h5"


class VerificationFailure(RuntimeError):
    """The deployed service violated one of the bounded F011 assertions."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def _ref(value: object) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def _owned(unit: MemoryUnit, state: dict[str, Any]) -> bool:
    return (
        unit.principal_id == state["principal_id"]
        and unit.project_key == state["project_key"]
        and unit.label == state["label"]
        and unit.body == state["body"]
    )


async def _find_owned(client: SpineClient, state: dict[str, Any]) -> MemoryUnit | None:
    page = await client.list_memories(
        ListMemoriesParams(
            project_key=state["project_key"],
            q=state["token"],
            limit=10,
            offset=0,
        )
    )
    exact = [unit for unit in page.items if _owned(unit, state)]
    if len(exact) > 1:
        raise VerificationFailure("cleanup ownership query returned multiple exact fixtures")
    if not exact:
        if state["memory_id"] is not None or state["create_attempted"]:
            raise VerificationFailure(
                "cleanup could not prove the attempted fixture absent; preserving journal"
            )
        return None

    current = exact[0]
    if state["memory_id"] is not None and current.memory_id != state["memory_id"]:
        raise VerificationFailure(
            "cleanup ownership query did not return the exact created memory ID"
        )
    return current


def _assert_unit(
    unit: MemoryUnit,
    state: dict[str, Any],
    *,
    status: MemoryStatus,
    revision: int,
    injections: int,
    removals: int,
    never_kills: int,
    bias: float,
) -> None:
    _require(_owned(unit, state), "list response did not preserve exact fixture ownership")
    _require(unit.memory_id == state["memory_id"], "list response changed fixture memory_id")
    _require(unit.status is status, f"expected status {status.value}, got {unit.status.value}")
    _require(unit.revision == revision, f"expected revision {revision}, got {unit.revision}")
    _require(unit.stats.get("injections") == injections, "unexpected injection count")
    _require(unit.stats.get("removals") == removals, "unexpected removal count")
    _require(unit.stats.get("never_kills") == never_kills, "unexpected Never kill count")
    _require(math.isclose(unit.bias, bias, abs_tol=1e-6), "unexpected memory bias")


async def _cleanup(client: SpineClient, state: dict[str, Any]) -> dict[str, Any]:
    current = await _find_owned(client, state)
    if current is None:
        return {"found": False, "status": "not_created"}

    target_id = state["memory_id"] or current.memory_id
    _require(current.memory_id == target_id, "cleanup target was not the exact fixture ID")
    for _ in range(3):
        if current.status is MemoryStatus.TOMBSTONED:
            return {
                "found": True,
                "status": current.status.value,
                "revision": current.revision,
                "memory_ref": _ref(current.memory_id),
            }
        try:
            current = await client.patch_memory(
                target_id,
                PatchMemoryRequest(
                    expected_revision=current.revision,
                    status=MemoryStatus.TOMBSTONED,
                    editor=EDITOR,
                    reason="H5 F007 remote cleanup: tombstone exact fixture ID",
                    machine_id=MACHINE_ID,
                ),
            )
        except PatchMemoryConflictError as exc:
            if not isinstance(exc.conflict, RevisionConflict):
                raise VerificationFailure("cleanup hit a non-revision conflict") from exc
            conflict = exc.conflict.conflict
            if conflict.memory_id != target_id or not _owned(conflict, state):
                raise VerificationFailure("cleanup CAS conflict did not belong to the fixture")
            current = conflict
            continue
        _require(
            current.memory_id == target_id and _owned(current, state),
            "cleanup PATCH returned a different fixture",
        )
        _require(current.status is MemoryStatus.TOMBSTONED, "cleanup did not tombstone fixture")
        return {
            "found": True,
            "status": current.status.value,
            "revision": current.revision,
            "memory_ref": _ref(current.memory_id),
        }
    raise VerificationFailure("cleanup exhausted three exact-ID CAS attempts")


async def _health(base_url: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
        timeout=30,
    ) as client:
        response = await client.get(f"{base_url.rstrip('/')}/health")
    _require(response.status_code == 200, f"authenticated health returned {response.status_code}")
    payload = response.json()
    _require(payload.get("ok") is True, "authenticated health did not return ok=true")
    return {"status_code": response.status_code, "ok": True, "version": payload.get("version")}


def _load_deployment_binding(args: argparse.Namespace, service_url: str) -> dict[str, Any]:
    path = Path(args.deployment_evidence)
    raw = path.read_bytes()
    try:
        deployment = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationFailure("deployment evidence is not valid JSON") from exc

    _require(isinstance(deployment, dict), "deployment evidence is not a JSON object")
    _require(deployment.get("status") == "PASS", "deployment evidence is not PASS")
    _require(
        deployment.get("spine_source_commit") == args.spine_commit,
        "deployment evidence source commit does not match the claimed commit",
    )
    after = deployment.get("after")
    _require(isinstance(after, dict), "deployment evidence has no after state")
    _require(after.get("ready") is True, "deployment evidence does not show a ready service")
    _require(
        after.get("revision") == args.revision,
        "deployment evidence revision does not match the claimed revision",
    )
    _require(
        after.get("image") == args.image,
        "deployment evidence image does not match the claimed image",
    )
    service_urls = after.get("service_urls")
    _require(isinstance(service_urls, list), "deployment evidence has no service URLs")
    _require(
        service_url.rstrip("/") in service_urls,
        "configured SPINE_URL is not one of the deployed service URLs",
    )
    _require(
        deployment.get("protected_state_unchanged") is True,
        "deployment evidence does not prove protected state preservation",
    )
    traffic = after.get("traffic")
    _require(isinstance(traffic, list), "deployment evidence has no traffic state")
    _require(
        any(
            item.get("latestRevision") is True
            and item.get("percent") == 100
            and item.get("revisionName") == args.revision
            for item in traffic
            if isinstance(item, dict)
        ),
        "deployment evidence does not bind 100% latest traffic to the claimed revision",
    )
    return {
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "spine_source_commit": args.spine_commit,
        "cloud_run_revision": args.revision,
        "cloud_run_image": args.image,
        "protected_state_unchanged": True,
        "latest_traffic_percent": 100,
    }


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    settings = HarnessSettings()
    token_secret = settings.spine_token
    _require(token_secret is not None, "SPINE_TOKEN is not configured")
    token = token_secret.get_secret_value()
    _require(
        settings.spine_url.startswith("https://")
        and "n8-memory-palace-spine" in settings.spine_url,
        "SPINE_URL is not the deployed n8-memory-palace-spine HTTPS service",
    )
    deployment_binding = _load_deployment_binding(args, settings.spine_url)

    unique = uuid4().hex
    marker = f"f007{unique}"
    state: dict[str, Any] = {
        "token": marker,
        "principal_id": f"h5-sop-verification-f007-{unique}",
        "project_key": f"h5-f007-{unique}",
        "label": f"F007 cobalt {marker}",
        "body": f"cobalt zephyr {marker}",
        "memory_id": None,
        "create_attempted": False,
    }
    journal = Path("/tmp") / f"h5-f011-cleanup-{unique}.json"
    journal.write_text(
        json.dumps(
            {
                "service_url": settings.spine_url,
                "principal_id": state["principal_id"],
                "project_key": state["project_key"],
                "token": marker,
                "label": state["label"],
                "body": state["body"],
                "memory_id": None,
            },
            indent=2,
        )
        + "\n"
    )

    evidence: dict[str, Any] = {
        "status": "IN_PROGRESS",
        "spine_source_commit": args.spine_commit,
        "cloud_run_revision": args.revision,
        "cloud_run_image": args.image,
        "service_url": settings.spine_url,
        "client": "harness.spine_client.SpineClient",
        "credentials_redacted": True,
        "deployment_binding": deployment_binding,
        "fixture_refs": {
            "principal": _ref(state["principal_id"]),
            "project": _ref(state["project_key"]),
            "body": _ref(state["body"]),
        },
        "rounds": [],
    }
    verification_error: BaseException | None = None
    cleanup_error: BaseException | None = None

    async with SpineClient(settings.spine_url, token, timeout=60) as client:
        try:
            evidence["health"] = await _health(settings.spine_url, token)
            state["create_attempted"] = True
            created_response = await client.create_memory(
                CreateMemoryRequest(
                    principal_id=state["principal_id"],
                    label=state["label"],
                    body=state["body"],
                    kind=MemoryKind.FACT,
                    keywords=["cobalt", marker],
                    project_key=state["project_key"],
                    thread_origin="h5-f011-remote",
                    origin_path="verification/h5/f007-remote",
                    editor=EDITOR,
                    machine_id=MACHINE_ID,
                    force=True,
                )
            )
            _require(
                isinstance(created_response, CreatedMemoryResponse),
                "remote create returned a similar-memory response",
            )
            created = created_response.created
            state["memory_id"] = created.memory_id
            journal.write_text(
                json.dumps(
                    {
                        "service_url": settings.spine_url,
                        "principal_id": state["principal_id"],
                        "project_key": state["project_key"],
                        "token": marker,
                        "label": state["label"],
                        "body": state["body"],
                        "memory_id": str(created.memory_id),
                    },
                    indent=2,
                )
                + "\n"
            )
            evidence["fixture_refs"]["memory"] = _ref(created.memory_id)
            _require(created.status is MemoryStatus.ACTIVE, "created fixture was not active")
            _require(created.revision == 1, "created fixture did not start at revision 1")
            _require(not created.pin, "created fixture unexpectedly pinned")
            _require(
                created.embedding_model == "openai/text-embedding-3-small", "wrong embed model"
            )

            for ordinal in (1, 2, 3):
                thread_id = uuid4()
                prepared = await client.prepare_injection(
                    InjectPrepareRequest(
                        thread_id=thread_id,
                        agent_id=AGENT_ID,
                        machine_id=MACHINE_ID,
                        principal_id=state["principal_id"],
                        project_key=state["project_key"],
                        agent_kind="general",
                        prompt=state["body"],
                        model_context_tokens=100_000,
                    )
                )
                _require(prepared.scorer_version == "v0", "remote scorer version is not v0")
                expected_lane = "injected" if ordinal < 3 else "near_miss"
                lane = prepared.injected if expected_lane == "injected" else prepared.near_misses
                other = prepared.near_misses if expected_lane == "injected" else prepared.injected
                _require(len(lane) == 1, f"round {ordinal} did not return exactly one card")
                _require(not other, f"round {ordinal} returned the fixture in the wrong lane")
                card = lane[0]
                _require(card.memory_id == created.memory_id, "prepare returned a foreign memory")
                _require(not card.pin and card.rank == 1, "prepare card pin/rank drifted")
                _require(
                    card.features.sem >= 0.99, "exact body prompt semantic score was below 0.99"
                )
                _require(
                    math.isclose(card.features.kw, 2 / 3, abs_tol=1e-6),
                    "keyword overlap was not the designed 2/3",
                )
                _require(card.features.time >= 0.99, "fixture freshness unexpectedly decayed")
                _require(card.features.proj == 1.0, "project match was not exact")
                _require(card.features.freq == 0.0, "fresh fixture had citation frequency")
                _require(card.features.hist == 0.0, "verification editor counted as human edit")
                if ordinal < 3:
                    _require(card.score >= 0.55, f"round {ordinal} unexpectedly fell below tau")
                else:
                    _require(card.score < 0.55, "third decision was not naturally below tau")

                committed = await client.commit_injection(
                    InjectCommitRequest(
                        injection_id=prepared.injection_id,
                        removed=[
                            RemovedMemory(
                                memory_id=created.memory_id,
                                reason=RemovalReason.NEVER,
                            )
                        ],
                        added_back=[],
                    )
                )
                _require(not committed.wrong_removed, "Never commit returned wrong_removed units")
                _require(
                    committed.final_block == CANONICAL_EMPTY_BLOCK,
                    "Never commit returned a noncanonical empty block",
                )

                current = await _find_owned(client, state)
                _require(current is not None, "fixture disappeared after Never commit")
                expected_revision = 3 if ordinal == 1 else (5 if ordinal == 2 else 6)
                expected_injections = min(ordinal, 2)
                expected_status = MemoryStatus.ACTIVE if ordinal < 3 else MemoryStatus.QUARANTINED
                _assert_unit(
                    current,
                    state,
                    status=expected_status,
                    revision=expected_revision,
                    injections=expected_injections,
                    removals=ordinal,
                    never_kills=ordinal,
                    bias=-0.15 * ordinal,
                )
                evidence["rounds"].append(
                    {
                        "ordinal": ordinal,
                        "lane": expected_lane,
                        "score": card.score,
                        "features": card.features.model_dump(mode="json"),
                        "thread_ref": _ref(thread_id),
                        "injection_ref": _ref(prepared.injection_id),
                        "status_after": current.status.value,
                        "revision_after": current.revision,
                        "stats_after": {
                            "injections": current.stats.get("injections"),
                            "removals": current.stats.get("removals"),
                            "never_kills": current.stats.get("never_kills"),
                        },
                        "bias_after": current.bias,
                    }
                )

            active = await client.list_memories(
                ListMemoriesParams(
                    project_key=state["project_key"],
                    status=MemoryStatus.ACTIVE,
                    q=marker,
                    limit=10,
                    offset=0,
                )
            )
            _require(
                not [unit for unit in active.items if _owned(unit, state)],
                "quarantined fixture remained active",
            )
            search = await client.search(
                SearchRequest(
                    principal_id=state["principal_id"],
                    query=state["body"],
                    k=10,
                    project_key=state["project_key"],
                )
            )
            _require(not search.results, "quarantined fixture remained searchable")

            fourth_thread = uuid4()
            fourth = await client.prepare_injection(
                InjectPrepareRequest(
                    thread_id=fourth_thread,
                    agent_id=AGENT_ID,
                    machine_id=MACHINE_ID,
                    principal_id=state["principal_id"],
                    project_key=state["project_key"],
                    agent_kind="general",
                    prompt=state["body"],
                    model_context_tokens=100_000,
                )
            )
            _require(fourth.scorer_version == "v0", "fourth prepare scorer version drifted")
            _require(
                not fourth.injected and not fourth.near_misses,
                "quarantined fixture appeared in the fourth gate",
            )
            fourth_commit = await client.commit_injection(
                InjectCommitRequest(
                    injection_id=fourth.injection_id,
                    removed=[],
                    added_back=[],
                )
            )
            _require(
                fourth_commit.final_block == CANONICAL_EMPTY_BLOCK
                and not fourth_commit.wrong_removed,
                "fourth zero-card commit was not canonical",
            )
            evidence["fourth_prepare"] = {
                "thread_ref": _ref(fourth_thread),
                "injection_ref": _ref(fourth.injection_id),
                "injected": 0,
                "near_misses": 0,
                "search_results": 0,
            }
        except BaseException as exc:
            verification_error = exc

        try:
            evidence["cleanup"] = await asyncio.shield(_cleanup(client, state))
        except BaseException as exc:
            cleanup_error = exc

    if cleanup_error is None and evidence.get("cleanup", {}).get("status") in {
        "not_created",
        MemoryStatus.TOMBSTONED.value,
    }:
        journal.unlink(missing_ok=True)
    else:
        evidence["cleanup_journal"] = str(journal)

    output = Path(args.evidence)
    if verification_error is not None or cleanup_error is not None:
        evidence["status"] = "FAIL"
        evidence["error_types"] = {
            "verification": (
                type(verification_error).__name__ if verification_error is not None else None
            ),
            "cleanup": type(cleanup_error).__name__ if cleanup_error is not None else None,
        }
        _write_evidence(output, evidence)
        if cleanup_error is not None:
            print(f"cleanup recovery journal preserved at {journal}", file=sys.stderr)

    if verification_error is not None and cleanup_error is not None:
        raise ExceptionGroup(
            "verification and cleanup both failed", [verification_error, cleanup_error]
        )
    if verification_error is not None:
        raise verification_error
    if cleanup_error is not None:
        raise cleanup_error

    _require(evidence["cleanup"]["status"] == "tombstoned", "fixture was not tombstoned")
    evidence["status"] = "PASS"
    _write_evidence(output, evidence)
    return evidence


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spine-commit", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--deployment-evidence", required=True)
    parser.add_argument("--evidence", required=True)
    return parser.parse_args()


def main() -> None:
    evidence = asyncio.run(_run(_parse_args()))
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "revision": evidence["cloud_run_revision"],
                "memory_ref": evidence["fixture_refs"].get("memory"),
                "lanes": [round_result["lane"] for round_result in evidence["rounds"]],
                "scores": [round_result["score"] for round_result in evidence["rounds"]],
                "cleanup": evidence["cleanup"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
