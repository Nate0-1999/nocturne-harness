"""SD-059: file-authored workflows use the same daemon boundary as the Jobs module."""

import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from spine.jobs import WorkflowDefinition

from harness.bundle import (
    bundle_definition,
    bundle_record,
    check,
    pack,
    read_vault,
    set_vault,
)
from harness.envelope import generate_ulid
from harness.onboarding import OnboardingError, _terminal_prompt


def bundle_nocturne(args, *, stdout, stdin=sys.stdin):
    """A-084: the bundle folder, its vault and its tools, from the owner's terminal."""
    if args.command == "vault":
        value = (
            getpass.getpass(f"Value for {args.name} (hidden): ") if stdin.isatty() else stdin.read()
        )
        path = set_vault(args.workflow, args.name, value.removesuffix("\n"))
        print(f"{args.name} is set in {path}.", file=stdout)
        return 0
    if args.command == "tool":
        root = Path.cwd()
        definition = bundle_definition(root)
        tool = root / "tools" / args.name
        if tool.parent != root / "tools" or not tool.is_file():
            raise OnboardingError(f"No tool named {args.name} in {root / 'tools'}.")
        try:
            return subprocess.run(
                [str(tool), *args.arguments], env={**os.environ, **read_vault(definition.name)}
            ).returncode
        except OSError as exc:
            raise OnboardingError(f"tools/{args.name} did not run: {exc}") from exc
    root = args.folder.expanduser().resolve()
    if args.action == "new":
        if (root / "workflow.json").exists():
            raise OnboardingError("That folder already holds a workflow.json.")
        for folder in ("tools", ".agents/skills"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        recipe = {
            "name": root.name,
            "prompt": "Describe the work.",
            "folder": ".",
            "model_policy": "elbow",
            "budget_usd": 0.5,
            # F138: a job with a memory scope does not run yet; a new bundle starts without one.
            "memory_scope": "none",
            "exit_condition": "true",
        }
        (root / "workflow.json").write_text(json.dumps(recipe, indent=2) + "\n")
        (root / "keys.example").write_text(
            "# One key NAME per line. Set each value with: nocturne vault set <workflow> <NAME>\n"
        )
        print(
            f"Bundle folder ready: {root}\n"
            "Edit workflow.json, add skills under .agents/skills and executables under tools, "
            f"then run: nocturne workflow check {root}",
            file=stdout,
        )
        return 0
    if args.action == "check":
        definition, record = check(root)
    else:
        definition, record = bundle_definition(root), bundle_record(root)
        archive = Path.cwd() / f"{root.name}.tar"
        archive.write_bytes(pack(root))
        print(f"Packed {archive}", file=stdout)
    print(f"{definition.name}  {record.digest}", file=stdout)
    for tool in record.tools:
        print(f"  tool  {tool.name} — {tool.summary}", file=stdout)
    for name in record.keys:
        print(f"  key   {name}", file=stdout)
    for wall in definition.allow:
        print(f"  allow {wall}", file=stdout)
    if args.action == "check":
        print(f"Ready. Save it with: nocturne jobs save {root}", file=stdout)
    return 0


def jobs_nocturne(args, *, stdout, prompt=_terminal_prompt):
    action, target = args.action, args.target
    method, path, body = "GET", "/v1/jobs", None
    if action != "list" and not target:
        raise OnboardingError("Supply a recipe JSON file, bundle folder, job ID or run ID.")
    if action == "save":
        if Path(target).expanduser().is_dir():
            definition, _ = check(Path(target).expanduser().resolve())
        else:
            try:
                definition = WorkflowDefinition.model_validate_json(Path(target).read_text())
            except (OSError, ValueError) as exc:
                raise OnboardingError(f"Cannot read workflow: {exc}") from exc
        job_id = args.job_id or generate_ulid()
        method, path = "PUT", f"/v1/jobs/{job_id}"
        body = {"definition": definition.model_dump(mode="json")}
        if definition.allow:
            # ADR-015 / A-084: the owner sees the declared grants and confirms them once, here.
            question = (
                f"{definition.name} may cross these walls unattended: "
                f"{', '.join(definition.allow)}. Allow? [y/N] "
            )
            if not args.yes and prompt(question).strip().lower() not in {"y", "yes"}:
                raise OnboardingError("Not saved: the declared grants were not confirmed.")
            body["grants_confirmed"] = True
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
