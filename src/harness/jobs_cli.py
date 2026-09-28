"""SD-059: file-authored workflows use the same daemon boundary as the Jobs module."""

import json
import urllib.error
import urllib.request
from pathlib import Path

from spine.jobs import WorkflowDefinition

from harness.envelope import generate_ulid
from harness.onboarding import OnboardingError


def jobs_nocturne(args, *, stdout):
    action, target = args.action, args.target
    method, path, body = "GET", "/v1/jobs", None
    if action != "list" and not target:
        raise OnboardingError("Supply a recipe JSON file, job ID or run ID.")
    if action == "save":
        try:
            definition = WorkflowDefinition.model_validate_json(Path(target).read_text())
        except (OSError, ValueError) as exc:
            raise OnboardingError(f"Cannot read workflow: {exc}") from exc
        job_id = args.job_id or generate_ulid()
        method, path = "PUT", f"/v1/jobs/{job_id}"
        body = {"definition": definition.model_dump(mode="json")}
        if args.job_id:
            snapshot = _request(args.daemon_url, "GET", "/v1/jobs", None)
            job = next((job for job in snapshot["jobs"] if job["job_id"] == job_id), None)
            if job is None:
                raise OnboardingError("Saved workflow not found.")
            body.update(expected_revision=job["revision"], enabled=job["enabled"])
    elif action == "run":
        method, path = "POST", f"/v1/jobs/{target}/run"
    elif action == "stop":
        method, path = "POST", f"/v1/job-runs/{target}/stop"
    result = _request(args.daemon_url, method, path, body)
    if action == "list":
        _print_jobs(result, stdout)
        return 0
    print(json.dumps(result, indent=2), file=stdout)
    return 0


def _print_jobs(snapshot, stdout):
    """One line per saved job: the ID to run it by, its name, schedule and last outcome."""
    if not snapshot["jobs"]:
        print("No saved jobs. Save one with `nocturne jobs save recipe.json`.", file=stdout)
    for job in snapshot["jobs"]:
        definition = job["definition"]
        if definition.get("cron"):
            schedule = f"{definition['cron']} UTC"
        elif definition.get("trigger"):
            schedule = f"on {definition['trigger']} change"
        else:
            schedule = "on demand"
        runs = [run for run in snapshot["runs"] if run["job_id"] == job["job_id"]]
        last = max(runs, key=lambda run: run["started_at"], default=None)
        outcome = "ready" if last is None else last["state"]
        if last is not None and last.get("verdict"):
            outcome += f" — {last['verdict']}"
        paused = "" if job["enabled"] else " (paused)"
        print(f"{job['job_id']}  {definition['name']}  {schedule}{paused}  {outcome}", file=stdout)
    if snapshot.get("scheduler_error"):
        print(f"Scheduler: {snapshot['scheduler_error']}", file=stdout)


def _request(url, method, path, body):
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise OnboardingError(f"Jobs refused: {exc.read().decode()}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise OnboardingError("Nocturne is unavailable; start it with nocturne up.") from exc
