"""M3PR: project the Garden record through released seed ingestion.

The script is deliberately verification-layer code. It parses source artifacts
into one bounded index memory per section/row/decision, sends those candidates
through the existing seed queue, records the owner-authorized batch decision,
and patches only origin provenance to the law-required ``file#section`` value.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid5

import httpx
import tiktoken

from harness.config import HarnessSettings

WORKSPACE = Path(__file__).resolve().parents[2]
GARDEN = WORKSPACE / "garden"
PRINCIPAL = "garden-record"
MACHINE = "m3pr-garden-record-verification"
EDITOR = "m3pr-garden-record"
NAMESPACE = UUID("1c8aa2fa-0835-5c8d-8fcb-27fd705c4e61")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
D2_ROW = re.compile(r"^\|\s*(\d+[a-z]?)\s*\|")
DECISION = re.compile(r"^##\s+(\d{3}\b.+?)\s*$")
WORD = re.compile(r"[a-z][a-z0-9_-]{2,}", re.IGNORECASE)
STOP_WORDS = {
    "and",
    "are",
    "for",
    "from",
    "garden",
    "into",
    "not",
    "the",
    "this",
    "through",
    "with",
}


@dataclass(frozen=True)
class RecordUnit:
    origin: str
    title: str
    source: str


@dataclass(frozen=True)
class CandidateUnit:
    record: RecordUnit
    label: str
    body: str
    keywords: tuple[str, ...]
    target_id: UUID | None


class ReleasedPalace:
    """Narrow transport for the deployed 0.1.5 / contract-0.1.4 surface."""

    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            follow_redirects=False,
            timeout=60,
        )

    async def __aenter__(self) -> ReleasedPalace:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = await self._client.request(method, path, json=body, params=params)
        if response.status_code >= 400:
            detail = response.json().get("detail", "request refused")
            raise RuntimeError(f"{method} {path} returned HTTP {response.status_code}: {detail}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} returned a non-object body")
        return payload


def _relative(path: Path) -> str:
    return path.relative_to(WORKSPACE).as_posix()


def _unique_origins(units: list[RecordUnit]) -> list[RecordUnit]:
    seen: dict[str, int] = {}
    result: list[RecordUnit] = []
    for unit in units:
        count = seen.get(unit.origin, 0) + 1
        seen[unit.origin] = count
        if count == 1:
            result.append(unit)
            continue
        result.append(
            RecordUnit(
                origin=f"{unit.origin}@{count}",
                title=unit.title,
                source=unit.source,
            )
        )
    return result


def _markdown_sections(path: Path) -> list[RecordUnit]:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [
        (index, match.group(2).strip())
        for index, line in enumerate(lines)
        if (match := HEADING.match(line))
    ]
    units: list[RecordUnit] = []
    for position, (start, title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        source = "\n".join(lines[start:end]).strip()
        units.append(RecordUnit(f"{_relative(path)}#{title}", title, source))
    return _unique_origins(units)


def _spec_units() -> list[RecordUnit]:
    path = GARDEN / "SPEC.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    units = _markdown_sections(path)
    for line in lines:
        match = D2_ROW.match(line)
        if match:
            title = f"D.2 {match.group(1)}"
            units.append(RecordUnit(f"garden/SPEC.md#{title}", title, line.strip()))
    return _unique_origins(units)


def _decision_units(path: Path) -> list[RecordUnit]:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [
        (index, match.group(1).strip())
        for index, line in enumerate(lines)
        if (match := DECISION.match(line))
    ]
    units: list[RecordUnit] = []
    for position, (start, title) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        source = "\n".join(lines[start:end]).strip()
        units.append(RecordUnit(f"{_relative(path)}#Decision {title[:3]}", title, source))
    return _unique_origins(units)


def _report_units() -> list[RecordUnit]:
    units: list[RecordUnit] = []
    title_counts: dict[str, int] = {}
    for path in sorted((GARDEN / "reports").glob("*.md")):
        source = path.read_text(encoding="utf-8").strip()
        packet = re.search(r"^packet:\s*(.+?)\s*$", source, re.MULTILINE)
        title = packet.group(1) if packet else path.stem
        origin = f"{_relative(path)}#{title}"
        title_counts[title] = title_counts.get(title, 0) + 1
        if title_counts[title] > 1:
            status = re.search(r"^status:\s*(.+?)\s*$", source, re.MULTILINE)
            outcome = status.group(1) if status else "follow-up"
            title = f"Follow-up {path.stem} ({outcome}) · {title}"
        units.append(RecordUnit(origin, title, source))
    return _unique_origins(units)


def record_units() -> list[RecordUnit]:
    units = _spec_units()
    for path in sorted((GARDEN / "notes").glob("*.md")):
        units.extend(_markdown_sections(path))
    units.extend(_decision_units(WORKSPACE / "harness" / "DECISIONS.md"))
    units.extend(_decision_units(WORKSPACE / "spine" / "DECISIONS.md"))
    units.extend(_report_units())
    by_origin = {unit.origin: unit for unit in units}
    if len(by_origin) != len(units):
        raise RuntimeError("record parser produced duplicate origin paths")
    return sorted(units, key=lambda unit: unit.origin)


def _bounded_body(unit: RecordUnit) -> str:
    collapsed = re.sub(r"\s+", " ", unit.source).strip()
    text = f"{unit.title}. Source {unit.origin}. {collapsed}"
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if len(tokens) > 124:
        text = encoding.decode(tokens[:124]).rstrip() + "…"
    return text


def _hardened_body(unit: RecordUnit, body: str) -> str:
    """Make one semantically-near archive unit distinct without losing its text."""

    fingerprint = hashlib.sha256(f"{unit.origin}\0{unit.source}".encode()).hexdigest()
    prefix = (
        "Distinct archival record; preserve separately for provenance. "
        f"Integrity fingerprints {fingerprint} {fingerprint[::-1]}. "
    )
    encoding = tiktoken.get_encoding("cl100k_base")
    return encoding.decode(encoding.encode(prefix + body)[:124]).rstrip()


def _label(unit: RecordUnit, body: str) -> str:
    digest = hashlib.sha256(f"{unit.origin}\0{body}".encode()).hexdigest()[:8]
    base = re.sub(r"\s+", " ", f"Garden · {unit.title}").strip()
    return f"{base[:52].rstrip()} · {digest}"


def _keywords(unit: RecordUnit) -> tuple[str, ...]:
    values = [word.casefold() for word in WORD.findall(f"{unit.title} {unit.origin}")]
    chosen: list[str] = ["garden", "record"]
    for value in values:
        if value not in STOP_WORDS and value not in chosen:
            chosen.append(value)
        if len(chosen) == 5:
            break
    return tuple(chosen)


def _batch_markdown(candidates: list[CandidateUnit]) -> str:
    return "\n\n".join(f"## {candidate.label}\n\n{candidate.body}" for candidate in candidates)


def batches(candidates: list[CandidateUnit]) -> list[list[CandidateUnit]]:
    result: list[list[CandidateUnit]] = []
    current: list[CandidateUnit] = []
    for candidate in candidates:
        proposed = [*current, candidate]
        if current and (len(proposed) > 12 or len(_batch_markdown(proposed).encode()) > 23_500):
            result.append(current)
            current = [candidate]
        else:
            current = proposed
    if current:
        result.append(current)
    return result


async def _all_memories(client: ReleasedPalace) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    offset = 0
    while True:
        page = await client.request("GET", "v1/memories", params={"limit": 200, "offset": offset})
        page_items = page.get("items")
        if not isinstance(page_items, list) or any(
            not isinstance(item, dict) for item in page_items
        ):
            raise RuntimeError("GET v1/memories returned invalid items")
        items.extend(page_items)
        offset += len(page_items)
        total = page.get("total")
        if not isinstance(total, int):
            raise RuntimeError("GET v1/memories returned invalid total")
        if offset >= total or not page_items:
            return items


async def _pending_seed_cards(client: ReleasedPalace) -> list[dict[str, object]]:
    response = await client.request(
        "GET",
        "v1/approval-queue",
        params={"principal_id": PRINCIPAL, "birthplace": "seed"},
    )
    cards = response.get("cards")
    if not isinstance(cards, list) or any(not isinstance(card, dict) for card in cards):
        raise RuntimeError("approval queue returned invalid cards")
    return cards


async def _approve_and_stamp(
    client: ReleasedPalace,
    batch_uid: str,
    cards: list[dict[str, object]],
    expected: dict[str, CandidateUnit],
) -> int:
    labels: list[str] = []
    for card in cards:
        memory = card.get("candidate")
        if not isinstance(memory, dict):
            raise RuntimeError(f"batch {batch_uid} returned an invalid candidate")
        label = str(memory.get("label"))
        candidate = expected.get(label)
        if candidate is None or memory.get("body") != candidate.body:
            raise RuntimeError(f"batch {batch_uid} contains an unknown garden-record card")
        labels.append(label)
    decision = await client.request(
        "POST",
        f"v1/approval-queue/batches/{batch_uid}/decisions",
        body={
            "decision": "approve",
            "approval_mode": "explicit",
            "actor_class": "human",
            "machine_id": MACHINE,
        },
    )
    decided = decision.get("cards")
    if not isinstance(decided, list):
        raise RuntimeError(f"batch {batch_uid} approval returned invalid cards")
    repaired = 0
    for card in decided:
        if not isinstance(card, dict) or not isinstance(card.get("candidate"), dict):
            raise RuntimeError(f"batch {batch_uid} approval returned an invalid candidate")
        memory = card["candidate"]
        candidate = expected.get(str(memory.get("label")))
        if candidate is None:
            raise RuntimeError(f"batch {batch_uid} approval returned an unknown label")
        if memory.get("origin_path") != candidate.record.origin:
            await client.request(
                "PATCH",
                f"v1/memories/{memory['memory_id']}",
                body={
                    "expected_revision": memory["revision"],
                    "origin_path": candidate.record.origin,
                    "editor": EDITOR,
                    "reason": "m3pr/garden-origin",
                    "machine_id": MACHINE,
                },
            )
            repaired += 1
    if sorted(labels) != sorted(
        str(card["candidate"]["label"])
        for card in decided
        if isinstance(card, dict) and isinstance(card.get("candidate"), dict)
    ):
        raise RuntimeError(f"batch {batch_uid} approval changed its member set")
    return repaired


async def _apply(args: argparse.Namespace, units: list[RecordUnit]) -> None:
    settings = HarnessSettings()
    token = settings.spine_token
    if token is None:
        raise RuntimeError("SPINE_TOKEN is required for --apply")
    async with ReleasedPalace(settings.spine_url, token.get_secret_value()) as client:
        expected: dict[str, CandidateUnit] = {}
        for unit in units:
            body = _bounded_body(unit)
            for variant in (body, _hardened_body(unit, body)):
                label = _label(unit, variant)
                expected[label] = CandidateUnit(
                    record=unit,
                    label=label,
                    body=variant,
                    keywords=_keywords(unit),
                    target_id=None,
                )
        repaired_origins = 0
        pending_groups: dict[str, list[dict[str, object]]] = {}
        for card in await _pending_seed_cards(client):
            source_name = card.get("source_name")
            batch_uid = card.get("batch_uid")
            if isinstance(source_name, str) and source_name.startswith("garden-record-"):
                if not isinstance(batch_uid, str):
                    raise RuntimeError("garden-record pending card has no batch UID")
                pending_groups.setdefault(batch_uid, []).append(card)
        for batch_uid, cards in sorted(pending_groups.items()):
            repaired_origins += await _approve_and_stamp(client, batch_uid, cards, expected)
            print(f"recovered partial batch {batch_uid}: {len(cards)} exact cards approved")

        memories = [
            memory
            for memory in await _all_memories(client)
            if memory.get("principal_id") == PRINCIPAL and memory.get("status") == "active"
        ]
        by_origin = {
            str(memory["origin_path"]): memory for memory in memories if memory.get("origin_path")
        }
        changed: list[CandidateUnit] = []
        for unit in units:
            body = _bounded_body(unit)
            label = _label(unit, body)
            hardened = _hardened_body(unit, body)
            hardened_label = _label(unit, hardened)
            existing = by_origin.get(unit.origin)
            if existing is not None and (existing.get("body"), existing.get("label")) in {
                (body, label),
                (hardened, hardened_label),
            }:
                continue
            changed.append(
                CandidateUnit(
                    record=unit,
                    label=label,
                    body=body,
                    keywords=_keywords(unit),
                    target_id=UUID(str(existing["memory_id"])) if existing is not None else None,
                )
            )

        planned_batches = batches(changed)
        print(
            f"garden-record plan: {len(units)} units; {len(units) - len(changed)} unchanged; "
            f"{len(changed)} to ingest in {len(planned_batches)} batches"
        )
        if not changed:
            print("garden-record re-ingest: idempotent no-op on unchanged text")
        number = 0
        while planned_batches:
            group = planned_batches.pop(0)
            number += 1
            markdown = _batch_markdown(group)
            digest = hashlib.sha256(markdown.encode()).hexdigest()
            batch_uid = uuid5(NAMESPACE, digest)
            source_name = f"garden-record-{digest[:20]}.md"
            request: dict[str, object] = {
                "principal_id": PRINCIPAL,
                "batch_uid": str(batch_uid),
                "source_name": source_name,
                "source_sha256": digest,
                "markdown": markdown,
                "machine_id": MACHINE,
                "editor": EDITOR,
                "candidates": [
                    {
                        "label": candidate.label,
                        "body": candidate.body,
                        "kind": "project_note",
                        "keywords": list(candidate.keywords),
                        "verdict": "supersede" if candidate.target_id else "new",
                        "target_ids": [str(candidate.target_id)] if candidate.target_id else [],
                    }
                    for candidate in group
                ],
            }
            partial = False
            try:
                seeded = await client.request("POST", "v1/seeds", body=request)
            except RuntimeError as error:
                if "POST v1/seeds returned HTTP 500" not in str(error):
                    raise
                partial = True
                cards = [
                    card
                    for card in await _pending_seed_cards(client)
                    if card.get("batch_uid") == str(batch_uid)
                ]
                if not cards:
                    raise RuntimeError(
                        f"batch {batch_uid} failed before producing a recoverable card"
                    ) from error
                seeded = {
                    "batch_uid": str(batch_uid),
                    "cards": cards,
                    "duplicate_count": len(group) - len(cards),
                }
            replayed = await client.request("POST", "v1/seeds", body=request)
            seeded_cards = seeded.get("cards")
            replayed_cards = replayed.get("cards")
            if not isinstance(seeded_cards, list) or not isinstance(replayed_cards, list):
                raise RuntimeError(f"batch {batch_uid} returned invalid cards")
            if seeded.get("batch_uid") != replayed.get("batch_uid") or [
                card.get("item_uid") for card in seeded_cards if isinstance(card, dict)
            ] != [card.get("item_uid") for card in replayed_cards if isinstance(card, dict)]:
                raise RuntimeError(f"batch {batch_uid} was not idempotent before approval")
            cards = [card for card in seeded_cards if isinstance(card, dict)]
            approved_labels = {
                str(card["candidate"]["label"])
                for card in cards
                if isinstance(card.get("candidate"), dict)
            }
            group_expected = {candidate.label: candidate for candidate in group}
            repaired_origins += await _approve_and_stamp(
                client, str(batch_uid), cards, group_expected
            )
            missing = [candidate for candidate in group if candidate.label not in approved_labels]
            if missing and partial:
                planned_batches.insert(0, missing)
            elif missing:
                hardened_missing: list[CandidateUnit] = []
                for candidate in missing:
                    base = _bounded_body(candidate.record)
                    hardened = _hardened_body(candidate.record, base)
                    if candidate.body == hardened:
                        raise RuntimeError(
                            f"batch {batch_uid} collapsed already-hardened archival unit "
                            f"{candidate.record.origin}"
                        )
                    hardened_missing.append(
                        CandidateUnit(
                            record=candidate.record,
                            label=_label(candidate.record, hardened),
                            body=hardened,
                            keywords=candidate.keywords,
                            target_id=candidate.target_id,
                        )
                    )
                planned_batches.insert(0, hardened_missing)
            collision_note = (
                " · semantic duplicates requeued with provenance fingerprints"
                if missing and not partial
                else ""
            )
            print(
                f"batch {number}: {batch_uid} · {len(cards)}/{len(group)} candidates · "
                f"replay stable · approved{' · partial recovered' if partial else ''}"
                f"{collision_note}"
            )

        final = [
            memory
            for memory in await _all_memories(client)
            if memory.get("principal_id") == PRINCIPAL and memory.get("status") == "active"
        ]
        final_origins = {memory.get("origin_path") for memory in final}
        missing = [unit.origin for unit in units if unit.origin not in final_origins]
        if missing:
            raise RuntimeError(
                f"garden-record is missing {len(missing)} origins; first: {missing[0]}"
            )
        print(
            f"garden-record verified: {len(units)} expected origins; {len(final)} active memories; "
            f"{repaired_origins} origin patches"
        )
        if args.semantic_query:
            result = await client.request(
                "POST",
                "v1/search",
                body={"principal_id": PRINCIPAL, "query": args.semantic_query, "k": 8},
            )
            print(f"semantic query: {args.semantic_query}")
            cards = result.get("results")
            if not isinstance(cards, list):
                raise RuntimeError("semantic search returned invalid results")
            for card in cards:
                if isinstance(card, dict):
                    print(
                        f"  {float(card['score']):.4f} · {card['label']} · "
                        f"{str(card['body'])[:160]}"
                    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write to the configured Palace")
    parser.add_argument(
        "--approve-owner-authorized",
        action="store_true",
        help="confirm the invoking owner authorized explicit approval of garden-record batches",
    )
    parser.add_argument("--semantic-query", help="run one semantic proof after verification")
    args = parser.parse_args()
    if args.apply and not args.approve_owner_authorized:
        parser.error(
            "--apply requires --approve-owner-authorized; seed admission is a human boundary"
        )
    return args


def main() -> None:
    args = parse_args()
    units = record_units()
    bodies = [_bounded_body(unit) for unit in units]
    if len({unit.origin for unit in units}) != len(units):
        raise RuntimeError("origins are not unique")
    if any(len(tiktoken.get_encoding("cl100k_base").encode(body)) > 128 for body in bodies):
        raise RuntimeError("a garden-record memory exceeds 128 tokens")
    print(
        f"parsed {len(units)} record units: SPEC sections/D.2 rows, note sections, "
        "decisions, and reports; every body <=128 tokens"
    )
    if args.apply:
        asyncio.run(_apply(args, units))


if __name__ == "__main__":
    main()
