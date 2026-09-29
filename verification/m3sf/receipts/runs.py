"""Build runs.json: every Symphony the M3SF walk launched, from its own events.jsonl."""

import json
import sys
from pathlib import Path

HOME = Path("/private/tmp/m3sf-verification/home/palaces/test-m3sf/symphonies")
OUTCOMES = json.loads((Path(__file__).parent / "outcomes.json").read_text())
RUNS = [  # (symphony id, walk label, harness build, counted as proof run)
    (
        "01M3N820KWGDSTQZSCSCVP4WS4",
        "env run: README section (OpenRouter DNS-blocked)",
        "31d68ec~",
        False,
    ),
    (
        "01M3NEXZNV4KH4994GK5K3T059",
        "run 1: README 'Named palaces' (relaunched from its card)",
        "31d68ec",
        True,
    ),
    ("01M3NF4MS166F3B1AJ9C22HCMN", "run 2 try 1: palace help text", "31d68ec", False),
    ("01M3NFPWFZFMH8Z9039GWKDBW1", "run 2 try 2: palace help text", "7779224", False),
    ("01M3NQD6RK4G3R9WETZ52BWRV6", "run 2 try 3: palace help text", "03b3970", False),
    ("01M3NRKR41XKW33249FW9PZWQA", "run 2: palace help text", "c1dfc26", True),
    ("01M3NSHGE2NRGC10QA3E6GEQNQ", "run 3 try 1: nocturne --version", "c1dfc26", False),
    ("01M3NT2B1P62MPNJH8280PTQSB", "run 3: nocturne --version", "567ac93", True),
    ("01M3NTTMDF6280GW4J5Y02B79T", "run 4: README 'Tests' section", "6d97cc1", True),
    (
        "01M3NVAPCJX5AWKXHDD638TPBR",
        "run 5: confirmation on the rebased build, steered",
        "rebased",
        False,
    ),
]
out = []
for symphony_id, label, build, proof in RUNS:
    rounds, final = [], None
    for line in (HOME / symphony_id / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event.get("event") == "judge_panel_resolved":
            decision = event["decision"]
            rounds.append(
                {
                    "round": decision["search_child_id"],
                    "status": decision["status"],
                    "winner": decision["winner_attempt_id"],
                    "verdicts": [
                        {
                            "seat": v["seat"],
                            "outcome": v["outcome"],
                            "selected": v["selected_attempt_id"],
                            "rationale": " ".join(v["rationale"].split())[:400],
                        }
                        for v in decision["verdicts"]
                    ],
                }
            )
    out.append(
        {
            "symphony_id": symphony_id,
            "label": label,
            "build": build,
            "proof_run": proof,
            "outcome": OUTCOMES[symphony_id],
            "rounds": rounds,
        }
    )
json.dump(out, sys.stdout, indent=2)
