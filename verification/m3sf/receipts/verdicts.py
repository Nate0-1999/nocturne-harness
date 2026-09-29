"""Summarize a Symphony's judge panels from its events.jsonl (evidence for the report)."""

import json
import sys
from pathlib import Path

run = Path("/private/tmp/m3sf-verification/home/palaces/test-m3sf/symphonies") / sys.argv[1]
for line in (run / "events.jsonl").read_text().splitlines():
    event = json.loads(line)
    if event.get("event") != "judge_panel_resolved":
        continue
    decision = event["decision"]
    print(decision["search_child_id"], decision["status"], "winner:", decision["winner_attempt_id"])
    for verdict in decision["verdicts"]:
        rationale = " ".join(verdict["rationale"].split())[:300]
        choice = f"{verdict['outcome']} {verdict['selected_attempt_id']}"
        print(f"  {verdict['seat']}: {choice} — {rationale}")
