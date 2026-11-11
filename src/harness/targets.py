"""M7TG / SD-092: SSH delivers the same bundle to the same product, then proves it."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from harness import __version__
from harness.bundle import check, pack, read_vault
from harness.envelope import generate_ulid
from harness.jobs_cli import _request
from harness.onboarding import OnboardingError, _atomic_write_config, load_config


def add_commands(commands):
    target = commands.add_parser("target", help="add or initialize an SSH host")
    actions = target.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add", help="name an SSH address (user@host or ssh://user@host:port)")
    add.add_argument("name")
    add.add_argument("address")
    actions.add_parser(
        "init", help="install this version, start its service and run doctor"
    ).add_argument("name")
    # The SSH peer invokes these CLI operations; the daemon never gains a network listener.
    for action in ("state", "preflight", "receive", "archive", "restore", "setup"):
        peer = actions.add_parser(action, help=argparse.SUPPRESS)
        peer.add_argument("--workflow")
        peer.add_argument("--digest")
        peer.add_argument("--keys", default="[]")
        peer.add_argument("--sender-version", default=__version__)
        peer.add_argument("--source", default="local")
    commands.add_parser("targets", help="show workflow digests and verdicts on every tier")
    push = commands.add_parser("push", help="prove a bundle on an SSH target before enabling it")
    push.add_argument("bundle", type=Path)
    push.add_argument("--to", required=True)
    promote = commands.add_parser("promote", help="send only the digest proven on stage")
    promote.add_argument("workflow")
    promote.add_argument("--to", required=True)
    rollback = commands.add_parser("rollback", help="re-enable the previous proven digest")
    rollback.add_argument("workflow")
    rollback.add_argument("--on", required=True)


def _ssh(address, arguments, data=b"", *, timeout=660):
    command = 'export PATH="$HOME/.local/share/nocturne/venv/bin:$HOME/.local/bin:$PATH"; '
    command += shlex.join(["nocturne", *arguments])
    try:
        result = subprocess.run(
            ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", address, command],
            input=data,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OnboardingError(
            "SSH did not finish; inspect the target with `nocturne targets`."
        ) from exc
    if result.returncode:
        if result.stdout.startswith(b"{") and json.loads(result.stdout).get("verdict") == "FAIL":
            return result.stdout
        raise OnboardingError(
            result.stderr.decode(errors="replace").strip()
            or "SSH refused; check the address and your SSH access."
        )
    return result.stdout


def _remote(config, name, action, *, data=b"", **fields):
    address = config.targets.get(name)
    if address is None:
        raise OnboardingError(f"Unknown target {name}; add it with `nocturne target add`.")
    arguments = ["target", action, "--sender-version", __version__]
    for key, value in fields.items():
        arguments.extend(["--" + key.replace("_", "-"), value])
    result = _ssh(address, arguments, data)
    return result if action == "archive" else json.loads(result)


def _root(config):
    return config.home / "releases"


def _records(config):
    path = _root(config) / "log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _append(config, **record):
    record["when"] = datetime.now(UTC).isoformat()
    with (_root(config) / "log.jsonl").open("a") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def _folder(config, digest):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest or ""):
        raise OnboardingError("Supply the bundle's sha256 digest.")
    return _root(config) / digest[7:]


def _active(records, workflow):
    return next(
        (
            r
            for r in reversed(records)
            if r["workflow"] == workflow and r["action"] in {"activate", "rollback"}
        ),
        None,
    )


def _proven(records, workflow, digest):
    last = next(
        (
            r
            for r in reversed(records)
            if r["workflow"] == workflow and r["digest"] == digest and r["action"] == "proof"
        ),
        None,
    )
    if last is None or last["verdict"] != "PASS":
        raise OnboardingError(
            f"{workflow} has no passing proof for that digest; push it to stage first."
        )
    return last


def _jobs(config):
    return _request(config.local_url, "GET", "/v1/jobs", None)


def _save(config, job_id, definition, *, enabled, previous=None):
    return _request(
        config.local_url,
        "PUT",
        f"/v1/jobs/{job_id}",
        {
            "definition": definition,
            "enabled": enabled,
            "grants_confirmed": True,
            "expected_revision": previous["revision"] if previous else 0,
        },
    )


def _preflight(config, sender, workflow=None, keys=()):
    pair = [__version__, version("nocturne-memory")]
    if pair != [sender, sender]:
        raise OnboardingError(
            f"Target runs {' / '.join(pair)}; sender runs {sender}. "
            "Update the older installation to the same version; never downgrade."
        )
    if config.palace_mode != "local":
        raise OnboardingError(
            "A target needs its own local Palace; run `nocturne init` on that host."
        )
    if missing := [key for key in keys if key not in read_vault(workflow, config.home)]:
        raise OnboardingError(
            f"Target vault lacks {', '.join(missing)}. Pipe each value over SSH into "
            f"`nocturne vault set {shlex.quote(workflow)} <NAME>` and retry."
        )
    return _jobs(config)


def _state(config, sender=__version__):
    snapshot = _preflight(config, sender)
    records = _records(config)
    workflows = {}
    for name in dict.fromkeys(r["workflow"] for r in records):
        active = _active(records, name)
        last = next(r for r in reversed(records) if r["workflow"] == name)
        proof = next(
            (r for r in reversed(records) if r["workflow"] == name and r["action"] == "proof"), None
        )
        job = next(
            (j for j in snapshot["jobs"] if active and j["job_id"] == active["job_id"]), None
        )
        actual = job["definition"].get("bundle") if job else None
        last_for_active = next(
            (
                r
                for r in reversed(records)
                if actual
                and r["workflow"] == name
                and r["digest"] == actual["digest"]
                and r["action"] == "proof"
            ),
            None,
        )
        workflows[name] = {
            "digest": actual["digest"] if actual else None,
            "enabled": bool(job and job["enabled"]),
            "verdict": proof["verdict"] if proof else last["verdict"],
            "attempted_digest": proof["digest"] if proof else last["digest"],
            "when": last["when"],
            "from": last["source"],
            "proven": bool(
                active
                and actual
                and active["digest"] == actual["digest"]
                and last_for_active
                and last_for_active["verdict"] == "PASS"
            ),
        }
    return {"version": __version__, "workflows": workflows}


def _activate(config, workflow, digest, source, *, action="activate"):
    records = _records(config)
    proof = _proven(records, workflow, digest)
    if "sha256:" + hashlib.sha256(pack(_folder(config, digest))).hexdigest() != digest:
        raise OnboardingError(
            "The proven bundle changed; restore its original bytes before enabling."
        )
    snapshot = _jobs(config)
    if any(
        run["state"] in {"running", "waiting"}
        and run["job_id"] == (_active(records, workflow) or {}).get("job_id")
        for run in snapshot["runs"]
    ):
        raise OnboardingError(
            "The enabled release is running; let it finish before switching releases."
        )
    candidate = next(j for j in snapshot["jobs"] if j["job_id"] == proof["job_id"])
    active = _active(records, workflow)
    job_id = active["job_id"] if active else generate_ulid()
    previous = next((j for j in snapshot["jobs"] if j["job_id"] == job_id), None)
    definition = candidate["definition"].copy()
    if previous is None:
        definition["bundle"] = None  # save re-records the checked folder, as A-084 requires
    _save(config, job_id, definition, enabled=True, previous=previous)
    return _append(
        config,
        workflow=workflow,
        digest=digest,
        verdict="PASS",
        source=source,
        action=action,
        job_id=job_id,
        proof_run_id=proof["proof_run_id"],
    )


def _receive(config, data, digest, sender, source):
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise OnboardingError(
            "The transferred bytes do not match the bundle digest; pack and push again."
        )
    # Validate paths and recipe without writing any bundle member to the target.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive.getmembers()
        if any(
            not m.isfile()
            or not (
                m.name in {"workflow.json", "keys.example"}
                or m.name.startswith(("tools/", ".agents/skills/"))
            )
            or Path(m.name).is_absolute()
            or ".." in Path(m.name).parts
            for m in members
        ):
            raise OnboardingError("A bundle contains only plain files in its four declared parts.")
        recipe = json.load(archive.extractfile("workflow.json"))
        key_file = (
            archive.extractfile("keys.example") if "keys.example" in archive.getnames() else None
        )
        keys = (
            [
                line.strip().split("=", 1)[0]
                for line in key_file.read().decode().splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if key_file
            else []
        )
        _preflight(config, sender, recipe["name"], keys)
        root = _folder(config, digest)
        if root.exists():
            if pack(root) != data:
                raise OnboardingError(
                    "The target's stored bundle changed; inspect it before pushing again."
                )
        else:
            with tempfile.TemporaryDirectory(dir=_root(config)) as temporary:
                staged = Path(temporary)
                archive.extractall(staged, filter="data")
                check(staged, config.home)
                if pack(staged) != data:
                    raise OnboardingError(
                        "The archive is not the canonical packed bundle; "
                        "run `nocturne workflow pack` again."
                    )
                staged.rename(root)
    definition, _ = check(root, config.home)
    job = _save(config, generate_ulid(), definition.model_dump(mode="json"), enabled=False)
    run = _request(config.local_url, "POST", f"/v1/jobs/{job['job_id']}/run", None)
    deadline = time.monotonic() + 600
    while True:
        observed = next(r for r in _jobs(config)["runs"] if r["run_id"] == run["run_id"])
        if observed["state"] != "running":
            break
        if time.monotonic() >= deadline:
            _request(config.local_url, "POST", f"/v1/job-runs/{run['run_id']}/stop", None)
            observed["state"] = "cancelled"
            break
        time.sleep(1)
    passed = (
        observed["state"] == "completed"
        and observed["definition"].get("bundle", {}).get("digest") == digest
    )
    receipt = _append(
        config,
        workflow=definition.name,
        digest=digest,
        verdict="PASS" if passed else "FAIL",
        source=source,
        action="proof",
        job_id=job["job_id"],
        proof_run_id=run["run_id"],
    )
    if passed:
        receipt = _activate(config, definition.name, digest, source)
    return receipt


def push_bundle(path, target, config=None):
    config = config or load_config()
    if path.is_dir():
        definition, record = check(path.resolve(), config.home)
        data = pack(path.resolve())
    else:
        data = path.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
                archive.extractall(temporary, filter="data")
            definition, record = check(Path(temporary), config.home)
            if pack(Path(temporary)) != data:
                raise OnboardingError("Push the plain tar written by `nocturne workflow pack`.")
    _remote(config, target, "preflight", workflow=definition.name, keys=json.dumps(record.keys))
    return _remote(
        config, target, "receive", data=data, digest=record.digest, source=config.machine_id
    )


def promote(workflow, target, config=None):
    config = config or load_config()
    if target == "stage":
        raise OnboardingError("Choose a production target; stage is where a push is proven.")
    state = _remote(config, "stage", "state")["workflows"].get(workflow)
    if not state or not state["enabled"] or not state["proven"]:
        raise OnboardingError(
            f"{workflow} has no enabled, proven digest on stage; push it there first."
        )
    digest = state["digest"]
    data = _remote(config, "stage", "archive", workflow=workflow, digest=digest)
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise OnboardingError("Stage's bundle differs from its proven digest; promotion refused.")
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "proven.tar"
        archive.write_bytes(data)
        return push_bundle(archive, target, config)


def tiers(config=None):
    config = config or load_config()
    snapshot = _jobs(config)
    local = {}
    for job in snapshot["jobs"]:
        bundle = job["definition"].get("bundle")
        if bundle:
            runs = [
                r
                for r in snapshot["runs"]
                if r["job_id"] == job["job_id"]
                and r["definition"].get("bundle", {}).get("digest") == bundle["digest"]
            ]
            last = max(runs, key=lambda r: r["started_at"], default=None)
            local[job["definition"]["name"]] = {
                "digest": bundle["digest"],
                "verdict": "PASS"
                if last and last["state"] == "completed"
                else last["state"]
                if last
                else "unproven",
                "enabled": job["enabled"],
            }
    result = {"local": {"version": __version__, "workflows": local}}
    for name in config.targets:
        try:
            result[name] = _remote(config, name, "state")
        except OnboardingError as exc:
            result[name] = {"error": str(exc), "workflows": {}}
    return result


def _setup(config):
    """The host's CLI starts its ordinary loopback-only product under the user's service manager."""
    if config.palace_mode != "local":
        raise OnboardingError("Initialize this host with its own local Palace first.")
    system = os.geteuid() == 0
    unit = (
        Path("/etc/systemd/system/nocturne.service")
        if system
        else Path.home() / ".config/systemd/user/nocturne.service"
    )
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(
        "[Unit]\nDescription=Nocturne\n[Service]\n"
        f"Environment=NOCTURNE_HOME={config.home}\n"
        f"Environment=PATH={Path(sys.executable).parent}:{os.environ.get('PATH', os.defpath)}\n"
        f"WorkingDirectory={config.home}\n"
        f"ExecStart={sys.executable} -m harness.cli up --no-open\n"
        "Restart=on-failure\n[Install]\nWantedBy=default.target\n"
    )
    for args in (["daemon-reload"], ["enable", "--now", "nocturne.service"]):
        subprocess.run(["systemctl", *([] if system else ["--user"]), *args], check=True)
    from harness.onboarding import _wait_for_url, doctor_nocturne

    _wait_for_url(config.local_url, timeout=300)

    return doctor_nocturne()


class Delivery(BaseModel):
    workflow: str
    target: str
    action: str


def mount_targets(app):
    import asyncio

    from fastapi import HTTPException

    @app.get("/v1/targets")
    async def read_targets():
        try:
            return await asyncio.to_thread(tiers)
        except (OnboardingError, OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/targets")
    async def deliver(body: Delivery):
        def act():
            config = load_config()
            if body.action == "promote":
                return promote(body.workflow, body.target, config)
            if body.action == "push":
                job = next(
                    (
                        j
                        for j in _jobs(config)["jobs"]
                        if j["definition"]["name"] == body.workflow
                        and j["definition"].get("bundle")
                    ),
                    None,
                )
                if job is None:
                    raise OnboardingError("Save this workflow's bundle locally before pushing it.")
                return push_bundle(Path(job["definition"]["folder"]), body.target, config)
            raise OnboardingError("Choose Push or Promote.")

        try:
            result = await asyncio.to_thread(act)
            if result.get("verdict") == "FAIL":
                raise HTTPException(409, "Proof failed. The previous proven release stays enabled.")
            return result
        except (OnboardingError, OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc


def targets_nocturne(args, *, stdout):
    config = load_config()
    if args.command == "targets":
        for tier, state in tiers(config).items():
            print(
                f"{tier}  {config.targets.get(tier, 'this machine')}  "
                f"{state.get('error', state.get('version', ''))}",
                file=stdout,
            )
            for name, release in state["workflows"].items():
                print(
                    f"  {name}  {release['digest'] or 'no enabled release'}  "
                    f"{release['verdict']}  {'enabled' if release['enabled'] else 'paused'}",
                    file=stdout,
                )
        return 0
    if args.command == "push":
        result = push_bundle(args.bundle, args.to, config)
    elif args.command == "promote":
        result = promote(args.workflow, args.to, config)
    elif args.command == "rollback":
        result = _remote(
            config, args.on, "restore", workflow=args.workflow, source=config.machine_id
        )
    elif args.action == "add":
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", args.name) or args.name == "local":
            raise OnboardingError(
                "Name the target, for example stage or prod; local is this machine."
            )
        if (
            not args.address
            or args.address.startswith("-")
            or any(c.isspace() for c in args.address)
        ):
            raise OnboardingError("Supply one SSH address, for example user@host.")
        value = json.dumps(json.dumps({**config.targets, args.name: args.address}))
        lines = config.path.read_text().splitlines(keepends=True)
        _atomic_write_config(
            config.path,
            "".join(
                f"NOCTURNE_TARGETS={value}\n" if line.startswith("NOCTURNE_TARGETS=") else line
                for line in lines
            ),
        )
        print(f"{args.name}: {args.address}", file=stdout)
        return 0
    elif args.action == "init":
        address = config.targets.get(args.name)
        if address is None:
            raise OnboardingError("Add the target's SSH address first.")
        # Only installation precedes the host CLI; never replace a newer installation.
        script = f"""set -eu
