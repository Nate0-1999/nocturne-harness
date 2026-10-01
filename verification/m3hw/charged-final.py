"""M3HW: the charged rows again on the final build, three fresh runs each; the test palace's env is
passed to the walks without being printed. usage: charged-final.py <fl166|walks>"""
import json
import os
import subprocess
import sys

lane = sys.argv[1]
OUT = "/private/tmp/m3hw-final/harness/verification/m3hw"
values = {k: json.loads(v) for k, v in (l.split("=", 1) for l in open(
    "/private/tmp/m3hw-verification/home/palaces/test-m3hw/env").read().splitlines() if "=" in l)}
env = {**os.environ, **{k: values[k] for k in ("SPINE_URL", "SPINE_TOKEN", "OPENROUTER_API_KEY")}}
log = open(f"/private/tmp/m3hw-work/logs/charged-final-{lane}.log", "a")
def run(command, **extra):
    log.write(f"\n$ {' '.join(command)}\n"); log.flush()
    code = subprocess.call(command, env={**env, **extra}, stdout=log, stderr=subprocess.STDOUT)
    log.write(f"(exit {code})\n"); log.flush()
if lane == "fl166":
    for i in (sys.argv[2:] or (1, 2, 3)):
        run(["/bin/zsh", f"{OUT}/fl166-walk.sh", str(i), f"{OUT}/receipts/FL-166-run{i}.txt"])
else:
    profile = {"WALK_PROFILE": "/private/tmp/m3hw-final-walk-profile"}
    for row in ("FL-198", "FL-184", "FL-133"):
        for i in (1, 2, 3):
            run(["node", f"{OUT}/walk.mjs", "http://127.0.0.1:8793", OUT, row, str(i)], **profile)
