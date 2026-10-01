"""M3LV: for each run's log, pair every feed change with the first moment its module showed it.

usage: python lags.py run-1/run1.json [...]  — prints one line per change: module, what, feed time, shown time, lag (s).
Farm: a thread's folder in the feed → the Farm table's row; Roots: touched files in the feed → the Roots readout's
capillary count; Palace: the Palace API's memory count → the module's bodies; ghosts: a finding's targets in the feed →
the module's curator readout.
"""

import json
import sys
from datetime import datetime


def stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def first_after(events, source, since, test):
    return next((e for e in events if e["source"] == source and stamp(e["t"]) >= since and test(e["value"])), None)


for path in sys.argv[1:]:
    log = json.load(open(path))
    events = log["events"]
    rows = []
    for e in events:
        value, at = e["value"], stamp(e["t"])
        if e["source"] == "feed.T2" and isinstance(value, dict):
            where = value["where"].split("/")[-1]
            shown = first_after(events, "farm.T2row", at, lambda v: isinstance(v, str) and f"./{where} " in v or f"/{where} " in str(v))
            rows.append(("farm", f"folder {value['where']}", at, shown))
            files = value.get("files") or 0
            if files:
                # The readout logs only its changes, so its first change after the feed's is the module reacting.
                shown = first_after(events, "roots.readout", at, lambda v: "touched-file" in str(v))
                rows.append(("roots", f"{files} file(s) touched", at, shown))
        if e["source"] == "palace.api" and isinstance(value, str) and value.endswith("nodes") and e is not next(x for x in events if x["source"] == "palace.api"):
            count = int(value.split()[0])
            # The module polls on its own, so it may show the memory before the walk's once-a-second API read does.
            shown = first_after(events, "palace.readout", stamp(events[0]["t"]), lambda v: f" {count} bodies" in f" {v}")
            rows.append(("palace", f"{count} memories", at, shown))
        if e["source"] == "feed.progress" and isinstance(value, dict) and value["phase"] == "finding.started":
            shown = first_after(events, "palace.curator", at, lambda v: f"{value['targets']} targets finding.started" in str(v))
            rows.append(("ghosts", f"{value['targets']} target(s) {value['ts']}", at, shown))
    print(f"== {path}")
    seen = set()
    for module, what, at, shown in rows:
        key = (module, what)
        if key in seen:
            continue
        seen.add(key)
        lag = None if shown is None else round((stamp(shown["t"]) - at).total_seconds(), 2)
        print(f"  {module:7} {what:40} feed {at.strftime('%H:%M:%S.%f')[:12]}  shown {shown['t'][11:23] if shown else '—':12}  lag {lag}")