export PATH="$HOME/.local/share/nocturne/venv/bin:$HOME/.local/bin:$PATH"
if test -x "$HOME/.local/share/nocturne/venv/bin/nocturne"; then
python3.12 - <<'PY'
from importlib.metadata import version
from packaging.version import Version
if any(Version(version(p)) > Version({__version__!r})
       for p in ('nocturne-harness', 'nocturne-memory')):
    raise SystemExit('Target is newer; update the sender, never downgrade.')
PY
fi
python3.12 -m venv "$HOME/.local/share/nocturne/venv"
python -m pip install --index-url https://pypi.org/simple \\
    nocturne-harness=={__version__} nocturne-memory=={__version__}
nocturne init
nocturne target setup
"""
        result = subprocess.run(["ssh", "-t", address, "sh -c " + shlex.quote(script)])
        return result.returncode
    elif args.action == "setup":
        return _setup(config)
    elif args.action == "state":
        result = _state(config, args.sender_version)
    elif args.action == "preflight":
        _preflight(config, args.sender_version, args.workflow, json.loads(args.keys))
        result = {"ready": True}
    elif args.action == "archive":
        _preflight(config, args.sender_version)
        _proven(_records(config), args.workflow, args.digest)
        data = pack(_folder(config, args.digest))
        if "sha256:" + hashlib.sha256(data).hexdigest() != args.digest:
            raise OnboardingError("The proven bundle changed; promotion refused.")
        stdout.buffer.write(data)
        return 0
    else:
        _root(config).mkdir(parents=True, exist_ok=True, mode=0o700)
        with (_root(config) / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.action == "receive":
                result = _receive(
                    config, sys.stdin.buffer.read(), args.digest, args.sender_version, args.source
                )
            else:
                _preflight(config, args.sender_version)
                records = _records(config)
                active = _active(records, args.workflow)
                previous = next(
                    (
                        r
                        for r in reversed(records)
                        if r["workflow"] == args.workflow
                        and r["action"] in {"activate", "rollback"}
                        and active
                        and r["digest"] != active["digest"]
                    ),
                    None,
                )
                if previous is None:
                    raise OnboardingError("There is no previous proven release to roll back to.")
                result = _activate(
                    config, args.workflow, previous["digest"], args.source, action="rollback"
                )
    print(json.dumps(result), file=stdout)
    return 0 if result.get("verdict") != "FAIL" else 2
