"""Assert the canonical H5 live-Spine trace without contacting either service."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

FIRST_PROMPT = "Use the H5 verification memories to explain the handoff."
SECOND_PROMPT = "Confirm that the second prompt skips the memory gate."
CORRECTED_WRONG_BODY = (
    "The first-prompt memory gate waits for a human decision before the model starts."
)
MACHINE_ID = "h5-verification-machine"
REQUIRED_ROLES = {"keep", "not_relevant", "wrong", "never", "add_back"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", default=Path(__file__).with_name("trace.jsonl"))
    parser.add_argument(
        "--failure-phase",
        choices=("prepare", "commit"),
        help="assert the named one-shot memory-unavailable path instead of the happy path",
    )
    args = parser.parse_args()
    path = Path(args.trace)
    records = _read_trace(path)
    if args.failure_phase is None:
        _assert_happy_path(records)
        label = "happy path"
    else:
        _assert_failure_path(records, args.failure_phase)
        label = f"{args.failure_phase} failure"
    print(f"H5 trace PASS ({label}): {path} ({len(records)} records)")


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SystemExit(f"trace does not exist: {path}")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"trace line {line_number} is not JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise AssertionError(f"trace line {line_number} is not an event object")
        records.append(value)
    if not records:
        raise AssertionError("trace is empty")
    return records


def _assert_happy_path(records: list[dict[str, Any]]) -> None:
    if any(record["kind"].startswith("scenario.failure_") for record in records):
        raise AssertionError("happy-path trace contains an armed or triggered failure")

    seeded = _exactly_one(records, "scenario.seeded")
    roles = seeded.get("roles")
    if not isinstance(roles, dict) or set(roles) != REQUIRED_ROLES:
        observed_roles = sorted(roles) if isinstance(roles, dict) else roles
        raise AssertionError(f"seed roles differ: {observed_roles}")

    prepares = _records(records, "spine.prepare.call")
    prepare_results = _records(records, "spine.prepare.result")
    pause_checks = _records(records, "scenario.pause_checked")
    wrong_pause_checks = _records(records, "scenario.wrong_pause_checked")
    commits = _records(records, "spine.commit.call")
    commit_results = _records(records, "spine.commit.result")
    patch_calls = _records(records, "spine.patch.call")
    patch_results = _records(records, "spine.patch.result")
    model_calls = _records(records, "model.call")
    if len(prepares) != 1 or len(prepare_results) != 1:
        raise AssertionError("the two-prompt run must prepare exactly once")
    if len(pause_checks) != 1:
        raise AssertionError("the open gate must receive one explicit hard-pause check")
    if len(wrong_pause_checks) != 1:
        raise AssertionError("the wrong-resolution gate must receive one hard-pause check")
    if len(commits) != 1 or len(commit_results) != 1:
        raise AssertionError("the first prompt must commit exactly once")
    if len(patch_calls) != 1 or len(patch_results) != 1:
        raise AssertionError("the wrong removal must produce exactly one resolution PATCH")
    if len(model_calls) != 2:
        raise AssertionError("the canonical run must invoke the model once per prompt")

    expected_order = (
        "scenario.seeded",
        "spine.prepare.call",
        "spine.prepare.result",
        "scenario.pause_checked",
        "spine.commit.call",
        "spine.commit.result",
        "scenario.wrong_pause_checked",
        "spine.patch.call",
        "spine.patch.result",
        "model.call",
    )
    positions = [_first_position(records, kind) for kind in expected_order]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise AssertionError(f"prepare/commit/model ordering is wrong: {positions}")

    prepare = prepares[0]
    if prepare.get("prompt_sha256") != _digest(FIRST_PROMPT):
        raise AssertionError("prepare did not receive the canonical first prompt")
    if prepare.get("model_context_tokens") != 1:
        raise AssertionError("fixture did not guarantee a zero regular-token budget")

    prepared = prepare_results[0]
    injected = _card_ids(prepared, "injected")
    near_misses = _card_ids(prepared, "near_misses")
    expected_injected = {
        _role_id(roles, "keep"),
        _role_id(roles, "not_relevant"),
        _role_id(roles, "wrong"),
        _role_id(roles, "never"),
    }
    if set(injected) != expected_injected or len(injected) != len(expected_injected):
        raise AssertionError(f"injected cards differ: {injected}")
    if near_misses != [_role_id(roles, "add_back")]:
        raise AssertionError(f"near-miss card differs: {near_misses}")
    _assert_prepare_cards(prepared, roles)

    pause_state = {
        name: pause_checks[0].get(name)
        for name in (
            "prepare_calls",
            "prepare_results",
            "commit_calls",
            "commit_results",
            "model_calls",
        )
    }
    if pause_state != {
        "prepare_calls": 1,
        "prepare_results": 1,
        "commit_calls": 0,
        "commit_results": 0,
        "model_calls": 0,
    }:
        raise AssertionError(f"hard-pause check differs: {pause_state}")
    pause_seconds = (_timestamp(pause_checks[0]) - _timestamp(prepare_results[0])).total_seconds()
    if pause_seconds < 5:
        raise AssertionError(f"hard-pause observation was only {pause_seconds:.3f}s")

    wrong_pause_state = {
        name: wrong_pause_checks[0].get(name)
        for name in (
            "prepare_calls",
            "prepare_results",
            "commit_calls",
            "commit_results",
            "model_calls",
        )
    }
    if wrong_pause_state != {
        "prepare_calls": 1,
        "prepare_results": 1,
        "commit_calls": 1,
        "commit_results": 1,
        "model_calls": 0,
    }:
        raise AssertionError(f"wrong-resolution hard-pause check differs: {wrong_pause_state}")

    commit = commits[0]
    if commit.get("injection_id") != prepared.get("injection_id"):
        raise AssertionError("commit injection_id differs from prepare result")
    expected_removed = {
        (_role_id(roles, "not_relevant"), "not_relevant"),
        (_role_id(roles, "wrong"), "wrong"),
        (_role_id(roles, "never"), "never"),
    }
    removed = commit.get("removed")
    if not isinstance(removed, list):
        raise AssertionError("commit removed is not a list")
    actual_removed = {
        (item.get("memory_id"), item.get("reason")) for item in removed if isinstance(item, dict)
    }
    if actual_removed != expected_removed or len(removed) != len(expected_removed):
        raise AssertionError(f"exact removal decisions differ: {removed}")
    expected_added = [_role_id(roles, "add_back")]
    if commit.get("added_back") != expected_added:
        raise AssertionError(f"exact add-back decision differs: {commit.get('added_back')}")

    committed = commit_results[0]
    final_block = committed.get("final_block")
    if not isinstance(final_block, str):
        raise AssertionError("commit result has no final_block")
    first_model = model_calls[0]
    second_model = model_calls[1]
    if first_model.get("call") != 1 or second_model.get("call") != 2:
        raise AssertionError("model call counters are not stable")
    first_instructions = first_model.get("instructions")
    second_instructions = second_model.get("instructions")
    if not isinstance(first_instructions, str) or not first_instructions.endswith(
        f"\n{final_block}"
    ):
        raise AssertionError("the first model call does not end with the exact final_block")
    if not isinstance(second_instructions, str):
        raise AssertionError("the second model call lacks its static capability instructions")
    if final_block in second_instructions:
        raise AssertionError("the second prompt unexpectedly received the first injection block")
    if first_instructions.removesuffix(f"\n{final_block}") != second_instructions:
        raise AssertionError("first model instructions differ beyond the exact final_block suffix")
    if first_model.get("prompt_sha256") != _digest(FIRST_PROMPT):
        raise AssertionError("first model invocation prompt differs")
    if second_model.get("prompt_sha256") != _digest(SECOND_PROMPT):
        raise AssertionError("second model invocation prompt differs")

    _assert_final_block_members(final_block, roles)
    wrong_removed = committed.get("wrong_removed")
    if wrong_removed != [_role_id(roles, "wrong")]:
        raise AssertionError(f"wrong_removed differs: {wrong_removed}")
    _assert_wrong_resolution(committed, patch_calls[0], patch_results[0], roles)


def _assert_failure_path(records: list[dict[str, Any]], phase: str) -> None:
    seeded = _exactly_one(records, "scenario.seeded")
    roles = seeded.get("roles")
    if not isinstance(roles, dict) or set(roles) != REQUIRED_ROLES:
        raise AssertionError("failure trace lacks the exact isolated seed catalog")

    armed = _exactly_one(records, "scenario.failure_armed")
    triggered = _exactly_one(records, "scenario.failure_triggered")
    if armed.get("phase") != phase or triggered.get("phase") != phase:
        raise AssertionError("armed and triggered failure phases must match the assertion")

    prepares = _records(records, "spine.prepare.call")
    prepare_results = _records(records, "spine.prepare.result")
    commits = _records(records, "spine.commit.call")
    commit_results = _records(records, "spine.commit.result")
    patch_calls = _records(records, "spine.patch.call")
    patch_results = _records(records, "spine.patch.result")
    model_calls = _records(records, "model.call")
    if len(prepares) != 1 or len(model_calls) != 1:
        raise AssertionError("failure path must prepare and invoke the model exactly once")
    if prepares[0].get("prompt_sha256") != _digest(FIRST_PROMPT):
        raise AssertionError("failure prepare did not receive the canonical first prompt")
    if model_calls[0].get("prompt_sha256") != _digest(FIRST_PROMPT):
        raise AssertionError("memoryless model did not receive the canonical first prompt")

    expected_counts = {
        "prepare": (0, 0),
        "commit": (1, 1),
    }
    expected_prepare_results, expected_commits = expected_counts[phase]
    if len(prepare_results) != expected_prepare_results:
        raise AssertionError(f"{phase} failure has an unexpected prepare result")
    if len(commits) != expected_commits or commit_results:
        raise AssertionError(f"{phase} failure has an unexpected commit boundary")
    if patch_calls or patch_results:
        raise AssertionError(f"{phase} failure must not reach wrong-resolution PATCH")

    order = [
        _first_position(records, "scenario.failure_armed"),
        _first_position(records, "spine.prepare.call"),
    ]
    if phase == "commit":
        order.extend(
            (
                _first_position(records, "spine.prepare.result"),
                _first_position(records, "spine.commit.call"),
            )
        )
    order.extend(
        (
            _first_position(records, "scenario.failure_triggered"),
            _first_position(records, "model.call"),
        )
    )
    if order != sorted(order) or len(set(order)) != len(order):
        raise AssertionError(f"{phase} failure ordering is wrong: {order}")

    instructions = model_calls[0].get("instructions")
    if not isinstance(instructions, str):
        raise AssertionError("failure-path model call lacks static instructions")
    if "<memory_system>" in instructions:
        raise AssertionError("failure-path model call received an injection block")
    for role in REQUIRED_ROLES:
        if _role_value(roles, role, "body") in instructions:
            raise AssertionError(f"failure-path instructions contain seeded role {role}")


def _assert_wrong_resolution(
    committed: dict[str, Any],
    patch_call: dict[str, Any],
    patch_result: dict[str, Any],
    roles: dict[str, Any],
) -> None:
    current_values = committed.get("wrong_removed_current")
    if (
        not isinstance(current_values, list)
        or len(current_values) != 1
        or not isinstance(current_values[0], dict)
    ):
        raise AssertionError("commit result must trace one current wrong memory unit")
    current = current_values[0]
    wrong_id = _role_id(roles, "wrong")
    wrong_body = _role_value(roles, "wrong", "body")
    current_revision = current.get("revision")
    if (
        current.get("memory_id") != wrong_id
        or current.get("body") != wrong_body
        or current.get("status") != "active"
        or type(current_revision) is not int
        or current_revision < 1
    ):
        raise AssertionError(f"current wrong unit differs: {current}")

    expected_call = {
        "memory_id": wrong_id,
        "expected_revision": current_revision,
        "body": CORRECTED_WRONG_BODY,
        "status": None,
        "editor": "user",
        "reason": "gate/wrong:edit",
        "machine_id": MACHINE_ID,
    }
    actual_call = {field: patch_call.get(field) for field in expected_call}
    if actual_call != expected_call:
        raise AssertionError(f"wrong-resolution PATCH differs: {actual_call}")

    expected_result = {
        "memory_id": wrong_id,
        "revision": current_revision + 1,
        "body": CORRECTED_WRONG_BODY,
        "status": "active",
    }
    actual_result = {field: patch_result.get(field) for field in expected_result}
    if actual_result != expected_result:
        raise AssertionError(f"wrong-resolution PATCH result differs: {actual_result}")


def _assert_final_block_members(final_block: str, roles: dict[str, Any]) -> None:
    if not final_block.startswith("<memory_system>\n") or not final_block.endswith(
        "\n</memory_system>"
    ):
        raise AssertionError("final_block lacks the canonical memory_system boundary")
    for role in ("keep", "add_back"):
        body = _role_value(roles, role, "body")
        label = _role_value(roles, role, "label")
        if final_block.count(body) != 1 or final_block.count(f'label="{label}"') != 1:
            raise AssertionError(f"final_block does not contain exact kept role {role}")
    for role in ("not_relevant", "wrong", "never"):
        body = _role_value(roles, role, "body")
        label = _role_value(roles, role, "label")
        if body in final_block or f'label="{label}"' in final_block:
            raise AssertionError(f"final_block still contains removed role {role}")
    if final_block.count("<memory label=") != 2:
        raise AssertionError("final_block contains an unexpected memory member")


def _assert_prepare_cards(prepared: dict[str, Any], roles: dict[str, Any]) -> None:
    cards = prepared.get("injected", []) + prepared.get("near_misses", [])
    if not all(isinstance(card, dict) for card in cards):
        raise AssertionError("prepare result contains a non-object card")
    by_id = {card.get("memory_id"): card for card in cards}
    for role in REQUIRED_ROLES:
        memory_id = _role_id(roles, role)
        card = by_id.get(memory_id)
        if card is None:
            raise AssertionError(f"prepare trace omits role {role}")
        for field in ("label", "body", "kind", "pin"):
            expected = roles[role][field]
            if card.get(field) != expected:
                raise AssertionError(f"prepare card {role}.{field} differs")
        features = card.get("features")
        if not isinstance(features, dict) or set(features) != {
            "sem",
            "kw",
            "time",
            "proj",
            "freq",
            "hist",
        }:
            raise AssertionError(f"prepare card {role} lacks the six raw feature scores")


def _records(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [record for record in records if record["kind"] == kind]


def _exactly_one(records: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = _records(records, kind)
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind}, found {len(matches)}")
    return matches[0]


def _first_position(records: list[dict[str, Any]], kind: str) -> int:
    return next(index for index, record in enumerate(records) if record["kind"] == kind)


def _card_ids(record: dict[str, Any], name: str) -> list[str]:
    cards = record.get(name)
    if not isinstance(cards, list) or not all(isinstance(card, dict) for card in cards):
        raise AssertionError(f"{name} is not a card list")
    return [str(card["memory_id"]) for card in cards]


def _role_id(roles: dict[str, Any], role: str) -> str:
    return _role_value(roles, role, "memory_id")


def _role_value(roles: dict[str, Any], role: str, field: str) -> str:
    value = roles.get(role)
    if not isinstance(value, dict) or not isinstance(value.get(field), str):
        raise AssertionError(f"seed role {role}.{field} is missing")
    return value[field]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp(record: dict[str, Any]) -> datetime:
    value = record.get("at")
    if not isinstance(value, str):
        raise AssertionError(f"{record.get('kind')} has no trace timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise AssertionError(f"{record.get('kind')} has an invalid trace timestamp") from exc


if __name__ == "__main__":
    main()
