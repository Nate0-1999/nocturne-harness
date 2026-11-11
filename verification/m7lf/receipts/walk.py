"""M7LF: use a saved forecast bundle on Linux, with real OpenRouter and the local Palace."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from harness.onboarding import load_config

RUN = sys.argv[1]
ROOT = Path("/root/m7lf-walk")
HOME = Path("/root/m7lf-home")
OUT = ROOT / f"run-{RUN}"
BASE = "http://127.0.0.1:8898"
MINI = "pinned:openrouter:openai/gpt-4.1-mini"
KEY = "lf-fixture-" + secrets.token_hex(16)
HASH = hashlib.sha256(KEY.encode()).hexdigest()
REQUESTS = []
RECEIPT = {"run": RUN, "started": datetime.now(UTC).isoformat(), "checks": []}
OUT.mkdir(parents=True, exist_ok=True)


def clean(value):
    return str(value).replace(KEY, "<KEY LEAKED>")


def api(path, method="GET", body=None):
    response = httpx.request(method, BASE + path, json=body, timeout=60)
    response.raise_for_status()
    return response.json()


def cli(*args, stdin=None, cwd=None):
    result = subprocess.run(
        ["/venv/bin/nocturne", *args],
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        env={**os.environ, "NOCTURNE_HOME": str(HOME)},
    )
    if result.returncode:
        raise RuntimeError(clean(result.stdout + result.stderr))
    return clean(result.stdout)


def check(row, name, ok, **detail):
    RECEIPT["checks"].append({"row": row, "name": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {row}: {name}", flush=True)


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        authorized = hashlib.sha256(self.headers.get("X-Api-Key", "").encode()).hexdigest() == HASH
        REQUESTS.append({"path": self.path, "authorized": authorized})
        self.send_response(200 if authorized else 401)
        self.end_headers()
        self.wfile.write(f"Austin: clear, 21C (report #{len(REQUESTS)})\n".encode())

    def log_message(self, *args):
        pass


def runs(job_id):
    return sorted(
        (r for r in api("/v1/jobs")["runs"] if r["job_id"] == job_id), key=lambda r: r["started_at"]
    )


def wait(job_id, count):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        found = runs(job_id)
        if len(found) >= count and found[count - 1]["state"] in {
            "completed",
            "failed",
            "waiting",
            "cancelled",
            "interrupted",
        }:
            return found[count - 1]
        time.sleep(2)
    raise TimeoutError(f"Job did not finish: {runs(job_id)}")


def calls(thread_id):
    result = []
    for path in (HOME / "transcripts").glob("*.jsonl"):
        if thread_id not in path.read_text()[:4000]:
            continue
        for line in path.read_text().splitlines():
            for event in (json.loads(line).get("message") or {}).get("events") or []:
                if event.get("event_kind") in {"function_tool_call", "function_tool_result"}:
                    result.append(event)
    return result


def jobs_module(page):
    page.goto(BASE, wait_until="domcontentloaded")
    page.get_by_role("button", name="Sheet", exact=True).click()
    page.wait_for_timeout(2000)
    if page.locator('[data-testid="rack-plugin-frame-jobs"]').count() == 0:
        page.get_by_role("button", name="Library", exact=True).click()
        page.get_by_role("button", name="Add Jobs", exact=True).click()
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Library", exact=True).click()
    page.locator('[data-testid="rack-plugin-frame-jobs"]').scroll_into_view_if_needed()
    page.wait_for_timeout(2000)
    return page.frame_locator('[data-testid="rack-plugin-frame-jobs"]')


def main():
    policies = api("/v1/model-policies")
    assert set(policies["policies"].values()) == {MINI}, policies
    config = load_config(home=HOME)
    usage = httpx.get(
        "https://openrouter.ai/api/v1/key",
        timeout=20,
        headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
    )
    usage.raise_for_status()
    RECEIPT["key_usage_before"] = usage.json()["data"]["usage"]
    cap_start = float(os.environ["M7LF_USAGE_START"])
    assert RECEIPT["key_usage_before"] - cap_start < 2.8, "STOP: cap headroom exhausted"
    name = f"forecast-lf-{RUN}-{datetime.now(UTC):%H%M%S}"
    folder = ROOT / "bundles" / name
    cli("workflow", "new", str(folder))
    tool = folder / "tools/forecast"
    tool.write_text("""#!/usr/bin/env python3
import os, sys, urllib.request
if "--help" in sys.argv:
    print("forecast <city>: read the forecast service with the saved key.")
    raise SystemExit
r = urllib.request.Request("http://127.0.0.1:8948/forecast",
                           headers={"X-Api-Key": os.environ["FORECAST_KEY"]})
print(urllib.request.urlopen(r, timeout=10).read().decode().strip())
""")
    tool.chmod(0o755)
    (folder / "keys.example").write_text("FORECAST_KEY\n")
    vault = HOME / "vault" / f"{name}.env"
    outside = ROOT / f"outside-{RUN}.txt"
    skill = folder / ".agents/skills/forecast"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(f"""---
