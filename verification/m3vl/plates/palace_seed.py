"""M3VL send-back 1: a real Palace for the look — memories, injections and a curator pass
under the disposable verification identity. Every write goes through the Palace API; receipts
record each call.

usage: NOCTURNE_HOME=<scratch> python palace_seed.py <evidence-dir> memories|inject|curate
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from harness.spine_client import (
    CreateMemoryConflictError,
    CreateMemoryRequest,
    InjectCommitRequest,
    InjectPrepareRequest,
    PatchMemoryRequest,
    SpineClient,
)

HOME = Path(os.environ["NOCTURNE_HOME"])
CONFIG = dict(line.split("=", 1) for line in (HOME / "env").read_text().splitlines() if "=" in line)
CONFIG = {key: value.strip('"') for key, value in CONFIG.items()}
PRINCIPAL, MACHINE = CONFIG["PRINCIPAL_ID"], CONFIG["MACHINE_ID"]
assert PRINCIPAL.startswith("nocturne-verification-"), "disposable identities only"
PROJECT = "/private/tmp/m3vl24c-verification/project"

# Six subject families: the active riverflow project, and five unrelated subjects a Palace holds.
# Keywords are family-specific; a few notes carry one keyword, and two facts are filed twice under
# different subjects — ordinary untidiness that gives a real curator pass work across families.
FAMILIES = {
    "river": (
        ["river", "discharge"],
        PROJECT,
        [
            "A confluence conserves discharge",
            "merge() sums incoming discharges",
            "Reach.discharge recurses through children",
            "Manning velocity uses slope and roughness",
            "Travel time is length over velocity",
            "Roughness 0.035 suits natural channels",
            "read_stations loads flow per station",
            "Mouth flow should equal the fork sum",
            "Floodplains store peak flow",
            "Sediment load rises with discharge",
        ],
    ),
    "orchard": (
        ["orchard", "pruning"],
        None,
        [
            "Prune apple trees while dormant",
            "Open-center pruning lets light reach fruit",
            "Thin apples to one per cluster",
            "Water sprouts should be removed in summer",
            "Grafted rootstock sets final tree size",
            "Mulch keeps orchard roots cool",
        ],
    ),
    "telescope": (
        ["telescope", "optics"],
        None,
        [
            "Focal ratio sets field of view and brightness",
            "Collimate a reflector before observing",
            "Aperture limits resolving power",
            "Dew heaters keep the corrector plate clear",
            "Eyepiece focal length sets magnification",
            "Let the mirror cool to ambient",
        ],
    ),
    "sourdough": (
        ["sourdough", "baking"],
        None,
        [
            "Feed the starter at one to one to one",
            "Autolyse flour and water before salt",
            "Bulk ferment until the dough rises by half",
            "Bake in a preheated dutch oven",
            "Higher hydration gives a more open crumb",
            "Cold retard deepens sourdough flavor",
        ],
    ),
    "typesetting": (
        ["typesetting", "typography"],
        None,
        [
            "Set body text between 45 and 75 characters per line",
            "Leading near 1.4 suits body text",
            "Use true small caps not scaled capitals",
            "Hang punctuation into the margin",
            "Kerning adjusts single letter pairs",
        ],
    ),
    "harmony": (
        ["harmony", "music"],
        None,
        [
            "A dominant seventh resolves to the tonic",
            "Avoid parallel fifths in four-part writing",
            "The circle of fifths orders the keys",
            "Secondary dominants tonicize other chords",
            "A deceptive cadence moves V to vi",
        ],
    ),
}
UNTIDY = [
    ("orchard", ["orchard"], "Summer pruning slows vigorous growth"),
    ("telescope", ["Telescope"], "Seeing limits planetary detail more than aperture"),
    ("harmony", ["harmony"], "Voice leading favors the smallest motion"),
    ("sourdough", ["sourdough", "baking"], "Floodplains store the flood peak"),
    (
        "typesetting",
        ["typesetting", "typography"],
        "A confluence conserves the discharge it receives",
    ),
]
PROMPTS = [
    "How does riverflow conserve discharge where tributaries meet?",
    "Explain merge() and how Reach.discharge sums children.",
    "What sets the travel time of a flood wave in routing.py?",
    "How are gauge readings loaded and used for calibration?",
    "Why should the mouth flow equal the sum of the forks?",
    "Describe how a confluence changes discharge downstream.",
    "What roughness value does routing use and why?",
    "How does the watershed outlet relate to catchment area?",
    "How do floodplains attenuate the flood peak?",
    "Explain Manning velocity with slope and roughness.",
    "Which modules handle confluences and discharge sums?",
    "How does sediment load respond to high discharge?",
]


def client() -> SpineClient:
    return SpineClient(CONFIG["SPINE_URL"], CONFIG["SPINE_TOKEN"], principal_id=PRINCIPAL)


async def create(palace: SpineClient, keywords: list[str], project: str | None, fact: str) -> dict:
    try:
        response = await palace.create_memory(
            CreateMemoryRequest(
                principal_id=PRINCIPAL,
                label=f"VL24C {fact[:40]}",
                body=f"{fact}.",
                kind="fact",
                keywords=keywords,
                project_key=project,
                editor="m3vl-vl24c-verification",
                machine_id=MACHINE,
                force=True,
            )
        )
        return response.model_dump(mode="json")
    except CreateMemoryConflictError as conflict:  # created by an interrupted earlier call
        return {"existing": conflict.conflict.model_dump(mode="json")}


async def memories(evidence: Path) -> None:
    created = []
    async with client() as palace:
        for keywords, project, facts in FAMILIES.values():
            for fact in facts:
                created.append(await create(palace, keywords, project, fact))
        for family, keywords, fact in UNTIDY:
            created.append(await create(palace, keywords, FAMILIES[family][1], fact))
    path = evidence / "receipts" / "memories-created.json"
    previous = json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps(previous + created, indent=2) + "\n")
    print(f"created {len(created)} memories")


def created_ids(evidence: Path) -> list[str]:
    rows = json.loads((evidence / "receipts" / "memories-created.json").read_text())
    return sorted(
        {
            row["created"]["memory_id"]
            if "created" in row
            else next(iter(row["existing"].values()))["memory_id"]
            for row in rows
        }
    )


async def tombstone(evidence: Path) -> None:
    """Retire exactly the memories this walk created, by recorded id; nothing else is touched."""
    results = []
    # Current revisions of exactly these ids, read from the app's own Palace graph feed.
    feed = httpx.get("http://127.0.0.1:8765/v1/visualization", timeout=60).json()["palace"]["nodes"]
    revisions = {node["memory"]["memory_id"]: node["memory"]["revision"] for node in feed}
    async with client() as palace:
        for memory_id in created_ids(evidence):
            if memory_id not in revisions:
                results.append({"memory_id": memory_id, "status": "not active"})
                continue
            patched = await palace.patch_memory(
                UUID(memory_id),
                PatchMemoryRequest(
                    expected_revision=revisions[memory_id],
                    status="tombstoned",
                    editor="m3vl-vl24c-verification",
                    reason="M3VL verification cleanup",
                    machine_id=MACHINE,
                ),
            )
            results.append(
                {"memory_id": memory_id, "status": patched.status, "revision": patched.revision}
            )
    path = evidence / "receipts" / "tombstones.json"
    previous = json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps(previous + results, indent=2) + "\n")
    print(f"{sum(item['status'] == 'tombstoned' for item in results)} tombstoned of {len(results)}")


async def inject(evidence: Path, rounds: int) -> None:
    history = []
    async with client() as palace:
        for round_index in range(rounds):
            for index, prompt in enumerate(
                PROMPTS[: 4 + round_index * 2] if rounds > 1 else PROMPTS
            ):
                # The Palace holds one injection per thread: each retrieval is its own session.
                thread = str(uuid4())
                prepared = await palace.prepare_injection(
                    InjectPrepareRequest(
                        thread_id=UUID(thread),
                        agent_id="nocturne",
                        machine_id=MACHINE,
                        principal_id=PRINCIPAL,
                        project_key=PROJECT,
                        current_location=PROJECT,
                        prompt=prompt,
                        model_context_tokens=64000,
                    )
                )
                await palace.commit_injection(
                    InjectCommitRequest(
                        injection_id=prepared.injection_id, removed=[], added_back=[]
                    )
                )
                history.append(
                    {
                        "prompt": prompt,
                        "thread_id": thread,
                        "injection_id": str(prepared.injection_id),
                        "injected": [str(item.memory_id) for item in prepared.injected],
                    }
                )
    path = evidence / "receipts" / "injections.json"
    previous = json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps(previous + history, indent=2) + "\n")
    injected = sum(len(item["injected"]) for item in history)
    print(f"{len(history)} injections, {injected} memory injections")


async def curate(evidence: Path) -> None:
    async with httpx.AsyncClient(
        base_url=CONFIG["SPINE_URL"],
        timeout=600,
        headers={"Authorization": f"Bearer {CONFIG['SPINE_TOKEN']}"},
    ) as http:
        response = await http.post(
            "v1/curation/runs", json={"principal_id": PRINCIPAL, "machine_id": MACHINE}
        )
        path = evidence / "receipts" / "curator-runs.json"
        previous = json.loads(path.read_text()) if path.exists() else []
        path.write_text(
            json.dumps(
                previous + [{"status": response.status_code, "body": response.json()}], indent=2
            )
            + "\n"
        )
        print(
            response.status_code,
            response.json().get("status"),
            response.json().get("verdict_count"),
        )


if __name__ == "__main__":
    evidence, action = Path(sys.argv[1]), sys.argv[2]
    if action == "memories":
        asyncio.run(memories(evidence))
    elif action == "inject":
        asyncio.run(inject(evidence, int(sys.argv[3]) if len(sys.argv) > 3 else 4))
    elif action == "untidy":
        UNTIDY[:] = [
            ("harmony", ["Harmony"], "Modulation pivots on a shared chord"),
            ("orchard", ["orchard"], "Cross-pollination needs a compatible variety"),
        ]
        FAMILIES.clear()
        FAMILIES.update({"harmony": ([], None, []), "orchard": ([], None, [])})
        asyncio.run(memories(evidence))
    elif action == "tombstone":
        asyncio.run(tombstone(evidence))
    elif action == "topics":
        every = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        PROMPTS[:] = [
            f"Remind me: {fact.lower()}." for _, _, facts in FAMILIES.values() for fact in facts
        ][::every]
        asyncio.run(inject(evidence, 1))
    elif action == "curate":
        asyncio.run(curate(evidence))
