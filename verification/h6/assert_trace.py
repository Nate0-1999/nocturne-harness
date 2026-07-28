"""Assert the canonical H6 live-Spine trace without contacting either service."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FIRST_PROMPT = "Open the H6 verification thread context."
SECOND_PROMPT = "Report which H6 context markers are present now."
EDITED_BODY = "H6 edit saved through the memory panel with compare-and-swap."
CONFLICT_DRAFT_BODY = "H6 draft that must survive a visible revision conflict."
CONFLICT_CURRENT_BODY = "H6 concurrent editor won this revision before panel save."
REQUIRED_ROLES = {
    "thread_remove",
    "thread_keep",
    "edit_success",
    "edit_conflict",
    "pin_toggle",
}
FOREIGN_ROLE = "foreign_sentinel"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", default=Path(__file__).with_name("trace.jsonl"))
    args = parser.parse_args()
    path = Path(args.trace)
    records = _read_trace(path)
    _assert_trace(records)
    print(f"H6 trace PASS: {path} ({len(records)} records)")


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


def _assert_trace(records: list[dict[str, Any]]) -> None:
    seeded = _exactly_one(records, "scenario.seeded")
    roles = seeded.get("roles")
    foreign = seeded.get("foreign")
    if not isinstance(roles, dict) or set(roles) != REQUIRED_ROLES:
        observed = sorted(roles) if isinstance(roles, dict) else roles
        raise AssertionError(f"seed roles differ: {observed}")
    if not isinstance(foreign, dict):
        raise AssertionError("foreign-principal isolation sentinel is missing")
    seeded_ids = {item.get("memory_id") for item in roles.values() if isinstance(item, dict)}
    foreign_id = foreign.get("memory_id")
    if (
        len(seeded_ids) != len(REQUIRED_ROLES)
        or not all(isinstance(value, str) for value in seeded_ids)
        or not isinstance(foreign_id, str)
        or foreign_id in seeded_ids
    ):
        raise AssertionError("seed IDs are missing, duplicated, or overlap the sentinel")

    _assert_initial_injection(records)
    _assert_panel_states(records)
    _assert_removal_and_next_call(records)
    _assert_edit(records)
    _assert_conflict(records)
    _assert_pin(records)
    _assert_cleanup(records, seeded_ids | {foreign_id})
    _assert_ordering(records)


def _assert_initial_injection(records: list[dict[str, Any]]) -> None:
    prepare = _exactly_one(records, "spine.prepare.call")
    prepared = _exactly_one(records, "spine.prepare.result")
    commit = _exactly_one(records, "spine.commit.call")
    committed = _exactly_one(records, "spine.commit.result")
    if prepare.get("principal_matches") is not True:
        raise AssertionError("prepare did not use the fixture principal")
    if prepare.get("prompt_sha256") != _digest(FIRST_PROMPT):
        raise AssertionError("prepare did not receive the canonical first prompt")
    if prepare.get("model_context_tokens") != 1:
        raise AssertionError("fixture did not force the regular-token budget to zero")
    if set(_string_list(prepared, "injected")) != {
        "thread_remove",
        "thread_keep",
        "edit_success",
    }:
        raise AssertionError(f"exact injected roles differ: {prepared.get('injected')}")
    if set(_string_list(prepared, "near_misses")) != {"edit_conflict", "pin_toggle"}:
        raise AssertionError(f"exact near-miss roles differ: {prepared.get('near_misses')}")
    if commit.get("matches_prepared") is not True:
        raise AssertionError("commit did not use the prepared injection ID")
    if commit.get("removed") != [] or commit.get("added_back") != []:
        raise AssertionError("canonical H6 setup must commit the two pinned cards unchanged")
    if committed.get("memory_block_count") != 1:
        raise AssertionError("commit did not return one canonical memory block")
    if (
        committed.get("keep_present") is not True
        or committed.get("remove_present") is not True
        or committed.get("edit_original_present") is not True
        or committed.get("pin_present") is not False
    ):
        raise AssertionError("committed context has incorrect frozen fixture membership")
    if committed.get("wrong_removed") != []:
        raise AssertionError("H6 setup unexpectedly entered wrong-memory resolution")


def _assert_panel_states(records: list[dict[str, Any]]) -> None:
    states = _records(records, "browser.panel.state")
    if not states:
        raise AssertionError("the browser received no memory-panel state")
    for state in states:
        if state.get("unknown_count") != 0:
            raise AssertionError("a non-fixture memory crossed the browser trace boundary")
        if state.get("principal_mismatch_count") != 0:
            raise AssertionError("a different principal crossed the browser boundary")
        if state.get("foreign_visible") is not False:
            raise AssertionError("the synthetic foreign-principal sentinel became visible")
        if state.get("total") != len(REQUIRED_ROLES):
            raise AssertionError(f"panel total differs from exact active fixture set: {state}")
        if set(_state_items(state)) != REQUIRED_ROLES:
            raise AssertionError(f"panel roles differ from exact active fixture set: {state}")

    context_state = next(
        (
            state
            for state in states
            if _item(state, "thread_keep").get("in_context") is True
            and _item(state, "thread_remove").get("in_context") is True
        ),
        None,
    )
    if context_state is None:
        raise AssertionError("panel never showed both committed units as in context")
    if _item(context_state, "edit_success").get("in_context") is not True:
        raise AssertionError("the committed edit fixture was not marked in context")
    for role in {"edit_conflict", "pin_toggle"}:
        if _item(context_state, role).get("in_context") is not False:
            raise AssertionError(f"regular near miss {role} was mislabeled as in context")


def _assert_removal_and_next_call(records: list[dict[str, Any]]) -> None:
    feedback_call = _exactly_one(records, "spine.feedback.call")
    feedback_result = _exactly_one(records, "spine.feedback.result")
    if feedback_call.get("role") != "thread_remove":
        raise AssertionError("feedback targeted a memory other than thread_remove")
    if feedback_call.get("signal") != "mid_thread_removed":
        raise AssertionError("panel removal did not use mid_thread_removed")
    if feedback_call.get("matches_committed") is not True:
        raise AssertionError("panel removal did not use daemon-held injection identity")
    if feedback_result.get("role") != "thread_remove" or feedback_result.get("ok") is not True:
        raise AssertionError("panel removal lacks a typed ok result")

    removed_states = [
        state
        for state in _records(records, "browser.panel.state")
        if state.get("result") == "removed"
    ]
    if len(removed_states) != 1:
        raise AssertionError("the browser must receive exactly one removed state")
    removed = removed_states[0]
    if _item(removed, "thread_remove").get("in_context") is not False:
        raise AssertionError("removed unit remained marked in context")
    if _item(removed, "thread_keep").get("in_context") is not True:
        raise AssertionError("retained unit fell out of context with the removed unit")

    models = _records(records, "model.call")
    if len(models) != 2:
        raise AssertionError("canonical H6 flow must invoke the model exactly twice")
    first, second = models
    if first.get("call") != 1 or first.get("prompt_sha256") != _digest(FIRST_PROMPT):
        raise AssertionError("first deterministic model call differs")
    if (
        first.get("keep_present") is not True
        or first.get("remove_present") is not True
        or first.get("edit_original_present") is not True
        or first.get("edited_body_present") is not False
        or first.get("pin_present") is not False
    ):
        raise AssertionError("first model call did not receive the exact frozen membership")
    if second.get("call") != 2 or second.get("prompt_sha256") != _digest(SECOND_PROMPT):
        raise AssertionError("second deterministic model call differs")
    if (
        second.get("keep_present") is not True
        or second.get("remove_present") is not False
        or second.get("edit_original_present") is not True
        or second.get("edited_body_present") is not False
        or second.get("pin_present") is not False
    ):
        raise AssertionError(
            "next model call did not exclude removal while preserving frozen edit/pin semantics"
        )
    if first.get("memory_block_count") != 1 or second.get("memory_block_count") != 1:
        raise AssertionError("a model call duplicated or omitted the canonical memory block")


def _assert_edit(records: list[dict[str, Any]]) -> None:
    calls = _panel_patch_records(records, "spine.patch.call", "panel/edit", "edit_success")
    results = _panel_patch_records(records, "spine.patch.result", "panel/edit", "edit_success")
    conflicts = _panel_patch_records(records, "spine.patch.conflict", "panel/edit", "edit_success")
    if len(calls) != 1 or len(results) != 1 or conflicts:
        raise AssertionError("edit_success must make one successful CAS PATCH")
    if calls[0].get("body") != EDITED_BODY:
        raise AssertionError("edit_success PATCH body differs")
    if calls[0].get("editor") != "user" or calls[0].get("machine_id") != "h6-sop-verification":
        raise AssertionError("edit_success PATCH did not use daemon-derived audit identity")
    if results[0].get("body") != EDITED_BODY or results[0].get("status") != "active":
        raise AssertionError("edit_success result differs")

    states = [
        state
        for state in _records(records, "browser.panel.state")
        if state.get("result") == "edited"
    ]
    if len(states) != 1 or _item(states[0], "edit_success").get("body") != EDITED_BODY:
        raise AssertionError("browser did not receive the saved current memory body")
    if _item(states[0], "edit_success").get("in_context") is not True:
        raise AssertionError("successful edit rewrote committed context membership")


def _assert_conflict(records: list[dict[str, Any]]) -> None:
    staged = _exactly_one(records, "scenario.conflict_staged")
    if staged.get("role") != "edit_conflict" or staged.get("body") != CONFLICT_CURRENT_BODY:
        raise AssertionError("concurrent edit setup differs")
    calls = _panel_patch_records(records, "spine.patch.call", "panel/edit", "edit_conflict")
    results = _panel_patch_records(records, "spine.patch.result", "panel/edit", "edit_conflict")
    conflicts = _panel_patch_records(records, "spine.patch.conflict", "panel/edit", "edit_conflict")
    if len(calls) != 1 or results or len(conflicts) != 1:
        raise AssertionError("panel must surface one real CAS conflict without retry")
    if calls[0].get("body") != CONFLICT_DRAFT_BODY:
        raise AssertionError("conflict PATCH did not carry the preserved browser draft")
    conflict = conflicts[0]
    if (
        conflict.get("current_body") != CONFLICT_CURRENT_BODY
        or conflict.get("current_status") != "active"
        or conflict.get("current_revision") == conflict.get("expected_revision")
    ):
        raise AssertionError("Spine conflict did not return the current active unit")

    browser = _exactly_one(records, "browser.panel.conflict")
    if (
        browser.get("operation") != "edit"
        or browser.get("role") != "edit_conflict"
        or browser.get("current_body") != CONFLICT_CURRENT_BODY
        or browser.get("current_revision") != conflict.get("current_revision")
    ):
        raise AssertionError("browser conflict does not carry the current Spine unit")


def _assert_pin(records: list[dict[str, Any]]) -> None:
    calls = _panel_patch_records(records, "spine.patch.call", "panel/pin", "pin_toggle")
    results = _panel_patch_records(records, "spine.patch.result", "panel/pin", "pin_toggle")
    conflicts = _panel_patch_records(records, "spine.patch.conflict", "panel/pin", "pin_toggle")
    if len(calls) != 1 or len(results) != 1 or conflicts:
        raise AssertionError("pin_toggle must make one successful CAS PATCH")
    if calls[0].get("pin") is not True or results[0].get("pin") is not True:
        raise AssertionError("pin_toggle did not persist pin=true")
    states = [
        state
        for state in _records(records, "browser.panel.state")
        if state.get("result") == "pin_changed"
    ]
    if len(states) != 1 or _item(states[0], "pin_toggle").get("pin") is not True:
        raise AssertionError("browser did not receive the persisted pin state")
    if _item(states[0], "pin_toggle").get("in_context") is not False:
        raise AssertionError("pin toggle rewrote current frozen context membership")


def _assert_cleanup(records: list[dict[str, Any]], exact_ids: set[object]) -> None:
    cleaned = _exactly_one(records, "scenario.cleaned")
    cleaned_ids = cleaned.get("memory_ids")
    if not isinstance(cleaned_ids, list) or set(cleaned_ids) != exact_ids:
        raise AssertionError("cleanup did not tombstone exactly the six fixture IDs")
    if cleaned.get("remaining_active_ids") != []:
        raise AssertionError("one or more exact fixture IDs remained active")


def _assert_ordering(records: list[dict[str, Any]]) -> None:
    kinds = (
        "spine.prepare.call",
        "spine.commit.result",
        "model.call",
        "spine.feedback.call",
        "spine.feedback.result",
        "scenario.conflict_staged",
        "browser.panel.conflict",
        "scenario.cleaned",
    )
    positions = [_first_position(records, kind) for kind in kinds]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise AssertionError(f"H6 operation ordering differs: {positions}")
    model_positions = _positions(records, "model.call")
    feedback_result_position = _first_position(records, "spine.feedback.result")
    if not model_positions[0] < feedback_result_position < model_positions[1]:
        raise AssertionError("removal was not committed between first and next model calls")
    conflict_position = _first_position(records, "browser.panel.conflict")
    if not feedback_result_position < conflict_position < model_positions[1]:
        raise AssertionError("canonical conflict did not occur before the immediate next call")


def _state_items(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = state.get("items")
    if not isinstance(items, list):
        raise AssertionError("panel state items is not a list")
    result: dict[str, dict[str, Any]] = {}
    for value in items:
        if not isinstance(value, dict) or not isinstance(value.get("role"), str):
            raise AssertionError("panel state contains an invalid sanitized item")
        role = value["role"]
        if role in result:
            raise AssertionError(f"panel state duplicated role {role}")
        result[role] = value
    return result


def _item(state: dict[str, Any], role: str) -> dict[str, Any]:
    try:
        return _state_items(state)[role]
    except KeyError as exc:
        raise AssertionError(f"panel state lacks role {role}") from exc


def _panel_patch_records(
    records: list[dict[str, Any]],
    kind: str,
    reason: str,
    role: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record["kind"] == kind and record.get("reason") == reason and record.get("role") == role
    ]


def _string_list(record: dict[str, Any], name: str) -> list[str]:
    value = record.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AssertionError(f"{name} is not a string list: {value}")
    return value


def _records(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [record for record in records if record["kind"] == kind]


def _exactly_one(records: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = _records(records, kind)
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {kind}, got {len(matches)}")
    return matches[0]


def _first_position(records: list[dict[str, Any]], kind: str) -> int:
    try:
        return next(index for index, record in enumerate(records) if record["kind"] == kind)
    except StopIteration as exc:
        raise AssertionError(f"trace lacks {kind}") from exc


def _positions(records: list[dict[str, Any]], kind: str) -> list[int]:
    return [index for index, record in enumerate(records) if record["kind"] == kind]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    main()