name: forecast
description: Run the saved forecast tool and verify the workflow's host boundaries.
---
Follow these steps exactly; each bash command is its own tool call.
1. Run bash `printf fenced > shell.txt`.
2. Run bash `nocturne tool run forecast Austin`.
3. Use the write tool to create forecast.md containing exactly the forecast returned by step 2.
4. Run bash `printf forbidden > {outside}` once. It must fail; record that refusal.
5. Run bash `cat {vault}` once. It must fail; never retry or use another route.
6. Write checks.md saying what the two refused commands returned. Do not include any key value.
Finish. Never change workflow.json, tools/ or this skill.
""")
    recipe = json.loads((folder / "workflow.json").read_text())
    recipe.update(
        name=name,
        prompt="Load the forecast skill and follow its six steps for Austin. "
        "After running the forecast tool, use write to put its exact output in forecast.md. "
        "Create shell.txt and checks.md too, as the skill says.",
        model_policy=MINI,
        budget_usd=0.08,
        memory_scope="none",
        cron="* * * * *",
        exit_condition="test -s shell.txt && grep -q 'Austin: .*report #' forecast.md "
        f"&& test ! -e {outside}",
    )
    (folder / "workflow.json").write_text(json.dumps(recipe, indent=2) + "\n")
    cli("vault", "set", name, "FORECAST_KEY", stdin=KEY + "\n")
    cli("workflow", "check", str(folder))
    saved = cli("jobs", "save", str(folder), "--daemon-url", BASE)
    job = json.loads(saved[saved.index("{") :])
    RECEIPT["job_id"] = job["job_id"]
    RECEIPT["bundle_digest"] = job["definition"]["bundle"]["digest"]
    fixture = ThreadingHTTPServer(("127.0.0.1", 8948), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1600, "height": 1500})
            jobs = jobs_module(page)
            row = jobs.locator("tr", has=jobs.get_by_role("button", name=name, exact=True))
            row.get_by_role("button", name="Run now", exact=True).click()
            first = wait(job["job_id"], 1)
            actions = calls(first["thread_id"])
            text = json.dumps(actions)
            note = (folder / "checks.md").read_text() if (folder / "checks.md").exists() else ""
            output = (
                (folder / "forecast.md").read_text() if (folder / "forecast.md").exists() else ""
            )
            check(
                "FL-210",
                "Linux agent uses fenced bash; outside write and vault read refused; exit passes",
                first["state"] == "completed"
                and (folder / "shell.txt").read_text() == "fenced"
                and not outside.exists()
                and "Read-only file system" in text
                and "Permission denied" in text
                and KEY not in text + note,
                state=first["state"],
                verdict=first["verdict"],
                note=note,
            )
            check(
                "FL-209",
                "declared sealed tool reaches the service with its key outside the network fence",
                "nocturne tool run forecast Austin" in text
                and REQUESTS
                and REQUESTS[-1]["authorized"]
                and "Austin: clear" in output
                and KEY not in output + text,
                requests=list(REQUESTS),
                output=output,
            )
            second = wait(job["job_id"], 2)
            check(
                "FL-185",
                "Linux cron runs the saved bundle unattended and its fenced exit passes",
                second["state"] == "completed"
                and second["trigger_key"] != second["run_id"]
                and len(REQUESTS) >= 2
                and all(r["authorized"] for r in REQUESTS),
                trigger=second["trigger_key"],
                state=second["state"],
                verdict=second["verdict"],
            )
            RECEIPT["runs"] = [first, second]
            jobs = jobs_module(page)
            jobs.get_by_role("button", name=name, exact=True).click()
            page.wait_for_timeout(800)
            page.locator('[data-testid="rack-plugin-frame-jobs"]').screenshot(
                path=str(OUT / "FL-185.png")
            )
            jobs.get_by_role("button", name="Pause schedule", exact=True).click()
            page.wait_for_timeout(1000)
            jobs.get_by_role("button", name="Open thread", exact=True).first.click()
            page.wait_for_timeout(2500)
            conversation = page.frame_locator('[data-testid="rack-plugin-frame-conversation"]')
            for summary in conversation.locator("summary", has_text="Tools ·").all():
                if not summary.evaluate("e => e.parentElement.open"):
                    summary.click()
            for row_id in ("FL-210", "FL-209"):
                page.locator('[data-testid="rack-plugin-frame-conversation"]').screenshot(
                    path=str(OUT / f"{row_id}.png")
                )
            (OUT / "page-text.txt").write_text(clean(conversation.locator("body").inner_text()))
            browser.close()
        leak_count = sum(
            p.read_bytes().count(KEY.encode()) for p in (HOME / "transcripts").glob("*.jsonl")
        )
        check(
            "FL-209",
            "fixture key absent from transcripts and captures' page text",
            leak_count == 0 and KEY not in (OUT / "page-text.txt").read_text(),
            transcript_hits=leak_count,
        )
        (OUT / "tool-events.json").write_text(clean(json.dumps(actions, indent=2)) + "\n")
        (OUT / "fixture.json").write_text(json.dumps(REQUESTS, indent=2) + "\n")
    finally:
        current = next(j for j in api("/v1/jobs")["jobs"] if j["job_id"] == job["job_id"])
        if current["enabled"]:
            api(
                "/v1/jobs/" + job["job_id"],
                "PUT",
                {
                    "definition": current["definition"],
                    "expected_revision": current["revision"],
                    "enabled": False,
                },
            )
        fixture.shutdown()
        fixture.server_close()
        RECEIPT["finished"] = datetime.now(UTC).isoformat()
        (OUT / "walk.json").write_text(clean(json.dumps(RECEIPT, indent=2)) + "\n")
    assert all(c["ok"] for c in RECEIPT["checks"]), "Walk has red checks; inspect the receipt"


if __name__ == "__main__":
    main()
