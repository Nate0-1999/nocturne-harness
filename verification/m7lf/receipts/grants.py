"""M7LF / FL-209 neighbour: undeclared and confirmed network crossings on Linux."""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from walk import BASE, HOME, MINI, OUT, ROOT, RUN, api, cli, jobs_module, wait

requests = []


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"public notice m7lf run {RUN}\n".encode())

    def log_message(self, *args):
        pass


def main():
    jobs = []
    fixture = ThreadingHTTPServer(("127.0.0.1", 8949), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    results = []
    try:
        for declared in (False, True):
            folder = ROOT / "grants" / f"run-{RUN}-{'declared' if declared else 'plain'}"
            cli("workflow", "new", str(folder))
            path = folder / "workflow.json"
            recipe = json.loads(path.read_text())
            recipe.update(
                name=folder.name,
                model_policy=MINI,
                budget_usd=0.05,
                memory_scope="none",
                prompt="Run this one bash command exactly: "
                "`curl -fsS http://127.0.0.1:8949/notice > notice.md`. Then finish.",
                exit_condition="grep -q 'public notice m7lf' notice.md",
                allow=["remote"] if declared else [],
            )
            path.write_text(json.dumps(recipe, indent=2) + "\n")
            if declared:
                refusal = subprocess.run(
                    ["/venv/bin/nocturne", "jobs", "save", str(folder), "--daemon-url", BASE],
                    input="n\n",
                    capture_output=True,
                    text=True,
                    env={**os.environ, "NOCTURNE_HOME": str(HOME)},
                )
                results.append(
                    {
                        "check": "decline saves nothing",
                        "ok": refusal.returncode == 2
                        and "Not saved" in refusal.stderr
                        and "remote" in refusal.stdout + refusal.stderr,
                    }
                )
            saved = cli(
                "jobs", "save", str(folder), "--daemon-url", BASE, *(["--yes"] if declared else [])
            )
            job = json.loads(saved[saved.index("{") :])
            jobs.append(job)
            before = len(requests)
            cli("jobs", "run", job["job_id"], "--daemon-url", BASE)
            run = wait(job["job_id"], 1)
            if declared:
                note = (
                    folder.joinpath("notice.md").read_text()
                    if folder.joinpath("notice.md").exists()
                    else ""
                )
                ok = (
                    run["state"] == "completed"
                    and len(requests) > before
                    and "public notice m7lf" in note
                )
            else:
                ok = run["state"] == "waiting" and len(requests) == before
            results.append(
                {
                    "check": "confirmed grant runs" if declared else "undeclared parks",
                    "ok": ok,
                    "state": run["state"],
                    "verdict": run["verdict"],
                    "requests": list(requests),
                }
            )
        with sync_playwright() as play:
            browser = play.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1600, "height": 1500})
            module = jobs_module(page)
            module.get_by_role("button", name=jobs[-1]["definition"]["name"], exact=True).click()
            page.wait_for_timeout(800)
            detail = module.locator("aside dl").inner_text()
            results.append(
                {
                    "check": "Jobs shows confirmed remote grant",
                    "ok": "remote" in detail,
                    "detail": detail,
                }
            )
            page.locator('[data-testid="rack-plugin-frame-jobs"]').screenshot(
                path=str(OUT / "FL-209-grants.png")
            )
            browser.close()
    finally:
        for job in jobs:
            for run in api("/v1/jobs")["runs"]:
                if run["job_id"] == job["job_id"] and run["state"] in {"waiting", "running"}:
                    api(f"/v1/job-runs/{run['run_id']}/stop", "POST")
        fixture.shutdown()
        fixture.server_close()
        (OUT / "grants.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results), flush=True)
    assert all(r["ok"] for r in results)


if __name__ == "__main__":
    main()
