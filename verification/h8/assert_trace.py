"""Assert the canonical H8 trace without contacting either service."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scenario_app import (
    MARKDOWN_PROMPT,
    MARKDOWN_RESPONSE,
    MODEL_SLUG,
    REMEMBER_BODY,
    REMEMBER_COMMAND,
    REMEMBER_KEYWORDS,
    REMEMBER_LABEL,
    REMEMBER_MODEL_OUTPUT,
    REMEMBER_MODEL_PROMPT,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", default=Path(__file__).with_name("trace.jsonl"))
    args = parser.parse_args()
    path = Path(args.trace)
    records = _read_trace(path)
    _assert_trace(records)
    print(f"H8 trace PASS: {path} ({len(records)} records)")


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
    started = _exactly_one(records, "scenario.started")
    if (
        started.get("resolved_model") != MODEL_SLUG
        or started.get("machine_id") != "h8-sop-verification"
        or started.get("agent_id") != "h8-verification-agent"
        or not isinstance(started.get("principal_id"), str)
        or not started["principal_id"].startswith("h8-verification-")
    ):
        raise AssertionError(f"scenario identity differs: {started}")

    prompts = _records(records, "wire.prompt.submit")
    if [record.get("purpose") for record in prompts] != ["remember", "markdown"]:
        raise AssertionError(f"canonical prompt order differs: {prompts}")
    _assert_prompt(prompts[0], REMEMBER_COMMAND)
    _assert_prompt(prompts[1], MARKDOWN_PROMPT)
    if prompts[0].get("thread_id") == prompts[1].get("thread_id"):
        raise AssertionError("canonical H8 flow must use a fresh thread for the Markdown reply")

    starts = _records(records, "wire.run.started")
    if len(starts) != 2:
        raise AssertionError(f"canonical H8 flow must start exactly two runs, got {len(starts)}")
    for prompt, run_started in zip(prompts, starts, strict=True):
        if (
            run_started.get("thread_id") != prompt.get("thread_id")
            or run_started.get("prompt_id") != prompt.get("prompt_id")
            or run_started.get("resolved_model") != MODEL_SLUG
            or not isinstance(run_started.get("run_id"), str)
        ):
            raise AssertionError(f"run.started does not match its prompt/model: {run_started}")

    snapshots = _records(records, "wire.thread.snapshot")
    if not snapshots:
        raise AssertionError("browser received no authoritative thread snapshot")
    prompt_threads = {record.get("thread_id") for record in prompts}
    snapshot_threads = {record.get("thread_id") for record in snapshots}
    if not prompt_threads.issubset(snapshot_threads):
        raise AssertionError("both canonical threads were not hydrated from snapshots")
    first_start_by_thread = {
        run_started.get("thread_id"): records.index(run_started) for run_started in starts
    }
    for index, record in enumerate(records):
        if record.get("kind") != "wire.thread.snapshot":
            continue
        resolved_model = record.get("resolved_model")
        if resolved_model not in {None, MODEL_SLUG}:
            raise AssertionError("a thread snapshot changed the resolved model")
        first_start = first_start_by_thread.get(record.get("thread_id"))
        if first_start is not None and index > first_start and resolved_model != MODEL_SLUG:
            raise AssertionError("a post-resolution thread snapshot omitted the resolved model")

    _assert_model_calls(records)
    created_id = _assert_create(records, prompts[0])
    _assert_wire_outputs(records, prompts, starts, created_id)
    _assert_cleanup(records, created_id)
    _assert_ordering(records)
    if _records(records, "wire.error"):
        raise AssertionError(f"browser received an error frame: {_records(records, 'wire.error')}")
    if _records(records, "agent.remember.exception"):
        raise AssertionError(
            "the /remember path raised unexpectedly: "
            f"{_records(records, 'agent.remember.exception')}"
        )
    if _records(records, "spine.create.rejected"):
        raise AssertionError(
            "the canonical path attempted a second fixture save: "
            f"{_records(records, 'spine.create.rejected')}"
        )


def _assert_prompt(record: dict[str, Any], prompt: str) -> None:
    if (
        record.get("prompt_sha256") != _digest(prompt)
        or not isinstance(record.get("prompt_id"), str)
        or not isinstance(record.get("thread_id"), str)
    ):
        raise AssertionError(f"prompt trace differs: {record}")


def _assert_model_calls(records: list[dict[str, Any]]) -> None:
    calls = _records(records, "model.call")
    if [record.get("purpose") for record in calls] != ["remember", "markdown"]:
        raise AssertionError(f"deterministic model call order differs: {calls}")
    remember, markdown = calls
    if (
        remember.get("resolved_model") != MODEL_SLUG
        or remember.get("prompt_sha256") != _digest(REMEMBER_MODEL_PROMPT)
        or remember.get("function_tools") != []
        or remember.get("output_tools") != []
        or remember.get("allow_text_output") is not True
        or remember.get("output_sha256") != _digest(REMEMBER_MODEL_OUTPUT)
    ):
        raise AssertionError(f"/remember metadata completion differs: {remember}")
    if (
        markdown.get("resolved_model") != MODEL_SLUG
        or markdown.get("prompt_sha256") != _digest(MARKDOWN_PROMPT)
        or markdown.get("output_sha256") != _digest(MARKDOWN_RESPONSE)
    ):
        raise AssertionError(f"Markdown model completion differs: {markdown}")
    if any(not _is_sha256(record.get("instructions_sha256")) for record in calls):
        raise AssertionError("one or more model calls lack a valid instruction digest")


def _assert_create(records: list[dict[str, Any]], remember_prompt: dict[str, Any]) -> str:
    call = _exactly_one(records, "spine.create.call")
    if (
        call.get("principal_matches") is not True
        or call.get("label") != REMEMBER_LABEL
        or call.get("body_sha256") != _digest(REMEMBER_BODY)
        or call.get("memory_kind") != "fact"
        or call.get("keywords") != list(REMEMBER_KEYWORDS)
        or call.get("project_key") is not None
        or call.get("thread_origin") != remember_prompt.get("thread_id")
        or call.get("origin_path") is not None
        or call.get("editor") != "user"
        or call.get("machine_id") != "h8-sop-verification"
        or call.get("force") is not False
    ):
        raise AssertionError(f"/remember C.4 create request differs: {call}")
    keywords = call["keywords"]
    if not 2 <= len(keywords) <= 5 or any(
        not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
    ):
        raise AssertionError(f"/remember did not supply 2–5 nonblank keywords: {keywords}")

    result = _exactly_one(records, "spine.create.result")
    memory_id = result.get("memory_id")
    if (
        result.get("outcome") != "created"
        or not isinstance(memory_id, str)
        or result.get("label") != REMEMBER_LABEL
        or result.get("body_sha256") != _digest(REMEMBER_BODY)
        or result.get("keywords") != list(REMEMBER_KEYWORDS)
        or result.get("status") != "active"
        or result.get("revision") != 1
    ):
        raise AssertionError(f"/remember did not land as the exact active memory: {result}")
    return memory_id


def _assert_wire_outputs(
    records: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    starts: list[dict[str, Any]],
    created_id: str,
) -> None:
    texts: dict[str, str] = {}
    for record in _records(records, "wire.run.text"):
        run_id = record.get("run_id")
        value = record.get("text")
        if not isinstance(run_id, str) or not isinstance(value, str):
            raise AssertionError(f"invalid text delta trace: {record}")
        texts[run_id] = texts.get(run_id, "") + value

    remember_run_id = starts[0]["run_id"]
    markdown_run_id = starts[1]["run_id"]
    expected_remember = f"Remembered {REMEMBER_LABEL!r} ({created_id})."
    if texts.get(remember_run_id) != expected_remember:
        observed = texts.get(remember_run_id)
        raise AssertionError(f"visible /remember confirmation differs: {observed!r}")
    if texts.get(markdown_run_id) != MARKDOWN_RESPONSE:
        raise AssertionError("Markdown text crossing the daemon→browser wire differs")

    done = _records(records, "wire.run.done")
    if len(done) != 2:
        raise AssertionError(f"canonical H8 flow must finish exactly two runs, got {len(done)}")
    done_by_run = {record.get("run_id"): record for record in done}
    if set(done_by_run) != {remember_run_id, markdown_run_id}:
        raise AssertionError("run.done IDs differ from the two started runs")
    for run_id, prompt in zip(
        (remember_run_id, markdown_run_id),
        prompts,
        strict=True,
    ):
        record = done_by_run[run_id]
        if (
            record.get("thread_id") != prompt.get("thread_id")
            or record.get("stop_reason") != "end_turn"
            or record.get("partial") is not False
        ):
            raise AssertionError(f"run did not finish cleanly: {record}")


def _assert_cleanup(records: list[dict[str, Any]], created_id: str) -> None:
    patch_calls = _records(records, "spine.patch.call")
    if not patch_calls:
        raise AssertionError("cleanup issued no exact-ID tombstone PATCH")
    for call in patch_calls:
        if (
            call.get("memory_id") != created_id
            or call.get("status") != "tombstoned"
            or call.get("editor") != "verification:h8"
            or call.get("machine_id") != "h8-sop-verification"
            or call.get("reason") != "H8 verification cleanup: tombstone exact fixture ID"
        ):
            raise AssertionError(f"cleanup PATCH escaped the exact fixture contract: {call}")

    results = _records(records, "spine.patch.result")
    if len(results) != 1:
        raise AssertionError(f"cleanup must end in one successful PATCH result: {results}")
    if results[0].get("memory_id") != created_id or results[0].get("status") != "tombstoned":
        raise AssertionError(f"cleanup result differs: {results[0]}")

    cleaned = _exactly_one(records, "scenario.cleaned")
    if (
        cleaned.get("memory_ids") != [created_id]
        or cleaned.get("remaining_active_ids") != []
        or not isinstance(cleaned.get("final_revision"), int)
        or cleaned["final_revision"] < 2
    ):
        raise AssertionError(f"exact-ID cleanup did not close: {cleaned}")


def _assert_ordering(records: list[dict[str, Any]]) -> None:
    sequence = [
        _position(records, "wire.prompt.submit", purpose="remember"),
        _position(records, "wire.run.started", occurrence=0),
        _position(records, "model.call", purpose="remember"),
        _position(records, "spine.create.call"),
        _position(records, "spine.create.result"),
        _position(records, "wire.run.done", occurrence=0),
        _position(records, "wire.prompt.submit", purpose="markdown"),
        _position(records, "wire.run.started", occurrence=1),
        _position(records, "model.call", purpose="markdown"),
        _position(records, "wire.run.done", occurrence=1),
        _position(records, "scenario.cleaned"),
    ]
    if sequence != sorted(sequence) or len(set(sequence)) != len(sequence):
        raise AssertionError(f"H8 operation ordering differs: {sequence}")


def _records(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [record for record in records if record["kind"] == kind]


def _exactly_one(records: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = _records(records, kind)
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {kind}, got {len(matches)}")
    return matches[0]


def _position(
    records: list[dict[str, Any]],
    kind: str,
    *,
    purpose: str | None = None,
    occurrence: int = 0,
) -> int:
    matches = [
        index
        for index, record in enumerate(records)
        if record["kind"] == kind and (purpose is None or record.get("purpose") == purpose)
    ]
    try:
        return matches[occurrence]
    except IndexError as exc:
        raise AssertionError(
            f"trace lacks {kind} occurrence {occurrence} for purpose {purpose}"
        ) from exc


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    main()
